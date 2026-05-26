"""api/routers/agents.py — Phase 2 Agent API 端点。

提供 8 个独立可调用的 Agent 端点：
  POST /api/v1/agents/plan               — Planner Agent（意图解析 + 节点检索）
  POST /api/v1/agents/yaml               — YAML Coder Agent（语义工作流 → MF YAML）
  POST /api/v1/agents/node               — Node Generator Prefab（设计时 -1 循环：生成 nodespec）
  POST /api/v1/agents/node/run           — Node Generator Prefab（运行时 sandbox + evaluate 外循环）
  POST /api/v1/agents/node/accept        — 将 Prefab 生成的节点持久化到节点库
  POST /api/v1/agents/ephemeral          — Ephemeral Agent（运行时临时节点脚本生成 + sandbox 执行）
  POST /api/v1/agents/ephemeral/evaluate — 多模态视觉评估临时节点图像输出
  POST /api/v1/agents/save-session       — 保存对话会话到 userdata/agent_sessions/
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser, require_user
from api.config import Settings, get_settings
from api.dependencies import get_user_paths
from api.user_paths import UserPaths
from api.models.agents import (
    PlanRequest, PlanResponse,
    YAMLRequest, YAMLResponse,
    NodeGenAPIRequest, NodeGenAPIResponse,
    NodeRunAPIRequest,
    NodeAcceptRequest, NodeAcceptResponse,
    EphemeralGenRequest, EphemeralGenResponse,
    EphemeralEvalRequest, EphemeralEvalResponse,
    SaveSessionRequest, SaveSessionResponse,
)
from agents.llm_config import LLMConfig
from agents.schemas import NodeGenRequest, EvaluationResult
from agents.common.session_logger import (
    start_session, end_session,
    save_agent_log, save_conversation,
)
from api.tracking.llm_tracker import TokenUsageTracker

router = APIRouter(prefix="/agents", tags=["agents"])


def _load_currency(settings) -> str:
    """从 compute_pricing.yaml 读取币种，fallback 到 models.yaml。"""
    import yaml
    cp = settings.shared_root / "compute_pricing.yaml"
    if cp.exists():
        with cp.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            if cfg.get("currency"):
                return str(cfg["currency"])
    mp = settings.shared_root / "models.yaml"
    if mp.exists():
        with mp.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            defaults = cfg.get("default_pricing", {})
            if defaults.get("currency"):
                return str(defaults["currency"])
    return "USD"


# ─── Planner Agent ────────────────────────────────────────────────────────────

@router.post("/plan", response_model=PlanResponse, summary="运行 Planner Agent")
async def plan_workflow(
    request: PlanRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> PlanResponse:
    """解析用户意图，通过 RAG 检索节点，生成语义工作流蓝图。"""
    try:
        from agents.planner.graph import run_planner
        from agents.llm_config import LLMConfig
        from api.tracking.llm_tracker import TokenUsageTracker

        tracker = TokenUsageTracker(paths, purpose="planner", currency=_load_currency(settings))

        # 前端未传 session_id 时，服务端自动生成（确保日志总能被保存）
        effective_session_id = (
            request.session_id
            or f"auto-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        def _run_with_session():
            LLMConfig.set_token_tracker(tracker)
            session = start_session("planner", {
                "intent": request.intent,
                "molecule": request.molecule,
                "preferences": request.preferences,
            })
            try:
                state = run_planner(
                    intent=request.intent,
                    molecule=request.molecule,
                    preferences=request.preferences,
                )
                return state
            finally:
                log = end_session()
                if log:
                    try:
                        save_agent_log(
                            log.to_dict(),
                            session_id=effective_session_id,
                            userdata_root=paths.agent_sessions_dir.parent,
                        )
                    except Exception:
                        pass
                tracker.flush()
                LLMConfig.clear_token_tracker()

        state = await asyncio.to_thread(_run_with_session)

        workflow = state.get("semantic_workflow")
        if not workflow:
            error_msg = state.get("error") or "Planner 未能生成工作流"
            raise HTTPException(status_code=500, detail=error_msg)

        return PlanResponse(
            semantic_workflow=workflow,
            evaluation=state.get("evaluation"),
            available_nodes=workflow.available_implementations,
            error=state.get("error"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Planner Agent 失败: {e}")


# ─── YAML Coder Agent ─────────────────────────────────────────────────────────

@router.post("/yaml", response_model=YAMLResponse, summary="运行 YAML Coder Agent")
async def generate_yaml(
    request: YAMLRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> YAMLResponse:
    """将语义工作流翻译为可执行的 MF YAML。"""
    try:
        from agents.yaml_coder.graph import run_yaml_coder
        tracker = TokenUsageTracker(paths, purpose="yaml_coder", currency=_load_currency(settings))

        effective_session_id = (
            request.session_id
            or f"auto-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        def _run_with_session():
            LLMConfig.set_token_tracker(tracker)
            start_session("yaml_coder", {
                "workflow_name": request.semantic_workflow.name,
                "step_count": len(request.semantic_workflow.steps),
                "selected_implementations": request.selected_implementations,
            })
            try:
                state = run_yaml_coder(
                    semantic_workflow=request.semantic_workflow,
                    user_params=request.user_params,
                    selected_implementations=request.selected_implementations,
                )
                return state
            finally:
                log = end_session()
                if log:
                    try:
                        save_agent_log(
                            log.to_dict(),
                            session_id=effective_session_id,
                            userdata_root=paths.agent_sessions_dir.parent,
                        )
                    except Exception:
                        pass

        state = await asyncio.to_thread(_run_with_session)
        tracker.flush()
        LLMConfig.clear_token_tracker()

        result = state.get("result")
        mf_yaml = state.get("mf_yaml", "")

        if not mf_yaml:
            error_msg = state.get("error") or "YAML Coder 未能生成 YAML"
            raise HTTPException(status_code=500, detail=error_msg)

        validation_report = {
            "valid": state.get("validation_valid", False),
            "errors": state.get("validation_errors", []),
            "warnings": state.get("validation_warnings", []),
        }

        return YAMLResponse(
            mf_yaml=mf_yaml,
            validation_report=validation_report,
            result=result,
            error=state.get("error"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"YAML Coder Agent 失败: {e}")


# ─── Node Generator Agent (设计时) ────────────────────────────────────────────

@router.post("/node", response_model=NodeGenAPIResponse, summary="设计时生成节点（无 sandbox）")
async def generate_node(
    request: NodeGenAPIRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> NodeGenAPIResponse:
    """设计时生成节点（-1 循环）：仅生成 nodespec.yaml + run.sh，无 sandbox 测试。

    文件通过 write_file 工具写入 _sandbox_dir 工作目录，
    生成完成后从工作目录读取并保存到 userdata/projects/{project_id}/tmp/{node_name}/。
    运行时由 /node/run 端点接管，进行 sandbox + evaluate 循环。
    """
    try:
        from agents.node_generator.prefab.graph import run_prefab_node_generator

        gen_request = NodeGenRequest(
            semantic_type=request.semantic_type,
            description=request.description,
            target_software=request.target_software,
            target_method=request.target_method,
            category=request.category,
            resource_overrides=request.resource_overrides,
        )

        effective_session_id = (
            request.session_id
            or f"design-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        last_state = None
        last_error = None

        # 使用 proj/tmp/pending/ 作为工作目录，Agent 通过 write_file 写入
        pending_dir = None
        if request.project_id:
            pending_dir = paths.projects_dir / request.project_id / "tmp" / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)

        prefab_cfg = _load_prefab_settings()
        mf_test_design = prefab_cfg.get("mf_test", False)

        tracker2 = TokenUsageTracker(paths, purpose="node_generator", currency=_load_currency(settings))

        def _run_with_session():
            nonlocal last_state, last_error
            LLMConfig.set_token_tracker(tracker2)
            start_session("prefab_design", {
                "semantic_type": request.semantic_type,
                "target_software": request.target_software,
                "category": request.category,
                "project_id": request.project_id,
            })
            try:
                extra = {
                    "_sandbox_enabled": False,
                    "_mf_test": mf_test_design,
                    "iteration": 0,
                }
                if pending_dir:
                    extra["_sandbox_dir"] = str(pending_dir)
                if request.project_id:
                    extra["_project_id"] = request.project_id
                    extra["_projects_root"] = str(paths.projects_dir)
                state = run_prefab_node_generator(gen_request, **extra)
                last_state = state
                last_error = state.get("error")
            finally:
                log = end_session()
                if log:
                    try:
                        log_dict = log.to_dict()
                        # 保存到项目 conversations 目录（JSON + 人类可读文本）
                        if request.project_id:
                            from agents.common.session_logger import save_agent_log_text
                            proj_conv_dir = (
                                paths.projects_dir
                                / request.project_id / "conversations"
                            )
                            # 人类可读文本格式（保留所有换行符）
                            save_agent_log_text(
                                log_dict,
                                session_id=effective_session_id,
                                userdata_root=proj_conv_dir,
                            )
                            # JSON 格式（机器可读，作为备份）
                            proj_conv_dir_session = proj_conv_dir / effective_session_id
                            proj_conv_dir_session.mkdir(parents=True, exist_ok=True)
                            time_str = datetime.now().strftime("%H-%M-%S")
                            agent_type = log_dict.get("agent_type", "unknown")
                            (proj_conv_dir_session / f"{agent_type}_{time_str}.json").write_text(
                                json.dumps(log_dict, indent=2, ensure_ascii=False, default=str)
                            )
                    except Exception:
                        pass
                tracker2.flush()
                LLMConfig.clear_token_tracker()

        await asyncio.to_thread(_run_with_session)

        # 从 _sandbox_dir 读取生成的文件（优先），否则从 state 读取
        nodespec_yaml = ""
        run_sh = ""
        input_templates: dict[str, str] = {}
        extra_profile_files: dict[str, str] = {}  # 辅助文件（postprocess.py, data.json 等）
        if pending_dir and pending_dir.exists():
            ns_path = pending_dir / "nodespec.yaml"
            if ns_path.exists():
                nodespec_yaml = ns_path.read_text("utf-8")
            profile_pending = pending_dir / "profile"
            if profile_pending.exists():
                rs_path = profile_pending / "run.sh"
                if rs_path.exists():
                    run_sh = rs_path.read_text("utf-8")
                # 读取 profile/ 下所有文件（run.sh 单独处理）
                for f_path in profile_pending.iterdir():
                    if not f_path.is_file():
                        continue
                    if f_path.name == "run.sh":
                        continue
                    if f_path.suffix == ".template":
                        input_templates[f_path.name] = f_path.read_text("utf-8")
                    else:
                        extra_profile_files[f_path.name] = f_path.read_text("utf-8")

        # 如果 sandbox_dir 中没有，fallback 到 state
        if not nodespec_yaml and last_state:
            nodespec_yaml = last_state.get("nodespec_yaml", "")
        if not run_sh and last_state:
            run_sh = last_state.get("run_sh", "")
        if not input_templates and last_state:
            input_templates = last_state.get("input_templates") or {}

        if not nodespec_yaml:
            error_msg = last_error or "Node Generator 未能生成节点"
            raise HTTPException(status_code=500, detail=error_msg)

        # 提取语义节点名（仅用于响应 display，不用于目录命名）
        import yaml as _yaml
        try:
            spec_data = _yaml.safe_load(nodespec_yaml)
            node_name = spec_data.get("metadata", {}).get("name", "generated-node")
        except Exception:
            node_name = "generated-node"

        # 保存到 proj/tmp/<canvas_node_id>/（用 canvas node ID 避免多节点重名）
        saved_path = None
        if request.project_id:
            # 目录名：优先使用前端传来的 canvas node ID
            dir_name = request.node_id or node_name
            tmp_dir = paths.projects_dir / request.project_id / "tmp" / dir_name
            tmp_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / "nodespec.yaml").write_text(nodespec_yaml, encoding="utf-8")
            if run_sh:
                profile_dir = tmp_dir / "profile"
                profile_dir.mkdir(exist_ok=True)
                (profile_dir / "run.sh").write_text(run_sh, encoding="utf-8")
                (profile_dir / "run.sh").chmod(0o755)
                for tpl_name, tpl_content in input_templates.items():
                    (profile_dir / tpl_name).write_text(tpl_content, encoding="utf-8")
                for extra_name, extra_content in extra_profile_files.items():
                    (profile_dir / extra_name).write_text(extra_content, encoding="utf-8")
            saved_path = str(tmp_dir.relative_to(settings.project_root))

            # 清理 pending 工作目录
            import shutil
            if pending_dir and pending_dir.exists():
                shutil.rmtree(pending_dir)

        return NodeGenAPIResponse(
            node_name=node_name,
            nodespec_yaml=nodespec_yaml,
            run_sh=run_sh,
            input_templates=input_templates,
            saved_path=saved_path,
            evaluation=None,
            error=last_error,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Node Generator Agent 失败: {e}")


# ─── Node Generator helpers ────────────────────────────────────────────────────


def _collect_sandbox_outputs(
    sandbox_dir: Path,
    nodespec_yaml: str,
    max_file_size: int = 1_000_000,
) -> dict[str, str]:
    """从 sandbox 输出目录收集所有声明的输出端口值。

    根据 nodespec 中声明的 stream_outputs 和 onboard_outputs 端口名，
    在 sandbox_dir/output/ 中查找同名文件并读取内容。

    Returns:
        {port_name: file_content} 字典。
    """
    import yaml as _yaml
    outputs: dict[str, str] = {}

    try:
        spec = _yaml.safe_load(nodespec_yaml)
        stream_outputs = spec.get("stream_outputs", []) if isinstance(spec, dict) else []
        onboard_outputs = spec.get("onboard_outputs", []) if isinstance(spec, dict) else []
        all_outputs = list(stream_outputs) + list(onboard_outputs)
    except Exception:
        return outputs

    output_dir = sandbox_dir / "output"
    if not output_dir.exists():
        return outputs

    for port in all_outputs:
        port_name = port.get("name", "") if isinstance(port, dict) else ""
        if not port_name:
            continue
        out_file = output_dir / port_name
        if out_file.is_file():
            try:
                content = out_file.read_text("utf-8")
                outputs[port_name] = content[:max_file_size]
            except Exception:
                pass

    return outputs


def _resolve_nodegen_spec(
    node_name: str,
    project_id: str,
    project_root: Path,
    userdata_root: Path,
) -> tuple[str, str, dict[str, str]] | None:
    """为 nodegen 运行时读取预生成的 nodespec + run.sh + 所有 profile 文件。

    搜索优先级：
    1. userdata/nodes/**/<node_name>/nodespec.yaml（已 Accept）
    2. userdata/projects/<project_id>/tmp/<node_name>/nodespec.yaml（未 Accept）

    Returns:
        (nodespec_yaml, run_sh, profile_files) 或 None。
        profile_files 是 {filename: content} 字典，包含 profile/ 下除 run.sh 外的所有文件。
    """
    import yaml as _yaml

    def _read_all(spec_path: Path) -> tuple[str, str, dict[str, str]] | None:
        """读取 nodespec + run.sh + 所有 profile 文件。"""
        if not spec_path.exists():
            return None
        nodespec = spec_path.read_text("utf-8")
        profile_dir = spec_path.parent / "profile"
        run_sh = ""
        profile_files: dict[str, str] = {}
        if profile_dir.exists():
            for f_path in profile_dir.iterdir():
                if not f_path.is_file():
                    continue
                try:
                    content = f_path.read_text("utf-8")
                except Exception:
                    continue
                if f_path.name == "run.sh":
                    run_sh = content
                else:
                    profile_files[f_path.name] = content
        return nodespec, run_sh, profile_files

    # 1. 搜索 userdata/nodes/
    userdata_nodes = userdata_root / "nodes"
    if userdata_nodes.exists():
        for spec_path in userdata_nodes.rglob(f"{node_name}/nodespec.yaml"):
            if "schemas" in spec_path.parts or "base_images" in spec_path.parts:
                continue
            result = _read_all(spec_path)
            if result:
                return result

    # 2. 搜索 proj/tmp/
    if project_id:
        tmp_spec = userdata_root / "projects" / project_id / "tmp" / node_name / "nodespec.yaml"
        result = _read_all(tmp_spec)
        if result:
            return result

    return None


def _apply_onboard_overrides_to_nodespec(
    nodespec_yaml: str,
    input_data: dict[str, str],
) -> str:
    """将 input_data 中的 onboard param 覆盖值应用到 nodespec 的 resources 字段。

    input_data 中包含 stream inputs 和 onboard params。
    只处理与 resources 相关的已知 param 名（n_cores → cpu_cores, mem_gb → mem_gb,
    walltime_hours → estimated_walltime_hours 等）。
    """
    import yaml as _yaml
    try:
        spec = _yaml.safe_load(nodespec_yaml)
    except Exception:
        return nodespec_yaml

    if not isinstance(spec, dict):
        return nodespec_yaml

    resources = spec.get("resources", {})
    if not isinstance(resources, dict):
        return nodespec_yaml

    # onboard param name → nodespec resource field
    _RESOURCE_PARAM_MAP = {
        "n_cores": "cpu_cores",
        "mem_gb": "mem_gb",
        "walltime_hours": "estimated_walltime_hours",
        "mem_overhead": "mem_overhead",
        "gpu_count": "gpu_count",
        "scratch_disk_gb": "scratch_disk_gb",
        "parallel_tasks": "parallel_tasks",
    }

    for param_name, res_field in _RESOURCE_PARAM_MAP.items():
        if param_name in input_data:
            raw = input_data[param_name].strip()
            if raw:
                try:
                    # 数值类型转换
                    if res_field in ("cpu_cores", "gpu_count", "parallel_tasks"):
                        resources[res_field] = int(raw)
                    else:
                        resources[res_field] = float(raw)
                except (ValueError, TypeError):
                    pass  # 保留原值

    spec["resources"] = resources
    return _yaml.dump(spec, default_flow_style=False, allow_unicode=True)


# ─── Node Generator Agent (运行时) ────────────────────────────────────────────

@router.post("/node/run", response_model=NodeGenAPIResponse, summary="运行时节点生成循环（sandbox + evaluate）")
async def run_node_runtime(
    request: NodeRunAPIRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> NodeGenAPIResponse:
    """运行时节点生成：完整 generate → sandbox → evaluate → retry 循环。

    与 ephemeral 外循环模式一致：
    - 每轮：生成器 ReAct Agent（含最多 3 次 sandbox）→ evaluator 检查
    - evaluator 通过 → 直接使用结果（不重跑）
    - evaluator 不通过 → 带反馈进下一轮（至多 3 轮外循环）
    """
    try:
        from agents.node_generator.prefab.graph import run_prefab_node_generator
        from agents.node_generator.prefab.evaluator import evaluate_prefab_node

        gen_request = NodeGenRequest(
            semantic_type=request.semantic_type,
            description=request.description,
            target_software=request.target_software,
            target_method=request.target_method,
            category=request.category,
            resource_overrides=request.resource_overrides,
        )

        effective_session_id = (
            request.session_id
            or f"runtime-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        prefab_cfg = _load_prefab_settings()
        max_outer = prefab_cfg.get("max_outer_rounds", 2)
        max_inner = prefab_cfg.get("max_inner_rounds", 3)
        mf_test = prefab_cfg.get("mf_test", False)
        evaluation = None
        last_state = None
        last_error = None
        nodespec_yaml = request.existing_nodespec or ""
        run_sh = request.existing_run_sh or ""
        sandbox_result = None
        eval_issues: list[str] = []
        _internal_errors: list[str] = []
        _recorded_lesson: str = ""          # 跨轮次累积 record_lesson 输出
        profile_files: dict[str, str] = {}

        # ── prefab_node_id: 从 proj/tmp/ 或 userdata/nodes/ 读取预生成 nodespec ──
        if request.prefab_node_id and not nodespec_yaml:
            resolved = _resolve_nodegen_spec(
                node_name=request.prefab_node_id,
                project_id=request.project_id,
                project_root=settings.project_root,
                userdata_root=paths.agent_sessions_dir.parent,
            )
            if resolved:
                nodespec_yaml, run_sh, profile_files = resolved
                # 应用 input_data 中的 onboard param 覆盖到 nodespec resources
                nodespec_yaml = _apply_onboard_overrides_to_nodespec(
                    nodespec_yaml, request.input_data
                )

        _sandbox_dir = ""
        _exec_sandbox_dirs: list[str] = []
        _collected_outputs: dict[str, str] = {}

        tracker3 = TokenUsageTracker(paths, purpose="node_generator", currency=_load_currency(settings))

        def _run_with_session():
            nonlocal evaluation, last_state, last_error
            nonlocal nodespec_yaml, run_sh, sandbox_result, eval_issues, _internal_errors, _recorded_lesson, profile_files
            nonlocal _sandbox_dir, _exec_sandbox_dirs, _collected_outputs
            LLMConfig.set_token_tracker(tracker3)

            _sandbox_dir = ""
            _exec_sandbox_dirs = []
            _collected_outputs = {}

            # ── 确定节点工作目录（tmp/<node_name>/）──
            _node_name_hint = request.prefab_node_id or ""
            if not _node_name_hint and nodespec_yaml:
                import yaml as _yaml_hint
                try:
                    _spec_hint = _yaml_hint.safe_load(nodespec_yaml)
                    _node_name_hint = _spec_hint.get("metadata", {}).get("name", "") if isinstance(_spec_hint, dict) else ""
                except Exception:
                    pass
            if _node_name_hint and request.project_id:
                _node_work_dir = paths.projects_dir / request.project_id / "tmp" / _node_name_hint
                _node_work_dir.mkdir(parents=True, exist_ok=True)
                _sandbox_dir = str(_node_work_dir)

            for outer_round in range(max_outer):
                # --- Generate (含 ReAct Agent 内循环 + sandbox) ---
                start_session("prefab_runtime", {
                    "semantic_type": request.semantic_type,
                    "target_software": request.target_software,
                    "category": request.category,
                    "iteration": outer_round,
                    "run_name": request.run_name,
                    "project_id": request.project_id,
                })
                try:
                    extra_state: dict[str, Any] = {
                        "_input_data": request.input_data,
                        "_sandbox_enabled": True,
                        "_project_id": request.project_id,
                        "_projects_root": str(paths.projects_dir),
                        "_run_name": request.run_name,
                        "_mf_test": mf_test,
                        "_max_inner": max_inner,
                        "_input_ports": request.input_ports or [],
                        "_output_ports": request.output_ports or [],
                        "iteration": outer_round,
                    }
                    # 传入预生成的 nodespec（第一轮即传入，让 Agent 以此为参考修改）
                    if nodespec_yaml:
                        extra_state["nodespec_yaml"] = nodespec_yaml
                        extra_state["run_sh"] = run_sh
                        extra_state["input_templates"] = profile_files
                    if evaluation and not evaluation.passed:
                        extra_state["evaluation"] = evaluation
                    if sandbox_result:
                        extra_state["sandbox_test_result"] = sandbox_result
                    # 节点工作目录（tmp/<node_name>/）
                    if _sandbox_dir:
                        extra_state["_sandbox_dir"] = _sandbox_dir

                    state = run_prefab_node_generator(gen_request, **extra_state)
                    last_state = state
                except Exception as gen_error:
                    # 生成异常不终止外循环 — 记录并继续下一轮
                    session = get_session()
                    if session:
                        session.log_event("outer_generate_error", {
                            "round": outer_round,
                            "error": str(gen_error),
                        })
                    last_error = f"Outer round {outer_round} generate error: {gen_error}"
                    continue
                finally:
                    log = end_session()
                    if log:
                        try:
                            log_dict = log.to_dict()
                            if request.run_name and request.project_id:
                                run_log_dir = (
                                    paths.projects_dir / request.project_id
                                    / "runs" / request.run_name
                                )
                                run_log_dir.mkdir(parents=True, exist_ok=True)
                                time_str = datetime.now().strftime("%H-%M-%S")
                                agent_type = log_dict.get("agent_type", "unknown")
                                node_id = request.prefab_node_id or "unknown"
                                json_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.json"
                                json_path.write_text(json.dumps(log_dict, indent=2, ensure_ascii=False, default=str))
                                # 同步保存人类可读 .txt 文件
                                from agents.common.session_logger import format_log_as_text
                                txt_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.txt"
                                txt_path.write_text(format_log_as_text(log_dict), encoding="utf-8")
                        except Exception:
                            pass

                # 防御性检查：确保 state 有效
                if not state:
                    continue

                nodespec_yaml = state.get("nodespec_yaml", "")
                run_sh = state.get("run_sh", "")
                sandbox_result = state.get("sandbox_test_result")
                last_error = state.get("error")
                _sandbox_dir = state.get("_sandbox_dir", _sandbox_dir)
                # 追踪执行沙箱目录（test_in_sandbox 创建的临时目录）
                for _esb in state.get("_exec_sandbox_dirs", []):
                    if _esb not in _exec_sandbox_dirs:
                        _exec_sandbox_dirs.append(_esb)

                # 收集 generator 内部错误（供 memory 系统使用，跨轮次累积）
                round_errors = state.get("_internal_errors", [])
                for err in round_errors:
                    if err not in _internal_errors:
                        _internal_errors.append(err)

                # 收集 record_lesson 输出（跨轮次累积，保留首个非空值）
                if not _recorded_lesson:
                    _recorded_lesson = state.get("_recorded_lesson", "")

                # terminate 信号：Agent 判定计算不科学，跳过 evaluator 直接结束
                if state.get("_terminated"):
                    evaluation = EvaluationResult(
                        passed=False,
                        issues=[f"Agent 主动终止: {state.get('_terminate_reason', '计算输入不合理')}"],
                        suggestions=[],
                        iteration=outer_round,
                    )
                    eval_issues = evaluation.issues
                    break

                # --- 评估 ---
                start_session("prefab_eval", {
                    "semantic_type": request.semantic_type,
                    "target_software": request.target_software,
                    "iteration": outer_round,
                    "run_name": request.run_name,
                    "project_id": request.project_id,
                })
                try:
                    eval_state = {
                        "request": gen_request,
                        "nodespec_yaml": nodespec_yaml,
                        "run_sh": run_sh,
                        "available_images": state.get("available_images"),
                        "semantic_types": state.get("semantic_types"),
                        "sandbox_test_result": sandbox_result,
                        "sandbox_test_passed": state.get("sandbox_test_passed", False),
                        "sandbox_call_count": state.get("sandbox_call_count", 0),
                        "_sandbox_enabled": True,
                        "_sandbox_dir": state.get("_sandbox_dir", ""),
                        "iteration": outer_round,
                    }
                    eval_result = evaluate_prefab_node(eval_state)
                except Exception as eval_error:
                    # 评估异常不终止 — 构造失败结果继续下一轮
                    session = get_session()
                    if session:
                        session.log_event("outer_eval_error", {
                            "round": outer_round,
                            "error": str(eval_error),
                        })
                    eval_result = {
                        "evaluation": EvaluationResult(
                            passed=False,
                            issues=[f"Evaluator error in round {outer_round}: {eval_error}"],
                            suggestions=["Retry with more careful generation"],
                            iteration=outer_round,
                        )
                    }
                finally:
                    log = end_session()
                    if log:
                        try:
                            log_dict = log.to_dict()
                            if request.run_name and request.project_id:
                                run_log_dir = (
                                    paths.projects_dir / request.project_id
                                    / "runs" / request.run_name
                                )
                                run_log_dir.mkdir(parents=True, exist_ok=True)
                                time_str = datetime.now().strftime("%H-%M-%S")
                                agent_type = log_dict.get("agent_type", "unknown")
                                node_id = request.prefab_node_id or "unknown"
                                json_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.json"
                                json_path.write_text(json.dumps(log_dict, indent=2, ensure_ascii=False, default=str))
                                # 同步保存人类可读 .txt 文件
                                from agents.common.session_logger import format_log_as_text
                                txt_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.txt"
                                txt_path.write_text(format_log_as_text(log_dict), encoding="utf-8")
                        except Exception:
                            pass

                evaluation = eval_result.get("evaluation")
                if evaluation and evaluation.passed:
                    break
                if evaluation:
                    eval_issues = evaluation.issues

            # ── 收集 sandbox 输出（在 exec 清理前，_run_with_session 内部）──
            if sandbox_result and sandbox_result.get("test_passed"):
                if _sandbox_dir:
                    sandbox_output_dir = Path(_sandbox_dir) / "output"
                    if sandbox_output_dir.exists():
                        _collected_outputs = _collect_sandbox_outputs(
                            sandbox_dir=Path(_sandbox_dir),
                            nodespec_yaml=nodespec_yaml,
                        )
                if not _collected_outputs and _exec_sandbox_dirs:
                    _collected_outputs = _collect_sandbox_outputs(
                        sandbox_dir=Path(_exec_sandbox_dirs[-1]),
                        nodespec_yaml=nodespec_yaml,
                    )
                # 应用 port_map 反向映射
                if _collected_outputs and _sandbox_dir:
                    port_map_path = Path(_sandbox_dir) / "port_map.json"
                    if port_map_path.exists():
                        try:
                            import json as _json
                            pm = _json.loads(port_map_path.read_text("utf-8"))
                            reverse = {v: k for k, v in pm.get("outputs", {}).items()}
                            remapped: dict[str, str] = {}
                            for name, content in _collected_outputs.items():
                                mapped = reverse.get(name, name)
                                if mapped in remapped:
                                    continue
                                remapped[mapped] = content
                            _collected_outputs = remapped
                        except Exception:
                            pass

        try:
            await asyncio.to_thread(_run_with_session)
        finally:
            tracker3.flush()
            LLMConfig.clear_token_tracker()
            # ── 清理执行沙箱目录 + 节点工作目录临时文件 ──
            import shutil as _shutil
            # 1) 清理追踪到的 exec sandbox 目录
            for _esb in _exec_sandbox_dirs:
                try:
                    _shutil.rmtree(_esb, ignore_errors=True)
                except Exception:
                    pass
            # 2) 兜底：扫描 tmp/ 中遗漏的 _exec_* 目录
            if _sandbox_dir:
                tmp_root = Path(_sandbox_dir).parent
                for _d in tmp_root.iterdir():
                    if _d.is_dir() and _d.name.startswith("_exec_"):
                        try:
                            _shutil.rmtree(_d, ignore_errors=True)
                        except Exception:
                            pass
            # 3) 清理节点工作目录中的运行时临时文件（保留 nodespec.yaml + profile/ + port_map.json + input/ + output/）
            if _sandbox_dir:
                _node_work = Path(_sandbox_dir)
                for _item in _node_work.iterdir():
                    if _item.name in ("nodespec.yaml", "profile", "port_map.json", "input", "output"):
                        continue
                    try:
                        if _item.is_dir():
                            _shutil.rmtree(_item, ignore_errors=True)
                        else:
                            _item.unlink(missing_ok=True)
                    except Exception:
                        pass

        # ── 管理 Agent 记录的经验（record_lesson 工具输出，跨轮次累积）──
        if _recorded_lesson:
            print(f"[Memory Curator] Starting review of lesson: {_recorded_lesson[:80]}...", flush=True)
            try:
                import json as _json_local, re as _re_local
                from agents.llm_config import LLMConfig as _LLMCfg
                from agents.node_generator.shared.memory import (
                    get_experience_store as _get_store,
                    build_experience_entry as _build_entry,
                )

                sw_name = request.target_software or ""
                if not sw_name and nodespec_yaml:
                    try:
                        import yaml as _y_local
                        spec = _y_local.safe_load(nodespec_yaml)
                        sw_name = (spec.get("metadata", {}).get("tags", {}).get("software", "")) or ""
                    except Exception:
                        pass
                if not sw_name:
                    sw_name = "general"

                store = _get_store(sw_name)
                existing = store.query(task=request.description or "", n=5)
                existing_text = "\n".join(
                    f"- [{e.get('result','?')}] {e.get('task','')[:80]}: {'; '.join(e.get('lessons',[]))}"
                    for e in existing
                ) or "(no existing memories)"

                msgs = (last_state or {}).get("messages_history", [])
                from langchain_core.messages import AIMessage as _AIMsg
                ai_msgs = [m for m in msgs if isinstance(m, _AIMsg)]
                context = "\n---\n".join(
                    (m.content or "")[:400] for m in ai_msgs[-3:]
                ) if ai_msgs else "(no context)"

                curator = _LLMCfg.get_chat_model(purpose="memory_curator", temperature=0.0)
                from agents.common.prompt_loader import load_prompt as _load_prompt
                prompt = _load_prompt(
                    "subagent/memory_curator/prompts/curator.jinja2",
                    lesson=_recorded_lesson,
                    software=sw_name,
                    existing=existing_text,
                    context=context,
                )
                resp = curator.invoke(prompt)
                content = resp.content if hasattr(resp, 'content') else str(resp)
                try:
                    m = _re_local.search(r'\{[^}]+\}', content)
                    decision = _json_local.loads(m.group()) if m else _json_local.loads(content)
                except Exception:
                    decision = {"action": "add", "modified_lesson": _recorded_lesson}

                action = decision.get("action", "add")
                if action in ("add", "modify"):
                    lesson = decision.get("modified_lesson", _recorded_lesson)[:200]
                    entry = _build_entry(
                        task=request.description or "",
                        software=sw_name,
                        result="failure",
                        lessons=[lesson],
                    )
                    store.add(entry)
                    print(f"[Memory Curator] {action} for '{sw_name}': {lesson[:80]}", flush=True)
                else:
                    print(f"[Memory Curator] Skipped for '{sw_name}'. decision={_json_local.dumps(decision, ensure_ascii=False)}", flush=True)

                # ── 保存 curator 决策日志 ──
                try:
                    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    curator_log = {
                        "timestamp": timestamp,
                        "action": action,
                        "proposed_lesson": _recorded_lesson,
                        "curator_decision": decision,
                        "software": sw_name,
                    }
                    log_dir = paths.projects_dir / request.project_id / "tmp"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    (log_dir / f"curator_{timestamp}.json").write_text(
                        _json_local.dumps(curator_log, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[Memory Curator] Failed: {e}. Fallback save.", flush=True)
                try:
                    from agents.node_generator.shared.memory import (
                        get_experience_store as _fb_store,
                        build_experience_entry as _fb_entry,
                    )
                    s = _fb_store(request.target_software or "general")
                    s.add(_fb_entry(
                        task=request.description or "",
                        software=request.target_software or "general",
                        result="failure",
                        lessons=[_recorded_lesson[:200]],
                    ))
                except Exception:
                    pass

        # 保存到 run 目录
        saved_path = None
        # 节点工作目录即 saved_path（文件已在 tmp/<node_name>/ 中）
        if _sandbox_dir:
            try:
                saved_path = str(Path(_sandbox_dir).relative_to(settings.project_root))
            except ValueError:
                saved_path = _sandbox_dir
        result = last_state.get("result") if last_state else None
        if not result and not nodespec_yaml:
            error_msg = last_error or "Node Generator 未能生成节点"
            raise HTTPException(status_code=500, detail=error_msg)

        # 提取节点名
        if nodespec_yaml:
            import yaml as _yaml
            try:
                spec_data = _yaml.safe_load(nodespec_yaml)
                node_name = spec_data.get("metadata", {}).get("name", "generated-node")
            except Exception:
                node_name = "generated-node"
        else:
            node_name = result.node_name if result else "unknown"

        # ── outputs 已在 _run_with_session 中收集（清理前），直接使用 ──
        outputs = _collected_outputs

        return NodeGenAPIResponse(
            node_name=node_name,
            nodespec_yaml=nodespec_yaml,
            run_sh=run_sh or None,
            input_templates=result.input_templates if result else {},
            saved_path=saved_path,
            evaluation=evaluation,
            error=last_error,
            outputs=outputs,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Node Generator 运行时失败: {e}")


# ─── Node Accept — 持久化生成的节点 ────────────────────────────────────────────

@router.post("/node/accept", response_model=NodeAcceptResponse, summary="将生成的节点持久化到节点库")
async def accept_generated_node(
    request: NodeAcceptRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> NodeAcceptResponse:
    """将 prefab generator 生成的节点保存到 userdata/nodes/。

    - 重名检测：同时检查 userdata/nodes/ 和根目录 nodes/
    - 重名时自动添加后缀 _1, _2, ...
    - 写入后触发 node index reindex
    """
    try:
        import yaml

        node_name = request.node_name
        category = request.category

        # ── 重名检测与自动后缀 ──
        nodes_root = paths.nodes_dir / category
        builtin_nodes_root = settings.project_root / "nodes" / category
        target_dir = nodes_root / node_name
        collision_renamed = False

        def _name_exists(name: str) -> bool:
            """检查名称是否已存在于 userdata 或 builtin 节点目录。"""
            userdata_check = nodes_root / name / "nodespec.yaml"
            builtin_check = builtin_nodes_root / name / "nodespec.yaml"
            return userdata_check.exists() or builtin_check.exists()

        if _name_exists(node_name):
            suffix = 1
            while True:
                candidate = f"{node_name}_{suffix}"
                if not _name_exists(candidate):
                    node_name = candidate
                    target_dir = nodes_root / candidate
                    collision_renamed = True
                    break
                suffix += 1

        # ── 写入文件 ──
        target_dir.mkdir(parents=True, exist_ok=True)

        # nodespec.yaml
        (target_dir / "nodespec.yaml").write_text(request.nodespec_yaml, encoding="utf-8")

        saved_path = str(target_dir.relative_to(settings.project_root))

        # profile/run.sh
        if request.run_sh:
            profile_dir = target_dir / "profile"
            profile_dir.mkdir(exist_ok=True)
            (profile_dir / "run.sh").write_text(request.run_sh, encoding="utf-8")
            (profile_dir / "run.sh").chmod(0o755)

            # 输入模板
            for tpl_name, tpl_content in request.input_templates.items():
                (profile_dir / tpl_name).write_text(tpl_content, encoding="utf-8")

        # ── 触发 reindex ──
        try:
            from node_index.scanner import scan_nodes, write_index
            index = scan_nodes(settings.project_root)
            write_index(index, settings.project_root)
        except Exception:
            pass

        return NodeAcceptResponse(
            node_name=node_name,
            saved_path=saved_path,
            collision_renamed=collision_renamed,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"节点入库失败: {e}")


# ─── Ephemeral Node Agent (Runtime) ────────────────────────────────────────────

def _load_ephemeral_settings() -> dict[str, Any]:
    """从 userdata/settings.yaml 加载 ephemeral 运行时配置。"""
    settings_path = Path(__file__).parent.parent.parent / "userdata" / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        import yaml
        with settings_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("ephemeral", {})
    except Exception:
        return {}


def _load_prefab_settings() -> dict[str, Any]:
    """从 userdata/settings.yaml 加载 prefab 运行时配置。"""
    settings_path = Path(__file__).parent.parent.parent / "userdata" / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        import yaml
        with settings_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("prefab", {})
    except Exception:
        return {}


@router.post("/ephemeral", response_model=EphemeralGenResponse, summary="运行临时节点 Agent")
async def ephemeral_generate(
    request: EphemeralGenRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> EphemeralGenResponse:
    """为临时节点生成 Python 脚本并在服务端沙箱执行。

    由 Argo Pod 的 wrapper 脚本在运行时调用。
    内部运行完整的外循环（generate → evaluate → retry），wrapper 只需调一次。
    """
    try:
        from agents.node_generator.ephemeral.graph import run_ephemeral_node_generator
        from agents.node_generator.ephemeral.evaluator import evaluate_ephemeral_node
        from agents.schemas import NodeGenRequest, EvaluationResult

        gen_request = NodeGenRequest(
            semantic_type="ephemeral",
            description=request.description,
            node_mode="ephemeral",
            ports=request.ports,
            context=request.context,
        )

        ephemeral_cfg = _load_ephemeral_settings()
        max_outer = ephemeral_cfg.get("max_outer_rounds", 2)

        script = ""
        exec_stdout = ""
        exec_stderr = ""
        exec_return_code = -1
        generated_files: list[str] = []
        image_files: list[str] = []
        vision_feedback: list[str] = []
        evaluation = None
        sandbox_dirs: list[str] = []

        tracker4 = TokenUsageTracker(paths, purpose="ephemeral", currency=_load_currency(settings))

        def _run_with_session():
            nonlocal script, exec_stdout, exec_stderr, exec_return_code
            nonlocal generated_files, image_files, vision_feedback, evaluation
            LLMConfig.set_token_tracker(tracker4)

            try:
                for outer_round in range(max_outer):
                    # --- Generate (含内循环 agent + sandbox) ---
                    start_session("ephemeral_gen", {
                        "description": request.description,
                        "ports": request.ports,
                        "outer_round": outer_round,
                        "run_name": request.run_name,
                        "project_id": request.project_id,
                    })
                    try:
                        state = run_ephemeral_node_generator(
                            gen_request,
                            _input_data=request.input_data,
                            _project_id=request.project_id,
                            _projects_dir=str(paths.projects_dir),
                            _run_name=request.run_name,
                            iteration=outer_round,
                            script=script,
                            run_sh=script,
                            exec_stderr=exec_stderr,
                            vision_feedback=vision_feedback,
                        )
                    finally:
                        log = end_session()
                        if log:
                            try:
                                log_dict = log.to_dict()
                                if request.run_name and request.project_id:
                                    run_log_dir = (
                                        paths.projects_dir / request.project_id
                                        / "runs" / request.run_name
                                    )
                                    run_log_dir.mkdir(parents=True, exist_ok=True)
                                    time_str = datetime.now().strftime("%H-%M-%S")
                                    agent_type = log_dict.get("agent_type", "unknown")
                                    node_id = request.context.get("node_id", "unknown") if request.context else "unknown"
                                    json_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.json"
                                    json_path.write_text(json.dumps(log_dict, indent=2, ensure_ascii=False, default=str))
                                    # 同步保存人类可读 .txt 文件
                                    from agents.common.session_logger import format_log_as_text
                                    txt_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.txt"
                                    txt_path.write_text(format_log_as_text(log_dict), encoding="utf-8")
                            except Exception:
                                pass

                    script = state.get("script", "") or state.get("run_sh", "")
                    exec_stdout = state.get("exec_stdout", "")
                    exec_stderr = state.get("exec_stderr", "")
                    exec_return_code = state.get("exec_return_code", -1)
                    generated_files = state.get("generated_files", [])
                    image_files = state.get("image_files", [])

                    # 记录沙箱目录（用于后续清理）
                    sb_dir = state.get("_sandbox_dir", "")
                    if sb_dir:
                        sandbox_dirs.append(sb_dir)

                    # --- 执行失败 → 带 stderr 进下一轮 ---
                    if exec_return_code != 0:
                        vision_feedback = []
                        continue

                    # --- 执行成功 → 评估 ---
                    start_session("ephemeral_eval", {
                        "description": request.description,
                        "ports": request.ports,
                        "outer_round": outer_round,
                        "image_count": len(image_files),
                        "run_name": request.run_name,
                        "project_id": request.project_id,
                    })
                    try:
                        eval_state = {
                            "request": gen_request,
                            "script": script,
                            "run_sh": script,
                            "exec_stdout": exec_stdout,
                            "exec_stderr": exec_stderr,
                            "exec_return_code": exec_return_code,
                            "image_files": image_files,
                            "generated_files": generated_files,
                            "iteration": outer_round,
                        }
                        eval_result = evaluate_ephemeral_node(eval_state)
                    finally:
                        log = end_session()
                        if log:
                            try:
                                log_dict = log.to_dict()
                                if request.run_name and request.project_id:
                                    run_log_dir = (
                                        paths.projects_dir / request.project_id
                                        / "runs" / request.run_name
                                    )
                                    run_log_dir.mkdir(parents=True, exist_ok=True)
                                    time_str = datetime.now().strftime("%H-%M-%S")
                                    agent_type = log_dict.get("agent_type", "unknown")
                                    node_id = request.context.get("node_id", "unknown") if request.context else "unknown"
                                    json_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.json"
                                    json_path.write_text(json.dumps(log_dict, indent=2, ensure_ascii=False, default=str))
                                    # 同步保存人类可读 .txt 文件
                                    from agents.common.session_logger import format_log_as_text
                                    txt_path = run_log_dir / f"{agent_type}_r{outer_round}_{node_id}_{time_str}.txt"
                                    txt_path.write_text(format_log_as_text(log_dict), encoding="utf-8")
                            except Exception:
                                pass

                    evaluation = eval_result.get("evaluation")
                    if evaluation and evaluation.passed:
                        break

                    # 评估不通过 → 带反馈进下一轮
                    if evaluation:
                        vision_feedback = evaluation.issues + evaluation.suggestions
                    else:
                        vision_feedback = []

            finally:
                # 清理沙箱工作目录
                from agents.node_generator.shared.sandbox_base import cleanup_sandbox_dir
                for sb_dir in sandbox_dirs:
                    cleanup_sandbox_dir(Path(sb_dir))

        await asyncio.to_thread(_run_with_session)
        tracker4.flush()
        LLMConfig.clear_token_tracker()

        # success 要求：脚本执行成功 且 evaluator 通过（或未评估）
        eval_passed = evaluation.passed if evaluation else True
        overall_success = (exec_return_code == 0) and eval_passed

        # 将 sandbox 中生成的图片复制到项目文件目录，使前端可通过项目 files API 访问
        if image_files:
            import shutil as _shutil
            if request.project_id:
                from api.services.project_service import _project_files_dir
                target_dir = _project_files_dir(request.project_id)
            else:
                target_dir = paths.globalfiles_dir
            for img_path in image_files:
                try:
                    src = Path(img_path)
                    if src.is_file():
                        _shutil.copy2(src, target_dir / src.name)
                except Exception:
                    pass

        return EphemeralGenResponse(
            script=script,
            stdout=exec_stdout[:5000],
            stderr=exec_stderr[:2000],
            return_code=exec_return_code,
            success=overall_success,
            generated_files=generated_files,
            image_files=image_files,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ephemeral Agent 失败: {e}")


@router.post("/ephemeral/evaluate", response_model=EphemeralEvalResponse, summary="视觉评估临时节点输出")
async def ephemeral_evaluate(
    request: EphemeralEvalRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> EphemeralEvalResponse:
    """对临时节点的输出进行多模态视觉评估。

    接收脚本输出和 base64 编码的图片，返回评估结果。
    """
    try:
        from agents.node_generator.ephemeral.evaluator import evaluate_node_vision
        from agents.schemas import NodeGenRequest, EvaluationResult

        gen_request = NodeGenRequest(
            semantic_type="ephemeral",
            description=request.description,
            node_mode="ephemeral",
            ports=request.ports,
        )

        state: dict[str, Any] = {
            "request": gen_request,
            "script": request.script,
            "run_sh": request.script,
            "exec_stdout": request.stdout,
            "exec_stderr": request.stderr,
            "exec_return_code": 0 if not request.stderr else 1,
            "image_files": [],  # 图片通过 base64 传入
            "iteration": 0,
        }

        # 将 base64 图片写入临时文件
        import tempfile
        import base64 as b64mod
        tmp_image_paths: list[str] = []
        if request.image_base64_list:
            tmpdir = tempfile.mkdtemp(prefix="mf_eval_")
            for i, b64str in enumerate(request.image_base64_list):
                img_path = f"{tmpdir}/image_{i}.png"
                with open(img_path, "wb") as f:
                    f.write(b64mod.b64decode(b64str))
                tmp_image_paths.append(img_path)
            state["image_files"] = tmp_image_paths

        tracker5 = TokenUsageTracker(paths, purpose="ephemeral_evaluator", currency=_load_currency(settings))

        def _run_eval():
            LLMConfig.set_token_tracker(tracker5)
            start_session("ephemeral_eval", {
                "description": request.description,
                "ports": request.ports,
                "image_count": len(request.image_base64_list),
                "run_name": request.run_name,
                "project_id": request.project_id,
            })
            try:
                return evaluate_node_vision(state)
            finally:
                log = end_session()
                if log:
                    try:
                        log_dict = log.to_dict()
                        if request.run_name and request.project_id:
                            run_log_dir = (
                                paths.projects_dir / request.project_id
                                / "runs" / request.run_name
                            )
                            run_log_dir.mkdir(parents=True, exist_ok=True)
                            time_str = datetime.now().strftime("%H-%M-%S")
                            agent_type = log_dict.get("agent_type", "unknown")
                            json_path = run_log_dir / f"{agent_type}_{time_str}.json"
                            json_path.write_text(json.dumps(log_dict, indent=2, ensure_ascii=False, default=str))
                            # 同步保存人类可读 .txt 文件
                            from agents.common.session_logger import format_log_as_text
                            txt_path = run_log_dir / f"{agent_type}_{time_str}.txt"
                            txt_path.write_text(format_log_as_text(log_dict), encoding="utf-8")
                    except Exception:
                        pass

        result = await asyncio.to_thread(_run_eval)
        tracker5.flush()
        LLMConfig.clear_token_tracker()

        # 清理临时文件
        for p in tmp_image_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

        evaluation = result.get("evaluation")
        if evaluation:
            return EphemeralEvalResponse(
                passed=evaluation.passed,
                issues=evaluation.issues,
                suggestions=evaluation.suggestions,
            )
        return EphemeralEvalResponse(passed=True, issues=[], suggestions=["评估未返回结果"])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ephemeral 评估失败: {e}")


# ─── Save Session ─────────────────────────────────────────────────────────────

@router.post("/save-session", response_model=SaveSessionResponse, summary="保存对话会话")
async def save_session(
    request: SaveSessionRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> SaveSessionResponse:
    """将前端对话消息保存到 userdata/agent_sessions/{date}/{session_id}/conversation.json。

    由前端在用户清空对话面板时调用，保存完整的对话历史。
    Agent 调用详情（prompt + LLM response）已在每次调用时自动保存。
    """
    try:
        saved_path = await asyncio.to_thread(
            save_conversation,
            messages=request.messages,
            session_id=request.session_id,
            userdata_root=paths.agent_sessions_dir.parent,
        )
        return SaveSessionResponse(
            saved=True,
            session_id=request.session_id,
            path=str(saved_path.relative_to(settings.project_root)),
            message_count=len(request.messages),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存会话失败: {e}")
