"""agents/node_generator/prefab/tools.py — Prefab 模式工具系统。

LangChain @tool 分为 5 组：
  手册导航（5）：list_manual_chapters / get_chapter_outline / search_manual / get_section / find_command_docs
  节点参考（3）：search_reference_nodes / get_node_detail / get_run_sh
  Schema 参考（2）：query_resource_defaults / query_shared_params
  文件系统（3）：list_node_files / read_node_file / write_file
  沙箱 + 环境（4）：test_in_sandbox / check_sandbox / kill_sandbox / pip_install

所有工具通过 make_*_tool() 工厂函数创建，闭包绑定当前上下文。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


# ═══════════════════════════════════════════════════════════════════════════
# 手册导航工具（5 个）
# ═══════════════════════════════════════════════════════════════════════════

def make_manual_tools(default_software: str, available_manuals: list[str]):
    """创建手册导航相关的 5 个工具。每个工具接受 software 参数，Agent 可自由选择查哪个软件的手册。

    参数:
        default_software: 默认软件名（inspector 中的 SOFTWARE_HINT），无手册时可为空。
        available_manuals: 有手册可用的软件列表，如 ['gaussian']。
    """

    _default = default_software
    _available = available_manuals
    _available_str = ", ".join(_available) if _available else "(none available)"

    def _get_index(software: str):
        from agents.node_generator.shared.manual_index import get_manual_index
        sw = (software or _default or "").lower()
        if not sw:
            return None, f"No software specified and no default set. Available manuals: {_available_str}"
        idx = get_manual_index(sw)
        if idx is None:
            return None, f"No manual available for '{sw}'. Available manuals: {_available_str}"
        return idx, None

    @tool
    def list_manual_chapters(software: str = "") -> str:
        """List all available software manual chapters with their sizes and summaries.
        Use this first to see what documentation is available before diving into specifics.

        Args:
            software: Software name (e.g. 'gaussian', 'orca'). Leave empty to use default.
        """
        idx, err = _get_index(software)
        if err:
            return json.dumps({"error": err, "available_manuals": _available})
        chapters = idx.list_chapters()
        if not chapters:
            return "No manual chapters found."
        return json.dumps(chapters, ensure_ascii=False, indent=2)

    @tool
    def get_chapter_outline(chapter: str, software: str = "") -> str:
        """Get the section outline of a specific manual chapter.
        Shows section IDs, titles, and page numbers. Use this to navigate within a chapter.

        Args:
            chapter: Chapter filename (e.g. 'gaussian_freq.md'). Use list_manual_chapters() to see available chapters.
            software: Software name (e.g. 'gaussian'). Leave empty to use default.
        """
        idx, err = _get_index(software)
        if err:
            return json.dumps({"error": err})
        outline = idx.get_chapter_outline(chapter)
        if not outline:
            return f"No sections found in chapter '{chapter}'."
        return json.dumps(outline, ensure_ascii=False, indent=2)

    @tool
    def search_manual(query: str, software: str = "") -> str:
        """Search the software manual for relevant content using keyword search.
        Returns matching sections with context snippets. Best for finding specific parameters or commands.

        Args:
            query: Search query (e.g. 'frequency calculation', 'Opt keyword', 'scf convergence').
            software: Software name (e.g. 'gaussian'). Leave empty to use default.
        """
        idx, err = _get_index(software)
        if err:
            return json.dumps({"error": err})
        results = idx.search(query, top_k=8)
        if not results:
            return f"No results found for '{query}'."
        for r in results:
            if len(r.get("snippet", "")) > 250:
                r["snippet"] = r["snippet"][:250] + "..."
        return json.dumps(results, ensure_ascii=False, indent=2)

    @tool
    def get_section(chapter: str, section_id: str, software: str = "") -> str:
        """Get the full content of a specific section in a manual chapter.
        Use after get_chapter_outline() to read detailed documentation.

        Args:
            chapter: Chapter filename (e.g. 'gaussian_freq.md').
            section_id: Section ID from get_chapter_outline() (e.g. 'page-734' or '7.26').
            software: Software name (e.g. 'gaussian'). Leave empty to use default.
        """
        idx, err = _get_index(software)
        if err:
            return json.dumps({"error": err})
        result = idx.get_section(chapter, section_id)
        if "error" in result:
            return result["error"]
        content = result.get("content", "")
        if len(content) > 50000:
            content = content[:50000] + "\n\n[... truncated at 50KB ...]"
        return content

    @tool
    def find_command_docs(keyword: str, software: str = "") -> str:
        """Find documentation for a specific command, keyword, or parameter across all manual chapters.
        Use this when you know the exact keyword (e.g. 'Opt', 'Freq', '%freq', 'B3LYP').

        Args:
            keyword: The command or parameter to search for.
            software: Software name (e.g. 'gaussian'). Leave empty to use default.
        """
        idx, err = _get_index(software)
        if err:
            return json.dumps({"error": err})
        results = idx.find_command_docs(keyword, top_k=8)
        if not results:
            return f"No documentation found for '{keyword}'."
        # 压缩 context
        for r in results:
            ctx = r.get("context", "")
            if len(ctx) > 250:
                r["context"] = "...".join([ctx[:120], ctx[-120:]])
        return json.dumps(results, ensure_ascii=False, indent=2)

    return [list_manual_chapters, get_chapter_outline, search_manual, get_section, find_command_docs]


# ═══════════════════════════════════════════════════════════════════════════
# 节点参考工具（3 个）
# ═══════════════════════════════════════════════════════════════════════════

def _find_node_dir(node_name: str) -> Path | None:
    """查找节点目录路径。搜索 node_index.yaml 和 userdata/nodes/。

    Returns:
        Path to the node directory, or None if not found.
    """
    try:
        from node_index.scanner import load_index
        from api.config import get_settings
        settings = get_settings()

        # 1. 搜索 node_index.yaml
        index = load_index(settings.project_root)
        for e in index.entries:
            if e.name == node_name:
                node_dir = settings.project_root / Path(e.nodespec_path).parent
                if node_dir.exists():
                    return node_dir

        # 2. fallback: userdata/nodes
        for p in (settings.userdata_root / "nodes").rglob(f"{node_name}/nodespec.yaml"):
            return p.parent

        return None
    except Exception:
        return None


def make_node_reference_tools(target_software: str = ""):
    """创建节点参考相关的 3 个工具。target_software 用于过滤/排序搜索结果。"""

    _target_software = target_software.lower()

    @tool
    def search_reference_nodes(query: str) -> str:
        """Search existing nodes for reference. Returns concise node summaries (name, description).
        Use list_reference_node_files / read_reference_node_file to explore interesting nodes in detail.

        Args:
            query: Search query (e.g. 'geometry optimization', 'frequency calculation').
        """
        try:
            from vectorstore.retriever import get_retriever
            retriever = get_retriever()
            results = retriever.search_summary(query, n=8)
            if not results:
                return "No matching nodes found."
            # 过滤掉 test 节点
            results = [r for r in results if "nodes/test/" not in r.get("nodespec_path", "")]
            # 按软件相关性排序：目标软件匹配的在前
            if _target_software:
                def _score(r: dict) -> int:
                    sw = (r.get("software") or "").lower()
                    if _target_software == sw:
                        return 0  # 精确匹配优先
                    if _target_software in sw or sw in _target_software:
                        return 1
                    return 2
                results.sort(key=_score)
            # 裁剪输出：只保留名称和描述
            trimmed = []
            for r in results:
                entry: dict = {
                    "name": r.get("name", ""),
                    "description": (r.get("description", "") or "")[:200],
                }
                sw = r.get("software")
                if sw:
                    entry["software"] = sw
                st = r.get("semantic_type")
                if st:
                    entry["semantic_type"] = st
                trimmed.append(entry)
            return json.dumps(trimmed, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Search error: {e}"

    @tool
    def list_reference_node_files(node_name: str, subdir: str = "") -> str:
        """List files in a reference node's directory, two levels deep.
        Shows root files + contents of all subdirectories inline. Use after
        search_reference_nodes to see the full structure of a reference node.

        Args:
            node_name: Node name (e.g. 'orca-geo-opt', 'gaussian-freq').
            subdir: Optional subdirectory (e.g. '', 'profile' for profile dir).
        """
        node_dir = _find_node_dir(node_name)
        if not node_dir:
            return json.dumps({"error": f"Node '{node_name}' not found. Use search_reference_nodes to find available nodes."})

        target = (node_dir / subdir) if subdir else node_dir
        if not target.exists():
            return json.dumps({"error": f"Directory not found in '{node_name}': {subdir or '.'}"})

        def _scandir(d: Path, prefix: str = "") -> list[dict]:
            entries = []
            for entry in sorted(d.iterdir()):
                is_dir = entry.is_dir()
                name = f"{prefix}{entry.name}"
                if is_dir:
                    name += "/"
                entries.append({
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else entry.stat().st_size,
                })
                if is_dir:
                    for child in sorted(entry.iterdir()):
                        child_is_dir = child.is_dir()
                        child_name = f"  {child.name}"
                        if child_is_dir:
                            child_name += "/"
                        entries.append({
                            "name": child_name,
                            "type": "dir" if child_is_dir else "file",
                            "size": 0 if child_is_dir else child.stat().st_size,
                        })
            return entries

        result = _scandir(target)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool
    def read_reference_node_file(node_name: str, filepath: str, start_line: int = 1, end_line: int = 0) -> str:
        """Read a file from a reference node's directory. Like 'cat' on a reference node.
        Use after list_reference_node_files to read specific files.
        Use start_line and end_line to read specific line ranges.

        Args:
            node_name: Node name (e.g. 'orca-geo-opt', 'gaussian-freq').
            filepath: Path relative to the node directory (e.g. 'nodespec.yaml', 'profile/run.sh').
            start_line: First line to read (1-indexed, default 1).
            end_line: Last line to read (0 = read to end, default 0).
        """
        node_dir = _find_node_dir(node_name)
        if not node_dir:
            return json.dumps({"error": f"Node '{node_name}' not found."})

        target = node_dir / filepath
        # Safety: prevent path traversal
        try:
            target.resolve().relative_to(node_dir.resolve())
        except ValueError:
            return json.dumps({"error": f"Path traversal denied: {filepath}"})

        if not target.exists():
            return json.dumps({"error": f"File not found in '{node_name}': {filepath}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {filepath}"})

        try:
            content = target.read_text("utf-8")
            lines = content.splitlines()
            total_lines = len(lines)

            start = max(1, start_line) - 1
            end = total_lines if end_line <= 0 else min(end_line, total_lines)
            if start >= total_lines:
                return json.dumps({"error": f"start_line {start_line} exceeds file length ({total_lines} lines)"})

            selected = lines[start:end]
            result = "\n".join(selected)
            if len(result) > 20000:
                result = result[:20000] + "\n\n[... truncated at 20KB ...]"
            header = f"[{node_name}/{filepath} lines {start+1}-{min(end, total_lines)} of {total_lines}]\n"
            return header + result
        except Exception as e:
            return json.dumps({"error": f"Read error: {e}"})

    return [search_reference_nodes, list_reference_node_files, read_reference_node_file]


# ═══════════════════════════════════════════════════════════════════════════
# Schema 参考工具（2 个）
# ═══════════════════════════════════════════════════════════════════════════

def make_schema_tools():
    """创建 Schema 参考相关的 2 个工具。"""

    @tool
    def query_resource_defaults() -> str:
        """Get the resource defaults configuration (resource_defaults.yaml).
        This defines how resource fields (cpu_cores, mem_gb, etc.) map to OnBoardInput parameters.
        Use this to understand what resource parameters to declare in nodespec.yaml."""
        try:
            from pathlib import Path
            path = Path(__file__).parent.parent.parent.parent / "nodes" / "schemas" / "resource_defaults.yaml"
            if not path.exists():
                return "resource_defaults.yaml not found."
            content = path.read_text("utf-8")
            return content
        except Exception as e:
            return f"Error: {e}"

    @tool
    def query_shared_params(software: str) -> str:
        """Get the shared parameter table for a specific software.
        This shows how canonical parameter names (like B3LYP, def2-SVP) map to software-native keywords.
        Use this to correctly set functional, basis_set, and dispersion parameters.

        Args:
            software: Software name (e.g. 'orca', 'gaussian', 'psi4', 'cp2k').
        """
        try:
            import yaml
            from pathlib import Path
            path = Path(__file__).parent.parent.parent.parent / "nodes" / "schemas" / "shared_params.yaml"
            if not path.exists():
                return "shared_params.yaml not found."
            data = yaml.safe_load(path.read_text("utf-8"))

            software_lower = software.lower()
            result = {}

            for category in ["functionals", "basis_sets", "dispersions"]:
                cat_data = data.get(category, {})
                software_params = {}
                for name, mapping in cat_data.items():
                    if isinstance(mapping, dict) and software_lower in mapping:
                        native = mapping[software_lower]
                        if native is not None:
                            software_params[name] = native
                if software_params:
                    result[category] = software_params

            if not result:
                # Dynamically list available software from shared_params.yaml
                # Exclude metadata keys like 'display_name', 'kind', 'allow_other', 'description'
                _META_KEYS = {'display_name', 'description', 'kind', 'allow_other'}
                available = set()
                for cat_data in [data.get("functionals", {}), data.get("basis_sets", {}), data.get("dispersions", {})]:
                    for mapping in cat_data.values():
                        if isinstance(mapping, dict):
                            available.update(k for k, v in mapping.items()
                                           if v is not None and k not in _META_KEYS)
                avail_list = ", ".join(sorted(available)) if available else "none"
                return f"No shared params found for '{software}'. Available software with shared params: {avail_list}"

            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error: {e}"

    return [query_resource_defaults, query_shared_params]


# ═══════════════════════════════════════════════════════════════════════════
# 文件系统工具（3 个）
# ═══════════════════════════════════════════════════════════════════════════

def make_filesystem_tools(sandbox_dir: Path | None = None):
    """创建文件系统相关的 3 个工具。闭包绑定 sandbox_dir。"""

    _sandbox_dir = sandbox_dir

    @tool
    def list_node_files(subdir: str = "") -> str:
        """List files in the sandbox working directory, two levels deep.
        Shows root files and the contents of each subdirectory inline (like 'ls -R' with depth 2).
        Use this to see the full layout of your node files in one call.

        Args:
            subdir: Optional subdirectory to start from (e.g. '', 'profile/').
        """
        if not _sandbox_dir:
            return json.dumps({"error": "No sandbox directory configured"})

        target = (_sandbox_dir / subdir) if subdir else _sandbox_dir
        if not target.exists():
            return json.dumps({"error": f"Directory not found: {subdir or '.'}"})

        def _scandir(d: Path, prefix: str = "") -> list[dict]:
            entries = []
            for entry in sorted(d.iterdir()):
                is_dir = entry.is_dir()
                name = f"{prefix}{entry.name}"
                if is_dir:
                    name += "/"
                entries.append({
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else entry.stat().st_size,
                })
                # 递归一层：显示子目录内容（内联在 name 中）
                if is_dir:
                    for child in sorted(entry.iterdir()):
                        child_is_dir = child.is_dir()
                        child_name = f"  {child.name}"
                        if child_is_dir:
                            child_name += "/"
                        entries.append({
                            "name": child_name,
                            "type": "dir" if child_is_dir else "file",
                            "size": 0 if child_is_dir else child.stat().st_size,
                        })
            return entries

        result = _scandir(target)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool
    def read_node_file(filepath: str, start_line: int = 1, end_line: int = 0) -> str:
        """Read a file from the sandbox working directory. Like 'cat' on the sandbox.
        Use this to review files you've written before making changes.
        Use start_line and end_line to read specific line ranges (especially useful for long files).

        Args:
            filepath: Path relative to sandbox dir (e.g. 'nodespec.yaml', 'profile/run.sh').
            start_line: First line to read (1-indexed, default 1).
            end_line: Last line to read (0 = read to end, default 0).
        """
        if not _sandbox_dir:
            return json.dumps({"error": "No sandbox directory configured"})

        target = _sandbox_dir / filepath
        # Safety: prevent path traversal
        try:
            target.resolve().relative_to(_sandbox_dir.resolve())
        except ValueError:
            return json.dumps({"error": f"Path traversal denied: {filepath}"})

        if not target.exists():
            return json.dumps({"error": f"File not found: {filepath}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {filepath}"})

        try:
            content = target.read_text("utf-8")
            lines = content.splitlines()
            total_lines = len(lines)

            # 应用行数范围
            start = max(1, start_line) - 1  # 转为 0-indexed
            end = total_lines if end_line <= 0 else min(end_line, total_lines)
            if start >= total_lines:
                return json.dumps({"error": f"start_line {start_line} exceeds file length ({total_lines} lines)"})

            selected = lines[start:end]
            result = "\n".join(selected)
            if len(result) > 20000:
                result = result[:20000] + "\n\n[... truncated at 20KB ...]"
            # 标注行号范围
            header = f"[Lines {start+1}-{min(end, total_lines)} of {total_lines}]\n"
            return header + result
        except Exception as e:
            return json.dumps({"error": f"Read error: {e}"})

    @tool
    def write_file(filepath: str, content: str) -> str:
        """Write a file to the sandbox working directory. Creates parent directories as needed.
        Use this for ALL output files (nodespec.yaml, profile/run.sh, templates, helper scripts, etc).

        Args:
            filepath: Path relative to sandbox dir (e.g. 'nodespec.yaml', 'profile/run.sh').
            content: File content to write.
        """
        if not _sandbox_dir:
            return json.dumps({"error": "No sandbox directory configured"})

        target = _sandbox_dir / filepath
        # Safety: prevent path traversal
        try:
            target.resolve().relative_to(_sandbox_dir.resolve())
        except ValueError:
            return json.dumps({"error": f"Path traversal denied: {filepath}"})

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            if filepath.endswith(".sh") or "run.sh" in filepath:
                target.chmod(0o755)
            size = target.stat().st_size
            return json.dumps({
                "saved": filepath,
                "size_bytes": size,
            })
        except Exception as e:
            return json.dumps({"error": f"Write error: {e}"})

    @tool
    def update_file(filepath: str, old_string: str, new_string: str) -> str:
        """Perform an exact string replacement in a file. Like sed but safer.
        Use this for targeted edits instead of rewriting the entire file with write_file.

        Args:
            filepath: Path relative to sandbox dir (e.g. 'nodespec.yaml', 'profile/run.sh').
            old_string: The exact text to replace. Must match uniquely in the file.
            new_string: The text to replace it with.
        """
        if not _sandbox_dir:
            return json.dumps({"error": "No sandbox directory configured"})

        target = _sandbox_dir / filepath
        # Safety: prevent path traversal
        try:
            target.resolve().relative_to(_sandbox_dir.resolve())
        except ValueError:
            return json.dumps({"error": f"Path traversal denied: {filepath}"})

        if not target.exists():
            return json.dumps({"error": f"File not found: {filepath}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {filepath}"})

        try:
            content = target.read_text("utf-8")
            if old_string not in content:
                return json.dumps({
                    "error": f"old_string not found in {filepath}. Use read_node_file to verify the current content.",
                })
            occurrences = content.count(old_string)
            if occurrences > 1:
                return json.dumps({
                    "error": f"old_string matches {occurrences} times in {filepath}. "
                             "Provide more surrounding context to make the match unique.",
                })
            new_content = content.replace(old_string, new_string, 1)
            target.write_text(new_content, encoding="utf-8")
            if filepath.endswith(".sh") or "run.sh" in filepath:
                target.chmod(0o755)
            return json.dumps({
                "updated": filepath,
                "replaced": True,
                "old_bytes": len(old_string),
                "new_bytes": len(new_string),
            })
        except Exception as e:
            return json.dumps({"error": f"Update error: {e}"})

    return [list_node_files, read_node_file, write_file, update_file]


# ═══════════════════════════════════════════════════════════════════════════
# Workspace 工具（2 个）
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# 端口重命名工具
# ═══════════════════════════════════════════════════════════════════════════

def make_port_tools(sandbox_dir: Path | None = None, input_ports: list[str] | None = None, output_ports: list[str] | None = None):
    """创建端口映射工具。Agent 通过它把 Argo DAG 端口名映射为 nodespec 中的语义名。

    port_map.json 格式:
      {"inputs": {"I1": "xyz_geometry"}, "outputs": {"O1": "optimized_xyz"}}

    test_in_sandbox 和 API 端点都会读取此文件做映射。

    约束：stream outputs 必须全部映射（下游 Argo DAG 等待固定端口名）；
    stream inputs 和 onboard inputs 可以自由映射或忽略。
    """
    _sandbox_dir = sandbox_dir
    _input_ports = input_ports or []
    _output_ports = output_ports or []

    _input_desc = ", ".join(_input_ports) if _input_ports else "(unknown)"
    _output_desc = ", ".join(_output_ports) if _output_ports else "(unknown)"

    @tool(description=(
        f"Map Argo DAG port names to semantic names in your nodespec.yaml. "
        f"Available Argo input ports: [{_input_desc}] (can be mapped or ignored). "
        f"Available Argo output ports: [{_output_desc}] — ALL of these MUST be mapped "
        f"to corresponding stream_outputs in your nodespec, otherwise the downstream "
        f"DAG will break. Input mapping is optional but recommended for clarity. "
        f"Call AFTER writing nodespec.yaml. "
        f"Example: port_mapping(inputs=[[<argo_port>,<semantic_name>]], outputs=[[<argo_port>,<semantic_name>]])"
    ))
    def port_mapping(inputs: list = [], outputs: list = []) -> str:
        """Map Argo DAG port names to nodespec stream_io semantic names.

        Args:
            inputs: List of [argo_port_name, semantic_name] pairs.
                    Example: [[<argo_port>, <semantic_name>]]
            outputs: List of [argo_port_name, semantic_name] pairs —
                     ALL Argo output ports must be mapped.
                     Example: [[<argo_port>, <semantic_name>]]
        """
        if not _sandbox_dir:
            return json.dumps({"error": "No sandbox directory configured"})

        port_map = {}
        port_map_path = _sandbox_dir / "port_map.json"

        # 读取已有映射（支持增量更新）
        if port_map_path.exists():
            try:
                port_map = json.loads(port_map_path.read_text("utf-8"))
            except Exception:
                port_map = {}

        if "inputs" not in port_map:
            port_map["inputs"] = {}
        if "outputs" not in port_map:
            port_map["outputs"] = {}

        for pair in (inputs or []):
            if len(pair) == 2:
                port_map["inputs"][pair[0]] = pair[1]

        for pair in (outputs or []):
            if len(pair) == 2:
                port_map["outputs"][pair[0]] = pair[1]

        # 检查：所有 Argo output 端口是否都已映射
        unmapped_outputs = [p for p in _output_ports if p not in port_map["outputs"]]
        if unmapped_outputs:
            return json.dumps({
                "saved": True,
                "port_map": port_map,
                "warning": f"Unmapped Argo output ports: {unmapped_outputs}. "
                           f"These MUST be mapped or downstream nodes will fail.",
            }, ensure_ascii=False)

        port_map_path.write_text(json.dumps(port_map, ensure_ascii=False, indent=2))
        return json.dumps({
            "saved": True,
            "port_map": port_map,
            "message": f"Port mapping updated: {len(port_map['inputs'])} inputs, {len(port_map['outputs'])} outputs",
        }, ensure_ascii=False)

    return [port_mapping]


def make_workspace_tools(project_id: str | None = None, projects_root: str = ""):
    """创建 workspace 访问工具。闭包绑定 project_id，直接访问项目 workspace 目录。"""

    _project_id = project_id
    _projects_root = projects_root

    def _get_workspace_dir() -> Path | None:
        """解析项目 workspace 目录路径。"""
        if not _project_id:
            return None
        try:
            from api.config import get_settings
            settings = get_settings()
            if _projects_root:
                wspath = Path(_projects_root) / _project_id / "files"
            else:
                wspath = settings.userdata_root / "projects" / _project_id / "files"
            if wspath.exists():
                return wspath.resolve()  # 解析 symlink
            return None
        except Exception:
            return None

    @tool
    def list_workspace_files(subdir: str = "") -> str:
        """List files in the project workspace directory. Like 'ls' on the workspace.
        Use this to see what user-uploaded files are available.

        Args:
            subdir: Optional subdirectory (e.g. '', 'inputs').
        """
        ws_dir = _get_workspace_dir()
        if not ws_dir:
            return json.dumps({"error": "Workspace not available (no project_id configured)"})

        target = (ws_dir / subdir) if subdir else ws_dir
        if not target.exists():
            return json.dumps({"error": f"Directory not found in workspace: {subdir or '.'}"})

        result = []
        for entry in sorted(target.iterdir()):
            is_dir = entry.is_dir()
            size = 0 if is_dir else entry.stat().st_size
            result.append({
                "name": entry.name,
                "type": "dir" if is_dir else "file",
                "size": size,
            })
        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool
    def read_workspace_file(filepath: str, start_line: int = 1, end_line: int = 0) -> str:
        """Read a file from the project workspace. Like 'cat' on the workspace.
        Use this to read user-uploaded input files (e.g. .xyz geometries).

        Args:
            filepath: Path relative to workspace (e.g. 'h2o.xyz', 'inputs/geometry.xyz').
            start_line: First line to read (1-indexed, default 1).
            end_line: Last line to read (0 = read to end, default 0).
        """
        ws_dir = _get_workspace_dir()
        if not ws_dir:
            return json.dumps({"error": "Workspace not available (no project_id configured)"})

        target = ws_dir / filepath
        # Safety: prevent path traversal
        try:
            target.resolve().relative_to(ws_dir.resolve())
        except ValueError:
            return json.dumps({"error": f"Path traversal denied: {filepath}"})

        if not target.exists():
            return json.dumps({"error": f"File not found in workspace: {filepath}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {filepath}"})

        try:
            content = target.read_text("utf-8")
            lines = content.splitlines()
            total_lines = len(lines)

            start = max(1, start_line) - 1
            end = total_lines if end_line <= 0 else min(end_line, total_lines)
            if start >= total_lines:
                return json.dumps({"error": f"start_line {start_line} exceeds file length ({total_lines} lines)"})

            selected = lines[start:end]
            result = "\n".join(selected)
            if len(result) > 20000:
                result = result[:20000] + "\n\n[... truncated at 20KB ...]"
            header = f"[workspace/{filepath} lines {start+1}-{min(end, total_lines)} of {total_lines}]\n"
            return header + result
        except Exception as e:
            return json.dumps({"error": f"Read error: {e}"})

    return [list_workspace_files, read_workspace_file]


# ═══════════════════════════════════════════════════════════════════════════
# 沙箱 + 环境工具（4 个）
# ═══════════════════════════════════════════════════════════════════════════

# 与编译器 workflows/pipeline/compiler.py:_process_run_sh() 完全相同的正则
_MF2_INIT_RE = re.compile(r"^# MF2 init[^\S\n]*$", re.MULTILINE)


def _run_sh_has_mf2_init(sandbox_dir: Path) -> bool:
    """检查 run.sh 是否包含编译器识别的 # MF2 init 标记。"""
    run_sh = sandbox_dir / "profile" / "run.sh"
    if not run_sh.exists():
        return False
    return bool(_MF2_INIT_RE.search(run_sh.read_text()))


def _generate_mf_node_params_sh(nodespec_path: Path, software_image: str) -> str | None:
    """从 sandbox nodespec.yaml 生成 mf_node_params.sh。

    复现编译器 _generate_node_params_sh() 的行为：
    1. 为每个 onboard_input 生成 shell 变量赋值
    2. 为 resources.parametrize 中的资源参数也生成变量（编译器由 Pydantic validator 自动注入）
    3. 处理 _shared_param 翻译
    4. 布尔值使用小写 true/false

    Returns:
        生成的 shell 脚本内容，无 onboard_inputs 且无 parametrize 时返回 None。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(nodespec_path.read_text("utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    onboard_inputs = list(data.get("onboard_inputs", []))
    resources = data.get("resources", {}) if isinstance(data, dict) else {}

    # ── 注入 resources.parametrize 中的资源参数 ──
    # 编译器通过 Pydantic validator 自动将 parametrize 条目注入 onboard_inputs，
    # 但我们读的是原始 YAML，需手动处理。
    # 必须查询 resource_defaults.yaml 获取正确的 param_name（如 cpu_cores → n_cores）
    if isinstance(resources, dict):
        parametrize = resources.get("parametrize", []) or []
        existing_names = {p.get("name", "") for p in onboard_inputs}
        # 加载 resource_defaults 以获取 param_name 映射
        try:
            from nodes.schemas.resource_defaults import get_resource_defaults
            rd = get_resource_defaults()
        except Exception:
            rd = {}
        for res_name in parametrize:
            entry = rd.get(res_name, {})
            param_name = entry.get("param_name", res_name)
            if param_name not in existing_names:
                default_val = resources.get(res_name)
                # 优先使用 resource_defaults 中定义的 kind
                kind = entry.get("kind") or (
                    "integer" if isinstance(default_val, int) else (
                        "float" if isinstance(default_val, float) else "string"
                    )
                )
                onboard_inputs.append({
                    "name": param_name,
                    "kind": kind,
                    "default": default_val,
                })
                existing_names.add(param_name)

    if not onboard_inputs:
        return None

    # 解析 software 名：优先 metadata.tags.software，fallback 镜像名去 tag
    software = ""
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    if isinstance(metadata, dict):
        tags = metadata.get("tags", {}) or {}
        software = (tags.get("software") or "").lower()
    if not software:
        software = software_image.split(":")[0].lower()

    node_name = metadata.get("name", "unknown") if isinstance(metadata, dict) else "unknown"
    node_version = metadata.get("version", "0.0.0") if isinstance(metadata, dict) else "0.0.0"

    lines = [
        "# Auto-generated by MiQroForge sandbox — do not edit manually",
        f"# Node: {node_name}  v{node_version}",
        "",
    ]

    for param in onboard_inputs:
        name = param.get("name", "")
        if not name:
            continue
        default = param.get("default")
        kind = param.get("kind", "")
        default_str = "" if default is None else str(default)

        # 布尔值统一小写，避免 bash 中 True/False 大小写问题
        if kind == "boolean" or isinstance(default, bool):
            default_str = "true" if default else "false"

        # _shared_param 翻译（复现编译器 _translate_shared_param）
        shared_param = param.get("_shared_param") or param.get("shared_param")
        if shared_param and software:
            try:
                from nodes.schemas.shared_params import load_shared_params
                sp = load_shared_params()
                resolved = sp.resolve(default_str, software, shared_param)
                if resolved is not None:
                    default_str = resolved
            except Exception:
                pass

        # 对默认值做 shell 转义：反斜杠和双引号
        escaped = default_str.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{name}=$(mf_param {name} "{escaped}")')

    return "\n".join(lines) + "\n"


def make_sandbox_tools(
    input_data: dict[str, str],
    env_overrides: dict[str, str] | None = None,
    sandbox_dir: Path | None = None,
    project_id: str | None = None,
    projects_root: str = "",
):
    """创建沙箱测试和 pip_install 工具。闭包绑定输入数据和环境。"""
    from agents.node_generator.shared.sandbox_base import _ensure_docker, _scan_output_files
    from agents.node_generator.ephemeral.sandbox import _run_pip_install

    _input_data = input_data
    _env_overrides = env_overrides or {}
    _sandbox_dir = sandbox_dir  # 节点工作目录（tmp/<node_name>/）
    _project_id = project_id
    _projects_root = projects_root
    # container_id → 执行沙箱目录映射（check_sandbox 需要知道输出文件在哪）
    _container_exec_map: dict[str, Path] = {}

    @tool
    def test_in_sandbox() -> str:
        """Test the generated node in Docker sandbox with real upstream data.
        Copies files from the node work directory to a temporary execution sandbox,
        compiles run.sh during the copy (original files are NOT modified).
        Docker image is read from nodespec.yaml metadata.base_image_ref.

        IMPORTANT: Write all required files with write_file() before calling this.
        At minimum, nodespec.yaml (with base_image_ref) and profile/run.sh must exist.
        """
        _ensure_docker()

        if not _sandbox_dir:
            return json.dumps({"error": "No node work directory configured"})

        # ── 从工作目录的 nodespec 解析 Docker 镜像 ──
        nodespec_path = _sandbox_dir / "nodespec.yaml"
        if not nodespec_path.exists():
            return json.dumps({
                "error": "nodespec.yaml not found in node work directory. "
                         "Use write_file('nodespec.yaml', <content>) first — "
                         "must include metadata.base_image_ref.",
                "test_passed": False,
            })
        try:
            from agents.node_generator.prefab.generator import _resolve_image_from_nodespec
            _software_image = _resolve_image_from_nodespec(nodespec_path.read_text("utf-8"))
        except ValueError as e:
            return json.dumps({
                "error": str(e),
                "test_passed": False,
            })

        # 确保 profile/run.sh 存在
        run_sh_path = _sandbox_dir / "profile" / "run.sh"
        if not run_sh_path.exists():
            return json.dumps({
                "error": "profile/run.sh not found in node work directory. "
                         "Use write_file('profile/run.sh', <content>) first to write the execution script.",
                "test_passed": False,
            })

        # ── 创建临时执行沙箱（从工作目录复制，不修改原文件）──
        exec_sandbox = _sandbox_dir.parent / f"_exec_{uuid.uuid4().hex[:8]}"
        exec_sandbox.mkdir(parents=True, exist_ok=True)

        # 复制 profile/ 并编译 run.sh
        src_profile = _sandbox_dir / "profile"
        dst_profile = exec_sandbox / "profile"
        if src_profile.exists():
            shutil.copytree(src_profile, dst_profile)
            # 编译器步骤 1：run.sh 文本替换 # MF2 init → source /mf/profile/mf2_init.sh
            compiled_run_sh = dst_profile / "run.sh"
            if compiled_run_sh.exists():
                run_sh_content = compiled_run_sh.read_text()
                run_sh_content = _MF2_INIT_RE.sub(
                    "source /mf/profile/mf2_init.sh", run_sh_content, count=1,
                )
                compiled_run_sh.write_text(run_sh_content)

        # 编译器步骤 2：复制 mf2_init.sh
        mf2_init_src = Path(__file__).parent.parent.parent.parent / "nodes" / "common" / "mf2_init.sh"
        if mf2_init_src.exists():
            shutil.copy2(mf2_init_src, dst_profile / "mf2_init.sh")

        # 编译器步骤 3：生成 mf_node_params.sh
        if nodespec_path.exists():
            params_content = _generate_mf_node_params_sh(nodespec_path, _software_image)
            if params_content:
                (dst_profile / "mf_node_params.sh").write_text(params_content, encoding="utf-8")

        # 复制 nodespec.yaml
        shutil.copy2(nodespec_path, exec_sandbox / "nodespec.yaml")

        # 写入输入数据
        input_dir = exec_sandbox / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        for port_name, content in _input_data.items():
            (input_dir / port_name).write_text(content, encoding="utf-8")

        # 确保 output, workdir 目录（777 权限：部分镜像以非 root 用户运行，如 Psi4 mambauser）
        for _d in [(exec_sandbox / "output"), (exec_sandbox / "workdir")]:
            _d.mkdir(parents=True, exist_ok=True)
            _d.chmod(0o777)

        # ── 应用 port_map 输入别名：通用名(I1) → 语义名(xyz_geometry) ──
        port_map_path = _sandbox_dir / "port_map.json"
        if port_map_path.exists():
            try:
                pm = json.loads(port_map_path.read_text("utf-8"))
                for generic, semantic in pm.get("inputs", {}).items():
                    generic_file = input_dir / generic
                    semantic_file = input_dir / semantic
                    if generic_file.exists() and generic != semantic:
                        semantic_file.write_text(generic_file.read_text("utf-8"))
            except Exception:
                pass

        # ── 解析 workspace 挂载路径 ──
        workspace_mount = f"{exec_sandbox}/workspace:/mf/workspace"
        if _project_id:
            try:
                from api.config import get_settings
                settings = get_settings()
                if _projects_root:
                    wspath = Path(_projects_root) / _project_id / "files"
                else:
                    wspath = settings.userdata_root / "projects" / _project_id / "files"
                if wspath.exists():
                    workspace_mount = f"{wspath.resolve()}:/mf/workspace"
            except Exception:
                pass

        # 构建 Docker 命令（不用 --rm，由 check_sandbox 显式清理，确保容器日志可被收集）
        cmd = [
            "docker", "run",
            "-v", f"{dst_profile}:/mf/profile:ro",
            "-v", f"{input_dir}:/mf/input",
            "-v", f"{exec_sandbox}/output:/mf/output",
            "-v", workspace_mount,
            "-v", f"{exec_sandbox}/workdir:/mf/workdir",
            "-e", "INPUT_DIR=/mf/input",
            "-e", "OUTPUT_DIR=/mf/output",
            "-e", "WORKDIR=/mf/workdir",
            "-e", "PROFILE_DIR=/mf/profile",
            "-e", "WORKSPACE_DIR=/mf/workspace",
        ]

        # 添加资源环境变量
        for k, v in _env_overrides.items():
            cmd.extend(["-e", f"{k}={v}"])

        # ── 从 nodespec 提取资源用于 Docker 限制 ──
        import yaml as _yaml_res
        cpu_cores = 4
        memory_gb = 8.0
        # 默认 30 分钟 — 仅作为 Agent 上下文信息传递，Docker --detach 模式下无自动 kill。
        # 若需终止容器，Agent 必须主动调用 kill_sandbox()。
        walltime_seconds = 1800  # 默认 30 分钟
        if nodespec_path.exists():
            try:
                spec = _yaml_res.safe_load(nodespec_path.read_text("utf-8"))
                res = spec.get("resources", {}) if isinstance(spec, dict) else {}
                if res.get("cpu_cores"):
                    cpu_cores = int(res["cpu_cores"])
                if res.get("mem_gb"):
                    memory_gb = float(res["mem_gb"])
                if res.get("estimated_walltime_hours"):
                    walltime_seconds = int(float(res["estimated_walltime_hours"]) * 3600)
            except Exception:
                pass

        # ── 生成唯一容器名 ──
        container_name = f"mf_sandbox_{uuid.uuid4().hex[:8]}"

        # 添加资源限制 + 后台运行
        cmd.extend([
            "--cpus", str(cpu_cores),
            "--memory", f"{memory_gb}g",
            "--name", container_name,
            "--detach",
        ])

        # ── 入口点：run.sh 已被处理为自包含（含 source /mf/profile/mf2_init.sh），直接执行 ──
        cmd.extend([_software_image, "bash", "/mf/profile/run.sh"])

        # ── 启动容器（后台、非阻塞）──
        try:
            run_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(exec_sandbox),
            )
            container_id = run_result.stdout.strip()
            if run_result.returncode != 0 or not container_id:
                return json.dumps({
                    "error": f"Docker run failed: {run_result.stderr}",
                    "test_passed": False,
                })
        except Exception as e:
            return json.dumps({
                "error": f"Docker run exception: {e}",
                "test_passed": False,
            })

        # 记录 container → exec_sandbox 映射
        _container_exec_map[container_id] = exec_sandbox

        return json.dumps({
            "status": "started",
            "container_id": container_id,
            "container_name": container_name,
            "exec_sandbox": str(exec_sandbox),
            "cpu_cores": cpu_cores,
            "memory_gb": memory_gb,
            "walltime_seconds": walltime_seconds,
            "message": (
                f"Sandbox container started with {cpu_cores} CPU, {memory_gb}GB memory, "
                f"walltime={walltime_seconds/3600:.1f}h. "
                f"Use check_sandbox('{container_id}') to poll for completion, "
                f"or kill_sandbox('{container_id}') to terminate."
            ),
        }, ensure_ascii=False)

    @tool
    def check_sandbox(container_id: str) -> str:
        """Check the status of a running sandbox container.

        If the container is still running, returns status and last 50 lines of logs.
        If the container has exited, returns full results (stdout, stderr, return_code,
        generated_files, image_files) and auto-cleans the container.

        Args:
            container_id: The Docker container ID returned by test_in_sandbox.
        """
        try:
            # 检查容器是否存在
            inspect_result = subprocess.run(
                ["docker", "inspect", container_id],
                capture_output=True, text=True, timeout=10,
            )
            container_exists = inspect_result.returncode == 0

            if container_exists:
                info = json.loads(inspect_result.stdout)[0]
                state = info.get("State", {})
                running = state.get("Running", False)
                exit_code = state.get("ExitCode", 0)

                # 获取最后 50 行日志
                logs_result = subprocess.run(
                    ["docker", "logs", "--tail", "50", container_id],
                    capture_output=True, text=True, timeout=10,
                )

                if running:
                    return json.dumps({
                        "status": "running",
                        "logs_tail": logs_result.stdout[-3000:] if logs_result.stdout else "",
                        "stderr_tail": logs_result.stderr[-2000:] if logs_result.stderr else "",
                    }, ensure_ascii=False)

                # ── 容器已退出：收集完整结果 ──
                full_logs = subprocess.run(
                    ["docker", "logs", container_id],
                    capture_output=True, text=True, timeout=30,
                )
                stdout = full_logs.stdout or ""
                stderr = full_logs.stderr or ""
                return_code = exit_code

                # 容器不在此处删除 — 由 generate_prefab_node 结束时统一清理
            else:
                # 容器已被 auto-clean 或从未存在 — 仍扫描输出文件（bind mount 在宿主机上持久存在）
                stdout = ""
                stderr = f"Container {container_id} not found (already cleaned). Output files may still be available."
                return_code = -1

            # 扫描输出文件（从执行沙箱目录读取）
            generated_files = []
            image_files = []
            exec_sb = _container_exec_map.get(container_id)
            if exec_sb and exec_sb.exists():
                output_dir = exec_sb / "output"
                workspace_dir = exec_sb / "workspace"
                if output_dir.exists() or workspace_dir.exists():
                    generated_files, image_files = _scan_output_files(output_dir, workspace_dir)
                # ── 复制 output 到节点工作目录，让 Agent 可用 read_node_file 检查 ──
                if return_code == 0 and _sandbox_dir and output_dir.exists():
                    dst_output = _sandbox_dir / "output"
                    dst_output.mkdir(parents=True, exist_ok=True)
                    for f_path in output_dir.iterdir():
                        if f_path.is_file():
                            try:
                                shutil.copy2(f_path, dst_output / f_path.name)
                            except Exception:
                                pass

            if container_exists:
                return json.dumps({
                    "status": "exited",
                    "return_code": return_code,
                    "stdout": stdout[:5000],
                    "stderr": stderr[:3000],
                    "generated_files": generated_files,
                    "image_files": image_files,
                    "test_passed": return_code == 0,
                }, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "not_found",
                    "return_code": return_code,
                    "stdout": stdout[:5000],
                    "stderr": stderr[:3000],
                    "generated_files": generated_files,
                    "image_files": image_files,
                    "test_passed": len(generated_files) > 0,
                    "error": stderr,
                }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"check_sandbox failed: {e}"})

    @tool
    def kill_sandbox(container_id: str) -> str:
        """Kill a running sandbox container and remove it.

        Args:
            container_id: The Docker container ID to kill and remove.
        """
        try:
            kill_result = subprocess.run(
                ["docker", "kill", container_id],
                capture_output=True, text=True, timeout=10,
            )
            rm_result = subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True, text=True, timeout=10,
            )
            return json.dumps({
                "killed": kill_result.returncode == 0 or "not running" in kill_result.stderr.lower(),
                "removed": rm_result.returncode == 0,
                "message": "Container terminated and removed.",
            })
        except Exception as e:
            return json.dumps({"error": f"kill_sandbox failed: {e}"})

    @tool
    def pip_install(package: str) -> str:
        """Install a Python package via pip in a Docker container.
        Use this only for lightweight nodes that need extra dependencies.

        Args:
            package: Package name (e.g. 'numpy', 'matplotlib').
        """
        result = _run_pip_install(package)
        return result.get("output", "No output")[:500]

    return [test_in_sandbox, check_sandbox, kill_sandbox, pip_install]


# ═══════════════════════════════════════════════════════════════════════════
# 控制工具
# ═══════════════════════════════════════════════════════════════════════════

def make_terminate_tool() -> list:
    """创建 terminate 工具 — Agent 遇到不科学输入时可主动终止，不进入 evaluator。"""
    import json as _json

    @tool
    def terminate(reason: str) -> str:
        """Terminate generation immediately when the computational task is scientifically invalid.

        Use this when:
        - The requested method is incompatible with the input (e.g. UHF with multiplicity=1)
        - The calculation cannot physically converge (e.g. impossible geometry)
        - The input parameters are self-contradictory
        - The task requires resources far beyond what's available

        This will skip the evaluator entirely and return the reason directly.

        Args:
            reason: Clear explanation of why the task is scientifically impossible.
        """
        return _json.dumps({
            "_terminate_": True,
            "reason": reason,
        }, ensure_ascii=False)

    return [terminate]


# ═══════════════════════════════════════════════════════════════════════════
# 记忆工具
# ═══════════════════════════════════════════════════════════════════════════

def make_memory_tool(call_state: dict | None = None) -> list:
    """创建 record_lesson 工具 — Agent 可将重要经验写入持久记忆。

    闭包通过 mutable dict 回传经验文本给调用方（generator → API endpoint）。
    仅允许调用一次，截断至 200 字符。
    """
    import json as _json
    _call_state = call_state if call_state is not None else {}

    @tool
    def record_lesson(lesson_text: str) -> str:
        """Record an important lesson learned during node generation.

        Use ONCE per run — save it for the most impactful insight. Examples:
        - Non-obvious input format rules (e.g. "Gaussian requires blank line after geometry")
        - Software-specific invocation quirks (e.g. "Psi4 molecule block uses Bohr not Angstrom")
        - Common failure patterns (e.g. "CP2K SCF fails with LSD, switch to GGA")

        Args:
            lesson_text: The lesson to record. Max 200 characters — will be truncated if longer.
        """
        if _call_state.get("_recorded_lesson"):
            return _json.dumps({
                "error": "Lesson already recorded. Only one lesson per run.",
                "recorded": _call_state["_recorded_lesson"],
            }, ensure_ascii=False)

        lesson = lesson_text[:200]
        _call_state["_recorded_lesson"] = lesson
        return _json.dumps({
            "recorded": True,
            "lesson": lesson,
            "chars": len(lesson),
        }, ensure_ascii=False)

    return [record_lesson]


# ═══════════════════════════════════════════════════════════════════════════
# Explore 子 Agent 工具（将研究任务委派给独立的快速模型子 Agent）
# ═══════════════════════════════════════════════════════════════════════════

def make_explore_tool(default_software: str, project_id: str = "", projects_root: str = "") -> list:
    """创建 explore_manuals 工具——将研究任务委派给 Explore 子 Agent。

    父 Agent 调用此工具时，Explore 子 Agent 用快速模型独立搜索手册、
    参考节点和 Schema，返回结构化摘要后丢弃上下文。
    父 Agent 只看到结论，上下文保持精简。
    """
    _software = default_software
    _project_id = project_id
    _projects_root = projects_root

    @tool
    def research(question: str, avoid_directions: str = "") -> str:
        """★★★ PREFERRED — Delegate research to a sub-agent. Covers ALL sources.

        Instead of calling individual tools one by one (search_manual → get_section →
        search_reference_nodes → read_reference_node_file → query_shared_params...),
        use this to delegate ALL research to a sub-agent that searches manuals,
        reference nodes, and schema registries concurrently. The sub-agent uses a
        speed-optimized model, runs parallel tool calls in its own context, and
        returns a concise synthesized summary. Your context stays clean.

        Use this FIRST for any research task. Launch MULTIPLE research() calls in
        one round for parallel investigation of different questions.

        Only fall back to individual search tools if you need to verify a specific
        detail the sub-agent might have missed.

        Args:
            question: Focused research question (one sentence per call).
                Example: "Gaussian RHF geo-opt: input format and % sections?"
            avoid_directions: Directions already tried that didn't work.
                Example: "Don't search for CASSCF — we need single-reference RHF"
        """
        from agents.subagent.explore import run_explore_agent
        sw = _software or ""
        return run_explore_agent(
            question=question,
            software=sw,
            avoid_directions=avoid_directions,
            project_id=_project_id,
            projects_dir=_projects_root,
        )

    return [research]


# ═══════════════════════════════════════════════════════════════════════════
# 工具注册入口
# ═══════════════════════════════════════════════════════════════════════════

def build_all_tools(
    software: str,
    input_data: dict[str, str],
    env_overrides: dict[str, str] | None = None,
    sandbox_dir: Path | None = None,
    sandbox_enabled: bool = True,
    project_id: str | None = None,
    input_ports: list[str] | None = None,
    output_ports: list[str] | None = None,
    projects_root: str = "",
    call_state: dict | None = None,
) -> list:
    """构建工具列表，返回 LangChain tool 列表。

    Parameters
    ----------
    software : str
        目标软件名（如 'gaussian'），用于加载手册和 shared_params。
    input_data : dict[str, str]
        真实上游输入数据 {port_name: content}。
    env_overrides : dict[str, str] | None
        资源环境变量（n_cores, mem_gb 等）。
    sandbox_dir : Path | None
        沙箱工作目录。sandbox 工具从此目录的 nodespec.yaml 读取 base_image_ref。
    sandbox_enabled : bool
        是否启用沙箱工具。设计时为 False（无上游数据），运行时为 True。
    project_id : str | None
         项目 ID，用于定位 workspace 目录。
    input_ports : list[str] | None
         Argo DAG 输入端口名列表（用于 port_mapping 工具描述）。
    output_ports : list[str] | None
         Argo DAG 输出端口名列表（用于 port_mapping 工具描述）。
    projects_root : str
         用户 projects 目录根路径（多用户场景）。
    call_state : dict | None
        可变字典，用于工具间回传状态（如 record_lesson 存储 _recorded_lesson）。
    """
    from agents.node_generator.shared.manual_index import get_manual_index, list_available_manuals

    _available_manuals = list_available_manuals()

    tools = []

    # 文件系统（3 个）— 始终可用
    tools.extend(make_filesystem_tools(sandbox_dir=sandbox_dir))

    # port_mapping（1 个）— 仅运行时可用（无 Argo DAG 时没有端口需要映射）
    if sandbox_enabled:
        tools.extend(make_port_tools(sandbox_dir=sandbox_dir, input_ports=input_ports, output_ports=output_ports))

    # 手册导航（5 个）— 每个工具接受 software 参数，Agent 自由选择
    tools.extend(make_manual_tools(software, _available_manuals))

    # 节点参考（3 个）— 传入 target_software 以过滤搜索结果
    tools.extend(make_node_reference_tools(target_software=software))

    # Schema 参考（2 个）
    tools.extend(make_schema_tools())

    # Explore 子 Agent（1 个）— 研究任务委派给快速模型，返回摘要后丢弃上下文
    tools.extend(make_explore_tool(default_software=software, project_id=project_id or "", projects_root=projects_root or ""))

    # Workspace（2 个）— 始终注册，无 project_id 时返回错误提示
    tools.extend(make_workspace_tools(project_id=project_id, projects_root=projects_root))

    # 沙箱 + 环境（4 个）— 仅运行时启用
    if sandbox_enabled:
        tools.extend(make_sandbox_tools(
            input_data=input_data,
            env_overrides=env_overrides,
            sandbox_dir=sandbox_dir,
            project_id=project_id,
            projects_root=projects_root,
        ))

    # 控制（1 个）— 始终可用
    tools.extend(make_terminate_tool())

    # 记忆（1 个）— 运行时启用，Agent 记录关键经验
    if sandbox_enabled and call_state is not None:
        tools.extend(make_memory_tool(call_state))

    return tools
