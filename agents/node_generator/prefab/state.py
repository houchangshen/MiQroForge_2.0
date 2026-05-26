"""agents/node_generator/prefab/state.py — Prefab 模式状态定义。

PrefabGenState 仅包含预制菜节点生成所需的字段，
不包含 ephemeral 模式的 script/exec_stdout/exec_stderr 等。
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict

from agents.schemas import NodeGenRequest, NodeGenResult, EvaluationResult


class PrefabGenState(TypedDict, total=False):
    """Prefab Node Generator 的 LangGraph 状态。"""

    # 输入
    request: NodeGenRequest

    # 中间状态
    reference_nodes: list[dict[str, Any]]   # few-shot 参考节点
    available_images: list[dict[str, Any]]  # 可用 Docker 镜像
    semantic_types: dict[str, Any]          # 语义类型注册表

    # 生成状态
    nodespec_yaml: str
    run_sh: str
    input_templates: dict[str, str]         # 文件名 → 内容

    # Prefab 模式 ReAct Agent
    software_manual_dir: str              # docs/software_manuals/<software>/
    generation_memory: list[dict]         # 从 JSONL 加载的相关经验
    sandbox_test_result: dict             # 沙箱测试结果 {stdout, stderr, return_code, ...}
    sandbox_test_passed: bool             # 沙箱测试是否通过
    sandbox_call_count: int               # 沙箱调用次数
    compressed_summary: str               # 上下文压缩后的摘要
    tool_call_count: int                  # ReAct 循环中的工具调用计数
    messages_history: list                # ReAct 循环的完整消息历史

    # Generator-Evaluator
    evaluation: Optional[EvaluationResult]
    iteration: int

    # 输出
    result: Optional[NodeGenResult]

    # 错误
    error: Optional[str]

    # 控制标志（以 _ 开头的为 API 端点注入的控制参数）
    _recorded_lesson: str                 # Agent 通过 record_lesson 工具记录的教训（≤200 字符）
    _sandbox_enabled: bool                # 是否启用沙箱工具（设计时 False，运行时 True）
    _input_data: dict[str, str]           # 真实上游输入数据
    _input_ports: list[str]               # Argo DAG 输入端口名（供 port_mapping 和 prompt 使用）
    _output_ports: list[str]              # Argo DAG 输出端口名（供 port_mapping 和 prompt 使用）
    _project_id: str                      # 项目 ID（用于 workspace 和 sandbox 定位）
    _projects_root: str                   # 用户 projects 目录根路径（多用户场景下替代 userdata/projects）
    _run_name: str                        # 运行名称（用于 sandbox 定位）
    _sandbox_dir: str                     # 沙箱持久化目录（API 端点读取输出文件）
