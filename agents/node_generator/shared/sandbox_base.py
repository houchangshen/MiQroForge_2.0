"""agents/node_generator/shared/sandbox_base.py — 共享沙箱工具。

提供 create_sandbox_dir / cleanup_sandbox_dir / _scan_output_files / save_pip_history
等在 prefab 和 ephemeral 模式中都会用到的基础设施。
"""

from __future__ import annotations

import glob as _glob
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 支持的图片扩展名
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".gif", ".webp"}


def _ensure_docker() -> None:
    """确认 Docker 可用，不可用时抛异常。"""
    if not _docker_available():
        raise RuntimeError(
            "Docker is required for sandbox but not available. "
            "Install Docker and ensure the daemon is running."
        )


def _docker_available() -> bool:
    """检查 Docker daemon 是否可用。"""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_sandbox_base_dir(
    project_id: str,
    run_name: str,
    projects_dir: str | Path,
) -> Path:
    """获取沙箱基础目录。

    必须在正确的用户项目目录下创建，不接受回退到旧路径。

    Args:
        project_id: 项目 ID（必填）。
        run_name: 运行名称（必填）。
        projects_dir: 用户项目根目录（必填）。

    Raises:
        ValueError: 任一参数缺失。
    """
    if not project_id or not run_name:
        raise ValueError("sandbox requires both project_id and run_name")
    if not projects_dir:
        raise ValueError("sandbox requires projects_dir (user-scoped projects root)")
    base = Path(projects_dir) / project_id / "runs" / run_name
    base.mkdir(parents=True, exist_ok=True)
    return base


def create_sandbox_dir(
    project_id: str | None = None,
    run_name: str | None = None,
    projects_dir: str | Path | None = None,
) -> Path:
    """创建一个持久化的沙箱工作目录。调用方负责在不再需要时清理。

    Args:
        project_id: 项目 ID（必填）。
        run_name: 运行名称（必填）。
        projects_dir: 用户项目根目录（必填）。

    Returns:
        沙箱目录路径（含 input/、output/、workspace/ 子目录），
        位于 projects/<id>/runs/<name>/sandbox_<timestamp>/。

    Raises:
        ValueError: 任一参数缺失。
    """
    if not project_id or not run_name:
        raise ValueError("sandbox requires both project_id and run_name")
    if not projects_dir:
        raise ValueError("sandbox requires projects_dir (user-scoped projects root)")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    sandbox_dir = _get_sandbox_base_dir(project_id, run_name, projects_dir) / f"sandbox_{run_id}"
    (sandbox_dir / "input").mkdir(parents=True)
    (sandbox_dir / "output").mkdir(parents=True)
    (sandbox_dir / "workspace").mkdir(parents=True)
    return sandbox_dir


def cleanup_sandbox_dir(sandbox_dir: Path) -> None:
    """清理沙箱工作目录。

    安全检查：仅删除包含 'sandbox_' 的目录，防止误删。
    """
    try:
        dir_name = str(sandbox_dir.name) if hasattr(sandbox_dir, 'name') else ""
        if sandbox_dir.exists() and "sandbox_" in dir_name:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
    except Exception:
        pass


def _scan_output_files(output_dir: Path, workspace_dir: Path) -> tuple[list[str], list[str]]:
    """扫描输出目录，返回 (generated_files, image_files)。"""
    generated_files: list[str] = []
    image_files: list[str] = []
    for dirpath in (output_dir, workspace_dir):
        for fpath in sorted(_glob.glob(str(dirpath / "**" / "*"), recursive=True)):
            if os.path.isfile(fpath):
                generated_files.append(fpath)
                ext = os.path.splitext(fpath)[1].lower()
                if ext in _IMAGE_EXTENSIONS:
                    image_files.append(fpath)
    return generated_files, image_files


def save_pip_history(
    pip_history: list[dict],
    description: str,
    userdata_root: Path | None = None,
) -> None:
    """将 pip 安装历史持久化到 userdata/pip_history.jsonl。"""
    if not pip_history:
        return

    if userdata_root is None:
        root = Path(__file__).parent.parent.parent.parent
        userdata_root = root / "userdata"

    history_path = userdata_root / "pip_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().isoformat()
    desc_short = description[:100]

    with open(history_path, "a", encoding="utf-8") as f:
        for entry in pip_history:
            record = {
                "timestamp": timestamp,
                "description": desc_short,
                **entry,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
