"""agents/node_generator/ephemeral/sandbox.py — 临时节点 Docker 沙箱执行环境。

使用 Docker 容器（ephemeral-py 镜像）为临时节点 Agent 提供安全的脚本执行环境：
- pip install 隔离（不污染宿主机）
- 文件系统隔离（容器内独立 /mf/ 路径）
- 沙箱工作目录使用 userdata/sandbox_runs/<run_id>/ 持久化
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from agents.node_generator.shared.sandbox_base import (
    create_sandbox_dir,
    _scan_output_files,
    _ensure_docker,
    save_pip_history,
)


# ═══════════════════════════════════════════════════════════════════════════
# Docker 执行（临时节点专用）
# ═══════════════════════════════════════════════════════════════════════════

_EPHEMERAL_IMAGE = "ephemeral-py:3.11"


def _execute_in_docker(
    script: str,
    input_data: dict[str, str] | None,
    env_overrides: dict[str, str] | None,
    timeout: int,
    sandbox_dir: Path | None = None,
) -> dict[str, Any]:
    """在 Docker 容器内执行脚本。"""
    if sandbox_dir is None:
        raise ValueError("sandbox_dir is required — caller must provide a user-scoped sandbox directory")

    input_dir = sandbox_dir / "input"
    output_dir = sandbox_dir / "output"
    workspace_dir = sandbox_dir / "workspace"

    # 写入输入数据
    if input_data:
        for port_name, content in input_data.items():
            port_file = input_dir / port_name
            port_file.write_text(content, encoding="utf-8")

    # 写入脚本
    script_path = sandbox_dir / "_script.py"
    script_path.write_text(script, encoding="utf-8")

    # 环境变量
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{sandbox_dir}:/sandbox",
        "-v", f"{input_dir}:/mf/input",
        "-v", f"{output_dir}:/mf/output",
        "-v", f"{workspace_dir}:/mf/workspace",
        "-e", "MF_INPUT_DIR=/mf/input",
        "-e", "MF_OUTPUT_DIR=/mf/output",
        "-e", "MF_WORKSPACE_DIR=/mf/workspace",
    ]
    # 传递额外环境变量
    for k, v in (env_overrides or {}).items():
        cmd.extend(["-e", f"{k}={v}"])

    cmd.extend([_EPHEMERAL_IMAGE, "python", "/sandbox/_script.py"])

    timed_out = False
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(sandbox_dir),
            env=env,
        )
        stdout = result.stdout
        stderr = result.stderr
        return_code = result.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = (
            e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        ) + "\n[TIMEOUT]"
        return_code = -1
        timed_out = True

    # 检测生成的文件
    generated_files, image_files = _scan_output_files(output_dir, workspace_dir)

    return {
        "stdout": stdout,
        "stderr": stderr,
        "return_code": return_code,
        "timed_out": timed_out,
        "generated_files": generated_files,
        "image_files": image_files,
        "sandbox_dir": str(sandbox_dir),
    }


def _docker_pip_install(package: str) -> dict[str, Any]:
    """在 Docker 容器内执行 pip install。"""
    cmd = [
        "docker", "run", "--rm",
        _EPHEMERAL_IMAGE,
        "pip", "install", "--no-cache-dir", package,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "return_code": result.returncode,
            "output": (result.stdout + result.stderr)[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"return_code": -1, "output": "pip install timed out"}
    except Exception as e:
        return {"return_code": -1, "output": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════════════════

def execute_script_sandbox(
    script: str,
    input_data: dict[str, str] | None = None,
    env_overrides: dict[str, str] | None = None,
    timeout: int = 120,
    sandbox_dir: Path | None = None,
) -> dict[str, Any]:
    """在 Docker 沙箱中执行 Python 脚本。

    Parameters
    ----------
    script:
        要执行的 Python 脚本内容。
    input_data:
        真实的输入数据 {port_name: file_content}。
    env_overrides:
        额外的环境变量。
    timeout:
        执行超时（秒）。
    sandbox_dir:
        沙箱工作目录。None 时自动创建（调用方需在不再需要时清理）。

    Returns
    -------
    dict:
        stdout, stderr, return_code, timed_out, generated_files, image_files, sandbox_dir
    """
    _ensure_docker()
    return _execute_in_docker(script, input_data, env_overrides, timeout, sandbox_dir)


def _run_pip_install(package: str) -> dict[str, Any]:
    """pip install（在 Docker 容器内执行）。"""
    _ensure_docker()
    return _docker_pip_install(package)


# ═══════════════════════════════════════════════════════════════════════════
# LangChain Tool 工厂
# ═══════════════════════════════════════════════════════════════════════════

def make_sandbox_tool(
    input_data: dict[str, str],
    env_overrides: dict[str, str] | None = None,
    sandbox_dir: Path | None = None,
):
    """创建绑定到特定 input_data 的 sandbox_execute Tool。

    Parameters
    ----------
    input_data:
        真实输入数据 {port_name: content}。
    env_overrides:
        额外环境变量。
    sandbox_dir:
        共享的沙箱目录（持久化，不会在每次调用后清理）。
    """
    from langchain_core.tools import tool

    _input_data = input_data
    _env_overrides = env_overrides or {}
    _sandbox_dir = sandbox_dir

    @tool
    def sandbox_execute(script: str) -> dict:
        """Execute a Python script in the sandbox.

        The script has access to /mf/input/I1, /mf/input/I2, ... for reading inputs
        and should write outputs to /mf/output/O1, /mf/output/O2, ...
        Images should be saved to the workspace directory.

        Returns dict with keys: stdout, stderr, return_code, image_files, image_paths.
        """
        result = execute_script_sandbox(
            script=script,
            input_data=_input_data,
            env_overrides=_env_overrides,
            timeout=60,
            sandbox_dir=_sandbox_dir,
        )
        return {
            "stdout": result["stdout"][:3000],
            "stderr": result["stderr"][:2000],
            "return_code": result["return_code"],
            "image_files": [os.path.basename(f) for f in result["image_files"]],
            "image_paths": result["image_files"],  # 完整路径，供 evaluator 读取
        }

    return sandbox_execute


def make_pip_install_tool():
    """创建 pip_install Tool 和安装历史记录器。

    Returns
    -------
    tuple:
        (pip_install_tool, install_history)
        install_history 是一个 list，在 LLM 调用 pip_install 时自动追加记录。
    """
    from langchain_core.tools import tool

    install_history: list[dict] = []

    @tool
    def pip_install(package: str) -> str:
        """Install a Python package via pip.

        Use this when your script needs a library NOT in the pre-installed list:
        numpy, matplotlib, scipy, pandas, pyyaml, jinja2, requests.
        For faster installs in China, packages are installed from PyPI directly.
        """
        result = _run_pip_install(package)
        install_history.append({
            "package": package,
            "return_code": result["return_code"],
            "output": result["output"][:500],
        })
        return result["output"][:500]

    return pip_install, install_history
