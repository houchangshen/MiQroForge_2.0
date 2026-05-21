"""agents/yaml_coder/generator.py — YAML Coder Agent 生成节点。

负责：
1. 构建步骤 → 节点解析映射（仅节点名，不预加载 NodeSpec 详情）
2. 向 LLM 绑定探索工具（get_node_details / search_nodes_by_semantic_type）
3. 通过工具调用循环让 LLM 按需查询 I/O 规范后生成 MF YAML
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agents.llm_config import LLMConfig
from agents.schemas import NodeResolution
from agents.common.prompt_loader import load_prompt
from agents.common.session_logger import get_session
from agents.yaml_coder.state import YAMLCoderState

# 工具调用最大轮次（每轮可含多个并行工具调用）
_MAX_TOOL_ROUNDS = 10


def make_node_tools(node_index_map: dict) -> list:
    """创建节点探索工具，供 YAML Coder LLM 按需调用。

    Args:
        node_index_map: {node_name: NodeIndexEntry} 映射，来自 node_index.yaml。

    Returns:
        包含 get_node_details 和 search_nodes_by_semantic_type 的工具列表。
    """
    index_entries = list(node_index_map.values())

    @tool
    def get_node_details(node_name: str) -> str:
        """Get full I/O specification for a node: nodespec_path, stream inputs,
        stream outputs, and onboard params. Call this BEFORE connecting or using
        a node in the generated YAML."""
        entry = node_index_map.get(node_name)
        if not entry:
            available = ", ".join(sorted(node_index_map.keys())[:20])
            return (
                f"Node '{node_name}' not found in index. "
                f"Available nodes (first 20): {available}"
            )
        lines = [
            f"Node: {entry.name}",
            f"nodespec_path: {entry.nodespec_path}",
            f"Description: {entry.description}",
            f"Semantic type: {entry.semantic_type or '(none)'}",
            f"Node type: {entry.node_type}",
            "",
            "Stream inputs:",
        ]
        for p in entry.stream_inputs:
            detail = f" / {p.detail}" if p.detail else ""
            lines.append(f"  - {p.name} [{p.category}{detail}]")
        if not entry.stream_inputs:
            lines.append("  (none)")
        lines.append("Stream outputs:")
        for p in entry.stream_outputs:
            detail = f" / {p.detail}" if p.detail else ""
            lines.append(f"  - {p.name} [{p.category}{detail}]")
        if not entry.stream_outputs:
            lines.append("  (none)")
        lines.append("Onboard params:")
        for p in entry.onboard_inputs:
            desc = (p.description or "")[:80]
            allowed = f" [options: {p.allowed_values}]" if p.allowed_values else ""
            default = f" (default: {p.default})" if p.default is not None else ""
            lines.append(f"  - {p.name} ({p.kind}){allowed}{default}: {desc}")
        if not entry.onboard_inputs:
            lines.append("  (none)")
        return "\n".join(lines)

    @tool
    def search_nodes_by_semantic_type(semantic_type: str) -> str:
        """Find all available nodes matching a semantic type string
        (e.g. 'geometry-input', 'single-point-energy', 'geometry-optimization').
        Use this to discover what node to use for a step that has no suggestion."""
        matches = [e for e in index_entries if e.semantic_type == semantic_type]
        if not matches:
            all_types = sorted({e.semantic_type for e in index_entries if e.semantic_type})
            return (
                f"No nodes found for semantic type '{semantic_type}'. "
                f"Known types: {', '.join(all_types)}"
            )
        lines = [f"Nodes with semantic_type='{semantic_type}':"]
        for e in matches:
            lines.append(f"  - {e.name} ({e.node_type}): {e.description[:100]}")
        return "\n".join(lines)

    return [get_node_details, search_nodes_by_semantic_type]


def _build_resolutions(
    semantic_workflow,
    selected_implementations: dict[str, str],
) -> list[NodeResolution]:
    """为每个语义步骤选择具体节点（仅节点名，不预加载 NodeSpec 详情）。"""
    resolutions = []
    for step in semantic_workflow.steps:
        # 用户指定 → available_implementations 候选 → 空
        selected_name = selected_implementations.get(step.id)
        if not selected_name:
            candidates = semantic_workflow.available_implementations.get(step.id, [])
            selected_name = candidates[0] if candidates else None

        resolution = NodeResolution(
            step_id=step.id,
            resolved_node=selected_name,
            onboard_params=dict(step.constraints),
            needs_new_node=(selected_name is None),
            new_node_request=step.description if selected_name is None else None,
        )
        resolutions.append(resolution)
    return resolutions


def generate_yaml(state: YAMLCoderState) -> dict[str, Any]:
    """LangGraph 生成节点 — 通过工具调用循环生成或修正 MF YAML。"""
    semantic_workflow = state.get("semantic_workflow")
    if not semantic_workflow:
        return {"error": "缺少 SemanticWorkflow 输入"}

    user_params = state.get("user_params") or {}
    selected_implementations = state.get("selected_implementations") or {}
    iteration = state.get("iteration", 0)
    evaluation = state.get("evaluation")

    # ── 加载 node_index（工具函数的数据来源）────────────────────────────────
    try:
        from node_index.scanner import load_index
        from api.config import get_settings
        index = load_index(get_settings().project_root)
        node_index_map = {e.name: e for e in index.entries}
    except Exception:
        node_index_map = {}

    # ── 构建步骤→节点解析映射（仅节点名，nodespec_path 按需补充）─────────
    resolutions = state.get("resolutions")
    if not resolutions or iteration > 0:
        resolutions = _build_resolutions(semantic_workflow, selected_implementations)

    for res in resolutions:
        if res.resolved_node and not res.resolved_nodespec_path:
            entry = node_index_map.get(res.resolved_node)
            if entry:
                res.resolved_nodespec_path = entry.nodespec_path

    # ── 构建 LLM + 工具 ───────────────────────────────────────────────────
    tools = make_node_tools(node_index_map)
    llm = LLMConfig.get_chat_model(purpose="yaml_coder", temperature=0.0)
    llm_with_tools = llm.bind_tools(tools)

    # ── 构建初始消息（节点名列表，无 NodeSpec 详情）───────────────────────
    system_content = load_prompt(
        "yaml_coder/prompts/yaml_system.jinja2",
        argo_namespace=os.environ.get("ARGO_NAMESPACE", ""),
    )
    user_content = load_prompt(
        "yaml_coder/prompts/yaml_generate.jinja2",
        semantic_workflow_json=json.dumps(
            semantic_workflow.model_dump(mode="json"), indent=2, ensure_ascii=False
        ),
        resolutions=[r.model_dump() for r in resolutions],
        user_params=user_params,
        iteration=iteration,
        prev_yaml=state.get("mf_yaml", ""),
        validation_errors=state.get("validation_errors", []),
        evaluation_issues=evaluation.issues if evaluation and not evaluation.passed else [],
    )

    messages: list = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

    # ── 工具调用循环（最多 _MAX_TOOL_ROUNDS 轮）──────────────────────────
    response = None
    try:
        for _round in range(_MAX_TOOL_ROUNDS):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break  # LLM 不再调用工具，response.content 是最终 YAML

            # 执行每个工具调用并追加 ToolMessage
            for tc in response.tool_calls:
                tool_fn = next((t for t in tools if t.name == tc["name"]), None)
                if tool_fn:
                    try:
                        result = tool_fn.invoke(tc["args"])
                    except Exception as e:
                        result = f"Tool error: {e}"
                else:
                    result = f"Unknown tool: {tc['name']}"
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        # ── 记录消息历史（messages[:-1] 不含最终 AIMessage，避免与 llm_response 重复）
        session = get_session()
        if session:
            session.log_llm_call(
                "generate", messages[:-1],
                response.content if response else "",
                iteration=iteration,
            )

        mf_yaml = (response.content or "").strip() if response else ""

        # 去除 markdown 代码块（LLM 有时仍会包裹）
        if mf_yaml.startswith("```yaml"):
            mf_yaml = mf_yaml[7:]
        elif mf_yaml.startswith("```"):
            mf_yaml = mf_yaml[3:]
        if mf_yaml.endswith("```"):
            mf_yaml = mf_yaml[:-3]
        mf_yaml = mf_yaml.strip()

        # 去除 LLM 在 YAML 前输出的分析文字（找到 mf_version: 作为起始行）
        mf_version_match = re.search(r'^(mf_version\s*:)', mf_yaml, re.MULTILINE)
        if mf_version_match and mf_version_match.start() > 0:
            mf_yaml = mf_yaml[mf_version_match.start():].strip()

        return {
            "mf_yaml": mf_yaml,
            "available_nodes": [],  # 工具链模式：不预加载；保留字段兼容评判器
            "resolutions": resolutions,
            "error": None,
        }

    except Exception as e:
        session = get_session()
        if session:
            session.log_event("generate_error", {
                "iteration": iteration,
                "error": str(e),
            })
        return {
            "mf_yaml": "",
            "available_nodes": [],
            "resolutions": resolutions,
            "error": f"YAML Coder 生成失败: {e}",
        }
