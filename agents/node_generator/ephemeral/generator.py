"""agents/node_generator/ephemeral/generator.py — 临时节点生成。

ReAct Agent 内循环，使用 sandbox_execute + pip_install 工具生成并执行脚本。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from agents.llm_config import LLMConfig
from agents.common.prompt_loader import load_prompt
from agents.common.session_logger import get_session
from agents.node_generator.ephemeral.state import EphemeralGenState
from agents.node_generator.ephemeral.sandbox import (
    execute_script_sandbox,
    make_sandbox_tool,
    make_pip_install_tool,
)
from agents.node_generator.shared.sandbox_base import create_sandbox_dir, save_pip_history


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


def _load_ephemeral_settings() -> dict[str, Any]:
    """从 userdata/settings.yaml 加载 ephemeral 运行时配置。"""
    from pathlib import Path
    import yaml
    settings_path = Path(__file__).parent.parent.parent.parent / "userdata" / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("ephemeral", {})
    except Exception:
        return {}


def generate_ephemeral_node(state: EphemeralGenState) -> dict[str, Any]:
    """临时节点生成节点 — LLM Agent 循环，把 sandbox 当工具用。"""
    request = state.get("request")
    if not request:
        return {"error": "缺少 NodeGenRequest 输入"}

    iteration = state.get("iteration", 0)

    ephemeral_cfg = _load_ephemeral_settings()
    max_inner_rounds = ephemeral_cfg.get("max_inner_rounds", 3)

    system_content = load_prompt("node_generator/prompts/ephemeral/nodegen_ephemeral_system.jinja2")

    input_data = state.get("_input_data") or {}
    input_data_preview: dict[str, str] = {}
    for k, v in input_data.items():
        input_data_preview[k] = v[:500] if len(v) > 500 else v

    prev_script = state.get("script", "")
    prev_stderr = state.get("exec_stderr", "")
    vision_feedback = state.get("vision_feedback", [])

    has_execution_history = bool(prev_script and (prev_stderr or vision_feedback))

    user_content = load_prompt(
        "node_generator/prompts/ephemeral/nodegen_ephemeral_generate.jinja2",
        request=request.model_dump(),
        iteration=iteration,
        prev_script=prev_script,
        prev_stderr=prev_stderr,
        vision_feedback=vision_feedback,
        input_data=input_data_preview,
        has_execution_history=has_execution_history,
    )

    context = request.context or {}
    sweep_ctx = context.get("sweep_context")
    env_overrides: dict[str, str] = {}

    if sweep_ctx:
        env_overrides["_sweep_keys"] = json.dumps(sweep_ctx.get("sweep_values", []))
    elif "_sweep_keys" in input_data:
        env_overrides["_sweep_keys"] = input_data["_sweep_keys"]
        try:
            sweep_values = json.loads(input_data["_sweep_keys"])
            sweep_ctx = {"sweep_values": sweep_values}
        except (json.JSONDecodeError, KeyError):
            pass

    sandbox_dir = create_sandbox_dir(
        project_id=state.get("_project_id"),
        run_name=state.get("_run_name"),
        projects_dir=state.get("_projects_dir"),
    )
    sandbox_tool = make_sandbox_tool(input_data, env_overrides, sandbox_dir=sandbox_dir)
    pip_tool, pip_history = make_pip_install_tool()

    llm = LLMConfig.get_chat_model(purpose="node_generator", temperature=0.1)
    llm_with_tools = llm.bind_tools([sandbox_tool, pip_tool])

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

    script = ""
    exec_stdout = ""
    exec_stderr = ""
    exec_return_code = -1
    generated_files: list[str] = []
    image_files: list[str] = []
    sandbox_exec_count = 0
    max_tool_calls = max_inner_rounds * 2
    last_tool_calls: list[str] = []

    try:
        for _ in range(max_tool_calls):
            response = llm_with_tools.invoke(messages)

            session = get_session()
            if session:
                tc_names = [tc.get("name", "") for tc in (response.tool_calls or [])]
                last_tool_calls = tc_names
                session.log_event("generate_agent_step", {
                    "iteration": iteration,
                    "tool_calls": tc_names,
                    "response_preview": response.content[:200] if response.content else "",
                })

            if not response.tool_calls:
                messages.append(response)
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if tc.get("name") == "sandbox_execute":
                                script = tc.get("args", {}).get("script", "")
                                break
                        if script:
                            break
                if not script:
                    script = _extract_script(response.content)
                break

            messages.append(response)

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "")

                if tool_name == "sandbox_execute":
                    if sandbox_exec_count >= max_inner_rounds:
                        tool_result = json.dumps({
                            "error": f"Maximum sandbox executions ({max_inner_rounds}) reached.",
                            "return_code": -1,
                        })
                    else:
                        sandbox_exec_count += 1
                        result = sandbox_tool.invoke(tool_args)
                        tool_result = json.dumps(result)

                        result_dict = result if isinstance(result, dict) else json.loads(result)
                        exec_stdout = result_dict.get("stdout", "")
                        exec_stderr = result_dict.get("stderr", "")
                        exec_return_code = result_dict.get("return_code", -1)
                        image_files = result_dict.get("image_paths", result_dict.get("image_files", []))

                    session = get_session()
                    if session:
                        script_preview = tool_args.get("script", "")[:500]
                        result_preview = tool_result[:800]
                        session.log_event("sandbox_call", {
                            "iteration": iteration,
                            "sandbox_exec_count": sandbox_exec_count,
                            "script_preview": script_preview,
                            "result_preview": result_preview,
                            "return_code": exec_return_code,
                        })

                elif tool_name == "pip_install":
                    result = pip_tool.invoke(tool_args)
                    tool_result = str(result)

                    session = get_session()
                    if session:
                        session.log_event("pip_install_call", {
                            "iteration": iteration,
                            "package": tool_args.get("package", ""),
                            "result_preview": tool_result[:500],
                        })
                else:
                    tool_result = f"Unknown tool: {tool_name}"

                messages.append(ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_id,
                ))

        else:
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc.get("name") == "sandbox_execute":
                            script = tc.get("args", {}).get("script", "")
                            break
                    if script:
                        break
                elif isinstance(msg, AIMessage) and msg.content:
                    script = _extract_script(msg.content)
                    break

        save_pip_history(
            pip_history,
            description=request.description or "",
            userdata_root=None,
        )

        session = get_session()
        if session:
            session.log_llm_call(
                "generate_agent_final", messages, script,
                iteration=iteration,
                sandbox_exec_count=sandbox_exec_count,
                exec_return_code=exec_return_code,
            )

        return {
            "script": script,
            "exec_stdout": exec_stdout,
            "exec_stderr": exec_stderr,
            "exec_return_code": exec_return_code,
            "generated_files": generated_files,
            "image_files": image_files,
            "_sandbox_dir": str(sandbox_dir),
            "error": None,
        }

    except Exception as e:
        session = get_session()
        if session:
            session.log_event("generate_agent_error", {
                "iteration": iteration,
                "error": str(e),
            })
        return {
            "script": script,
            "exec_stdout": exec_stdout,
            "exec_stderr": exec_stderr or str(e),
            "exec_return_code": exec_return_code,
            "generated_files": generated_files,
            "image_files": image_files,
            "_sandbox_dir": str(sandbox_dir),
            "error": f"Ephemeral Agent 生成失败: {e}",
        }
