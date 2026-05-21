"""agents/node_generator/knowledge.py — 参考节点加载 + 镜像注册表感知。

为 Node Generator 提供：
- 同软件/类别的参考节点（few-shot 示例）
- 可用 Docker 镜像列表
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_available_images(project_root: Path | None = None) -> list[dict[str, Any]]:
    """从 base_images/registry.yaml 加载可用镜像列表。"""
    if project_root is None:
        from api.config import get_settings
        project_root = get_settings().project_root

    registry_path = project_root / "nodes" / "base_images" / "registry.yaml"
    if not registry_path.exists():
        return []

    with registry_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    images_raw = data.get("images", [])
    images = []

    # 支持两种格式：列表（每项含 name 字段）或字典
    if isinstance(images_raw, list):
        for img_data in images_raw:
            images.append({
                "name": img_data.get("name", ""),
                "description": img_data.get("description", ""),
                "source_type": img_data.get("source_type", ""),
                "base": img_data.get("image", ""),
            })
    elif isinstance(images_raw, dict):
        for img_ref, img_data in images_raw.items():
            images.append({
                "name": img_ref,
                "description": img_data.get("description", ""),
                "source_type": img_data.get("source_type", ""),
                "base": img_data.get("base", ""),
            })

    # 过滤掉内部/测试用镜像
    _EXCLUDE_IMAGES = {"ephemeral-py"}
    images = [img for img in images if img.get("name", "") not in _EXCLUDE_IMAGES]

    return images


def load_reference_nodes(
    target_software: str | None = None,
    semantic_type: str | None = None,
    project_root: Path | None = None,
    max_refs: int = 2,
) -> list[dict[str, Any]]:
    """加载同软件/语义类型的参考节点作为 few-shot 示例。

    Parameters
    ----------
    target_software: 目标软件（如 "ORCA"）
    semantic_type:   语义类型（如 "geometry-optimization"）
    project_root:    项目根目录
    max_refs:        最多返回几个参考节点

    Returns
    -------
    list[dict]: 参考节点字典列表，包含 name, nodespec_yaml, run_sh
    """
    if project_root is None:
        from api.config import get_settings
        project_root = get_settings().project_root

    try:
        from node_index.scanner import load_index
        index = load_index(project_root)
    except Exception:
        return []

    # 三级 fallback 筛选：
    # 1. 同软件 + 同语义类型 → 最佳参考
    # 2. 不同软件 + 同语义类型 → 跨软件 fallback
    # 3. 同软件 + 不同语义类型 → 补充参考
    # 4. 不同软件 + 不同语义类型 → 兜底
    same_software = []
    other_software = []
    for entry in index.entries:
        if target_software and (entry.software or "").lower() == target_software.lower():
            same_software.append(entry)
        else:
            other_software.append(entry)

    candidates = []
    if semantic_type:
        # 1) 同软件 + 同语义
        candidates.extend(
            e for e in same_software if e.semantic_type == semantic_type
        )
        # 2) 不同软件 + 同语义（跨软件 fallback）
        candidates.extend(
            e for e in other_software if e.semantic_type == semantic_type
        )
        # 3) 同软件 + 不同语义
        candidates.extend(
            e for e in same_software if e.semantic_type != semantic_type
        )
        # 4) 不同软件 + 不同语义
        candidates.extend(
            e for e in other_software if e.semantic_type != semantic_type
        )
    else:
        candidates = same_software + other_software

    # 过滤 test 节点和内部节点
    candidates = [
        e for e in candidates
        if "nodes/test/" not in (e.nodespec_path or "")
    ]

    references = []
    for entry in candidates[:max_refs]:
        node_data: dict[str, Any] = {"name": entry.name}

        # 读取 nodespec.yaml
        spec_path = project_root / entry.nodespec_path
        if spec_path.exists():
            node_data["nodespec_yaml"] = spec_path.read_text(encoding="utf-8")

        # 读取 run.sh
        run_sh_path = spec_path.parent / "profile" / "run.sh"
        if run_sh_path.exists():
            node_data["run_sh"] = run_sh_path.read_text(encoding="utf-8")

        references.append(node_data)

    return references
