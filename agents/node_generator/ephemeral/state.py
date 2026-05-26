"""agents/node_generator/ephemeral/state.py — 临时节点生成状态定义。"""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from agents.schemas import NodeGenRequest, NodeGenResult, EvaluationResult


class EphemeralGenState(TypedDict, total=False):
    """临时节点生成 Agent 的 LangGraph 状态。"""

    # 输入
    request: NodeGenRequest

    # 中间状态
    _input_data: dict[str, str]             # 真实输入数据 {port_name: content}
    _project_id: str                        # 项目 ID（用于 workspace 和 sandbox 定位）
    _projects_dir: str                      # 用户 projects 目录根路径（多用户场景下替代 userdata/projects）
    _run_name: str                          # 运行名称（用于 sandbox 定位）
    script: str                             # 生成的 Python 脚本
    exec_stdout: str                        # 执行 stdout
    exec_stderr: str                        # 执行 stderr
    exec_return_code: int                   # 执行返回码
    generated_files: list[str]              # 沙箱生成的文件列表
    image_files: list[str]                  # 检测到的图片文件列表
    vision_feedback: list[str]              # 视觉评估反馈
    _sandbox_dir: str                       # 沙箱持久化目录（evaluator 可读取图片）

    # Generator-Evaluator
    evaluation: Optional[EvaluationResult]
    iteration: int

    # 输出
    result: Optional[NodeGenResult]

    # 错误
    error: Optional[str]
