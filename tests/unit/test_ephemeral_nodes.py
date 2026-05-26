"""临时节点（Ephemeral Nodes）单元测试。

覆盖：
- MFNodeInstance ephemeral 模型校验
- EphemeralPorts（整数计数）校验
- Validator 虚拟 NodeSpec 构建
- Evaluator 临时节点检查
- Compiler 临时节点 wrapper 脚本生成
- Sandbox 服务端执行
"""

from __future__ import annotations

import pytest
import shutil
import yaml

from nodes.schemas import NodeSpec
from workflows.pipeline.models import (
    EphemeralOnboardInput,
    EphemeralPorts,
    MFConnection,
    MFNodeInstance,
    MFWorkflow,
)
from workflows.pipeline.validator import validate_workflow, _build_ephemeral_nodespec
from workflows.pipeline.compiler import (
    compile_to_argo,
    _build_ephemeral_template,
    _build_ephemeral_wrapper_script,
)
from nodes.schemas.base_image import BaseImageRegistry, BaseImageSpec


# ═══════════════════════════════════════════════════════════════════════════
# 模型校验测试
# ═══════════════════════════════════════════════════════════════════════════


class TestEphemeralPorts:
    """EphemeralPorts 模型测试（整数计数格式）。"""

    def test_empty_ports(self):
        p = EphemeralPorts()
        assert p.inputs == 0
        assert p.outputs == 0

    def test_with_counts(self):
        p = EphemeralPorts(inputs=2, outputs=1)
        assert p.inputs == 2
        assert p.outputs == 1

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            EphemeralPorts(inputs=-1)

    def test_zero_valid(self):
        p = EphemeralPorts(inputs=0, outputs=0)
        assert p.inputs == 0
        assert p.outputs == 0


class TestMFNodeInstanceEphemeral:
    """MFNodeInstance 临时节点模式测试。"""

    def test_ephemeral_valid(self):
        inst = MFNodeInstance(
            id="extract-energy",
            ephemeral=True,
            description="提取能量",
            ports=EphemeralPorts(inputs=1, outputs=1),
        )
        assert inst.ephemeral is True
        assert inst.description == "提取能量"
        assert inst.ports.inputs == 1
        assert inst.ports.outputs == 1

    def test_ephemeral_requires_ports(self):
        with pytest.raises(ValueError, match="必须提供 ports"):
            MFNodeInstance(
                id="test",
                ephemeral=True,
                description="test",
            )

    def test_ephemeral_forbids_node(self):
        with pytest.raises(ValueError, match="ephemeral 节点不得指定"):
            MFNodeInstance(
                id="test",
                ephemeral=True,
                node="some-node",
                ports=EphemeralPorts(inputs=1),
            )

    def test_ephemeral_forbids_nodespec_path(self):
        with pytest.raises(ValueError, match="ephemeral 节点不得指定"):
            MFNodeInstance(
                id="test",
                ephemeral=True,
                nodespec_path="nodes/test/nodespec.yaml",
                ports=EphemeralPorts(inputs=1),
            )

    def test_ephemeral_with_onboard_inputs(self):
        inst = MFNodeInstance(
            id="test",
            ephemeral=True,
            description="test",
            ports=EphemeralPorts(inputs=1),
            onboard_inputs=[
                EphemeralOnboardInput(name="threshold", kind="number", default=0.001),
            ],
        )
        assert len(inst.onboard_inputs) == 1
        assert inst.onboard_inputs[0].name == "threshold"

    def test_non_ephemeral_still_requires_source(self):
        with pytest.raises(ValueError, match="必须提供"):
            MFNodeInstance(id="test", ephemeral=False)


# ═══════════════════════════════════════════════════════════════════════════
# Validator 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildEphemeralNodespec:
    """_build_ephemeral_nodespec 函数测试。"""

    def test_builds_valid_nodespec(self):
        inst = MFNodeInstance(
            id="ext",
            ephemeral=True,
            description="提取能量",
            ports=EphemeralPorts(inputs=1, outputs=1),
        )
        spec = _build_ephemeral_nodespec(inst)
        assert isinstance(spec, NodeSpec)
        assert spec.metadata.name == "ext"
        assert len(spec.stream_inputs) == 1
        assert len(spec.stream_outputs) == 1
        assert spec.stream_inputs[0].name == "I1"
        assert spec.stream_outputs[0].name == "O1"

    def test_auto_naming_multiple_ports(self):
        """多端口自动命名为 I1/I2/... 和 O1/O2/..."""
        inst = MFNodeInstance(
            id="multi",
            ephemeral=True,
            description="多端口测试",
            ports=EphemeralPorts(inputs=3, outputs=2),
        )
        spec = _build_ephemeral_nodespec(inst)
        input_names = [p.name for p in spec.stream_inputs]
        output_names = [p.name for p in spec.stream_outputs]
        assert input_names == ["I1", "I2", "I3"]
        assert output_names == ["O1", "O2"]

    def test_default_type_is_software_data_package(self):
        """端口类型统一为 software_data_package。"""
        inst = MFNodeInstance(
            id="ext",
            ephemeral=True,
            description="test",
            ports=EphemeralPorts(inputs=1, outputs=1),
        )
        spec = _build_ephemeral_nodespec(inst)
        from nodes.schemas.io import StreamIOCategory
        for port in spec.stream_inputs + spec.stream_outputs:
            assert port.io_type.category == StreamIOCategory.SOFTWARE_DATA_PACKAGE

    def test_nodespec_with_onboard_inputs(self):
        inst = MFNodeInstance(
            id="ext",
            ephemeral=True,
            description="test",
            ports=EphemeralPorts(outputs=1),
            onboard_inputs=[
                EphemeralOnboardInput(name="unit", kind="string", default="Ha"),
            ],
        )
        spec = _build_ephemeral_nodespec(inst)
        assert len(spec.onboard_inputs) == 1
        assert spec.onboard_inputs[0].name == "unit"
        assert spec.onboard_inputs[0].default == "Ha"


class TestValidateWorkflowEphemeral:
    """validate_workflow 中临时节点相关测试。"""

    def test_validate_with_ephemeral(self):
        """含临时节点的完整工作流校验。"""
        wf = MFWorkflow(
            name="test-ephemeral",
            nodes=[
                MFNodeInstance(
                    id="geom-input",
                    nodespec_path="nodes/chemistry/preprocessing/geometry-file-input/nodespec.yaml",
                ),
                MFNodeInstance(
                    id="extract-energy",
                    ephemeral=True,
                    description="提取总能量",
                    ports=EphemeralPorts(inputs=1, outputs=1),
                ),
            ],
            connections=[
                MFConnection(
                    **{"from": "geom-input.xyz_geometry", "to": "extract-energy.I1"}
                ),
            ],
        )
        report = validate_workflow(wf)
        # 临时节点应被解析为虚拟 NodeSpec
        assert "extract-energy" in report.resolved_nodes
        assert isinstance(report.resolved_nodes["extract-energy"], NodeSpec)

    def test_ephemeral_missing_connection_rejected(self):
        """临时节点的未连接必填输入应被拒绝。"""
        wf = MFWorkflow(
            name="test-missing-conn",
            nodes=[
                MFNodeInstance(
                    id="src",
                    nodespec_path="nodes/chemistry/preprocessing/geometry-file-input/nodespec.yaml",
                ),
                MFNodeInstance(
                    id="eph",
                    ephemeral=True,
                    description="需要输入",
                    ports=EphemeralPorts(inputs=1, outputs=1),
                ),
            ],
            connections=[],  # 没有连线
        )
        report = validate_workflow(wf)
        assert not report.valid
        errors_text = " ".join(e.message for e in report.errors)
        assert "I1" in errors_text


# ═══════════════════════════════════════════════════════════════════════════
# Evaluator 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestEphemeralEvaluator:
    """临时节点 evaluator 程序化检查测试。"""

    def test_syntax_check_passes(self):
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral
        from agents.schemas import NodeGenRequest

        request = NodeGenRequest(
            semantic_type="ephemeral",
            description="test",
            node_mode="ephemeral",
            ports={"inputs": 1, "outputs": 1},
        )
        state = {
            "request": request,
            "script": "import os\ndata = open('/mf/input/I1').read()\nopen('/mf/output/O1', 'w').write(data)",
            "iteration": 0,
        }
        issues = _programmatic_check_ephemeral(state)
        assert issues == []

    def test_syntax_check_catches_error(self):
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral
        from agents.schemas import NodeGenRequest

        request = NodeGenRequest(
            semantic_type="ephemeral",
            description="test",
            node_mode="ephemeral",
        )
        state = {
            "request": request,
            "script": "def foo(\n  broken syntax",
            "iteration": 0,
        }
        issues = _programmatic_check_ephemeral(state)
        assert any("语法错误" in i for i in issues)

    def test_empty_script_rejected(self):
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral

        state = {"script": "", "request": None}
        issues = _programmatic_check_ephemeral(state)
        assert "生成的脚本内容为空" in issues

    def test_missing_output_path(self):
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral
        from agents.schemas import NodeGenRequest

        request = NodeGenRequest(
            semantic_type="ephemeral",
            description="test",
            node_mode="ephemeral",
            ports={"inputs": 0, "outputs": 1},
        )
        state = {
            "request": request,
            "script": "print('hello')",
            "iteration": 0,
        }
        issues = _programmatic_check_ephemeral(state)
        assert any("O1" in i for i in issues)

    def test_multi_port_check(self):
        """多端口检查：验证所有 I/O 端口都被检查。"""
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral
        from agents.schemas import NodeGenRequest

        request = NodeGenRequest(
            semantic_type="ephemeral",
            description="test",
            node_mode="ephemeral",
            ports={"inputs": 2, "outputs": 1},
        )
        state = {
            "request": request,
            "script": "open('/mf/input/I1').read()\nopen('/mf/output/O1', 'w').write('x')",
            "iteration": 0,
        }
        issues = _programmatic_check_ephemeral(state)
        # I2 is declared but not used in script
        assert any("I2" in i for i in issues)

    def test_script_field_also_checked(self):
        """'script' 字段也应被检查（新增 ephemeral 路径使用 script 而非 run_sh）。"""
        from agents.node_generator.ephemeral.evaluator import _programmatic_check_ephemeral
        from agents.schemas import NodeGenRequest

        request = NodeGenRequest(
            semantic_type="ephemeral",
            description="test",
            node_mode="ephemeral",
            ports={"inputs": 1, "outputs": 1},
        )
        state = {
            "request": request,
            "script": "import os\ndata = open('/mf/input/I1').read()\nopen('/mf/output/O1', 'w').write(data)",
            "iteration": 0,
        }
        issues = _programmatic_check_ephemeral(state)
        assert issues == []


# ═══════════════════════════════════════════════════════════════════════════
# Compiler 测试 — wrapper 脚本模式
# ═══════════════════════════════════════════════════════════════════════════


class TestEphemeralCompiler:
    """临时节点编译测试（wrapper 脚本模式）。"""

    # 最小注册表（测试用，不含真实镜像）
    _empty_registry = BaseImageRegistry(images=[])

    def test_build_ephemeral_template(self):
        spec = _build_ephemeral_nodespec(
            MFNodeInstance(
                id="ext",
                ephemeral=True,
                description="test",
                ports=EphemeralPorts(inputs=1, outputs=1),
            )
        )
        tmpl = _build_ephemeral_template(
            template_name="mf-ext",
            spec=spec,
            script_source="print('hello')",
            registry=self._empty_registry,
            input_params=[{"name": "I1"}],
            output_params=[{
                "name": "O1",
                "valueFrom": {"path": "/mf/output/O1"},
            }],
        )
        assert tmpl["name"] == "mf-ext"
        assert tmpl["script"]["image"] == "python:3.11-slim"
        assert tmpl["script"]["command"] == ["python"]
        # 检查 preamble 被拼接到 source 中
        source = tmpl["script"]["source"]
        assert "import os, pathlib as _pl" in source
        assert "_pl.Path('/mf/input').mkdir" in source
        assert "_pl.Path('/mf/input/I1').write_text" in source
        assert "print('hello')" in source
        # 检查环境变量注入
        env_names = {e["name"] for e in tmpl["script"]["env"]}
        assert "MF_OUTPUT_DIR" in env_names
        assert "MF_WORKSPACE_DIR" in env_names
        assert "MF_API_URL" in env_names
        assert "I1" in env_names
        # 检查 workspace volume
        vol_names = {v["name"] for v in tmpl["volumes"]}
        assert "workspace" in vol_names

    def test_build_ephemeral_template_with_mirror(self):
        spec = _build_ephemeral_nodespec(
            MFNodeInstance(
                id="ext",
                ephemeral=True,
                description="test",
                ports=EphemeralPorts(outputs=1),
            )
        )
        tmpl = _build_ephemeral_template(
            template_name="mf-ext",
            spec=spec,
            script_source="x=1",
            registry=self._empty_registry,
            docker_hub_mirror="docker.m.daocloud.io",
            input_params=[],
            output_params=[],
        )
        assert tmpl["script"]["image"] == "docker.m.daocloud.io/library/python:3.11-slim"

    def test_ephemeral_template_writes_input_files(self):
        """关键 bug 修复验证：preamble 将 env var 写入 /mf/input/ 文件。"""
        spec = _build_ephemeral_nodespec(
            MFNodeInstance(
                id="ext",
                ephemeral=True,
                description="test",
                ports=EphemeralPorts(inputs=2, outputs=1),
            )
        )
        tmpl = _build_ephemeral_template(
            template_name="mf-ext",
            spec=spec,
            script_source="pass",
            registry=self._empty_registry,
            input_params=[{"name": "I1"}, {"name": "I2"}],
            output_params=[],
        )
        source = tmpl["script"]["source"]
        # 每个 input 都应有对应的文件写入逻辑
        assert "_pl.Path('/mf/input/I1').write_text(os.environ['I1'])" in source
        assert "_pl.Path('/mf/input/I2').write_text(os.environ['I2'])" in source
        # preamble 在 script source 之前
        assert source.index("import os") < source.index("pass")

    def test_wrapper_script_generation(self):
        """wrapper 脚本应包含 Agent API 调用逻辑。"""
        wf = MFWorkflow(
            name="test-wrapper",
            nodes=[
                MFNodeInstance(
                    id="src",
                    nodespec_path="nodes/chemistry/preprocessing/geometry-file-input/nodespec.yaml",
                ),
                MFNodeInstance(
                    id="plot",
                    ephemeral=True,
                    description="绘制势能曲线",
                    ports=EphemeralPorts(inputs=1, outputs=1),
                ),
            ],
            connections=[
                MFConnection(**{"from": "src.xyz_geometry", "to": "plot.I1"}),
            ],
        )
        report = validate_workflow(wf)
        wrapper = _build_ephemeral_wrapper_script(
            node_inst=wf.nodes[1],
            workflow=wf,
            resolved_nodes=report.resolved_nodes,
        )
        # wrapper 应包含 API 调用
        assert "/api/v1/agents/ephemeral" in wrapper
        assert "requests.post" in wrapper
        assert "MF_API_URL" in wrapper
        # wrapper 应包含执行逻辑
        assert "subprocess.run" in wrapper
        # wrapper 应写图片清单
        assert "_mf_images" in wrapper

    def test_compile_ephemeral_end_to_end(self):
        """端到端编译含临时节点的工作流（wrapper 模式，无需 mock Agent）。"""
        wf = MFWorkflow(
            name="test-compile",
            nodes=[
                MFNodeInstance(
                    id="geom-input",
                    nodespec_path=(
                        "nodes/chemistry/preprocessing/"
                        "geometry-file-input/nodespec.yaml"
                    ),
                ),
                MFNodeInstance(
                    id="extract",
                    ephemeral=True,
                    description="提取能量",
                    ports=EphemeralPorts(inputs=1, outputs=1),
                ),
            ],
            connections=[
                MFConnection(
                    **{"from": "geom-input.xyz_geometry", "to": "extract.I1"}
                ),
            ],
        )

        # 构建 resolved_nodes 手动（跳过 validator 的严格连接校验）
        src_report = validate_workflow(MFWorkflow(
            name="src-only",
            nodes=[
                MFNodeInstance(
                    id="geom-input",
                    nodespec_path=(
                        "nodes/chemistry/preprocessing/"
                        "geometry-file-input/nodespec.yaml"
                    ),
                ),
            ],
        ))
        eph_spec = _build_ephemeral_nodespec(
            MFNodeInstance(
                id="extract",
                ephemeral=True,
                description="提取能量",
                ports=EphemeralPorts(inputs=1, outputs=1),
            )
        )
        resolved = dict(src_report.resolved_nodes)
        resolved["extract"] = eph_spec

        # 无需 mock — wrapper 模式下编译器不再调用 Agent
        argo = compile_to_argo(wf, resolved)

        # 检查生成的 templates
        template_names = [t["name"] for t in argo["spec"]["templates"]]
        assert "mf-extract" in template_names

        # 找到临时节点的 template
        extract_tmpl = next(
            t for t in argo["spec"]["templates"]
            if t["name"] == "mf-extract"
        )
        assert "script" in extract_tmpl
        # source 应包含 wrapper 脚本逻辑
        source = extract_tmpl["script"]["source"]
        assert "MF_API_URL" in source
        assert "/api/v1/agents/ephemeral" in source
        assert extract_tmpl["script"]["image"].endswith("ephemeral-py:3.11") or \
               extract_tmpl["script"]["image"] == "python:3.11-slim"

        # 检查 DAG task
        dag_template = next(
            t for t in argo["spec"]["templates"]
            if t["name"] == "mf-dag"
        )
        dag_tasks = dag_template["dag"]["tasks"]
        extract_task = next(t for t in dag_tasks if t["name"] == "extract")
        assert extract_task["template"] == "mf-extract"
        # 应有依赖 geom-input
        assert "geom-input" in extract_task["depends"]

        # 检查输入参数传递
        params = extract_task["arguments"]["parameters"]
        param_names = {p["name"] for p in params}
        assert "I1" in param_names


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestSandbox:
    """服务端执行沙箱测试。"""

    @staticmethod
    def _make_sandbox_dir() -> "Path":
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp(prefix="mf_test_sandbox_"))
        (d / "input").mkdir(parents=True, exist_ok=True)
        (d / "output").mkdir(parents=True, exist_ok=True)
        (d / "workspace").mkdir(parents=True, exist_ok=True)
        return d

    def test_basic_execution(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script="print('hello world')",
                timeout=10,
                sandbox_dir=sandbox_dir,
            )
            assert result["return_code"] == 0
            assert "hello world" in result["stdout"]
            assert not result["timed_out"]
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    def test_with_input_data(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script=(
                    "import os\n"
                    "data = open('/mf/input/I1').read()\n"
                    "open('/mf/output/O1', 'w').write(data.upper())\n"
                ),
                input_data={"I1": "hello"},
                timeout=10,
                sandbox_dir=sandbox_dir,
            )
            assert result["return_code"] == 0
            # 检查输出文件
            output_files = [f for f in result["generated_files"] if "O1" in f]
            assert len(output_files) == 1
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    def test_syntax_error(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script="def foo(\n  broken",
                timeout=10,
                sandbox_dir=sandbox_dir,
            )
            assert result["return_code"] != 0
            assert "SyntaxError" in result["stderr"] or result["stderr"]
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    def test_timeout(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script="import time; time.sleep(100)",
                timeout=3,
                sandbox_dir=sandbox_dir,
            )
            assert result["timed_out"]
            assert result["return_code"] == -1
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    def test_image_detection(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script=(
                    "import matplotlib\n"
                    "matplotlib.use('Agg')\n"
                    "import matplotlib.pyplot as plt\n"
                    "plt.plot([1, 2, 3])\n"
                    "plt.savefig('/mf/workspace/test_plot.png')\n"
                    "plt.close()\n"
                ),
                timeout=30,
                sandbox_dir=sandbox_dir,
            )
            assert result["return_code"] == 0
            png_files = [f for f in result["image_files"] if f.endswith(".png")]
            assert len(png_files) == 1
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    def test_environment_variables(self):
        from agents.node_generator.ephemeral.sandbox import execute_script_sandbox

        sandbox_dir = self._make_sandbox_dir()
        try:
            result = execute_script_sandbox(
                script=(
                    "import os\n"
                    "print(os.environ.get('MF_INPUT_DIR', 'MISSING'))\n"
                    "print(os.environ.get('MF_OUTPUT_DIR', 'MISSING'))\n"
                    "print(os.environ.get('MF_WORKSPACE_DIR', 'MISSING'))\n"
                ),
                timeout=10,
                sandbox_dir=sandbox_dir,
            )
            assert result["return_code"] == 0
            assert "/mf/" in result["stdout"] or "MISSING" not in result["stdout"]
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
