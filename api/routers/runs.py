"""运行监控 API 路由。

GET  /api/v1/runs               — 列出 Argo 运行
GET  /api/v1/runs/{name}        — 运行详情
GET  /api/v1/runs/{name}/logs   — 运行日志
POST /api/v1/runs/{name}/save-outputs — 将输出参数写入 userdata/runs/{name}/outputs.json
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any

import yaml

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.auth import CurrentUser, require_user
from api.config import Settings, get_settings
from api.dependencies import get_user_paths
from api.user_paths import UserPaths
from api.models.runs import RunDetailResponse, RunListResponse, RunLogsResponse, RunSummaryResponse
from api.services.argo_service import ArgoService
from api.services.project_service import ProjectService

router = APIRouter(prefix="/runs", tags=["runs"])


def get_argo_service(settings: Settings = Depends(get_settings)) -> ArgoService:
    return ArgoService(namespace=settings.argo_namespace)


@router.get("", response_model=RunListResponse, summary="列出所有运行")
def list_runs(
    project_id: str | None = None,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> RunListResponse:
    """纯本地 runs 列表，不依赖 Argo。"""
    import datetime

    runs: list[dict] = []
    if not project_id:
        return RunListResponse(total=0, runs=[])

    project_runs_dir = paths.projects_dir / project_id / "runs" if paths else settings.userdata_root / "projects" / project_id / "runs"
    if not project_runs_dir.exists():
        return RunListResponse(total=0, runs=[])

    for d in sorted(project_runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        # 跳过孤儿目录：必须包含 outputs.json 或 mf-workflow.yaml 才算有效运行
        if not (d / "outputs.json").exists() and not (d / "mf-workflow.yaml").exists():
            continue
        name = d.name
        phase = "Local"
        started_at = None
        finished_at = None
        duration_seconds = None
        outputs_path = d / "outputs.json"
        if outputs_path.exists():
            try:
                data = json.loads(outputs_path.read_text())
                phase = data.get("phase", "Local")
                started_at = data.get("started_at") or None
                finished_at = data.get("finished_at") or None
            except (json.JSONDecodeError, OSError):
                pass
        # Fallback: use directory mtime if no timing in outputs.json
        if not finished_at:
            try:
                mtime = d.stat().st_mtime
                finished_at = datetime.datetime.fromtimestamp(
                    mtime, tz=datetime.timezone.utc
                ).isoformat()
            except OSError:
                pass
        # Compute duration from ISO timestamps
        if started_at and finished_at:
            try:
                t0 = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                duration_seconds = (t1 - t0).total_seconds()
            except (ValueError, TypeError):
                pass
        runs.append({
            "name": name,
            "namespace": "",
            "uid": "",
            "phase": phase,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "labels": {},
        })

    return RunListResponse(
        total=len(runs),
        runs=[RunSummaryResponse(**r) for r in runs],
    )


@router.get("/{name}", response_model=RunDetailResponse, summary="运行详情")
def get_run(
    name: str,
    project_id: str | None = None,
    argo: ArgoService = Depends(get_argo_service),
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> RunDetailResponse:
    # Try Argo first
    try:
        wf = argo.get_workflow(name)
        meta = wf.get("metadata", {})
        status = wf.get("status", {})
        return RunDetailResponse(
            name=meta.get("name", name),
            namespace=meta.get("namespace", ""),
            phase=status.get("phase", "Unknown"),
            raw=wf,
        )
    except RuntimeError:
        pass  # Fall through to local data

    # Fallback: local-only run
    if not project_id:
        raise HTTPException(status_code=404, detail=f"Run '{name}' not found in Argo or locally")

    projects_root = paths.projects_dir if paths else settings.userdata_root / "projects"
    run_dir = projects_root / project_id / "runs" / name
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{name}' not found")

    phase = "Local"
    outputs_path = run_dir / "outputs.json"
    node_outputs: dict[str, str] = {}
    if outputs_path.exists():
        try:
            data = json.loads(outputs_path.read_text())
            phase = data.get("phase", "Local")
            node_outputs = data.get("node_outputs", {})
        except (json.JSONDecodeError, OSError):
            pass

    # Build a synthetic Argo-like raw response for the frontend
    raw: dict[str, Any] = {
        "metadata": {"name": name, "namespace": ""},
        "status": {"phase": phase, "nodes": {}},
    }

    return RunDetailResponse(
        name=name,
        namespace="",
        phase=phase,
        raw=raw,
    )


@router.delete("/{name}", status_code=204, summary="删除运行本地数据")
def delete_run(
    name: str,
    project_id: str | None = None,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> None:
    """只删除本地 run 数据。Argo 数据由 TTL 策略自动清理。"""
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    projects_root = paths.projects_dir if paths else settings.userdata_root / "projects"
    run_dir = projects_root / project_id / "runs" / name
    if run_dir.exists():
        shutil.rmtree(run_dir)


@router.post("/{name}/stop", summary="中止运行中的工作流")
def stop_run(
    name: str,
    project_id: str | None = None,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    argo: ArgoService = Depends(get_argo_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    """终止 Argo 工作流并清理本地数据。"""
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    # 1. 终止 Argo 工作流
    try:
        argo.delete_workflow(name)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"终止 Argo 工作流失败: {e}")
    # 2. 清理本地数据
    projects_root = paths.projects_dir if paths else settings.userdata_root / "projects"
    run_dir = projects_root / project_id / "runs" / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    return {"stopped": name, "project_id": project_id}


@router.get("/{name}/logs", response_model=RunLogsResponse, summary="运行日志")
def get_run_logs(name: str, argo: ArgoService = Depends(get_argo_service)) -> RunLogsResponse:
    try:
        logs = argo.get_logs(name)
    except RuntimeError:
        logs = "Argo workflow 已删除或不可达，日志不可用。"
    return RunLogsResponse(name=name, logs=logs)


# ── helpers ──────────────────────────────────────────────────────────────────────

def _apply_nodespec_to_canvas_node(spec: dict, cn_data: dict) -> None:
    """将 nodespec 中的展示字段写入 canvas 节点 data dict（就地修改）。"""
    meta = spec.get("metadata", {}) or {}

    # 基础展示字段
    for key in ("display_name", "name", "version", "description", "category", "node_type"):
        if meta.get(key):
            cn_data[key] = meta[key]

    # software 来源：tags.software 或 base_image_ref
    tags = meta.get("tags", {}) or {}
    sw = tags.get("software") or meta.get("base_image_ref")
    if sw:
        cn_data["software"] = sw

    # 如果节点有 nodespec_path 指向 userdata/nodes/，更新之
    node_name = meta.get("name", "")
    if node_name:
        cn_data["nodespec_path"] = f"userdata/nodes/{node_name}/nodespec.yaml"

    # Stream I/O
    raw_stream_in = spec.get("stream_inputs", []) or []
    raw_stream_out = spec.get("stream_outputs", []) or []

    def _to_stream_port(p: dict) -> dict:
        io_type = p.get("io_type", {}) or {}
        return {
            "name": p.get("name", ""),
            "display_name": p.get("display_name", p.get("name", "")),
            "category": io_type.get("category", "software_data_package"),
            "detail": io_type.get("shape", "") or io_type.get("data_type", "") or "",
            "required": bool(p.get("required", False)),
        }

    cn_data["stream_inputs"] = [_to_stream_port(p) for p in raw_stream_in]
    cn_data["stream_outputs"] = [_to_stream_port(p) for p in raw_stream_out]

    # Onboard inputs (parameters)
    raw_inputs = spec.get("onboard_inputs", []) or []

    def _to_onboard_param(inp: dict) -> dict:
        return {
            "name": inp.get("name", ""),
            "display_name": inp.get("display_name", inp.get("name", "")),
            "type": inp.get("kind", inp.get("type", "text")),
            "default": inp.get("default"),
            "description": inp.get("description"),
            "unit": inp.get("unit"),
            "enum_values": inp.get("allowed_values") or inp.get("enum_values"),
            "required": bool(inp.get("required", False)),
            "min": inp.get("min_value") if inp.get("min_value") is not None else inp.get("min"),
            "max": inp.get("max_value") if inp.get("max_value") is not None else inp.get("max"),
            "resource_param": bool(inp.get("resource_param", False)),
            "multiple_input": bool(inp.get("multiple_input", False)),
            "allow_other": bool(inp.get("allow_other", False)),
        }

    cn_data["onboard_inputs"] = [_to_onboard_param(inp) for inp in raw_inputs]

    # Resources
    res = spec.get("resources", {}) or {}
    if res.get("cpu_cores") or res.get("cpu"):
        cn_data["resources"] = {
            "cpu": int(res.get("cpu_cores", res.get("cpu", 1))),
            "mem_gb": float(res.get("mem_gb", 0)),
            "mem_overhead": float(res.get("mem_overhead", 0)),
            "gpu": int(res.get("gpu", 0)),
            "estimated_walltime_hours": float(res.get("estimated_walltime_hours", 1)),
            "scratch_disk_gb": float(res.get("scratch_disk_gb", 0)),
            "parallel_tasks": int(res.get("parallel_tasks", 1)),
        }

    # Onboard outputs (quality gates)
    raw_outputs = spec.get("onboard_outputs", []) or []

    def _to_onboard_output(out: dict) -> dict:
        return {
            "name": out.get("name", ""),
            "display_name": out.get("display_name", out.get("name", "")),
            "kind": out.get("kind", out.get("type", "text")),
            "description": out.get("description"),
            "unit": out.get("unit"),
            "quality_gate": bool(out.get("quality_gate", False)),
            "gate_default": out.get("gate_default"),
            "gate_description": out.get("gate_description"),
        }

    cn_data["onboard_outputs"] = [_to_onboard_output(o) for o in raw_outputs]


@router.post("/{name}/save-outputs", summary="保存运行输出到 runs/ 目录")
def save_run_outputs(
    name: str,
    project_id: str | None = Query(None),
    canvas: dict[str, Any] | None = Body(None),
    argo: ArgoService = Depends(get_argo_service),
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    从 Argo 拉取工作流状态，将输出参数写入 runs/{name}/outputs.json。
    可选附带 canvas 状态（body），保存为 afterrun_canvas.json。
    由前端在运行到达终态时调用。
    """
    try:
        wf = argo.get_workflow(name)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    status = wf.get("status", {})
    nodes = status.get("nodes", {})

    # 提取每个 Pod 节点的输出参数，key = "{canvasNodeId}.{paramName}"
    # 对 Failed/Error 节点，抓取 pod 日志存入 _error 字段
    node_outputs: dict[str, str] = {}
    node_errors: dict[str, dict[str, str]] = {}
    node_details: dict[str, dict[str, str]] = {}
    for node in nodes.values():
        if node.get("type") != "Pod":
            continue
        template_name = node.get("templateName", "")
        if not template_name.startswith("mf-"):
            continue
        canvas_id = template_name[3:]
        phase = node.get("phase", "")

        # Collect per-node timing
        node_details[canvas_id] = {
            "phase": phase,
            "started_at": node.get("startedAt", ""),
            "finished_at": node.get("finishedAt", ""),
        }

        # Collect output parameters
        for param in node.get("outputs", {}).get("parameters", []):
            if param.get("name") and param.get("value") is not None:
                node_outputs[f"{canvas_id}.{param['name']}"] = str(param["value"])

        # For failed nodes, grab pod logs
        if phase in ("Failed", "Error"):
            argo_node_id = node.get("id", "")  # This IS the pod name in Argo
            argo_message = node.get("message", "")
            try:
                logs = argo.get_pod_logs(argo_node_id, tail=500)
                if logs is None:
                    error_msg = f"Pod 已被清理或命名空间不可达\nArgo message: {argo_message}" if argo_message else "Pod 已被清理或命名空间不可达"
                else:
                    error_msg = logs
            except Exception:
                error_msg = f"Pod 已被清理或命名空间不可达\nArgo message: {argo_message}" if argo_message else "Pod 已被清理或命名空间不可达"
            node_outputs[f"{canvas_id}._error"] = error_msg
            node_errors[canvas_id] = {
                "pod_name": argo_node_id,
                "phase": phase,
                "message": argo_message,
            }

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    projects_root = paths.projects_dir if paths else settings.userdata_root / "projects"
    run_dir = projects_root / project_id / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    outputs_path = run_dir / "outputs.json"
    # Workflow-level timing from Argo
    meta = wf.get("metadata", {})
    outputs_path.write_text(
        json.dumps(
            {
                "phase": status.get("phase", "Unknown"),
                "started_at": status.get("startedAt", ""),
                "finished_at": status.get("finishedAt", ""),
                "node_outputs": node_outputs,
                "node_errors": node_errors,
                "node_details": node_details,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Save afterrun_canvas if provided
    nodegen_updates: dict[str, dict[str, object]] = {}
    if canvas:
        # ── 对成功的 nodegen 节点，从 tmp/ 读取 nodespec 填充 node_generator.result ──
        for cn in canvas.get("nodes", []):
            cn_data = cn.get("data", {})
            ng = cn_data.get("node_generator")
            if not ng:
                continue
            cn_id = cn.get("id", "")
            node_detail = node_details.get(cn_id, {})
            if node_detail.get("phase") != "Succeeded":
                continue
            # 从 tmp/<node_id>/ 读取运行时生成的 nodespec + run.sh
            try:
                tmp_dir = paths.projects_dir / project_id / "tmp" / cn_id if paths else settings.userdata_root / "projects" / project_id / "tmp" / cn_id
                ns_path = tmp_dir / "nodespec.yaml"
                rs_path = tmp_dir / "profile" / "run.sh"
                if ns_path.exists():
                    nodespec_yaml = ns_path.read_text("utf-8")
                    run_sh = rs_path.read_text("utf-8") if rs_path.exists() else ""
                    spec = yaml.safe_load(nodespec_yaml) if nodespec_yaml else None
                    node_name = spec.get("metadata", {}).get("name", cn_id) if isinstance(spec, dict) else cn_id
                    ng["result"] = {
                        "node_name": node_name,
                        "nodespec_yaml": nodespec_yaml,
                        "run_sh": run_sh,
                        "input_templates": ng.get("result", {}).get("input_templates", {}),
                        "evaluation": ng.get("result", {}).get("evaluation"),
                    }
                    # ── 更新节点核心展示字段到 afterrun_canvas ──
                    if isinstance(spec, dict):
                        _apply_nodespec_to_canvas_node(spec, cn_data)
                        # 收集供前端更新 live canvas 的数据
                        nodegen_updates[cn_id] = {
                            "node_name": node_name,
                            "nodespec_yaml": nodespec_yaml,
                            "run_sh": run_sh,
                            "display_name": cn_data.get("display_name", ""),
                            "name": cn_data.get("name", ""),
                            "version": cn_data.get("version", ""),
                            "description": cn_data.get("description", ""),
                            "node_type": cn_data.get("node_type", ""),
                            "category": cn_data.get("category", ""),
                            "software": cn_data.get("software"),
                            "stream_inputs": cn_data.get("stream_inputs", []),
                            "stream_outputs": cn_data.get("stream_outputs", []),
                            "onboard_inputs": cn_data.get("onboard_inputs", []),
                            "onboard_outputs": cn_data.get("onboard_outputs", []),
                            "resources": cn_data.get("resources"),
                            "nodespec_path": cn_data.get("nodespec_path", ""),
                        }
                else:
                    import logging
                    logging.warning(
                        "save_run_outputs: no nodespec.yaml found for nodegen "
                        "node %s in tmp/%s — generated files were not persisted",
                        cn_id, cn_id,
                    )
            except Exception:
                import logging
                logging.warning(
                    "save_run_outputs: failed to read nodespec for nodegen "
                    "node %s from tmp/%s", cn_id, cn_id, exc_info=True,
                )

        # ── 用 port_map.json 重映射 edge handles（Agent 可能重命名了端口）──
        for cn_id in list(nodegen_updates.keys()):
            projects_root = paths.projects_dir if paths else settings.userdata_root / "projects"
            port_map_path = projects_root / project_id / "tmp" / cn_id / "port_map.json"
            if not port_map_path.exists():
                continue
            try:
                import json as _json2
                pm_raw = _json2.loads(port_map_path.read_text("utf-8"))
                input_map: dict[str, str] = (pm_raw.get("inputs") or {}) if isinstance(pm_raw, dict) else {}
                output_map: dict[str, str] = (pm_raw.get("outputs") or {}) if isinstance(pm_raw, dict) else {}

                # Remap edges that connect to/from this nodegen node
                for edge in canvas.get("edges", []):
                    source = edge.get("source", "")
                    target = edge.get("target", "")
                    if source == cn_id:
                        old_handle = edge.get("sourceHandle", "")
                        if old_handle in output_map:
                            edge["sourceHandle"] = output_map[old_handle]
                    if target == cn_id:
                        old_handle = edge.get("targetHandle", "")
                        if old_handle in input_map:
                            edge["targetHandle"] = input_map[old_handle]

                # 将 port_map 和 remapped edges 传回前端
                nodegen_updates[cn_id]["_port_map"] = pm_raw

                # ── 读取 sandbox 输出值（从 tmp/<node_id>/output/）──
                # 只收集 nodespec 中声明的 onboard outputs，不收集 stream outputs
                output_dir = tmp_dir / "output"
                if output_dir.is_dir():
                    ns_path_qg = tmp_dir / "nodespec.yaml"
                    onboard_output_names: set[str] = set()
                    qg_names: set[str] = set()
                    if ns_path_qg.exists():
                        try:
                            import yaml as _y2
                            spec_qg = _y2.safe_load(ns_path_qg.read_text("utf-8"))
                            if isinstance(spec_qg, dict):
                                for oo in spec_qg.get("onboard_outputs", []) or []:
                                    oo_name = oo.get("name", "")
                                    if oo_name:
                                        onboard_output_names.add(oo_name)
                                        if oo.get("quality_gate"):
                                            qg_names.add(oo_name)
                        except Exception:
                            pass

                    output_values: dict[str, str] = {}
                    for f in output_dir.iterdir():
                        if f.is_file() and f.name in onboard_output_names:
                            fname = f.name
                            # quality gate 输出加 _qg_ 前缀，匹配前端 inspector 的 runKey
                            key = f"_qg_{fname}" if fname in qg_names else fname
                            try:
                                output_values[key] = f.read_text("utf-8").strip()
                            except Exception:
                                pass
                    if output_values:
                        nodegen_updates[cn_id]["_output_values"] = output_values

                        # 同时注入 afterrun_canvas 的 nodeStatuses，确保 reload 后也有值
                        canvas_ns = canvas.get("nodeStatuses")
                        if isinstance(canvas_ns, dict) and cn_id in canvas_ns:
                            existing_outputs = dict(canvas_ns[cn_id].get("outputs", {}) or {})
                            existing_outputs.update(output_values)
                            canvas_ns[cn_id]["outputs"] = existing_outputs
            except Exception:
                import logging
                logging.warning(
                    "save_run_outputs: failed to process port_map.json for node %s",
                    cn_id, exc_info=True,
                )

        svc = ProjectService(paths)
        svc.save_afterrun_canvas(project_id, name, canvas)

    # Collect _error texts for failed nodes (so frontend can update nodeStatuses)
    error_texts: dict[str, str] = {}
    for key, val in node_outputs.items():
        if key.endswith("._error"):
            canvas_id = key.rsplit("._error", 1)[0]
            error_texts[canvas_id] = val

    # Record compute usage for billing
    try:
        from api.tracking.compute_tracker import ComputeUsageTracker
        from api.routers.agents import _load_currency
        ct = ComputeUsageTracker(paths, settings.argo_namespace, currency=_load_currency(settings))
        ct.record_workflow(wf, project_id)
    except Exception:
        pass  # Non-critical, don't block the main flow

    return {
        "saved": True,
        "run": name,
        "outputs_count": len(node_outputs),
        "error_texts": error_texts,
        "nodegen_updates": nodegen_updates,
    }


@router.get("/{name}/afterrun-canvas", summary="获取 run 后画布状态")
def get_afterrun_canvas(
    name: str,
    project_id: str,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
) -> dict:
    """返回 run 完成后保存的画布状态（含节点输出值）。"""
    svc = ProjectService(paths)
    canvas = svc.load_afterrun_canvas(project_id, name)
    if canvas is None:
        raise HTTPException(status_code=404, detail="afterrun_canvas.json not found")
    return canvas


@router.get("/{name}/node-logs/{node_id}", summary="获取失败节点的完整 Pod 日志")
def get_node_pod_logs(
    name: str,
    node_id: str,
    argo: ArgoService = Depends(get_argo_service),
    user: CurrentUser = Depends(require_user),
) -> dict:
    """返回指定节点的完整 pod 日志。Pod 已删除时返回 404。"""
    try:
        logs = argo.get_pod_logs(node_id)
    except Exception:
        logs = None
    if logs is None:
        raise HTTPException(
            status_code=404,
            detail="Pod 已被清理或命名空间不可达",
        )
    return {"node_id": node_id, "logs": logs}
