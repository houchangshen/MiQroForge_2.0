"""agents/subagent/explore/agent.py — Explore 子 Agent 核心逻辑。

作为 research 工具的内部实现：
  - 用快速模型独立搜索手册 + 参考节点 + Schema
  - 支持并发工具调用（单轮多 tool_call）
  - 循环结束后强制合成摘要（确保返回的是结论而非原始工具结果）
  - 支持 avoid_directions（父 Agent 告知哪些方向已经试过不对）
  - 每次调用自动保存 session log 到项目 conversations 目录
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agents.llm_config import LLMConfig
from agents.common.prompt_loader import load_prompt

# 搜索阶段轮次
_SEARCH_ROUNDS = 3


def run_explore_agent(
    question: str,
    software: str,
    avoid_directions: str = "",
    project_id: str = "",
    projects_dir: str = "",
) -> str:
    """运行 Explore 子 Agent：搜索 → 强制合成 → 返回摘要。

    两阶段：
      1. 搜索（2 轮）：LLM 并发调用工具收集信息
      2. 合成（1 轮）：不加工具，强制 LLM 基于所有工具结果写出摘要

    这确保永远不会把 raw tool output 直接返回给父 Agent。
    """
    started_at = datetime.now().isoformat()
    log_steps: list[dict[str, Any]] = []

    # ── 构建工具 ──
    from agents.node_generator.prefab.tools import (
        make_manual_tools,
        make_node_reference_tools,
    )
    from agents.node_generator.shared.manual_index import list_available_manuals as _list_manuals
    available_manuals = _list_manuals()
    manual_tools = make_manual_tools(software, available_manuals)
    node_tools = make_node_reference_tools(software)

    research_tools = manual_tools + node_tools
    tool_map = {t.name: t for t in research_tools}

    # ── 快速模型 ──
    llm = LLMConfig.get_chat_model(purpose="node_explorer", temperature=0.0)
    llm_with_tools = llm.bind_tools(research_tools)

    # ── System prompt ──
    system_content = load_prompt(
        "subagent/explore/prompts/explore_system.jinja2",
        software=software,
        avoid_directions=avoid_directions,
        max_search_rounds=_SEARCH_ROUNDS,
    )

    messages: list = [
        SystemMessage(content=system_content),
        HumanMessage(content=f"Research question: {question}"),
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # 阶段 1：搜索（带工具）
    # ═══════════════════════════════════════════════════════════════════════

    for round_idx in range(_SEARCH_ROUNDS):
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            log_steps.append({"round": round_idx, "timestamp": datetime.now().isoformat(), "error": str(e)})
            return f"[Explore agent error in search round {round_idx}]: {e}"

        messages.append(response)

        # 本轮没调工具 → 搜索完成，提前退出
        if not response.tool_calls:
            break

        # 记录并执行工具
        tc_names = [tc.get("name", "?") for tc in response.tool_calls]
        round_log: dict[str, Any] = {
            "round": round_idx,
            "stage": "search",
            "timestamp": datetime.now().isoformat(),
            "tool_calls": tc_names,
            "tools": [],
        }

        for tc in response.tool_calls:
            name = tc.get("name", "")
            args = tc.get("args", {})
            tid = tc.get("id", "")

            tool_fn = tool_map.get(name)
            if tool_fn is None:
                result = json.dumps({"error": f"Unknown tool: {name}"})
            else:
                try:
                    result = tool_fn.invoke(args)
                    if isinstance(result, str) and len(result) > 20000:
                        result = result[:20000] + "\n\n[... truncated at 20KB ...]"
                except Exception as e:
                    result = json.dumps({"error": f"Tool '{name}' failed: {e}"})

            messages.append(ToolMessage(content=str(result), tool_call_id=tid))
            round_log["tools"].append({
                "name": name,
                "args_preview": json.dumps(args, ensure_ascii=False)[:300],
                "result_preview": str(result)[:500],
            })

        log_steps.append(round_log)

    # ═══════════════════════════════════════════════════════════════════════
    # 阶段 2：强制合成（不带工具，确保返回的是摘要而非 raw output）
    # ═══════════════════════════════════════════════════════════════════════
    synthesize_prompt = (
        "TOOLS ARE NOW REMOVED. You can no longer search. "
        "Based on the information gathered above, write a research summary. "
        "Do NOT say what you would read next or plan further searches — "
        "just report what you found.\n\n"
        "Structure your summary:\n"
        "- Relevant commands/keywords and their format\n"
        "- Input file conventions (route section, molecule specification)\n"
        "- Reference node structure: ports, resource defaults, naming patterns\n"
        "- Any important caveats or gotchas\n"
        "- Manual or tool issues: note any problems with the manuals (incomplete, "
        "inaccurate, poorly formatted) or tools (wrong results, missing functionality)\n\n"
        "Be specific and factual. The parent agent depends on your findings.\n"
        "Plain text — no code blocks or JSON."
    )
    messages.append(HumanMessage(content=synthesize_prompt))

    try:
        # 不用 bind_tools —— 纯文本回复
        final_response = llm.invoke(messages)
    except Exception as e:
        log_steps.append({"round": "synthesize", "timestamp": datetime.now().isoformat(), "error": str(e)})
        return f"[Explore agent error during synthesis]: {e}"

    summary = _extract_text(final_response.content)

    log_steps.append({
        "round": "synthesize",
        "stage": "synthesis",
        "timestamp": datetime.now().isoformat(),
        "summary_preview": summary[:300],
    })

    # 截断保护
    if len(summary) > 5000:
        summary = summary[:5000] + "\n\n[... truncated ...]"

    # ── 保存 session log ──
    finished_at = datetime.now().isoformat()
    _save_log(
        project_id=project_id,
        projects_dir=projects_dir,
        started_at=started_at,
        finished_at=finished_at,
        software=software,
        question=question,
        avoid_directions=avoid_directions,
        summary=summary,
        steps=log_steps,
    )

    return summary


# ═══════════════════════════════════════════════════════════════════════════
# Session log 持久化
# ═══════════════════════════════════════════════════════════════════════════

def _save_log(
    project_id: str,
    projects_dir: str,
    started_at: str,
    finished_at: str,
    software: str,
    question: str,
    avoid_directions: str,
    summary: str,
    steps: list[dict[str, Any]],
) -> None:
    """将 Explore 子 Agent 的 session log 保存到项目 conversations 目录。"""
    if not project_id:
        return

    try:
        if not projects_dir:
            raise ValueError(
                "Explore sub-agent requires projects_dir (user-scoped projects root). "
                "The legacy V1 path fallback has been removed. "
                "Caller must provide a valid user-scoped projects directory."
            )
        log_dir = Path(projects_dir) / project_id / "conversations" / "explore"
        log_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        time_str = now.strftime("%H-%M-%S")
        base = f"explore_{time_str}"

        # JSON
        log_data = {
            "agent_type": "explore",
            "started_at": started_at,
            "finished_at": finished_at,
            "request": {
                "software": software,
                "question": question,
                "avoid_directions": avoid_directions,
            },
            "steps": steps,
            "summary": summary,
        }
        (log_dir / f"{base}.json").write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # TXT
        txt_lines = [
            "=" * 70,
            "MiQroForge Explore Sub-Agent Session Log",
            "=" * 70,
            f"Started:  {started_at}",
            f"Finished: {finished_at}",
            f"Software: {software}",
            "",
            "--- Question ---",
            question,
        ]
        if avoid_directions:
            txt_lines.append(f"\n--- Avoid ---\n{avoid_directions}")

        for i, step in enumerate(steps):
            txt_lines.append("")
            txt_lines.append("-" * 70)
            stage = step.get("stage", "?")
            rnd = step.get("round", i)
            txt_lines.append(f"  Round {rnd} ({stage})")
            txt_lines.append("-" * 70)

            if "error" in step:
                txt_lines.append(f"\n  [ERROR] {step['error']}")
            elif stage == "synthesis":
                txt_lines.append(f"\n  [Summary] {step.get('summary_preview', '')}")
            elif step.get("tool_calls"):
                txt_lines.append(f"\n  [Tool Calls] {', '.join(step['tool_calls'])}")
                for t in step.get("tools", []):
                    txt_lines.append(f"\n    [{t['name']}]")
                    txt_lines.append(f"      args:   {t['args_preview']}")
                    txt_lines.append(f"      result: {t['result_preview'][:200]}")

        txt_lines.append("")
        txt_lines.append("-" * 70)
        txt_lines.append("  Summary")
        txt_lines.append("-" * 70)
        for line in summary.split("\n"):
            txt_lines.append(f"  {line}")

        txt_lines.append("")
        txt_lines.append("=" * 70)
        txt_lines.append("End of Explore Session Log")
        txt_lines.append("=" * 70)

        (log_dir / f"{base}.txt").write_text("\n".join(txt_lines), encoding="utf-8")

    except Exception:
        pass  # log 失败不影响主流程


def _extract_text(content: Any) -> str:
    """从 LangChain message content 提取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)
