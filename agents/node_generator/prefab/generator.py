"""agents/node_generator/prefab/generator.py — Prefab 模式生成节点。

ReAct Agent 循环，使用工具研究、生成、测试预制菜节点。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from agents.llm_config import LLMConfig
from agents.common.prompt_loader import load_prompt
from agents.common.session_logger import get_session
from agents.node_generator.prefab.state import PrefabGenState
from agents.node_generator.shared.knowledge import load_available_images


def _extract_script(text: str) -> str:
    """从 LLM 纯文本响应中提取脚本。"""
    script = text.strip()

    if "```python" in script:
        try:
            start = script.index("```python") + 9
            end = script.index("```", start)
            return script[start:end].strip()
        except ValueError:
            pass
    elif "```bash" in script:
        try:
            start = script.index("```bash") + 7
            end = script.index("```", start)
            return script[start:end].strip()
        except ValueError:
            pass
    elif "```" in script:
        try:
            start = script.index("```") + 3
            end = script.index("```", start)
            return script[start:end].strip()
        except ValueError:
            pass

    return script


def _parse_prefab_output(text: str) -> dict[str, str]:
    """解析 prefab 模式 ReAct Agent 最终输出中的各部分。"""
    sections: dict[str, str] = {}

    markers = {
        "nodespec_yaml": "=== NODESPEC_YAML ===",
        "run_sh": "=== RUN_SH ===",
        "input_template": "=== INPUT_TEMPLATE ===",
    }

    current_section = None
    current_lines: list[str] = []

    for line in text.splitlines():
        found_marker = False
        for key, marker in markers.items():
            if marker in line:
                if current_section:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = key
                current_lines = []
                found_marker = True
                break

        if not found_marker and current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    # 清除代码块标记
    for key in list(sections.keys()):
        val = sections[key]
        if val.startswith("```yaml") or val.startswith("```bash") or val.startswith("```"):
            lines = val.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            sections[key] = "\n".join(lines).strip()

    # NONE 标记表示无模板
    if sections.get("input_template", "").upper() == "NONE":
        sections.pop("input_template", None)

    return sections


def _load_semantic_types() -> dict[str, Any]:
    from pathlib import Path
    import yaml
    registry_path = (
        Path(__file__).parent.parent.parent.parent / "nodes" / "schemas" / "semantic_registry.yaml"
    )
    if not registry_path.exists():
        return {}
    with registry_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("types", {})


def _resolve_image_from_nodespec(nodespec_yaml: str) -> str:
    """从 nodespec 的 metadata.base_image_ref 解析 Docker 镜像。

    在 base_images/registry.yaml 中查找与 base_image_ref 匹配的镜像条目，
    返回完整的 image:tag 引用。

    Raises:
        ValueError: nodespec 无 base_image_ref 或 registry 中找不到匹配镜像。
    """
    import yaml

    def _img_ref(img: dict) -> str:
        image = img.get("image", img.get("name", ""))
        tag = img.get("tag", "latest")
        return f"{image}:{tag}"

    if not nodespec_yaml:
        raise ValueError(
            "无法解析镜像: 没有 nodespec。Agent 必须先用 write_file 写入 nodespec.yaml "
            "(含 metadata.base_image_ref) 后才能调用 test_in_sandbox"
        )

    try:
        spec = yaml.safe_load(nodespec_yaml)
    except Exception as e:
        raise ValueError(f"无法解析镜像: nodespec YAML 解析失败: {e}")

    if not isinstance(spec, dict):
        raise ValueError("无法解析镜像: nodespec 格式不正确")

    base_image_ref = spec.get("metadata", {}).get("base_image_ref", "")
    if not base_image_ref:
        raise ValueError(
            "无法解析镜像: nodespec 中缺少 metadata.base_image_ref。"
            "Agent 必须在 nodespec 中指定 base_image_ref"
        )

    registry_path = (
        Path(__file__).parent.parent.parent.parent / "nodes" / "base_images" / "registry.yaml"
    )
    if not registry_path.exists():
        raise ValueError(f"无法解析镜像 base_image_ref='{base_image_ref}': registry.yaml 不存在")

    data = yaml.safe_load(registry_path.read_text("utf-8"))
    images = data if isinstance(data, list) else data.get("images", [])

    _EXCLUDE = {"ephemeral-py"}
    images = [img for img in images if isinstance(img, dict) and img.get("name", "") not in _EXCLUDE]

    # 精确匹配
    for img in images:
        if img.get("name", "") == base_image_ref:
            return _img_ref(img)

    # 部分匹配
    for img in images:
        name = img.get("name", "").lower()
        if base_image_ref.lower() in name:
            return _img_ref(img)

    raise ValueError(
        f"无法解析镜像 base_image_ref='{base_image_ref}': "
        f"registry 中找不到匹配的镜像。可用: {[img.get('name', '') for img in images]}"
    )


def _execute_tool(tools: list, tool_name: str, tool_args: dict) -> str:
    """执行指定的工具并返回结果字符串。"""
    for t in tools:
        if t.name == tool_name:
            try:
                result = t.invoke(tool_args)
                return str(result) if not isinstance(result, str) else result
            except Exception as e:
                return json.dumps({"error": f"Tool '{tool_name}' failed: {e}"})
    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def generate_prefab_node(state: PrefabGenState) -> dict[str, Any]:
    """Prefab 模式生成节点 — ReAct Agent 循环，使用工具研究、生成、测试预制菜节点。"""
    from agents.node_generator.prefab.tools import build_all_tools
    from agents.node_generator.shared.compression import compress_messages

    request = state.get("request")
    if not request:
        return {"error": "缺少 NodeGenRequest 输入"}

    iteration = state.get("iteration", 0)

    # ── 加载知识 ──
    available_images = state.get("available_images") or load_available_images()
    semantic_types = state.get("semantic_types") or _load_semantic_types()

    # ── 软件信息（仅用于 manual/reference 工具，不参与镜像选择）──
    software = (request.target_software or "").lower()
    prev_nodespec = state.get("nodespec_yaml", "")

    # ── 节点工作目录（tmp/<node_name>/）—— 工具读写此目录，test_in_sandbox 从此复制到执行沙箱 ──
    existing_work_dir = state.get("_sandbox_dir")  # 向后兼容：API 仍传 _sandbox_dir
    if existing_work_dir:
        sandbox_dir = Path(existing_work_dir) if isinstance(existing_work_dir, str) else existing_work_dir
    else:
        pid = state.get("_project_id")
        if not pid:
            raise ValueError(
                "prefab generator requires _sandbox_dir (node work directory in tmp/). "
                f"Got _project_id={pid!r}"
            )
        # 设计时 fallback：使用 tmp/pending/
        projects_root = state.get("_projects_root", "")
        if projects_root:
            sandbox_dir = Path(projects_root) / pid / "tmp" / "pending"
        else:
            from api.config import get_settings
            settings = get_settings()
            sandbox_dir = settings.userdata_root / "projects" / pid / "tmp" / "pending"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

    # ── 构建输入数据 ──
    input_data = state.get("_input_data") or {}

    # ── 项目 ID（用于 workspace 工具）──
    project_id = state.get("_project_id") or None

    # ── 构建 input_data_preview（截断 500 字符用于 prompt）──
    input_data_preview: dict[str, str] = {}
    for k, v in input_data.items():
        input_data_preview[k] = v[:500] if len(v) > 500 else v

    # ── 沙箱启用标志 ──
    sandbox_enabled = state.get("_sandbox_enabled", bool(input_data))
    mf_test = state.get("_mf_test", False)
    max_inner = state.get("_max_inner", 3)

    # ── 资源环境变量 ──
    env_overrides: dict[str, str] = {}
    if request.resource_overrides:
        for k, v in request.resource_overrides.items():
            env_overrides[str(k)] = str(v)

    # ── 构建工具 ──
    projects_root = state.get("_projects_root", "")
    tools = build_all_tools(
        software=software,
        input_data=input_data,
        env_overrides=env_overrides,
        sandbox_dir=sandbox_dir,
        sandbox_enabled=sandbox_enabled,
        project_id=project_id,
        input_ports=state.get("_input_ports") or [],
        output_ports=state.get("_output_ports") or [],
        projects_root=projects_root,
    )

    # ── 构建 prompt ──
    # 检索相关历史经验（纯 embedding 语义相似度）
    generation_memory = []
    try:
        from agents.node_generator.shared.memory import get_experience_store
        store = get_experience_store(software or "general")
        if request.description:
            generation_memory = store.query(task=request.description, n=5)
    except Exception:
        pass
    # Argo 端口名（供 prompt 和 port_mapping 工具使用）
    input_ports = state.get("_input_ports") or []
    output_ports = state.get("_output_ports") or []

    system_content = load_prompt(
        "node_generator/prompts/prefab/system.jinja2",
        available_images=available_images,
        semantic_types=semantic_types,
        generation_memory=generation_memory,
        sandbox_enabled=sandbox_enabled,
        mf_test=mf_test,
        input_ports=input_ports,
        output_ports=output_ports,
    )

    # 前轮反馈 + Argo 端口列表
    evaluation = state.get("evaluation")
    prev_run_sh = state.get("run_sh", "")
    eval_issues = (evaluation.issues if evaluation and not evaluation.passed else [])
    sandbox_result = state.get("sandbox_test_result") if iteration > 0 else None

    # 运行时预生成节点：第 0 轮即有 nodespec → 使用 runtime prompt（以预生成 nodespec 为参考）
    # 设计时：第 0 轮无 nodespec → 使用 design prompt（从零生成）
    is_runtime_with_spec = bool(prev_nodespec) and iteration == 0
    if is_runtime_with_spec:
        user_content = load_prompt(
            "node_generator/prompts/prefab/human_runtime.jinja2",
            request=request.model_dump(),
            iteration=iteration,
            prev_nodespec=prev_nodespec,
            prev_run_sh=prev_run_sh,
            eval_issues=eval_issues,
            sandbox_result=sandbox_result,
            input_data=input_data_preview,
            input_ports=input_ports,
            output_ports=output_ports,
            sandbox_enabled=sandbox_enabled,
        )
    else:
        # 设计时生成，或运行时第 N 轮（N>0）
        user_content = load_prompt(
            "node_generator/prompts/prefab/human_design.jinja2",
            request=request.model_dump(),
            iteration=iteration,
            prev_nodespec=prev_nodespec if iteration > 0 else "",
            prev_run_sh=prev_run_sh if iteration > 0 else "",
            eval_issues=eval_issues,
            sandbox_result=sandbox_result,
            input_data=input_data_preview,
            input_ports=input_ports,
            output_ports=output_ports,
            sandbox_enabled=sandbox_enabled,
        )

    # ── Runtime 模式：预写所有设计时文件到沙箱（让 Agent 用工具查看）──
    if is_runtime_with_spec:
        profile_dir = sandbox_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        # 写入预生成的 nodespec.yaml
        (sandbox_dir / "nodespec.yaml").write_text(prev_nodespec, encoding="utf-8")
        # 写入 run.sh
        if prev_run_sh:
            (profile_dir / "run.sh").write_text(prev_run_sh, encoding="utf-8")
            (profile_dir / "run.sh").chmod(0o755)
        # 写入所有 profile 文件（模板、辅助脚本如 postprocess.py 等）
        profile_files = state.get("input_templates") or {}
        for fname, fcontent in profile_files.items():
            (profile_dir / fname).write_text(fcontent, encoding="utf-8")
            if fname.endswith(".sh"):
                (profile_dir / fname).chmod(0o755)

    # ── 预写 input_data 到 sandbox/input/（让 Agent 用 list_node_files 能看到）──
    if input_data:
        input_dir = sandbox_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        for port_name, content in input_data.items():
            (input_dir / port_name).write_text(content, encoding="utf-8")

    # ── LLM ──
    llm = LLMConfig.get_chat_model(purpose="node_generator", temperature=0.1)
    llm_with_tools = llm.bind_tools(tools)

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

    # ── ReAct 循环 ──
    max_tool_calls = 25
    max_sandbox_calls = max_inner
    tool_call_count = 0
    sandbox_call_count = 0
    nodespec_yaml = ""
    run_sh = ""
    input_templates: dict[str, str] = {}
    sandbox_test_passed = False
    sandbox_test_result: dict[str, Any] = {}
    unchecked_containers: list[str] = []  # test_in_sandbox 启动但未 check 的容器 ID
    all_containers: list[str] = []  # 所有创建过的 sandbox 容器 ID（用于最终统一清理）
    exec_sandbox_dirs: list[Path] = []  # test_in_sandbox 创建的执行目录（由 API endpoint 收 outputs 后清理）
    _terminated = False
    _terminate_reason = ""
    _internal_errors: list[str] = []

    try:
        for _ in range(max_tool_calls):
            response = llm_with_tools.invoke(messages)

            session = get_session()
            if session:
                tc_names = [tc.get("name", "") for tc in (response.tool_calls or [])]
                session.log_event("prefab_react_step", {
                    "iteration": iteration,
                    "tool_calls": tc_names,
                    "response_preview": response.content[:200] if response.content else "",
                })

            # LLM 不再调工具 → Agent 完成。产出已在 sandbox 磁盘上，后续统一从磁盘读取。
            if not response.tool_calls:
                messages.append(response)
                break

            # 追加 AI 消息
            messages.append(response)

            # 执行每个工具调用
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "")
                tool_call_count += 1

                # 沙箱调用次数限制
                if tool_name == "test_in_sandbox":
                    sandbox_call_count += 1
                    if sandbox_call_count > max_sandbox_calls:
                        tool_result = json.dumps({
                            "error": f"Sandbox call limit reached ({max_sandbox_calls}/{max_sandbox_calls}). "
                                     "Finalize your work — check the last sandbox result and stop.",
                        }, ensure_ascii=False)
                        messages.append(ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_id,
                        ))
                        continue

                # 找到对应工具并执行
                tool_result = _execute_tool(tools, tool_name, tool_args)

                # 检测 terminate 信号
                if tool_name == "terminate":
                    try:
                        td = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                        if td.get("_terminate_"):
                            _terminated = True
                            _terminate_reason = td.get("reason", "")
                            messages.append(ToolMessage(
                                content=str(tool_result),
                                tool_call_id=tool_id,
                            ))
                            break  # 跳出工具调用 for 循环
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 收集工具错误（供 memory 系统使用）
                try:
                    result_str = str(tool_result)
                    if "error" in result_str.lower() or "failed" in result_str.lower():
                        # 截取关键信息
                        short = result_str[:300]
                        _internal_errors.append(f"{tool_name}: {short}")
                except Exception:
                    pass

                # 捕获 sandbox 测试结果
                if tool_name == "test_in_sandbox":
                    try:
                        result_dict = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                        sandbox_test_result = result_dict
                        sandbox_test_passed = result_dict.get("test_passed", False)
                        # 追踪容器 ID 以便后续自动轮询和最终清理
                        cid = result_dict.get("container_id")
                        if cid and result_dict.get("status") == "started":
                            unchecked_containers.append(cid)
                            all_containers.append(cid)
                        # 追踪执行沙箱目录
                        exec_sb = result_dict.get("exec_sandbox")
                        if exec_sb:
                            exec_sandbox_dirs.append(Path(exec_sb))
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 追踪 check_sandbox 调用 — 更新 sandbox 结果并从 unchecked 列表移除
                if tool_name == "check_sandbox":
                    cid = tool_args.get("container_id", "")
                    if cid and cid in unchecked_containers:
                        unchecked_containers.remove(cid)
                    # 解析 check_sandbox 结果，若有 test_passed 则更新
                    try:
                        check_result = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                        if "test_passed" in check_result:
                            sandbox_test_result = check_result
                            sandbox_test_passed = check_result.get("test_passed", False)
                    except (json.JSONDecodeError, TypeError):
                        pass

                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                ))

                if session:
                    result_str = str(tool_result)
                    if tool_name.startswith("read_"):
                        lines = result_str.split("\n")
                        result_preview = "\n".join(lines[:3])
                        if len(lines) > 3:
                            result_preview += "\n... (truncated)"
                    else:
                        result_preview = result_str[:500]
                    session.log_event("tool_call", {
                        "iteration": iteration,
                        "tool": tool_name,
                        "args_preview": str(tool_args)[:300],
                        "result_preview": result_preview,
                    })

            # terminate 信号：跳出外循环
            if _terminated:
                break

            # 上下文压缩检查
            messages = compress_messages(
                messages,
                max_tokens=100000,
                keep_recent=6,
                llm=llm,
            )

        else:
            # 达到最大工具调用次数，尝试从最后的响应中提取
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    sections = _parse_prefab_output(msg.content)
                    if sections.get("nodespec_yaml"):
                        nodespec_yaml = sections["nodespec_yaml"]
                        run_sh = sections.get("run_sh", "")
                        tpl = sections.get("input_template", "")
                        if tpl:
                            input_templates[f"input.{software}.template"] = tpl
                        break

        # ── 自动轮询未检查的 sandbox 容器 ──
        if unchecked_containers and sandbox_enabled:
            # 找到 check_sandbox 工具并轮询每个未检查的容器
            check_tool = None
            for t in tools:
                if t.name == "check_sandbox":
                    check_tool = t
                    break
            if check_tool:
                for cid in list(unchecked_containers):
                    try:
                        result_str = str(check_tool.invoke({"container_id": cid}))
                        try:
                            result_dict = json.loads(result_str)
                        except (json.JSONDecodeError, TypeError):
                            result_dict = {"error": result_str}
                        status = result_dict.get("status", "")
                        if status in ("exited", "not_found"):
                            sandbox_test_result = result_dict
                            sandbox_test_passed = result_dict.get("test_passed", False)
                            unchecked_containers.remove(cid)
                    except Exception:
                        pass

        # ── 统一清理所有 sandbox 容器（延迟到流程结束，不提前删除）──
        if all_containers:
            import subprocess as _sp
            for cid in all_containers:
                try:
                    # 安全检查：仅删除 mf_sandbox_ 前缀的容器，防止误删
                    inspect = _sp.run(
                        ["docker", "inspect", "--format", "{{.Name}}", cid],
                        capture_output=True, text=True, timeout=5,
                    )
                    name = inspect.stdout.strip().lstrip("/")
                    if name.startswith("mf_sandbox_"):
                        _sp.run(["docker", "rm", "-f", cid],
                                capture_output=True, timeout=10)
                except Exception:
                    pass

        # ── 从 sandbox 磁盘读取（Agent 通过 write_file 写入，文件在磁盘上）──
        if not nodespec_yaml:
            disk_nodespec = sandbox_dir / "nodespec.yaml"
            if disk_nodespec.exists():
                try:
                    nodespec_yaml = disk_nodespec.read_text(encoding="utf-8")
                except Exception:
                    pass
        if not run_sh:
            disk_run_sh = sandbox_dir / "profile" / "run.sh"
            if disk_run_sh.exists():
                try:
                    run_sh = disk_run_sh.read_text(encoding="utf-8")
                except Exception:
                    pass

        # ── 日志 ──
        session = get_session()
        if session:
            session.log_llm_call(
                "prefab_react_final", messages, nodespec_yaml[:500] if nodespec_yaml else "",
                iteration=iteration,
                tool_call_count=tool_call_count,
                sandbox_test_passed=sandbox_test_passed,
            )

        return {
            "nodespec_yaml": nodespec_yaml,
            "run_sh": run_sh,
            "input_templates": input_templates,
            "available_images": available_images,
            "semantic_types": semantic_types,
            "generation_memory": [],
            "sandbox_test_result": sandbox_test_result,
            "sandbox_test_passed": sandbox_test_passed,
            "sandbox_call_count": sandbox_call_count,
            "tool_call_count": tool_call_count,
            "messages_history": messages,
            "_sandbox_dir": str(sandbox_dir),
            "_exec_sandbox_dirs": [str(d) for d in exec_sandbox_dirs],
            "error": None,
            "_terminated": _terminated,
            "_terminate_reason": _terminate_reason,
            "_internal_errors": _internal_errors,
        }

    except Exception as e:
        session = get_session()
        if session:
            session.log_event("prefab_react_error", {
                "iteration": iteration,
                "error": str(e),
            })
        return {
            "nodespec_yaml": nodespec_yaml,
            "run_sh": run_sh,
            "input_templates": input_templates,
            "available_images": available_images,
            "semantic_types": semantic_types,
            "sandbox_test_result": sandbox_test_result,
            "sandbox_test_passed": sandbox_test_passed,
            "_sandbox_dir": str(sandbox_dir),
            "_exec_sandbox_dirs": [str(d) for d in exec_sandbox_dirs],
            "error": f"Formal ReAct Agent 生成失败: {e}",
            "_terminated": _terminated,
            "_terminate_reason": _terminate_reason,
            "_internal_errors": _internal_errors,
        }
