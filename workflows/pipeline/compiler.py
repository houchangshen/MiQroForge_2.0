"""MF 工作流编译器。

将校验通过的 MFWorkflow + resolved NodeSpecs 编译为 Argo Workflow YAML。

映射规则：
- 每个 MFNodeInstance → 一个 Argo template
  - compute → container template (base_image + resources + profile ConfigMap 挂载)
  - lightweight → script template (python + inline_script)
- 每个 StreamOutputPort → Argo output parameter, valueFrom.path: /mf/output/{port_name}
- 每个 MFConnection → DAG task argument ("{{tasks.src_id.outputs.parameters.port_name}}")
- onboard_params → DAG task argument（直接传值）
- resources → Argo resources.requests/limits
- 自动计算 DAG dependencies 从 connections
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

from nodes.schemas import (
    BaseImageRegistry,
    ComputeExecutionConfig,
    LightweightExecutionConfig,
    NodeSpec,
)
from nodes.schemas.io import GateDefault
from nodes.schemas.resources import ComputeResources
from nodes.schemas.resource_defaults import get_resource_defaults
from nodes.schemas.shared_params import load_shared_params

from .models import MFWorkflow, MFNodeInstance


# ═══════════════════════════════════════════════════════════════════════════
# 模块常量
# ═══════════════════════════════════════════════════════════════════════════

# 临时节点 Python 镜像（与 lightweight 节点一致）
_EPHEMERAL_PYTHON_VERSION = "3.11"

def _get_deploy_namespace() -> str:
    """读取 ARGO_NAMESPACE 作为部署命名空间。

    namespace 是部署层面的事，不属于 MF YAML。
    直接读 os.environ（load_dotenv 已在 api/config.py 导入时写入），
    避免 get_settings() 的 lru_cache 在 Settings 初始化过早时缓存空值。
    """
    import os
    return os.environ.get("ARGO_NAMESPACE", "")


def _get_pvc_name() -> str:
    """PVC 名用 ARGO_NAMESPACE，方便开发版/稳定版并行。"""
    import os
    return os.environ.get("ARGO_NAMESPACE", "")


def _workspace_volume_mount(project_id: str = "") -> dict[str, str]:
    """返回 workspace volumeMount dict。

    PVC hostPath = userdata/workspace/，subPath = proj_{pid}/。
    全程真实目录，零 symlink。
    """
    m: dict[str, str] = {"name": "workspace", "mountPath": "/mf/workspace"}
    if project_id:
        m["subPath"] = f"proj_{project_id}"
    return m


def _workspace_volume() -> dict[str, Any]:
    """返回 workspace volume dict（PVC 引用）。"""
    return {
        "name": "workspace",
        "persistentVolumeClaim": {"claimName": _get_pvc_name()},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════════════


def _slugify(name: str) -> str:
    """将任意字符串转换为合法的 Kubernetes RFC 1123 subdomain 名称。

    规则：全小写，空格/下划线/特殊字符→连字符，首尾必须是字母或数字，
    连续连字符折叠为单个，最长 52 字符（为随机后缀留余量）。
    """
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)   # 非法字符 → 连字符
    s = re.sub(r"-{2,}", "-", s)         # 连续连字符折叠
    s = s.strip("-")                      # 去除首尾连字符
    return s[:52] or "workflow"           # 兜底不能为空


def compile_to_argo(
    workflow: MFWorkflow,
    resolved_nodes: dict[str, NodeSpec],
    *,
    project_root: Path | None = None,
    docker_hub_mirror: str = "",
    ephemeral_logs: dict[str, Any] | None = None,
    project_id: str = "",
    username: str = "",
) -> dict[str, Any]:
    """将 MFWorkflow 编译为 Argo Workflow YAML dict。

    Parameters:
        workflow: 已校验的 MFWorkflow。
        resolved_nodes: 节点 ID → NodeSpec 映射（来自 ValidationReport）。
        project_root: 项目根目录，用于查找 base_images/registry.yaml 和 workspace/ 文件。
        username: 提交用户（用于内部认证 token）。
        docker_hub_mirror: Docker Hub 国内镜像加速站域名（如 docker.m.daocloud.io）。
            设置后，无 registry.yaml 条目的 Docker Hub 官方镜像将通过该镜像站拉取。
        ephemeral_logs: 已废弃，不再使用（临时节点改为运行时调用 Agent API）。
        project_id: 项目 ID，注入到临时节点环境变量中用于日志关联。

    Returns:
        Argo Workflow YAML 结构（可直接 yaml.dump）。

    Raises:
        ValueError: 编译错误（如镜像找不到）。
    """
    if project_root is None:
        project_root = Path.cwd()

    registry = _load_image_registry(project_root)

    # 将工作流名称规范化为合法的 Kubernetes 资源名（RFC 1123 subdomain）
    slug = _slugify(workflow.name)

    # 构建 DAG dependencies
    dep_map = _build_dependency_map(workflow)

    # 传播 fan-out：从显式 sweep 节点 BFS 传播 withParam 到下游
    auto_fan_out, sweep_source, sweep_origin = _propagate_sweep(workflow)

    # 检测 fan-in 节点（接收聚合 sweep 输出的节点）
    fan_in_map = _detect_fan_in_nodes(workflow, auto_fan_out, sweep_source, sweep_origin)

    # 构建 connection 信息：target (node_id, port_name) → (src_node_id, src_port_name)
    conn_map: dict[tuple[str, str], tuple[str, str]] = {}
    for conn in workflow.connections:
        key = (conn.target_node_id, conn.target_port_name)
        conn_map[key] = (conn.source_node_id, conn.source_port_name)

    # 计算被连接的输出端口集合：{(src_node_id, src_port_name)}
    # 只有被下游节点消费的端口才需要作为 Argo output parameter 收集
    # 未连接的大型二进制输出（如 gbw_file）跳过，避免 "request entity too large" 错误
    connected_outputs: set[tuple[str, str]] = set()
    for conn in workflow.connections:
        connected_outputs.add((conn.source_node_id, conn.source_port_name))

    # ── 嵌套 DAG：识别 sweep 链并构建 pipeline ─────────────────────────────
    sweep_chains = _identify_sweep_chains(
        workflow, auto_fan_out, sweep_source, sweep_origin, conn_map,
    )

    # 构建 pipeline 重映射结构
    pipelined_nodes: set[str] = set()
    inner_to_pipeline: dict[str, str] = {}   # inner_id → pipeline_task_name
    # (inner_id, port) → (pipeline_task_name, output_param_name)
    port_remap: dict[tuple[str, str], tuple[str, str]] = {}

    for chain in sweep_chains:
        pipeline_name = f"sweep-pipeline-{chain.sweep_node_id}"
        pipelined_nodes.update(chain.inner_node_ids)
        for nid in chain.inner_node_ids:
            inner_to_pipeline[nid] = pipeline_name
        # 构建 port_remap — 注意与 pipeline template output 命名保持一致
        seen_names: set[str] = set()
        for inner_id, port_name in chain.output_ports:
            if port_name in seen_names:
                out_name = f"{inner_id}--{port_name}"
            else:
                out_name = port_name
            seen_names.add(out_name)
            port_remap[(inner_id, port_name)] = (pipeline_name, out_name)

    # 重映射 dep_map：外层节点对内层节点的依赖 → 对 pipeline task 的依赖
    for target_id in list(dep_map.keys()):
        if target_id in pipelined_nodes:
            continue  # 内层节点的依赖由 pipeline 模板内部管理
        remapped: set[str] = set()
        for dep_id in dep_map[target_id]:
            if dep_id in inner_to_pipeline:
                remapped.add(inner_to_pipeline[dep_id])
            else:
                remapped.add(dep_id)
        dep_map[target_id] = remapped

    # 重映射 conn_map：外层节点从内层节点获取的输入 → 从 pipeline task 获取
    for key in list(conn_map.keys()):
        target_id, _target_port = key
        if target_id in pipelined_nodes:
            continue  # 内层节点的连接由 pipeline 模板内部管理
        src_id, src_port = conn_map[key]
        remap_key = (src_id, src_port)
        if remap_key in port_remap:
            pipeline_task, out_name = port_remap[remap_key]
            conn_map[key] = (pipeline_task, out_name)

    # 构建 templates 和 DAG tasks
    templates: list[dict[str, Any]] = []
    dag_tasks: list[dict[str, Any]] = []

    for node_inst in workflow.nodes:
        spec = resolved_nodes[node_inst.id]
        template_name = f"mf-{node_inst.id}"

        # 所有节点仍创建 template（pipeline 内层引用它们）
        template = _build_template(
            node_inst=node_inst,
            node_inst_id=node_inst.id,
            template_name=template_name,
            spec=spec,
            registry=registry,
            workflow=workflow,
            connected_outputs=connected_outputs,
            docker_hub_mirror=docker_hub_mirror,
            project_root=project_root,
            resolved_nodes=resolved_nodes,
            auto_fan_out=auto_fan_out,
            sweep_source=sweep_source,
            fan_in_map=fan_in_map,
            project_id=project_id,
            username=username,
        )
        templates.append(template)

        # 被 pipeline 管理的节点不在外层 DAG 创建 task
        if node_inst.id in pipelined_nodes:
            continue

        # 构建外层 DAG task（dep_map/conn_map 已重映射，自动引用 pipeline）
        task = _build_dag_task(
            node_inst=node_inst,
            template_name=template_name,
            spec=spec,
            dep_map=dep_map,
            conn_map=conn_map,
            resolved_nodes=resolved_nodes,
            workflow=workflow,
            project_root=project_root,
            auto_fan_out=auto_fan_out,
            sweep_source=sweep_source,
            sweep_origin=sweep_origin,
            fan_in_map=fan_in_map,
        )
        dag_tasks.append(task)

    # 为每个 sweep chain 创建 pipeline DAG 模板 + 外层 DAG task
    for chain in sweep_chains:
        pipeline_tmpl = _build_sweep_pipeline_template(
            chain, resolved_nodes, workflow, conn_map,
        )
        templates.append(pipeline_tmpl)

        pipeline_task = _build_sweep_pipeline_dag_task(
            chain, inner_to_pipeline=inner_to_pipeline, port_remap=port_remap,
        )
        dag_tasks.append(pipeline_task)

    # 组装 Argo Workflow
    resolved_ns = _get_deploy_namespace()
    argo_wf: dict[str, Any] = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "generateName": f"{slug}-",
            "namespace": resolved_ns,
            "labels": {
                "miqroforge.io/workflow": slug,
                "miqroforge.io/mf-version": workflow.mf_version,
            },
        },
        "spec": {
            "entrypoint": "mf-dag",
            "serviceAccountName": f"{resolved_ns}-workflow-sa",
            "templates": [
                {
                    "name": "mf-dag",
                    "dag": {
                        "tasks": dag_tasks,
                    },
                },
                *templates,
            ],
        },
    }

    return argo_wf


def compile_to_yaml_str(
    workflow: MFWorkflow,
    resolved_nodes: dict[str, NodeSpec],
    *,
    project_root: Path | None = None,
    docker_hub_mirror: str = "",
) -> str:
    """编译并返回 YAML 字符串。"""
    argo_dict = compile_to_argo(
        workflow, resolved_nodes, project_root=project_root, docker_hub_mirror=docker_hub_mirror
    )
    return yaml.dump(
        argo_dict,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _build_ephemeral_wrapper_script(
    node_inst: MFNodeInstance,
    workflow: MFWorkflow,
    resolved_nodes: dict[str, NodeSpec],
) -> str:
    """生成临时节点的 Pod wrapper 脚本（薄 API 调用层）。

    运行时流程：
    1. 读取 /mf/input/ 中的真实输入数据（含 _sweep_keys 文件）
    2. POST /api/v1/agents/ephemeral（一次性调用，服务端完成完整循环）
    3. 执行返回的脚本 + 写图片清单
    """

    # 收集连接上下文
    upstream: list[dict[str, str]] = []
    downstream: list[dict[str, str]] = []
    for conn in workflow.connections:
        if conn.target_node_id == node_inst.id:
            src_spec = resolved_nodes.get(conn.source_node_id)
            upstream.append({
                "source": conn.source_node_id,
                "port": conn.source_port_name,
                "description": src_spec.metadata.name if src_spec else conn.source_node_id,
            })
        if conn.source_node_id == node_inst.id:
            tgt_spec = resolved_nodes.get(conn.target_node_id)
            downstream.append({
                "target": conn.target_node_id,
                "port": conn.target_port_name,
                "description": tgt_spec.metadata.name if tgt_spec else conn.target_node_id,
            })

    ports_dict: dict[str, Any] = {}
    if node_inst.ports:
        ports_dict = {"inputs": node_inst.ports.inputs, "outputs": node_inst.ports.outputs}

    context: dict[str, Any] = {
        "node_id": node_inst.id,
        "upstream": upstream,
        "downstream": downstream,
        "onboard_params": node_inst.onboard_params,
    }
    # sweep 上下文由 generator 端从 input_data 中的 _sweep_keys 文件自动推断，无需 wrapper 传递

    description = node_inst.get_generation_description()

    # 用 json.dumps 生成 Python dict 字面量（安全转义引号）
    _jd = json.dumps

    return f'''#!/usr/bin/env python3
# MF Ephemeral Node Runtime Wrapper (thin API call layer)
# 服务端 API 完成完整的 generate→execute→evaluate 循环

import os, sys, json, subprocess
import requests

MF_API_URL = os.environ.get("MF_API_URL", "http://localhost:8200")
MF_INTERNAL_TOKEN = os.environ.get("MF_INTERNAL_TOKEN", "")
MF_USER = os.environ.get("MF_USER", "")

DESCRIPTION = {_jd(description)}
PORTS = {_jd(ports_dict)}
CONTEXT = {_jd(context)}

def main():
    # 1. 读取真实输入数据
    input_data = {{}}
    input_dir = "/mf/input"
    if os.path.isdir(input_dir):
        for fname in sorted(os.listdir(input_dir)):
            fpath = os.path.join(input_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, "r", errors="replace") as f:
                    input_data[fname] = f.read()

    # 2. 调用 Agent API（服务端完成 generate→sandbox→evaluate 完整循环）
    headers = {{}}
    if MF_INTERNAL_TOKEN and MF_USER:
        headers["X-Internal-Token"] = MF_INTERNAL_TOKEN
        headers["X-MF-User"] = MF_USER
    try:
        resp = requests.post(f"{{MF_API_URL}}/api/v1/agents/ephemeral",
                              json={{
            "description": DESCRIPTION,
            "ports": PORTS,
            "context": CONTEXT,
            "input_data": input_data,
            "run_name": os.environ.get("MF_RUN_NAME", ""),
            "project_id": os.environ.get("MF_PROJECT_ID", ""),
        }}, headers=headers or None, timeout=600)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        print(f"[MF Wrapper] Agent API 调用失败: {{e}}", file=sys.stderr)
        sys.exit(1)

    # 检查 Agent API 报告的成功状态
    api_success = result.get("success", True)
    api_rc = result.get("return_code", 0)
    if not api_success or api_rc != 0:
        api_stderr = result.get("stderr", "")[:2000]
        print(f"[MF Wrapper] Agent 报告失败: success={{api_success}}, return_code={{api_rc}}", file=sys.stderr)
        if api_stderr:
            print(f"[MF Wrapper] stderr: {{api_stderr}}", file=sys.stderr)
        sys.exit(1)

    script = result.get("script", "")
    if not script:
        print("[MF Wrapper] Agent API 未返回脚本", file=sys.stderr)
        sys.exit(1)

    # 3. 执行最终脚本
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mf_exec_") as tmpdir:
        script_path = os.path.join(tmpdir, "script.py")
        with open(script_path, "w") as f:
            f.write(script)

        env = os.environ.copy()
        env.setdefault("MF_INPUT_DIR", "/mf/input")
        env.setdefault("MF_OUTPUT_DIR", "/mf/output")
        env.setdefault("MF_WORKSPACE_DIR", "/mf/workspace")

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True,
                timeout=120, cwd=tmpdir, env=env,
            )
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("[MF Wrapper] 脚本执行超时", file=sys.stderr)
            sys.exit(1)

    # 4. 写图片清单到 output 供前端 inspector 使用（仅使用 Agent API 实际产出的图片）
    import pathlib as _pl
    api_image_files = result.get("image_files", [])
    if api_image_files:
        try:
            _pl.Path("/mf/output/_mf_images").write_text("\\n".join(sorted(set(api_image_files))))
        except Exception:
            pass

    print("[MF Wrapper] Done.")


if __name__ == "__main__":
    main()
'''


def _build_nodegen_wrapper_script(
    node_inst: MFNodeInstance,
    workflow: MFWorkflow,
    resolved_nodes: dict[str, NodeSpec],
    project_id: str,
) -> str:
    """生成 Prefab 节点的 Pod wrapper 脚本。

    与 ephemeral wrapper 不同，此 wrapper 向 API 传递 prefab_node_id
    （而非内嵌 nodespec 内容），由 API 服务端从 proj/tmp/<node_id>/ 或 userdata/nodes/
    读取预生成的 nodespec + run.sh。

    运行时流程：
    1. 读取 /mf/input/ 中的真实输入数据（含 onboard params 和 _software）
    2. POST /api/v1/agents/node/run（传递 prefab_node_id + input_data + target_software）
    3. 检查 evaluation.passed 和 error
    4. 将 outputs 写入 /mf/output/
    """
    description = node_inst.get_generation_description()
    prefab_node_id = node_inst.id  # 直接使用节点 ID，对应 tmp/<node_id>/ 下的预生成文件
    # _software 来自 inspector software selector，不在 NodeSpec onboard_inputs 中
    software_hint = (node_inst.onboard_params or {}).get("_software", "")

    # ── 端口名解析（优先级：pregenerate → resolved_nodes → 通用名）──
    stream_input_names: list[str] = []
    stream_output_names: list[str] = []

    # 1) pregenerate: -1 循环产物，直接包含端口名列表
    if node_inst.pregenerate:
        stream_input_names = node_inst.pregenerate.get("stream_inputs", []) or []
        stream_output_names = node_inst.pregenerate.get("stream_outputs", []) or []

    # 2) resolved_nodes: validator 从 tmp/userdata 解析的 NodeSpec
    if not stream_input_names and resolved_nodes:
        node_spec = resolved_nodes.get(node_inst.id) or resolved_nodes.get(node_inst.node)
        if node_spec:
            stream_input_names = [p.name for p in node_spec.stream_inputs]
            stream_output_names = [p.name for p in node_spec.stream_outputs]

    # 3) 通用名: I1/I2..., O1/O2...
    ports = node_inst.ports
    if not stream_input_names and ports:
        stream_input_names = [f"I{i+1}" for i in range(ports.inputs)] if ports.inputs > 0 else []
    if not stream_output_names and ports:
        stream_output_names = [f"O{i+1}" for i in range(ports.outputs)] if ports.outputs > 0 else []

    _jd = json.dumps

    return f'''#!/usr/bin/env python3
# MF Prefab Runtime Wrapper — calls /api/v1/agents/node/run
# prefab_node_id → API 从 proj/tmp/<node_id>/ 或 userdata/nodes/ 读取预生成 nodespec

import os, sys, json, subprocess
import requests

MF_API_URL = os.environ.get("MF_API_URL", "http://localhost:8200")
MF_INTERNAL_TOKEN = os.environ.get("MF_INTERNAL_TOKEN", "")
MF_USER = os.environ.get("MF_USER", "")

DESCRIPTION = {_jd(description)}
PREFAB_NODE_ID = {_jd(prefab_node_id)}
SOFTWARE_HINT = {_jd(software_hint)}
INPUT_PORTS = {_jd(stream_input_names)}
OUTPUT_PORTS = {_jd(stream_output_names)}

def main():
    # 1. 读取真实输入数据（含 stream inputs 和 onboard params，不含 _software）
    input_data = {{}}
    input_dir = "/mf/input"
    if os.path.isdir(input_dir):
        for fname in sorted(os.listdir(input_dir)):
            fpath = os.path.join(input_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, "r", errors="replace") as f:
                    input_data[fname] = f.read()

    # 2. 调用 Agent API（服务端完成 sandbox → evaluate 完整循环）
    headers = {{}}
    if MF_INTERNAL_TOKEN and MF_USER:
        headers["X-Internal-Token"] = MF_INTERNAL_TOKEN
        headers["X-MF-User"] = MF_USER
    try:
        resp = requests.post(f"{{MF_API_URL}}/api/v1/agents/node/run",
                              json={{
            "semantic_type": "compute",
            "description": DESCRIPTION,
            "target_software": SOFTWARE_HINT or None,
            "input_ports": INPUT_PORTS or None,
            "output_ports": OUTPUT_PORTS or None,
            "category": "chemistry",
            "input_data": input_data,
            "prefab_node_id": PREFAB_NODE_ID,
            "run_name": os.environ.get("MF_RUN_NAME", ""),
            "project_id": os.environ.get("MF_PROJECT_ID", ""),
        }}, headers=headers or None, timeout=1800)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        print(f"[MF Prefab Wrapper] Agent API call failed: {{e}}", file=sys.stderr)
        sys.exit(1)

    # 3. 检查 Agent 报告的状态
    error = result.get("error")
    if error:
        print(f"[MF Prefab Wrapper] Agent error: {{error}}", file=sys.stderr)
        sys.exit(1)

    evaluation = result.get("evaluation")
    if evaluation and not evaluation.get("passed", True):
        issues = evaluation.get("issues", [])
        print(f"[MF Prefab Wrapper] Evaluation failed: {{issues}}", file=sys.stderr)
        sys.exit(1)

    # 4. 将 outputs 写入 /mf/output/
    import pathlib as _pl
    _pl.Path("/mf/output").mkdir(parents=True, exist_ok=True)
    output_data = result.get("outputs", {{}})
    for port_name, content in output_data.items():
        out_path = _pl.Path("/mf/output") / port_name
        out_path.write_text(str(content), encoding="utf-8")

    # 5. 写出 quality gate 结果
    if evaluation:
        passed_str = "true" if evaluation.get("passed", False) else "false"
        gate_results = evaluation.get("gate_results", {{}})
        for gate_name, gate_val in gate_results.items():
            gate_path = _pl.Path("/mf/output") / gate_name
            gate_path.write_text(str(gate_val))

    print("[MF Prefab Wrapper] Done.")

if __name__ == "__main__":
    main()
'''


# ═══════════════════════════════════════════════════════════════════════════
# ConfigMap 生成
# ═══════════════════════════════════════════════════════════════════════════


def generate_configmaps(
    workflow: MFWorkflow,
    resolved_nodes: dict[str, NodeSpec],
    *,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """为所有 compute 节点生成 ConfigMap 清单。

    Parameters:
        workflow: 已校验的 MFWorkflow。
        resolved_nodes: 节点 ID → NodeSpec。
        project_root: 项目根目录。

    Returns:
        ConfigMap YAML dict 列表。
    """
    if project_root is None:
        project_root = Path.cwd()

    resolved_ns = _get_deploy_namespace()
    configmaps: list[dict[str, Any]] = []

    for node_inst in workflow.nodes:
        spec = resolved_nodes[node_inst.id]

        # compute 节点始终生成 ConfigMap
        # lightweight 节点仅在 entrypoint_script 模式下生成 ConfigMap
        if isinstance(spec.execution, LightweightExecutionConfig):
            if not spec.execution.entrypoint_script:
                continue
        elif not isinstance(spec.execution, ComputeExecutionConfig):
            continue

        cm_name = _configmap_name(spec)

        # 从 nodespec 旁的 profile/ 目录读取文件
        profile_data = _load_profile_files(node_inst, spec, project_root)
        if not profile_data:
            continue

        cm: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": cm_name,
                "namespace": resolved_ns,
                "labels": {
                    "miqroforge.io/node": spec.metadata.name,
                    "miqroforge.io/version": spec.metadata.version,
                },
            },
            "data": profile_data,
        }
        configmaps.append(cm)

    return configmaps


# ═══════════════════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════════════════


def _load_image_registry(project_root: Path) -> BaseImageRegistry:
    """加载 base_images/registry.yaml。"""
    registry_path = project_root / "nodes" / "base_images" / "registry.yaml"
    if not registry_path.exists():
        return BaseImageRegistry(images=[])
    with registry_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return BaseImageRegistry.model_validate(data)


def _resolve_resources(
    spec: NodeSpec,
    onboard_params: dict[str, Any],
) -> dict[str, Any]:
    """解析 parametrize，返回实际资源值。

    优先级：onboard_params 实例覆盖 > nodespec default > nodespec 静态值。
    """
    res = spec.resources
    if not isinstance(res, ComputeResources) or not res.parametrize:
        return {}

    defaults_config = get_resource_defaults()
    overrides: dict[str, Any] = {}
    onboard_map = {p.name: p for p in spec.onboard_inputs}

    for res_field in res.parametrize:
        param_name = defaults_config.get(res_field, {}).get("param_name", res_field)
        raw = onboard_params.get(param_name)
        if raw is not None and str(raw).strip() != "":
            overrides[res_field] = raw
            continue
        # 回退到 onboard input 默认值
        param = onboard_map.get(param_name)
        if param is not None and param.default is not None:
            overrides[res_field] = param.default

    return overrides


def _build_dependency_map(workflow: MFWorkflow) -> dict[str, set[str]]:
    """从 connections 构建 DAG 依赖关系。

    Returns:
        dict[target_node_id, set[source_node_id]]
    """
    dep_map: dict[str, set[str]] = defaultdict(set)
    for conn in workflow.connections:
        dep_map[conn.target_node_id].add(conn.source_node_id)
    return dep_map


def _propagate_sweep(
    workflow: MFWorkflow,
) -> tuple[set[str], dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """BFS 从显式 sweep 节点传播 fan-out 到下游。

    Returns:
        auto_fan_out: 自动 fan-out 的节点 ID 集合
        sweep_source: node_id → (最近上游任务名, 连接端口名)  — 用于 {{item}} 重写判断
        sweep_origin: node_id → (原始显式 sweep 节点 ID, 其 sweep 端口名)  — 用于 withParam
    """
    # 构建前向邻接表：src_node → [(tgt_node, src_port_name)]
    forward: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for conn in workflow.connections:
        forward[conn.source_node_id].append(
            (conn.target_node_id, conn.source_port_name)
        )

    # 识别显式 sweep 节点
    node_map = {n.id: n for n in workflow.nodes}
    explicit_sweeps = {
        n.id for n in workflow.nodes if n.parallel_sweep is not None
    }

    auto_fan_out: set[str] = set()
    sweep_source: dict[str, tuple[str, str]] = {}
    sweep_origin: dict[str, tuple[str, str]] = {}

    # BFS 从每个显式 sweep 节点出发
    queue: deque[str] = deque(explicit_sweeps)
    # 阻止传播的节点集合：fan_in、显式 sweep、生成类节点（ephemeral / prefab 均不可在内部分支）
    blocked: set[str] = {
        n.id for n in workflow.nodes
        if n.fan_in or n.parallel_sweep is not None or n.ephemeral or n.prefab
    }
    # 记录已入队的节点，避免重复入队
    enqueued: set[str] = set(explicit_sweeps)

    while queue:
        current = queue.popleft()
        # 追溯当前节点的原始 sweep 源（如果 current 本身是显式 sweep，就是自己）
        if current in explicit_sweeps:
            current_origin = current
        else:
            current_origin = sweep_origin.get(current, (current, ""))[0]

        for tgt_node_id, src_port_name in forward.get(current, []):
            if tgt_node_id in blocked:
                continue
            tgt_node = node_map.get(tgt_node_id)
            if tgt_node is None:
                continue
            # 只有有下游的节点才需要 auto fan-out（叶子节点不需要 withParam）
            if tgt_node_id not in forward:
                continue
            # 多个上游 sweep 源 → 发出 warning
            if tgt_node_id in auto_fan_out:
                existing = sweep_source[tgt_node_id]
                logger.warning(
                    "节点 '%s' 有多个 sweep 源: '%s' 和 '%s'，使用后者",
                    tgt_node_id, existing[0], current,
                )
            auto_fan_out.add(tgt_node_id)
            sweep_source[tgt_node_id] = (current, src_port_name)
            sweep_origin[tgt_node_id] = (current_origin, src_port_name)
            if tgt_node_id not in enqueued:
                enqueued.add(tgt_node_id)
                queue.append(tgt_node_id)

    return auto_fan_out, sweep_source, sweep_origin


def _detect_fan_in_nodes(
    workflow: MFWorkflow,
    auto_fan_out: set[str],
    sweep_source: dict[str, tuple[str, str]],
    sweep_origin: dict[str, tuple[str, str]],
) -> dict[str, list[tuple[str, list[Any]]]]:
    """检测接收聚合 sweep 输出的 fan-in 节点。

    一个节点是 fan-in 节点，当且仅当：
    1. 它不在 auto_fan_out 中（不是 sweep 传播链路的一部分）
    2. 它不是显式 parallel_sweep 节点
    3. 它不是显式 fan_in=True 的节点
    4. 它的至少一个上游是 sweep 参与者（显式 sweep 或 auto_fan_out）

    Returns:
        {fan_in_node_id: [(原始sweep源节点id, sweep_values), ...]}
    """
    node_map = {n.id: n for n in workflow.nodes}
    explicit_sweeps = {
        n.id for n in workflow.nodes if n.parallel_sweep is not None
    }
    blocked = explicit_sweeps | auto_fan_out

    # 构建反向连接表：target_node → [source_nodes]
    reverse: dict[str, list[str]] = defaultdict(list)
    for conn in workflow.connections:
        reverse[conn.target_node_id].append(conn.source_node_id)

    fan_in_map: dict[str, list[tuple[str, list[Any]]]] = {}

    for node_inst in workflow.nodes:
        nid = node_inst.id
        # 跳过 sweep 参与者和显式 fan-in 节点
        if nid in blocked or node_inst.fan_in:
            continue
        # 检查上游是否有 sweep 参与者
        for src_id in reverse.get(nid, []):
            # 追溯到原始 sweep 源
            orig_src_id = src_id
            if src_id in auto_fan_out:
                orig_src_id, _ = sweep_origin[src_id]
            src_node = node_map.get(orig_src_id)
            if src_node and src_node.parallel_sweep is not None:
                fan_in_map.setdefault(nid, []).append(
                    (orig_src_id, src_node.parallel_sweep.values)
                )

    return fan_in_map


def _find_sweep_param(node_inst: MFNodeInstance) -> str:
    """找出 onboard_params 中包含 {{item}} 的参数名。"""
    for key, val in node_inst.onboard_params.items():
        if isinstance(val, str) and "{{item}}" in val:
            return key
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 嵌套 DAG（Sweep Pipeline）
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class SweepChain:
    """描述一个 sweep 链的嵌套 DAG 子图。

    sweep 链 = 显式 sweep 节点 + 所有被 BFS 传播的 auto_fan_out 节点。
    fan-in 节点不在内层，在外层 DAG 接收 pipeline 聚合输出。
    """

    sweep_node_id: str
    """显式 sweep 源节点 ID。"""

    sweep_values: list[Any]
    """sweep 值列表（parallel_sweep.values）。"""

    inner_node_ids: set[str]
    """内层 DAG 中的所有节点 ID（含 sweep 源）。"""

    fan_in_connections: list[tuple[str, str, str, str]]
    """从内层到外层的连接：(inner_node_id, inner_port, outer_node_id, outer_port)。"""

    inner_deps: dict[str, set[str]]
    """内层 DAG 中的依赖关系：target_id → {source_ids}。"""

    output_ports: list[tuple[str, str]]
    """需要转发到外层的输出端口：(inner_node_id, port_name)。"""

    external_inputs: list[tuple[str, str, str, str]]
    """外层节点提供给内层节点的输入：(inner_node_id, inner_port, outer_node_id, outer_port)。"""

    external_deps: set[str]
    """pipeline task 在外层 DAG 中的额外依赖（提供 external_inputs 的外层节点）。"""


def _identify_sweep_chains(
    workflow: MFWorkflow,
    auto_fan_out: set[str],
    sweep_source: dict[str, tuple[str, str]],
    sweep_origin: dict[str, tuple[str, str]],
    conn_map: dict[tuple[str, str], tuple[str, str]],
) -> list[SweepChain]:
    """从 auto_fan_out 集合提取嵌套 DAG 子图。

    内层子图 = 显式 sweep 节点 + 所有 auto_fan_out 节点（按 sweep_origin 归属）。
    fan-in 节点不在内层，在外层 DAG 接收 pipeline 聚合输出。

    只有当内层节点有连接到外层节点时（即存在 fan-in），才创建 pipeline。
    使用 conn_map 而非 raw connections 确保多连接到同一端口时行为一致。
    """
    node_map = {n.id: n for n in workflow.nodes}
    explicit_sweeps = {
        n.id for n in workflow.nodes if n.parallel_sweep is not None
    }

    chains: list[SweepChain] = []

    for sweep_id in sorted(explicit_sweeps):
        sweep_node = node_map[sweep_id]

        # 内层节点：sweep 源 + 所有 origin 指向此 sweep 的 auto_fan_out 节点
        inner_ids: set[str] = {sweep_id}
        for afo_id in auto_fan_out:
            origin_id = sweep_origin.get(afo_id, (None, None))[0]
            if origin_id == sweep_id:
                inner_ids.add(afo_id)

        # 从 conn_map 提取 fan-in 连接（内层 → 外层）和外部输入（外层 → 内层）
        fan_in_conns: list[tuple[str, str, str, str]] = []
        output_port_set: set[tuple[str, str]] = set()
        external_inputs: list[tuple[str, str, str, str]] = []
        external_dep_ids: set[str] = set()

        for (tgt_id, tgt_port), (src_id, src_port) in conn_map.items():
            if src_id in inner_ids and tgt_id not in inner_ids:
                # 内层节点输出到外层 → fan-in 连接
                fan_in_conns.append((src_id, src_port, tgt_id, tgt_port))
                output_port_set.add((src_id, src_port))
            elif tgt_id in inner_ids and src_id not in inner_ids:
                # 外层节点输入到内层 → external input
                external_inputs.append((tgt_id, tgt_port, src_id, src_port))
                external_dep_ids.add(src_id)

        # 没有 fan-in 连接 → 不创建 pipeline（如 sweep-only 工作流）
        if not fan_in_conns:
            continue

        # 内层依赖关系（只看内层之间的连接）
        inner_deps: dict[str, set[str]] = defaultdict(set)
        for (tgt_id, _tgt_port), (src_id, _src_port) in conn_map.items():
            if src_id in inner_ids and tgt_id in inner_ids:
                inner_deps[tgt_id].add(src_id)

        chains.append(SweepChain(
            sweep_node_id=sweep_id,
            sweep_values=sweep_node.parallel_sweep.values,
            inner_node_ids=inner_ids,
            fan_in_connections=fan_in_conns,
            inner_deps=dict(inner_deps),
            output_ports=list(output_port_set),
            external_inputs=external_inputs,
            external_deps=external_dep_ids,
        ))

    return chains


def _build_sweep_pipeline_template(
    chain: SweepChain,
    resolved_nodes: dict[str, NodeSpec],
    workflow: MFWorkflow,
    conn_map: dict[tuple[str, str], tuple[str, str]],
) -> dict[str, Any]:
    """为一个 SweepChain 构建嵌套 DAG 模板。

    外层 DAG 用 withParam 并行化 N 个实例，每个实例执行此内层 DAG。
    quality gate 在内层 DAG 中自然生效。

    Returns:
        Argo template dict（DAG 类型）。
    """
    node_map = {n.id: n for n in workflow.nodes}
    gate_policy = _resolve_gate_policy(workflow)
    pipeline_name = f"sweep-pipeline-{chain.sweep_node_id}"

    # ── Pipeline input parameters ─────────────────────────────────────────
    input_params: list[dict[str, str]] = [{"name": "sweep_item"}]
    # 外部输入（内层节点依赖外层节点的输出）
    for _inner_id, _inner_port, outer_id, outer_port in chain.external_inputs:
        param_name = f"ext__{outer_id}__{outer_port}"
        # 去重（多个内层端口可能引用同一外部输出）
        if not any(p["name"] == param_name for p in input_params):
            input_params.append({"name": param_name})

    # ── Pipeline output parameters ────────────────────────────────────────
    # 转发内层节点的输出给外层 fan-in 节点
    output_params: list[dict[str, Any]] = []
    seen_output_names: set[str] = set()
    for inner_node_id, port_name in chain.output_ports:
        # 处理同名端口冲突
        if port_name in seen_output_names:
            param_name = f"{inner_node_id}--{port_name}"
        else:
            param_name = port_name
        seen_output_names.add(param_name)
        output_params.append({
            "name": param_name,
            "default": "",  # 兜底：quality gate 导致节点被 skip 时
            "valueFrom": {
                "parameter": f"{{{{tasks.{inner_node_id}.outputs.parameters.{port_name}}}}}",
            },
        })

    # ── 内层 DAG tasks ────────────────────────────────────────────────────
    inner_tasks: list[dict[str, Any]] = []

    for node_id in sorted(chain.inner_node_ids):
        node_inst = node_map[node_id]
        spec = resolved_nodes[node_id]

        task: dict[str, Any] = {
            "name": node_id,
            "template": f"mf-{node_id}",
        }

        # ── 内层依赖 + quality gate aware depends ────────────────────────
        deps = chain.inner_deps.get(node_id, set())
        if deps:
            must_succeed: set[str] = set()
            for dep_id in deps:
                dep_spec = resolved_nodes.get(dep_id)
                if dep_spec is None:
                    continue
                for gate in dep_spec.quality_gates:
                    effective = gate_policy.get(
                        (dep_id, gate.name), gate.gate_default
                    )
                    if effective == GateDefault.MUST_PASS:
                        must_succeed.add(dep_id)
                        break

            if must_succeed:
                dep_exprs = []
                for dep_id in sorted(deps):
                    dep_exprs.append(
                        f"{dep_id}.Succeeded" if dep_id in must_succeed else dep_id
                    )
                task["depends"] = " && ".join(dep_exprs)
            else:
                task["depends"] = " && ".join(sorted(deps))

        # ── Arguments: stream inputs + onboard params ─────────────────────
        arguments: list[dict[str, Any]] = []

        for port in spec.stream_inputs:
            key = (node_id, port.name)
            if key in conn_map:
                src_node_id, src_port_name = conn_map[key]
                if src_node_id in chain.inner_node_ids:
                    # 引用内层上游节点的输出
                    arguments.append({
                        "name": port.name,
                        "value": (
                            f"{{{{tasks.{src_node_id}.outputs.parameters"
                            f".{src_port_name}}}}}"
                        ),
                    })
                else:
                    # 引用 pipeline 输入参数（来自外层节点）
                    ext_param = f"ext__{src_node_id}__{src_port_name}"
                    arguments.append({
                        "name": port.name,
                        "value": f"{{{{inputs.parameters.{ext_param}}}}}",
                    })

        software = spec.metadata.tags.software or ""

        for param in spec.onboard_inputs:
            raw = node_inst.onboard_params.get(param.name)
            if raw is not None and str(raw).strip() != "":
                value = str(raw)
            elif param.default is not None:
                value = str(param.default)
            else:
                continue
            # _shared_param 翻译：canonical → 软件原生关键字
            if param.shared_param and software:
                value = _translate_shared_param(value, software, param.shared_param)
            # sweep 源节点：替换 {{item}} 为 pipeline 输入参数
            if node_id == chain.sweep_node_id:
                value = value.replace("{{item}}", "{{inputs.parameters.sweep_item}}")
            arguments.append({
                "name": param.name,
                "value": value,
            })

        if arguments:
            task["arguments"] = {"parameters": arguments}

        # ── Quality gate when conditions（内层上游的 quality gate）────────
        when_conditions: list[str] = []
        for dep_id in deps:
            dep_spec = resolved_nodes.get(dep_id)
            if dep_spec is None:
                continue
            for gate in dep_spec.quality_gates:
                effective = gate_policy.get(
                    (dep_id, gate.name), gate.gate_default
                )
                if effective == GateDefault.MUST_PASS:
                    when_conditions.append(
                        f"{{{{tasks.{dep_id}.outputs.parameters"
                        f"._qg_{gate.name}}}}} == true"
                    )
        if when_conditions:
            task["when"] = " && ".join(when_conditions)

        inner_tasks.append(task)

    # ── 组装模板 ──────────────────────────────────────────────────────────
    template: dict[str, Any] = {
        "name": pipeline_name,
        "inputs": {"parameters": input_params},
        "dag": {"tasks": inner_tasks},
    }
    if output_params:
        template["outputs"] = {"parameters": output_params}

    return template


def _build_sweep_pipeline_dag_task(
    chain: SweepChain,
    inner_to_pipeline: dict[str, str] | None = None,
    port_remap: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """在外层 DAG 中为 sweep pipeline 创建 task 条目。

    每个 item 触发一个独立的内层 DAG 实例，实现同流异步。
    如果 external deps/inputs 指向其他 pipeline 的内层节点，自动重映射。
    """
    if inner_to_pipeline is None:
        inner_to_pipeline = {}
    if port_remap is None:
        port_remap = {}

    pipeline_name = f"sweep-pipeline-{chain.sweep_node_id}"

    arguments: list[dict[str, Any]] = [
        {"name": "sweep_item", "value": "{{item}}"},
    ]

    # 传递外部依赖的输出作为 pipeline 参数
    seen_ext: set[str] = set()
    for _inner_id, _inner_port, outer_id, outer_port in chain.external_inputs:
        param_name = f"ext__{outer_id}__{outer_port}"
        if param_name not in seen_ext:
            seen_ext.add(param_name)
            # 如果外部节点是另一个 pipeline 的内层节点，重映射引用
            remap_key = (outer_id, outer_port)
            if remap_key in port_remap:
                p_task, p_out = port_remap[remap_key]
                value = (
                    f"{{{{tasks.{p_task}.outputs.parameters"
                    f".{p_out}}}}}"
                )
            else:
                value = (
                    f"{{{{tasks.{outer_id}.outputs.parameters"
                    f".{outer_port}}}}}"
                )
            arguments.append({"name": param_name, "value": value})

    task: dict[str, Any] = {
        "name": pipeline_name,
        "template": pipeline_name,
        "withParam": json.dumps(chain.sweep_values, ensure_ascii=False),
        "arguments": {"parameters": arguments},
    }

    # 外部依赖（pipeline 需要等待外部节点完成）
    # 如果外部节点自身被 pipeline 化，引用其 pipeline 任务名
    remapped_deps: set[str] = set()
    for dep_id in chain.external_deps:
        remapped_deps.add(inner_to_pipeline.get(dep_id, dep_id))
    if remapped_deps:
        task["depends"] = " && ".join(sorted(remapped_deps))

    return task


def _build_template(
    *,
    node_inst,  # MFNodeInstance
    node_inst_id: str,
    template_name: str,
    spec: NodeSpec,
    registry: BaseImageRegistry,
    workflow: MFWorkflow,
    connected_outputs: set[tuple[str, str]],
    docker_hub_mirror: str = "",
    project_root: Path | None = None,
    resolved_nodes: dict[str, NodeSpec] | None = None,
    auto_fan_out: set[str] | None = None,
    sweep_source: dict[str, tuple[str, str]] | None = None,
    fan_in_map: dict[str, list[tuple[str, list[Any]]]] | None = None,
    project_id: str = "",
    username: str = "",
) -> dict[str, Any]:
    """为单个节点构建 Argo template。

    只为有下游连接的 stream output 生成 Argo output parameter 收集规则。
    未连接的大型二进制输出（如 gbw_file）会被跳过，避免参数体积超限错误。
    Quality gate 输出始终收集（DAG depends 条件所需）。
    """
    if fan_in_map is None:
        fan_in_map = {}

    # 收集所有 input 参数名（stream inputs + onboard inputs）
    input_params: list[dict[str, str]] = []
    for port in spec.stream_inputs:
        input_params.append({"name": port.name})
    for param in spec.onboard_inputs:
        input_params.append({"name": param.name})

    # fan-in 临时节点：注入 _sweep_keys 作为隐式输入参数
    if node_inst_id in fan_in_map:
        input_params.append({"name": "_sweep_keys"})

    # 只收集被下游节点连接的 stream output 端口
    output_params: list[dict[str, Any]] = []
    for port in spec.stream_outputs:
        if (node_inst_id, port.name) in connected_outputs:
            output_params.append({
                "name": port.name,
                "valueFrom": {"path": f"/mf/output/{port.name}"},
            })
    # Quality gate 输出始终收集（DAG depends 条件所需，前缀 _qg_）
    for gate in spec.quality_gates:
        output_params.append({
            "name": f"_qg_{gate.name}",
            "valueFrom": {"path": f"/mf/output/{gate.name}"},
        })
    # Onboard outputs（非 quality gate）—— 始终收集，供 UI 和 runs/outputs.json 展示
    for ob_out in spec.onboard_outputs:
        if not ob_out.quality_gate:
            output_params.append({
                "name": ob_out.name,
                "valueFrom": {"path": f"/mf/output/{ob_out.name}"},
            })

    # 解析 parametrize（用实例的 onboard_params 覆盖静态资源值）
    resource_overrides = _resolve_resources(spec, node_inst.onboard_params)

    # ── Prefab 节点：生成 wrapper 脚本，运行时调用 /agents/node/run ───
    if node_inst.prefab:
        wrapper_source = _build_nodegen_wrapper_script(
            node_inst=node_inst,
            workflow=workflow,
            resolved_nodes=resolved_nodes or {},
            project_id=project_id,
        )
        return _build_prefab_template(
            template_name=template_name,
            script_source=wrapper_source,
            registry=registry,
            docker_hub_mirror=docker_hub_mirror,
            input_params=input_params,
            output_params=output_params,
            onboard_params=node_inst.onboard_params,
            project_id=project_id,
            username=username,
        )

    # ── 临时节点：生成 wrapper 脚本，运行时调用 Agent API ───
    if node_inst.ephemeral:
        # 注入隐藏的 _mf_images output param，wrapper 会把生成的图片清单写到这里
        output_params.append({
            "name": "_mf_images",
            "default": "",
            "valueFrom": {"path": "/mf/output/_mf_images"},
        })
        wrapper_source = _build_ephemeral_wrapper_script(
            node_inst=node_inst,
            workflow=workflow,
            resolved_nodes=resolved_nodes or {},
        )
        return _build_ephemeral_template(
            template_name=template_name,
            spec=spec,
            script_source=wrapper_source,
            registry=registry,
            docker_hub_mirror=docker_hub_mirror,
            input_params=input_params,
            output_params=output_params,
            onboard_params=node_inst.onboard_params,
            project_id=project_id,
            username=username,
        )

    if isinstance(spec.execution, ComputeExecutionConfig):
        return _build_compute_template(
            template_name=template_name,
            spec=spec,
            registry=registry,
            workflow=workflow,
            input_params=input_params,
            output_params=output_params,
            resource_overrides=resource_overrides,
            project_id=project_id,
        )
    elif isinstance(spec.execution, LightweightExecutionConfig):
        if spec.execution.entrypoint_script:
            # Profile-based shell 入口模式 — container template
            return _build_lightweight_profile_template(
                template_name=template_name,
                spec=spec,
                registry=registry,
                docker_hub_mirror=docker_hub_mirror,
                input_params=input_params,
                output_params=output_params,
                project_id=project_id,
            )
        else:
            # inline_script / script_path 模式 — script template（原有逻辑）
            spec_dir: Path | None = None
            if project_root and node_inst.nodespec_path:
                spec_dir = (project_root / node_inst.nodespec_path).parent
            elif project_root and node_inst.node:
                spec_dir = _find_node_dir(spec.metadata.name, project_root)
            return _build_lightweight_script_template(
                template_name=template_name,
                spec=spec,
                spec_dir=spec_dir,
                registry=registry,
                docker_hub_mirror=docker_hub_mirror,
                input_params=input_params,
                output_params=output_params,
                project_id=project_id,
            )
    else:
        raise ValueError(
            f"未知的执行配置类型: {type(spec.execution)}"
        )


def _build_compute_template(
    *,
    template_name: str,
    spec: NodeSpec,
    registry: BaseImageRegistry,
    workflow: MFWorkflow,
    input_params: list[dict[str, str]],
    output_params: list[dict[str, Any]],
    resource_overrides: dict[str, Any] | None = None,
    project_id: str = "",
) -> dict[str, Any]:
    """构建 compute 节点的 container template。"""
    exec_cfg = spec.execution  # ComputeExecutionConfig

    # 解析镜像
    image_ref = _resolve_image(spec, registry, workflow)

    cm_name = _configmap_name(spec)

    # 将 parametrize 覆盖应用到静态资源值
    overrides = resource_overrides or {}
    cpu_cores = int(overrides.get("cpu_cores", spec.resources.cpu_cores))
    mem_gb = float(overrides.get("mem_gb", spec.resources.mem_gb))
    mem_overhead = float(overrides.get("mem_overhead", spec.resources.mem_overhead))
    memory_gb = mem_gb + mem_overhead  # pod memory = app memory + overhead
    gpu_count = int(overrides.get("gpu_count", getattr(spec.resources, "gpu_count", 0)))

    # 构建写入参数到文件的 shell 命令
    # 先把所有 input 参数写到 /mf/input/{param_name}，然后运行 profile 脚本
    write_cmds: list[str] = ["mkdir -p /mf/input /mf/output"]
    for p in input_params:
        name = p["name"]
        write_cmds.append(
            f'echo -n "{{{{inputs.parameters.{name}}}}}" > /mf/input/{name}'
        )
    write_cmds.append(f"{exec_cfg.profile_mount_path}/{exec_cfg.entrypoint_script}")

    template: dict[str, Any] = {
        "name": template_name,
        "inputs": {"parameters": input_params} if input_params else {},
        "outputs": {"parameters": output_params} if output_params else {},
        "container": {
            "image": image_ref,
            "command": ["sh", "-c"],
            "args": [" && ".join(write_cmds)],
            "resources": {
                "requests": {
                    "cpu": str(cpu_cores),
                    "memory": f"{memory_gb}Gi",
                },
                "limits": {
                    "cpu": str(cpu_cores),
                    "memory": f"{memory_gb}Gi",
                },
            },
            "volumeMounts": [
                {
                    "name": "profile",
                    "mountPath": exec_cfg.profile_mount_path,
                },
                _workspace_volume_mount(project_id),
            ],
        },
        "volumes": [
            {
                "name": "profile",
                "configMap": {
                    "name": cm_name,
                    "defaultMode": 0o755,
                },
            },
            _workspace_volume(),
        ],
    }

    # GPU 资源
    if gpu_count > 0:
        template["container"]["resources"]["limits"][
            "nvidia.com/gpu"
        ] = str(gpu_count)

    # 环境变量
    if exec_cfg.environment:
        template["container"]["env"] = [
            {"name": k, "value": v}
            for k, v in exec_cfg.environment.items()
        ]

    return template


def _build_lightweight_script_template(
    *,
    template_name: str,
    spec: NodeSpec,
    spec_dir: Path | None = None,
    registry: BaseImageRegistry,
    docker_hub_mirror: str = "",
    input_params: list[dict[str, str]],
    output_params: list[dict[str, Any]],
    project_id: str = "",
) -> dict[str, Any]:
    """构建 lightweight 节点的 script template（inline_script / script_path 模式）。

    Python 镜像优先级：
      1. registry.yaml 中有 python-{version} 条目 → 使用私有仓库地址
      2. 配置了 DOCKER_HUB_MIRROR → 使用镜像站（{mirror}/library/python:{version}-slim）
      3. 回退到 Docker Hub 直连（python:{version}-slim）

    脚本来源优先级：
      1. exec_cfg.inline_script（直接内联）
      2. exec_cfg.script_path（相对于节点目录的文件路径，编译时读入）

    参数注入：
      所有 input_params（stream inputs + onboard inputs）均以 env var 形式注入容器，
      脚本通过 os.environ.get() 读取。MF_OUTPUT_DIR 固定为 /mf/output。
    """
    exec_cfg = spec.execution  # LightweightExecutionConfig

    # ── 读取脚本内容 ──────────────────────────────────────────────────────────
    if exec_cfg.inline_script:
        script_source = exec_cfg.inline_script
    elif exec_cfg.script_path and spec_dir is not None:
        script_file = spec_dir / exec_cfg.script_path
        script_source = script_file.read_text(encoding="utf-8")
    elif exec_cfg.script_path:
        # spec_dir 未知时降级警告
        import warnings
        warnings.warn(
            f"[lightweight] {template_name}: script_path={exec_cfg.script_path!r} "
            "但未提供 spec_dir，脚本内容为空",
            stacklevel=2,
        )
        script_source = ""
    else:
        script_source = ""  # schema 已保证不会到这里

    # ── Python 镜像解析 ───────────────────────────────────────────────────────
    reg_key = f"python-{exec_cfg.python_version}"
    reg_entry = next((img for img in registry.images if img.name == reg_key), None)
    if reg_entry:
        python_image = f"{reg_entry.image}:{reg_entry.tag}"
    elif docker_hub_mirror:
        python_image = f"{docker_hub_mirror}/library/python:{exec_cfg.python_version}-slim"
    else:
        python_image = f"python:{exec_cfg.python_version}-slim"

    # ── 环境变量注入：所有 input 参数 + MF 路径约定 ──────────────────────────
    # 脚本通过 os.environ.get(param_name) 读取参数，Argo 在容器启动前解析模板表达式
    env_vars: list[dict[str, str]] = [
        {"name": "MF_OUTPUT_DIR", "value": "/mf/output"},
        {"name": "MF_WORKSPACE_DIR", "value": "/mf/workspace"},
    ]
    for param in input_params:
        env_vars.append({
            "name": param["name"],
            "value": f"{{{{inputs.parameters.{param['name']}}}}}",
        })

    template: dict[str, Any] = {
        "name": template_name,
        "inputs": {"parameters": input_params} if input_params else {},
        "outputs": {"parameters": output_params} if output_params else {},
        "script": {
            "image": python_image,
            "command": ["python"],
            "env": env_vars,
            "source": script_source,
            "resources": {
                "requests": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
                "limits": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
            },
            "volumeMounts": [
                _workspace_volume_mount(project_id),
            ],
        },
        "volumes": [
            _workspace_volume(),
        ],
    }

    return template


def _build_ephemeral_template(
    *,
    template_name: str,
    spec: NodeSpec,
    script_source: str,
    registry: BaseImageRegistry,
    docker_hub_mirror: str = "",
    input_params: list[dict[str, str]],
    output_params: list[dict[str, Any]],
    onboard_params: dict[str, Any] | None = None,
    project_id: str = "",
    username: str = "",
) -> dict[str, Any]:
    """构建临时节点的 Argo script template（运行时 wrapper 模式）。

    使用 ephemeral-py 预装镜像（含 requests 库，可调用 Agent API）。
    脚本是 wrapper 脚本，负责在运行时调用 Agent API 生成并执行实际逻辑。
    Wrapper 自带 preamble 逻辑（创建目录、读取输入），不需要额外 preamble。
    """
    # ── Python 镜像解析：优先 ephemeral-py 专用镜像 ──
    reg_entry = next((img for img in registry.images if img.name == "ephemeral-py"), None)
    if reg_entry:
        python_image = f"{reg_entry.image}:{reg_entry.tag}"
    elif docker_hub_mirror:
        python_image = f"{docker_hub_mirror}/library/python:{_EPHEMERAL_PYTHON_VERSION}-slim"
    else:
        python_image = f"python:{_EPHEMERAL_PYTHON_VERSION}-slim"

    # ── 环境变量注入 ──
    import os as _os
    # MF_POD_API_URL 优先：Pod 内需要可达 API Server 的地址（非 localhost）。
    # 未设置时回退到 MF_API_URL（向后兼容运行版）。
    mf_api_url = _os.environ.get("MF_POD_API_URL") or _os.environ.get("MF_API_URL", "http://localhost:8200")
    mf_internal_token = _os.environ.get("MF_INTERNAL_TOKEN", "")
    env_vars: list[dict[str, str]] = [
        {"name": "MF_OUTPUT_DIR", "value": "/mf/output"},
        {"name": "MF_WORKSPACE_DIR", "value": "/mf/workspace"},
        {"name": "MF_API_URL", "value": mf_api_url},
    ]
    if mf_internal_token and username:
        env_vars.append({"name": "MF_INTERNAL_TOKEN", "value": mf_internal_token})
        env_vars.append({"name": "MF_USER", "value": username})
    if project_id:
        env_vars.append({"name": "MF_PROJECT_ID", "value": project_id})
    # MF_RUN_NAME：使用 Argo 的 workflow name 作为 run 标识
    env_vars.append({"name": "MF_RUN_NAME", "value": "{{workflow.name}}"})
    for param in input_params:
        env_vars.append({
            "name": param["name"],
            "value": "{{inputs.parameters.%s}}" % param["name"],
        })

    # ── Wrapper 脚本自带 preamble，不需要额外拼接 ──
    # wrapper 脚本中已包含创建目录、读取输入、执行脚本、评估等完整逻辑

    # ── Preamble：将环境变量写入 /mf/input/ 文件（wrapper 也需要）──
    preamble_lines = [
        "import os, pathlib as _pl",
        "_pl.Path('/mf/input').mkdir(parents=True, exist_ok=True)",
        "_pl.Path('/mf/output').mkdir(parents=True, exist_ok=True)",
    ]
    for param in input_params:
        name = param["name"]
        preamble_lines.append(
            f"if '{name}' in os.environ: "
            f"_pl.Path('/mf/input/{name}').write_text(os.environ['{name}'])"
        )
    preamble = "\n".join(preamble_lines) + "\n"
    full_source = preamble + script_source

    template: dict[str, Any] = {
        "name": template_name,
        "inputs": {"parameters": input_params} if input_params else {},
        "outputs": {"parameters": output_params} if output_params else {},
        "script": {
            "image": python_image,
            "command": ["python"],
            "env": env_vars,
            "source": full_source,
            "resources": {
                "requests": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
                "limits": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
            },
            "volumeMounts": [
                _workspace_volume_mount(project_id),
            ],
        },
        "volumes": [
            _workspace_volume(),
        ],
    }

    return template


def _build_prefab_template(
    *,
    template_name: str,
    script_source: str,
    registry: BaseImageRegistry,
    docker_hub_mirror: str = "",
    input_params: list[dict[str, str]],
    output_params: list[dict[str, Any]],
    onboard_params: dict[str, Any] | None = None,
    project_id: str = "",
    username: str = "",
) -> dict[str, Any]:
    """构建 Prefab 运行时节点的 Argo script template。

    与 _build_ephemeral_template 不同，此模板使用硬编码的最小资源
    （0.5 CPU, 1Gi memory），因为实际计算在 API 服务端的 Docker sandbox
    中执行，Argo pod 只运行一个薄的 Python wrapper。

    资源用量：
      - CPU: 0.5
      - Memory: 1Gi
    """
    # ── Python 镜像解析：优先 ephemeral-py 专用镜像 ──
    reg_entry = next((img for img in registry.images if img.name == "ephemeral-py"), None)
    if reg_entry:
        python_image = f"{reg_entry.image}:{reg_entry.tag}"
    elif docker_hub_mirror:
        python_image = f"{docker_hub_mirror}/library/python:{_EPHEMERAL_PYTHON_VERSION}-slim"
    else:
        python_image = f"python:{_EPHEMERAL_PYTHON_VERSION}-slim"

    # ── 环境变量注入 ──
    import os as _os
    mf_api_url = _os.environ.get("MF_POD_API_URL") or _os.environ.get("MF_API_URL", "http://localhost:8200")
    mf_internal_token = _os.environ.get("MF_INTERNAL_TOKEN", "")
    env_vars: list[dict[str, str]] = [
        {"name": "MF_OUTPUT_DIR", "value": "/mf/output"},
        {"name": "MF_WORKSPACE_DIR", "value": "/mf/workspace"},
        {"name": "MF_API_URL", "value": mf_api_url},
    ]
    if mf_internal_token and username:
        env_vars.append({"name": "MF_INTERNAL_TOKEN", "value": mf_internal_token})
        env_vars.append({"name": "MF_USER", "value": username})
    if project_id:
        env_vars.append({"name": "MF_PROJECT_ID", "value": project_id})
    env_vars.append({"name": "MF_RUN_NAME", "value": "{{workflow.name}}"})
    for param in input_params:
        env_vars.append({
            "name": param["name"],
            "value": f"{{{{inputs.parameters.{param['name']}}}}}",
        })
    
    # ── Preamble：将环境变量写入 /mf/input/ 文件 ──
    preamble_lines = [
        "import os, pathlib as _pl",
        "_pl.Path('/mf/input').mkdir(parents=True, exist_ok=True)",
        "_pl.Path('/mf/output').mkdir(parents=True, exist_ok=True)",
    ]
    for param in input_params:
        name = param["name"]
        preamble_lines.append(
            f"if '{name}' in os.environ: "
            f"_pl.Path('/mf/input/{name}').write_text(os.environ['{name}'])"
        )
    preamble = "\n".join(preamble_lines) + "\n"
    full_source = preamble + script_source

    # ── 硬编码最小资源：Argo pod 仅运行 thin wrapper ──
    NODEGEN_CPU = "0.5"
    NODEGEN_MEMORY = "1Gi"

    template: dict[str, Any] = {
        "name": template_name,
        "inputs": {"parameters": input_params} if input_params else {},
        "outputs": {"parameters": output_params} if output_params else {},
        "script": {
            "image": python_image,
            "command": ["python"],
            "env": env_vars,
            "source": full_source,
            "resources": {
                "requests": {
                    "cpu": NODEGEN_CPU,
                    "memory": NODEGEN_MEMORY,
                },
                "limits": {
                    "cpu": NODEGEN_CPU,
                    "memory": NODEGEN_MEMORY,
                },
            },
            "volumeMounts": [
                _workspace_volume_mount(project_id),
            ],
        },
        "volumes": [
            _workspace_volume(),
        ],
    }

    return template


def _build_lightweight_profile_template(
    *,
    template_name: str,
    spec: NodeSpec,
    registry: BaseImageRegistry,
    docker_hub_mirror: str = "",
    input_params: list[dict[str, str]],
    output_params: list[dict[str, Any]],
    project_id: str = "",
) -> dict[str, Any]:
    """构建 lightweight 节点的 container template（entrypoint_script 模式）。

    使用 profile ConfigMap + container 模板模式，与 compute 节点行为一致，
    只是镜像替换为 python:{version}-slim（自带 bash，无需额外安装）。

    适用场景：需要 shell 脚本编排、调用命令行工具或复杂初始化逻辑，
    但不需要 compute 节点那样的重型容器镜像。

    参数注入方式与 compute 节点相同：所有 input 参数写入 /mf/input/ 文件，
    脚本通过 source /mf/profile/mf2_init.sh + mf_param() 读取。
    """
    exec_cfg = spec.execution  # LightweightExecutionConfig

    # ── Python 镜像解析（复用 script 模式逻辑）───────────────────────────────
    reg_key = f"python-{exec_cfg.python_version}"
    reg_entry = next((img for img in registry.images if img.name == reg_key), None)
    if reg_entry:
        python_image = f"{reg_entry.image}:{reg_entry.tag}"
    elif docker_hub_mirror:
        python_image = f"{docker_hub_mirror}/library/python:{exec_cfg.python_version}-slim"
    else:
        python_image = f"python:{exec_cfg.python_version}-slim"

    # Profile 配置
    cm_name = _configmap_name(spec)
    profile_mount_path = "/mf/profile"
    entrypoint = exec_cfg.entrypoint_script  # 已由 schema 确保非空

    # 构建写参数 + 执行脚本的 shell 命令（与 compute 节点一致）
    write_cmds: list[str] = ["mkdir -p /mf/input /mf/output"]
    for p in input_params:
        name = p["name"]
        write_cmds.append(
            f'echo -n "{{{{inputs.parameters.{name}}}}}" > /mf/input/{name}'
        )
    write_cmds.append(f"{profile_mount_path}/{entrypoint}")

    template: dict[str, Any] = {
        "name": template_name,
        "inputs": {"parameters": input_params} if input_params else {},
        "outputs": {"parameters": output_params} if output_params else {},
        "container": {
            "image": python_image,
            "command": ["sh", "-c"],
            "args": [" && ".join(write_cmds)],
            "resources": {
                "requests": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
                "limits": {
                    "cpu": str(spec.resources.cpu_cores),
                    "memory": f"{spec.resources.memory_gb}Gi",
                },
            },
            "volumeMounts": [
                {
                    "name": "profile",
                    "mountPath": profile_mount_path,
                },
                _workspace_volume_mount(project_id),
            ],
        },
        "volumes": [
            {
                "name": "profile",
                "configMap": {
                    "name": cm_name,
                    "defaultMode": 0o755,
                },
            },
            _workspace_volume(),
        ],
    }

    # 额外环境变量（如有）
    if exec_cfg.environment:
        template["container"]["env"] = [
            {"name": k, "value": v}
            for k, v in exec_cfg.environment.items()
        ]

    return template


def _build_dag_task(
    *,
    node_inst,  # MFNodeInstance
    template_name: str,
    spec: NodeSpec,
    dep_map: dict[str, set[str]],
    conn_map: dict[tuple[str, str], tuple[str, str]],
    resolved_nodes: dict[str, NodeSpec],
    workflow: MFWorkflow,
    project_root: Path,
    auto_fan_out: set[str],
    sweep_source: dict[str, tuple[str, str]],
    sweep_origin: dict[str, tuple[str, str]],
    fan_in_map: dict[str, list[tuple[str, list[Any]]]] | None = None,
) -> dict[str, Any]:
    """构建 DAG task 条目。

    依赖表达式规则（统一使用 ``depends`` 字段）：
    - Argo 不允许同一 DAG 内混用 ``depends`` 和 ``dependencies`` 两种写法，
      因此无论上游是否有 quality gate，均使用 ``depends`` 字段。
    - 上游有 must_pass quality gate → ``upstream.Succeeded``（保证上游实际成功）
    - 上游无 must_pass gate → 裸任务名 ``upstream``（任意终止态即可触发）
    ``depends: "taskA"`` 与 ``dependencies: ["taskA"]`` 语义等价。
    """
    task: dict[str, Any] = {
        "name": node_inst.id,
        "template": template_name,
    }

    # ── Dependencies / depends ─────────────────────────────────────────────
    deps = dep_map.get(node_inst.id, set())
    if deps:
        gate_policy = _resolve_gate_policy(workflow)

        # 判断每个上游是否有 must_pass gate；有则需要 .Succeeded 语义
        must_succeed: set[str] = set()
        for dep_node_id in deps:
            dep_spec = resolved_nodes.get(dep_node_id)
            if dep_spec is None:
                continue
            for gate in dep_spec.quality_gates:
                effective = gate_policy.get(
                    (dep_node_id, gate.name), gate.gate_default
                )
                if effective == GateDefault.MUST_PASS:
                    must_succeed.add(dep_node_id)
                    break

        if must_succeed:
            # 至少一个上游要求 Succeeded — 添加 .Succeeded 后缀
            dep_exprs = []
            for dep_node_id in sorted(deps):
                if dep_node_id in must_succeed:
                    dep_exprs.append(f"{dep_node_id}.Succeeded")
                else:
                    dep_exprs.append(dep_node_id)
            task["depends"] = " && ".join(dep_exprs)
        else:
            # 无质量门控要求 — 裸任务名，仍使用 depends 字段保持 DAG 内格式统一
            # （Argo 不允许同一 DAG 内混用 depends 和 dependencies）
            task["depends"] = " && ".join(sorted(deps))

    # ── Arguments: stream inputs + onboard params ──────────────────────────
    arguments: list[dict[str, Any]] = []

    # 确定 auto fan-out 节点的 sweep 源任务（用于 {{item}} 重写）
    af_sweep_src_task: str | None = None
    if node_inst.id in auto_fan_out:
        af_sweep_src_task, _ = sweep_source.get(node_inst.id, (None, None))

    for port in spec.stream_inputs:
        key = (node_inst.id, port.name)
        if key in conn_map:
            src_node_id, src_port_name = conn_map[key]
            # auto fan-out 节点：来自 sweep 源的 stream 输入使用 {{item}}
            # （withParam 已设为上游聚合输出，{{item}} 逐迭代取值）
            if af_sweep_src_task and src_node_id == af_sweep_src_task:
                arguments.append({
                    "name": port.name,
                    "value": "{{item}}",
                })
            else:
                arguments.append({
                    "name": port.name,
                    "value": f"{{{{tasks.{src_node_id}.outputs.parameters.{src_port_name}}}}}",
                })

    software = spec.metadata.tags.software or ""

    for param in spec.onboard_inputs:
        raw = node_inst.onboard_params.get(param.name)
        # 优先使用实例值；空字符串实例值回退到 nodespec 默认值
        # 注意：default="" 的参数也必须传入 arguments，否则 Argo 报 "not supplied"
        if raw is not None and str(raw).strip() != "":
            value = raw
        elif param.default is not None:
            value = param.default
        else:
            continue
        value = str(value).lower() if isinstance(value, bool) else str(value)
        # _shared_param 翻译：canonical → 软件原生关键字
        if param.shared_param and software:
            value = _translate_shared_param(value, software, param.shared_param)
        arguments.append({
            "name": param.name,
            "value": value,
        })

    if arguments:
        task["arguments"] = {"parameters": arguments}

    # fan-in 节点：注入 _sweep_keys 常量值
    if fan_in_map and node_inst.id in fan_in_map:
        _, sweep_values = fan_in_map[node_inst.id][0]
        if "arguments" not in task:
            task["arguments"] = {"parameters": []}
        task["arguments"]["parameters"].append({
            "name": "_sweep_keys",
            "value": json.dumps(sweep_values, ensure_ascii=False),
        })

    # ── withParam（并行扫描）─────────────────────────────────────────────────
    if node_inst.parallel_sweep is not None:
        task["withParam"] = json.dumps(
            node_inst.parallel_sweep.values, ensure_ascii=False,
        )
    elif node_inst.id in auto_fan_out:
        # auto fan-out 节点：withParam 引用上游任务的动态输出。
        # Argo 会将上游 fan-out pod 的 valueFrom.path 输出自动聚合为 JSON 数组，
        # 下游 withParam 的 {{item}} 逐个取值。
        src_task, src_port = sweep_source[node_inst.id]
        task["withParam"] = (
            f"{{{{tasks.{src_task}.outputs.parameters.{src_port}}}}}"
        )

    # ── When conditions — from upstream must_pass quality gates ────────────
    gate_policy = _resolve_gate_policy(workflow)
    when_conditions: list[str] = []

    for dep_node_id in dep_map.get(node_inst.id, set()):
        # 跳过 auto fan-out 上游的 when 条件：fan-out 节点的 outputs 会被 Argo
        # 聚合为数组，`== true` 判断必然失败。fan-out 的 .Succeeded 语义已由
        # depends 字段保证（所有实例都成功才触发下游），无需额外 when。
        if dep_node_id in auto_fan_out:
            continue
        dep_spec = resolved_nodes.get(dep_node_id)
        if dep_spec is None:
            continue
        for gate in dep_spec.quality_gates:
            effective_action = gate_policy.get((dep_node_id, gate.name), gate.gate_default)
            if effective_action == GateDefault.MUST_PASS:
                when_conditions.append(
                    f"{{{{tasks.{dep_node_id}.outputs.parameters._qg_{gate.name}}}}} == true"
                )

    if when_conditions:
        task["when"] = " && ".join(when_conditions)

    return task


def _resolve_gate_policy(
    workflow: MFWorkflow,
) -> dict[tuple[str, str], GateDefault]:
    """构建 (node_id, gate_name) → 生效 GateDefault 映射。

    只包含 quality_policy 中明确 override 的条目；
    未 override 的 gate 由调用方回退到 gate.gate_default。
    """
    return {
        (o.node_id, o.gate_name): o.action
        for o in workflow.quality_policy
    }


def _resolve_image(
    spec: NodeSpec,
    registry: BaseImageRegistry,
    workflow: MFWorkflow,
) -> str:
    """解析 compute 节点的容器镜像引用。"""
    ref = spec.metadata.base_image_ref
    if ref is None:
        raise ValueError(
            f"Compute 节点 {spec.metadata.name!r} 缺少 base_image_ref"
        )

    img_spec = registry.get(ref)
    if img_spec is None:
        raise ValueError(
            f"BaseImageRegistry 中未找到镜像 {ref!r}。"
            f"请确认 nodes/base_images/registry.yaml 中已注册该镜像。"
        )

    full_ref = img_spec.full_image_ref()

    # 如果 global_params 中有 image-registry，作为前缀注入
    image_registry = workflow.global_params.get("image-registry")
    if image_registry:
        # image-registry/image:tag
        image_name = img_spec.image.split("/")[-1]
        full_ref = f"{image_registry}/{image_name}:{img_spec.tag}"

    return full_ref


def _configmap_name(spec: NodeSpec) -> str:
    """生成 ConfigMap 名称。"""
    return f"mf-profile-{spec.metadata.name}-{spec.metadata.version}"


def _load_profile_files(
    node_inst,
    spec: NodeSpec,
    project_root: Path,
) -> dict[str, str]:
    """从 nodespec 旁的 profile/ 目录加载文件，并注入公共库和节点参数。

    额外处理：
    - run.sh 中的 ``# MF2 init`` 指令替换为 ``source /mf/profile/mf2_init.sh``
    - 将 ``nodes/common/mf2_init.sh`` 注入 ConfigMap（作为 mf2_init.sh）
    - 根据 spec.onboard_inputs 生成 ``mf_node_params.sh`` 并注入 ConfigMap
    """
    # 找到 nodespec 所在目录
    if node_inst.nodespec_path:
        spec_dir = (project_root / node_inst.nodespec_path).parent
    elif node_inst.node:
        # 需要找到节点目录 — 搜索 nodes/ 下的 nodespec.yaml
        spec_dir = _find_node_dir(spec.metadata.name, project_root)
        if spec_dir is None:
            return {}
    else:
        return {}

    profile_dir = spec_dir / "profile"
    if not profile_dir.exists():
        return {}

    data: dict[str, str] = {}
    for filepath in sorted(profile_dir.iterdir()):
        if filepath.is_file():
            content = filepath.read_text(encoding="utf-8")
            if filepath.name == "run.sh":
                content = _process_run_sh(content)
            data[filepath.name] = content

    # 注入公共运行时库 mf2_init.sh
    common_init = project_root / "nodes" / "common" / "mf2_init.sh"
    if common_init.exists():
        data["mf2_init.sh"] = common_init.read_text(encoding="utf-8")

    # 注入编译器生成的节点参数加载文件
    data["mf_node_params.sh"] = _generate_node_params_sh(spec)

    return data


def _process_run_sh(content: str) -> str:
    """处理 run.sh 中的 ``# MF2 init`` 指令，替换为 source 命令。

    匹配整行（允许行尾空白），只替换第一次出现。
    未找到该指令时原样返回（兼容未使用该约定的旧脚本）。
    """
    return re.sub(
        r"^# MF2 init[^\S\n]*$",
        "source /mf/profile/mf2_init.sh",
        content,
        count=1,
        flags=re.MULTILINE,
    )


def _translate_shared_param(
    canonical_value: str,
    software: str,
    category: str,
) -> str:
    """将 canonical 参数值翻译为软件原生关键字。

    如果翻译失败（如 canonical name 不在表中），原样返回。
    """
    shared = load_shared_params()
    resolved = shared.resolve(canonical_value, software, category)
    return resolved if resolved is not None else canonical_value


def _generate_node_params_sh(spec: NodeSpec) -> str:
    """从 spec.onboard_inputs 生成 mf_node_params.sh 内容。

    为每个 onboard input 生成一行 BASH 变量赋值：
        UPPER_CASE_NAME=$(mf_param param_name "default")

    parametrize（如 n_cores）已由 NodeSpec 校验器自动注入到
    spec.onboard_inputs，因此无需特殊处理，直接遍历即可覆盖所有参数。

    如果参数设置了 shared_param，编译器会将 canonical 默认值翻译为
    对应计算软件的原生关键字（compile-time 硬映射）。
    """
    software = spec.metadata.tags.software or ""

    lines = [
        "# Auto-generated by MiQroForge compiler — do not edit manually",
        f"# Node: {spec.metadata.name}  v{spec.metadata.version}",
        "",
    ]
    for param in spec.onboard_inputs:
        default = "" if param.default is None else str(param.default)

        # _shared_param 翻译：将 canonical name 映射为软件原生关键字
        if param.shared_param and software:
            default = _translate_shared_param(default, software, param.shared_param)

        # 对默认值中的反斜杠和双引号做最小转义，确保 shell 赋值安全
        escaped = default.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{param.name}=$(mf_param {param.name} "{escaped}")')

    return "\n".join(lines) + "\n"


def _find_node_dir(name: str, project_root: Path) -> Path | None:
    """按名称查找节点目录。"""
    nodes_dir = project_root / "nodes"
    for spec_path in nodes_dir.rglob("nodespec.yaml"):
        if "schemas" in spec_path.parts:
            continue
        try:
            with spec_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data.get("metadata", {}).get("name") == name:
                return spec_path.parent
        except Exception:
            continue
    return None
