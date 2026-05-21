"""MF 工作流数据模型。

定义用户编写的 MF 格式工作流的 Pydantic 模型：
- :class:`MFNodeInstance` — 工作流中的节点实例
- :class:`MFConnection` — 节点间的连线
- :class:`QualityGateOverride` — 单个质量门控的策略覆盖
- :class:`MFWorkflow` — 完整的 MF 工作流定义
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from nodes.schemas.io import GateDefault


# ── 临时节点辅助模型 ──────────────────────────────────────────────────────────


class EphemeralPorts(BaseModel):
    """临时节点的端口声明集合。

    使用整数计数声明端口数量，端口自动命名为 I1, I2, ... / O1, O2, ...。
    不再需要手动指定 type category（统一使用 software_data_package）。
    """

    inputs: int = Field(default=0, ge=0, description="输入端口数量，自动命名为 I1, I2, ...")
    outputs: int = Field(default=0, ge=0, description="输出端口数量，自动命名为 O1, O2, ...")


class EphemeralOnboardInput(BaseModel):
    """临时节点的可选 onboard 参数。"""

    name: str
    kind: str = "string"
    default: Any = ""


class ParallelSweep(BaseModel):
    """并行扫描参数声明。"""

    values: list[Any] = Field(
        ...,
        min_length=1,
        description="扫描值列表，编译为 Argo withParam JSON array。",
    )


class MFNodeInstance(BaseModel):
    """工作流中的一个节点实例。

    节点解析优先级：``node`` → ``nodespec_path`` → ``inline_nodespec``。
    三选一，不得同时指定多个。

    当 ``ephemeral=True`` 时，上述三选一约束解除，
    改为使用 ``ports`` + ``description`` 声明临时节点。
    当 ``prefab=True`` 时同理（与 ephemeral 互斥）。
    """

    id: str = Field(
        ...,
        description="节点实例 ID，在工作流内唯一。",
    )
    node: Optional[str] = Field(
        default=None,
        description="节点名称（按名称从节点库中查找）。",
    )
    nodespec_path: Optional[str] = Field(
        default=None,
        description="节点规格文件路径（相对于项目根目录）。",
    )
    inline_nodespec: Optional[dict[str, Any]] = Field(
        default=None,
        description="内联节点规格定义（仅开发/测试用）。",
    )
    onboard_params: dict[str, Any] = Field(
        default_factory=dict,
        description="On-board 参数值。",
    )

    # ── 生成类节点字段 ───────────────────────────────────────────────────
    ephemeral: bool = Field(
        default=False,
        description="是否为临时节点（ephemeral）。True 时不需要 node/nodespec_path/inline_nodespec。",
    )
    prefab: bool = Field(
        default=False,
        description="是否为预制节点（prefab）。True 时不需要 node/nodespec_path/inline_nodespec。与 ephemeral 互斥。",
    )
    description: str = Field(
        default="",
        description="生成类节点的功能描述（Agent 据此生成脚本）。",
    )
    ports: Optional[EphemeralPorts] = Field(
        default=None,
        description="生成类节点的端口声明。ephemeral=True 或 prefab=True 时必填。",
    )
    onboard_inputs: list[EphemeralOnboardInput] = Field(
        default_factory=list,
        description="生成类节点的可选 onboard 参数。",
    )
    parallel_sweep: Optional[ParallelSweep] = Field(
        default=None,
        description="并行扫描声明。设置后节点将使用 Argo withParam 扇出执行。不可用于 ephemeral 或 prefab 节点。",
    )
    fan_in: bool = Field(
        default=False,
        description="显式标记此节点为 fan-in 收集点，不参与 sweep 传播。",
    )
    pregenerate: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Prefab -1 循环预生成信息。仅包含 stream_inputs / stream_outputs 端口名列表，"
            "供编译器确定 wrapper 端口映射。完整 nodespec 在磁盘 tmp/<node_id>/nodespec.yaml。"
        ),
    )

    @model_validator(mode="after")
    def _check_node_source(self) -> MFNodeInstance:
        """确保 node / nodespec_path / inline_nodespec 三选一（或 ephemeral / prefab）。"""
        # ephemeral 和 prefab 互斥
        if self.ephemeral and self.prefab:
            raise ValueError("ephemeral 和 prefab 互斥，不可同时为 True")

        if self.ephemeral or self.prefab:
            # 生成类节点模式：不需要传统节点源，但需要 ports
            label = "ephemeral" if self.ephemeral else "prefab"
            if self.ports is None:
                raise ValueError(
                    f"{label} 节点 ({label}=True) 必须提供 ports 声明"
                )
            forbidden = []
            if self.node is not None:
                forbidden.append("node")
            if self.nodespec_path is not None:
                forbidden.append("nodespec_path")
            if self.inline_nodespec is not None:
                forbidden.append("inline_nodespec")
            if forbidden:
                raise ValueError(
                    f"{label} 节点不得指定 {', '.join(forbidden)}，"
                    f"请只使用 {label} + ports + description"
                )
            return self

        # 非生成类节点：三选一
        sources = [
            ("node", self.node),
            ("nodespec_path", self.nodespec_path),
            ("inline_nodespec", self.inline_nodespec),
        ]
        provided = [name for name, val in sources if val is not None]
        if len(provided) == 0:
            raise ValueError(
                "必须提供 node, nodespec_path 或 inline_nodespec 之一"
            )
        if len(provided) > 1:
            raise ValueError(
                f"node, nodespec_path, inline_nodespec 只能三选一，"
                f"当前同时指定了: {', '.join(provided)}"
            )
        return self

    def get_generation_description(self) -> str:
        """获取用于脚本生成的 description。

        生成类节点（ephemeral / prefab）：从 onboard_params.description 读取（Agent 据此生成）。
        正式节点：fallback 到顶层 description 字段。
        """
        if self.ephemeral or self.prefab:
            return self.onboard_params.get("description", "")
        return self.onboard_params.get("description", "") or self.description

    @model_validator(mode="after")
    def _check_sweep_generated(self) -> MFNodeInstance:
        """parallel_sweep 不可与生成类节点（ephemeral / prefab）同时使用。"""
        if self.parallel_sweep is not None and (self.ephemeral or self.prefab):
            label = "ephemeral" if self.ephemeral else "prefab"
            raise ValueError(
                f"生成类节点 ({label}=True) 不支持 parallel_sweep"
            )
        return self


class MFConnection(BaseModel):
    """节点间的一条连线。

    格式：``node_id.port_name``
    """

    from_: str = Field(
        ...,
        alias="from",
        description="源端口，格式 'node_id.port_name'。",
    )
    to: str = Field(
        ...,
        description="目标端口，格式 'node_id.port_name'。",
    )

    model_config = {"populate_by_name": True}

    @property
    def source_node_id(self) -> str:
        """源节点 ID。"""
        return self.from_.split(".", 1)[0]

    @property
    def source_port_name(self) -> str:
        """源端口名称。"""
        return self.from_.split(".", 1)[1]

    @property
    def target_node_id(self) -> str:
        """目标节点 ID。"""
        return self.to.split(".", 1)[0]

    @property
    def target_port_name(self) -> str:
        """目标端口名称。"""
        return self.to.split(".", 1)[1]


class QualityGateOverride(BaseModel):
    """单个质量门控的策略覆盖。

    允许工作流级别对特定节点的 quality gate 行为进行 override。
    """

    node_id: str = Field(
        ...,
        description="目标节点实例 ID。",
    )
    gate_name: str = Field(
        ...,
        description="Gate 名称（onboard_output.name，quality_gate=True 的那个）。",
    )
    action: GateDefault = Field(
        ...,
        description="覆盖的策略：must_pass / warn / ignore。",
    )


class MFWorkflow(BaseModel):
    """MF 格式的完整工作流定义。

    用户只需选节点 + 填参数 + 连线，不碰容器。
    """

    mf_version: str = Field(
        default="1.0",
        description="MF 工作流格式版本。",
    )
    name: str = Field(
        ...,
        description="工作流名称。",
    )
    description: str = Field(
        default="",
        description="工作流描述。",
    )
    namespace: str = Field(
        default="",
        description="Kubernetes 命名空间。",
    )
    global_params: dict[str, Any] = Field(
        default_factory=dict,
        description="全局参数。",
    )
    nodes: list[MFNodeInstance] = Field(
        ...,
        min_length=1,
        description="节点实例列表。",
    )
    connections: list[MFConnection] = Field(
        default_factory=list,
        description="节点间连线列表。",
    )
    quality_policy: list[QualityGateOverride] = Field(
        default_factory=list,
        description=(
            "Quality Gate 策略覆盖列表。"
            "未在此列表中的 Gate 使用节点 NodeSpec 中定义的 gate_default。"
        ),
    )

    @model_validator(mode="after")
    def _validate_unique_node_ids(self) -> MFWorkflow:
        """确保节点 ID 在工作流内唯一。"""
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ValueError(f"节点 ID 重复: {node.id!r}")
            seen.add(node.id)
        return self
