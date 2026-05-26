"""节点目录 API 路由。

GET  /api/v1/nodes                   — 列出所有节点
GET  /api/v1/nodes/search            — 搜索节点
GET  /api/v1/nodes/semantic-registry — 返回完整语义类型注册表
GET  /api/v1/nodes/semantic-types    — 按语义类型分组列出节点
GET  /api/v1/nodes/units             — 返回 KNOWN_UNITS 物理单位注册表
GET  /api/v1/nodes/preferences       — 读取全局节点偏好设置
PUT  /api/v1/nodes/preferences       — 写入全局节点偏好设置
GET  /api/v1/nodes/{name}            — 节点详情
POST /api/v1/nodes/reindex           — 重新生成索引
"""

from __future__ import annotations

from typing import Optional

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user, require_user
from api.config import Settings, get_settings
from api.dependencies import get_user_paths
from api.user_paths import UserPaths
from api.routers.projects import DirectoryEntry, DirectoryListResponse, _scan_directory
from api.models.nodes import (
    NodeDetailResponse,
    NodeIndexInfoResponse,
    NodeListResponse,
    NodeSummaryResponse,
    OnBoardOutputResponse,
    OnBoardParamResponse,
    PortSummaryResponse,
    SemanticRegistryResponse,
    SemanticTypeEntry,
    SemanticTypeGroup,
    SemanticTypesResponse,
)
from api.services.node_index_service import NodeIndexService
from node_index.models import NodeIndexEntry
from nodes.schemas.semantic_registry import load_semantic_registry

router = APIRouter(prefix="/nodes", tags=["nodes"])


def get_node_service(
    settings: Settings = Depends(get_settings),
    paths: UserPaths | None = Depends(get_user_paths),
) -> NodeIndexService:
    svc = NodeIndexService(settings.project_root)
    if paths is not None:
        svc._user_settings_path = paths.settings_file
        svc._user_nodes_dirs = [paths.nodes_dir]
    return svc


def _entry_to_summary(entry: NodeIndexEntry) -> NodeSummaryResponse:
    return NodeSummaryResponse(
        name=entry.name,
        version=entry.version,
        display_name=entry.display_name,
        description=entry.description,
        node_type=entry.node_type,
        category=entry.category,
        semantic_type=entry.semantic_type,
        semantic_display_name=entry.semantic_display_name,
        base_image_ref=entry.base_image_ref,
        nodespec_path=entry.nodespec_path,
        software=entry.software,
        deprecated=entry.deprecated,
        methods=entry.methods,
        domains=entry.domains,
        capabilities=entry.capabilities,
        keywords=entry.keywords,
        resources_cpu=entry.resources_cpu,
        resources_memory_gb=entry.resources_memory_gb,
        resources_mem_gb=entry.resources_mem_gb,
        resources_gpu=entry.resources_gpu,
        resources_walltime_hours=entry.resources_walltime_hours,
        resources_scratch_disk_gb=entry.resources_scratch_disk_gb,
        resources_parallel_tasks=entry.resources_parallel_tasks,
        stream_inputs=[
            PortSummaryResponse(**p.model_dump()) for p in entry.stream_inputs
        ],
        stream_outputs=[
            PortSummaryResponse(**p.model_dump()) for p in entry.stream_outputs
        ],
        onboard_inputs_count=len(entry.onboard_inputs),
        onboard_outputs_count=len(entry.onboard_outputs),
    )


@router.get("", response_model=NodeListResponse, summary="列出所有节点")
def list_nodes(
    category: str | None = Query(None, description="按 category 过滤"),
    node_type: str | None = Query(None, description="按 node_type 过滤 (compute/lightweight)"),
    semantic_type: str | None = Query(None, description="按 semantic_type 过滤，如 'geometry-optimization'"),
    svc: NodeIndexService = Depends(get_node_service),
) -> NodeListResponse:
    entries = svc.list_all()

    if category:
        entries = [e for e in entries if e.category == category]
    if node_type:
        entries = [e for e in entries if e.node_type == node_type]
    if semantic_type:
        entries = [e for e in entries if e.semantic_type == semantic_type]

    return NodeListResponse(
        total=len(entries),
        nodes=[_entry_to_summary(e) for e in entries],
    )


@router.get("/search", response_model=NodeListResponse, summary="搜索节点")
def search_nodes(
    q: str = Query(..., description="搜索查询"),
    limit: int = Query(20, ge=1, le=100, description="最大返回数量"),
    svc: NodeIndexService = Depends(get_node_service),
) -> NodeListResponse:
    results = svc.search(q, max_results=limit)
    return NodeListResponse(
        total=len(results),
        nodes=[_entry_to_summary(e) for e in results],
    )


@router.get("/index-info", response_model=NodeIndexInfoResponse, summary="索引元信息")
def get_index_info(svc: NodeIndexService = Depends(get_node_service)) -> NodeIndexInfoResponse:
    info = svc.get_index_info()
    return NodeIndexInfoResponse(**info)


@router.post("/reindex", response_model=NodeIndexInfoResponse, summary="重新生成索引")
def reindex(svc: NodeIndexService = Depends(get_node_service)) -> NodeIndexInfoResponse:
    idx = svc.refresh()
    return NodeIndexInfoResponse(
        total_nodes=idx.total_nodes,
        generated_at=idx.generated_at,
        mf_version=idx.mf_version,
    )


# 注意：此端点必须定义在 /{name} 之前，否则 "semantic-registry" 会被当作 name 参数
@router.get("/semantic-registry", response_model=SemanticRegistryResponse, summary="返回完整语义类型注册表")
def get_semantic_registry() -> SemanticRegistryResponse:
    """返回完整的语义类型注册表，供前端在启动时加载。"""
    registry = load_semantic_registry()
    return SemanticRegistryResponse(
        version=registry.version,
        types={
            key: SemanticTypeEntry(
                display_name=entry.display_name,
                description=entry.description,
                domain=entry.domain,
            )
            for key, entry in registry.types.items()
        },
    )


@router.get("/semantic-types", response_model=SemanticTypesResponse, summary="按语义操作类型分组列出节点")
def list_semantic_types(
    svc: NodeIndexService = Depends(get_node_service),
) -> SemanticTypesResponse:
    """返回所有已知的 semantic_type 及其下的节点列表，供 Palette 两段式分组使用。"""
    entries = svc.list_all()
    registry = load_semantic_registry()

    # 按 semantic_type 分组（无 semantic_type 的节点跳过）
    groups_map: dict[str, list[NodeSummaryResponse]] = {}
    for entry in entries:
        st = entry.semantic_type
        if st is None:
            continue
        if st not in groups_map:
            groups_map[st] = []
        groups_map[st].append(_entry_to_summary(entry))

    groups = [
        SemanticTypeGroup(
            semantic_type=st,
            display_name=registry.display_name(st),
            nodes=nodes,
        )
        for st, nodes in sorted(groups_map.items())
    ]

    return SemanticTypesResponse(total=len(groups), groups=groups)


@router.get("/shared-params", summary="返回共享参数表（functionals / basis_sets / dispersions）")
def get_shared_params(software: Optional[str] = None) -> dict:
    """返回共享参数表。

    - 无 software 参数：返回完整表（供 Reference 页面显示）。
    - 带 software 参数：返回按软件过滤后的选项（供 Inspector 下拉渲染），
      包含 category 元数据（kind / display_name / description / allow_other）。
    """
    from nodes.schemas.shared_params import load_shared_params

    shared = load_shared_params()

    if software:
        result = {}
        for cat_name, cat_meta in shared.categories.items():
            entries = []
            table = getattr(shared, cat_name, {})
            for name, entry in table.items():
                native = entry.for_software(software)
                if native is not None:
                    entries.append({
                        "canonical": name,
                        "display_name": entry.display_name,
                        "native": native,
                    })
            allowed_values = [e["canonical"] for e in entries]
            result[cat_name] = {
                "kind": cat_meta.kind,
                "display_name": cat_meta.display_name,
                "description": cat_meta.description,
                "allow_other": cat_meta.allow_other,
                "allowed_values": allowed_values,
                "entries": entries,
            }
        return result

    return shared.model_dump(mode="json")


@router.get("/units", summary="返回 KNOWN_UNITS 物理单位注册表")
def get_units() -> dict:
    """返回所有已注册的物理单位，按量纲分组。

    供前端 Units Reference 面板显示，帮助用户理解 PQ 连接规则。
    连接校验逻辑：同 dimension + 同 shape → 合法（不同 unit 自动转换）。
    """
    from nodes.schemas.units import KNOWN_UNITS

    # 按 dimension 分组
    by_dimension: dict[str, list[dict]] = {}
    for symbol, unit in sorted(KNOWN_UNITS.items()):
        dim = unit.dimension
        if dim not in by_dimension:
            by_dimension[dim] = []
        by_dimension[dim].append({
            "symbol": symbol,
            "dimension": dim,
            "to_si_factor": unit.to_si_factor,
        })

    return {
        "total_units": len(KNOWN_UNITS),
        "total_dimensions": len(by_dimension),
        "dimensions": by_dimension,
    }


# ─── Node Preferences (global) ────────────────────────────────────────────────

class NodePreferenceEntry(BaseModel):
    collapsed_params: list[str] = []
    hidden_params: list[str] = []


class NodePreferencesResponse(BaseModel):
    version: str = "1.0"
    show_deprecated: bool = False
    node_preferences: dict[str, NodePreferenceEntry] = {}


class NodePreferencesUpdate(BaseModel):
    show_deprecated: bool = False
    node_preferences: dict[str, NodePreferenceEntry] = {}


def _prefs_path(paths: UserPaths = Depends(get_user_paths)) -> Path:
    return paths.preferences_file if paths else get_settings().userdata_root / "node_preferences.yaml"


@router.get("/preferences", response_model=NodePreferencesResponse, summary="读取用户节点偏好设置")
def get_node_preferences(
    user: CurrentUser | None = Depends(get_current_user),
    path: Path = Depends(_prefs_path),
) -> NodePreferencesResponse:
    if not path.exists():
        return NodePreferencesResponse()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return NodePreferencesResponse(
        version=data.get("version", "1.0"),
        show_deprecated=data.get("show_deprecated", False),
        node_preferences={
            k: NodePreferenceEntry(**v) for k, v in data.get("node_preferences", {}).items()
        },
    )


@router.put("/preferences", response_model=NodePreferencesResponse, summary="写入用户节点偏好设置")
def put_node_preferences(
    body: NodePreferencesUpdate,
    user: CurrentUser | None = Depends(get_current_user),
    path: Path = Depends(_prefs_path),
) -> NodePreferencesResponse:
    data = {
        "version": "1.0",
        "show_deprecated": body.show_deprecated,
        "node_preferences": {
            k: v.model_dump() for k, v in body.node_preferences.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return NodePreferencesResponse(
        version="1.0",
        show_deprecated=body.show_deprecated,
        node_preferences=body.node_preferences,
    )


# ── Node files (用户节点文件浏览与编辑) ─────────────────────────────────


def _safe_node_path(filename: str) -> str:
    """校验节点文件路径安全性（允许子目录，拒绝路径遍历）。"""
    if not filename or filename.startswith("/") or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件路径")
    return filename


def _get_userdata_nodes_dir(paths: UserPaths) -> Path:
    d = paths.nodes_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


class NodeFilesReadRequest(BaseModel):
    path: str


class NodeFilesWriteRequest(BaseModel):
    path: str
    content: str


@router.get("/files", response_model=DirectoryListResponse, summary="列出用户节点文件")
def list_node_files(
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
) -> DirectoryListResponse:
    d = _get_userdata_nodes_dir(paths)
    entries = _scan_directory(d, d)
    return DirectoryListResponse(entries=entries)


@router.get("/files/read", summary="读取用户节点文件内容")
def read_node_file(
    path: str = Query(..., description="相对于用户节点目录的文件路径"),
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
) -> PlainTextResponse:
    safe_path = _safe_node_path(path)
    d = _get_userdata_nodes_dir(paths)
    file_path = d / safe_path
    if not file_path.is_file():
        raise HTTPException(404, detail=f"文件 '{safe_path}' 不存在")
    try:
        file_path.resolve().relative_to(d.resolve())
    except ValueError:
        raise HTTPException(403, detail="禁止访问用户节点目录外的文件")
    content = file_path.read_text()
    return PlainTextResponse(content)


@router.put("/files/write", summary="写入用户节点文件")
def write_node_file(
    req: NodeFilesWriteRequest,
    user: CurrentUser = Depends(require_user),
    paths: UserPaths = Depends(get_user_paths),
) -> dict:
    safe_path = _safe_node_path(req.path)
    d = _get_userdata_nodes_dir(paths)
    file_path = d / safe_path
    try:
        file_path.resolve().relative_to(d.resolve())
    except ValueError:
        raise HTTPException(403, detail="禁止访问用户节点目录外的文件")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(req.content)
    return {"written": safe_path}


@router.get("/{name}", response_model=NodeDetailResponse, summary="节点详情")
def get_node(
    name: str,
    svc: NodeIndexService = Depends(get_node_service),
) -> NodeDetailResponse:
    entry = svc.get_by_name(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Node '{name}' not found")

    summary = _entry_to_summary(entry)

    # On-Board 参数完整定义直接从索引读取，无需二次解析 nodespec.yaml
    onboard_inputs = [
        OnBoardParamResponse(
            name=p.name,
            display_name=p.display_name,
            kind=p.kind,
            default=p.default,
            description=p.description,
            allowed_values=p.allowed_values,
            min_value=p.min_value,
            max_value=p.max_value,
            unit=p.unit,
            multiple_input=p.multiple_input,
            resource_param=p.resource_param,
            allow_other=p.allow_other,
        )
        for p in entry.onboard_inputs
    ]
    onboard_outputs = [
        OnBoardOutputResponse(
            name=o.name,
            display_name=o.display_name,
            kind=o.kind,
            unit=o.unit,
            description=o.description,
            quality_gate=o.quality_gate,
            gate_default=o.gate_default,
            gate_description=o.gate_description,
        )
        for o in entry.onboard_outputs
    ]

    return NodeDetailResponse(
        **summary.model_dump(),
        onboard_inputs=onboard_inputs,
        onboard_outputs=onboard_outputs,
    )
