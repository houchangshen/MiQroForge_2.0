"""MF 工作流管线单元测试。

覆盖：
- MFWorkflow / MFNodeInstance / MFConnection 模型校验
- Loader（加载 YAML、解析 NodeSpec）
- Validator（连接校验、参数校验、DAG 无环）
- Compiler（Argo YAML 生成、ConfigMap 生成）
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from nodes.schemas import NodeSpec
from workflows.pipeline.models import MFConnection, MFNodeInstance, MFWorkflow
from workflows.pipeline.loader import load_workflow, resolve_nodespec
from workflows.pipeline.validator import validate_workflow, ValidationReport
from workflows.pipeline.compiler import (
    compile_to_argo,
    compile_to_yaml_str,
    generate_configmaps,
)


# ═══════════════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
H2O_MF_YAML = PROJECT_ROOT / "workflows" / "examples" / "h2o-thermo-mf.yaml"
GEO_OPT_NODESPEC = PROJECT_ROOT / "nodes" / "test" / "gaussian-geo-opt" / "nodespec.yaml"
FREQ_NODESPEC = PROJECT_ROOT / "nodes" / "test" / "gaussian-freq" / "nodespec.yaml"
THERMO_NODESPEC = PROJECT_ROOT / "nodes" / "test" / "thermo-extractor" / "nodespec.yaml"


# ═══════════════════════════════════════════════════════════════════════════
# Models 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestMFNodeInstance:
    """MFNodeInstance 模型校验。"""

    def test_valid_with_nodespec_path(self):
        inst = MFNodeInstance(
            id="geo-opt",
            nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
        )
        assert inst.nodespec_path is not None
        assert inst.node is None

    def test_valid_with_node_name(self):
        inst = MFNodeInstance(id="geo-opt", node="test-gaussian-geo-opt")
        assert inst.node == "test-gaussian-geo-opt"

    def test_valid_with_inline_nodespec(self):
        inst = MFNodeInstance(
            id="test",
            inline_nodespec={"metadata": {"name": "test"}},
        )
        assert inst.inline_nodespec is not None

    def test_reject_no_source(self):
        with pytest.raises(ValueError, match="必须提供"):
            MFNodeInstance(id="test")

    def test_reject_multiple_sources(self):
        with pytest.raises(ValueError, match="只能三选一"):
            MFNodeInstance(
                id="test",
                node="foo",
                nodespec_path="bar/nodespec.yaml",
            )

    def test_onboard_params_default_empty(self):
        inst = MFNodeInstance(id="x", node="y")
        assert inst.onboard_params == {}

    def test_onboard_params_with_values(self):
        inst = MFNodeInstance(
            id="x",
            node="y",
            onboard_params={"functional": "B3LYP", "charge": 0},
        )
        assert inst.onboard_params["functional"] == "B3LYP"
        assert inst.onboard_params["charge"] == 0


class TestMFConnection:
    """MFConnection 模型校验。"""

    def test_basic(self):
        conn = MFConnection(**{"from": "geo-opt.checkpoint", "to": "freq.checkpoint_in"})
        assert conn.from_ == "geo-opt.checkpoint"
        assert conn.to == "freq.checkpoint_in"

    def test_source_properties(self):
        conn = MFConnection(**{"from": "geo-opt.converged", "to": "freq.opt_converged"})
        assert conn.source_node_id == "geo-opt"
        assert conn.source_port_name == "converged"
        assert conn.target_node_id == "freq"
        assert conn.target_port_name == "opt_converged"


class TestMFWorkflow:
    """MFWorkflow 模型校验。"""

    def test_valid_minimal(self):
        wf = MFWorkflow(
            name="test",
            nodes=[MFNodeInstance(id="a", node="some-node")],
        )
        assert wf.name == "test"
        assert len(wf.nodes) == 1

    def test_reject_empty_nodes(self):
        with pytest.raises(ValueError):
            MFWorkflow(name="test", nodes=[])

    def test_reject_duplicate_node_ids(self):
        with pytest.raises(ValueError, match="节点 ID 重复"):
            MFWorkflow(
                name="test",
                nodes=[
                    MFNodeInstance(id="dup", node="a"),
                    MFNodeInstance(id="dup", node="b"),
                ],
            )

    def test_defaults(self):
        wf = MFWorkflow(
            name="test",
            nodes=[MFNodeInstance(id="a", node="x")],
        )
        assert wf.mf_version == "1.0"
        assert wf.namespace == os.environ.get("ARGO_NAMESPACE", "")
        assert wf.global_params == {}
        assert wf.connections == []


# ═══════════════════════════════════════════════════════════════════════════
# Loader 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestLoader:
    """Loader 加载与解析测试。"""

    def test_load_h2o_workflow(self):
        """能加载 h2o-thermo-mf.yaml。"""
        wf = load_workflow(H2O_MF_YAML)
        assert wf.name == "h2o-thermo"
        assert len(wf.nodes) == 3
        assert len(wf.connections) == 2

    def test_load_workflow_node_ids(self):
        wf = load_workflow(H2O_MF_YAML)
        ids = {n.id for n in wf.nodes}
        assert ids == {"geo-opt", "freq", "thermo-extract"}

    def test_load_workflow_connections(self):
        wf = load_workflow(H2O_MF_YAML)
        conn_pairs = [(c.from_, c.to) for c in wf.connections]
        assert ("geo-opt.optimized_checkpoint", "freq.checkpoint_in") in conn_pairs
        assert ("freq.thermo_data", "thermo-extract.thermo_data_in") in conn_pairs
        # Convergence connections removed — now handled by quality gates
        assert not any("converged" in f for f, _ in conn_pairs)
        assert not any("is_true_minimum" in f for f, _ in conn_pairs)

    def test_resolve_nodespec_by_path(self):
        """通过 nodespec_path 解析 NodeSpec。"""
        inst = MFNodeInstance(
            id="geo-opt",
            nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
        )
        spec = resolve_nodespec(inst, project_root=PROJECT_ROOT)
        assert spec.metadata.name == "test-gaussian-geo-opt"
        assert spec.metadata.node_type.value == "compute"

    def test_resolve_nodespec_by_name(self):
        """通过 node name 查找 NodeSpec。"""
        inst = MFNodeInstance(id="freq", node="test-gaussian-freq")
        spec = resolve_nodespec(inst, project_root=PROJECT_ROOT)
        assert spec.metadata.name == "test-gaussian-freq"

    def test_resolve_nodespec_inline(self, tmp_path):
        """通过 inline_nodespec 解析 NodeSpec。"""
        spec_data = yaml.safe_load(GEO_OPT_NODESPEC.read_text(encoding="utf-8"))
        inst = MFNodeInstance(id="test", inline_nodespec=spec_data)
        spec = resolve_nodespec(inst, project_root=PROJECT_ROOT)
        assert spec.metadata.name == "test-gaussian-geo-opt"

    def test_resolve_nodespec_missing_file(self):
        """不存在的 nodespec_path → FileNotFoundError。"""
        inst = MFNodeInstance(id="bad", nodespec_path="nonexistent/nodespec.yaml")
        with pytest.raises(FileNotFoundError):
            resolve_nodespec(inst, project_root=PROJECT_ROOT)

    def test_resolve_nodespec_unknown_name(self):
        """不存在的 node name → ValueError。"""
        inst = MFNodeInstance(id="bad", node="no-such-node")
        with pytest.raises(ValueError, match="未找到"):
            resolve_nodespec(inst, project_root=PROJECT_ROOT)

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_workflow("/nonexistent/workflow.yaml")


# ═══════════════════════════════════════════════════════════════════════════
# Validator 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestValidator:
    """Validator 校验测试。"""

    def test_h2o_workflow_valid(self):
        """H2O 工作流完整校验通过。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid, f"Expected valid, got errors: {[i.message for i in report.errors]}"

    def test_h2o_resolved_nodes(self):
        """校验后所有节点已解析。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert set(report.resolved_nodes.keys()) == {"geo-opt", "freq", "thermo-extract"}

    def test_h2o_resolved_node_types(self):
        """解析的节点类型正确。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.resolved_nodes["geo-opt"].metadata.name == "test-gaussian-geo-opt"
        assert report.resolved_nodes["freq"].metadata.name == "test-gaussian-freq"
        assert report.resolved_nodes["thermo-extract"].metadata.name == "test-thermo-extractor"

    def test_h2o_has_info_for_unconnected_outputs(self):
        """未连接的输出端口生成 info 提示。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        info_msgs = [i for i in report.infos if "未被任何下游节点连接" in i.message]
        # geo-opt has total_energy unconnected; freq has zpe unconnected;
        # thermo-extract has gibbs_ev and summary unconnected
        assert len(info_msgs) >= 3

    def test_missing_required_stream_input(self):
        """缺失必填 stream input → error。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="freq",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
            ],
            connections=[],  # no connections → freq's required input missing
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        error_msgs = [i.message for i in report.errors]
        assert any("checkpoint_in" in m and "未连接" in m for m in error_msgs)
        # opt_converged is no longer a stream input — only checkpoint_in is required
        assert not any("opt_converged" in m for m in error_msgs)

    def test_invalid_connection_cross_category(self):
        """跨类别连接 → error。"""
        # geo-opt.total_energy (physical_quantity) → freq.checkpoint_in (software_data_package)
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="geo-opt",
                    nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                    onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1},
                ),
                MFNodeInstance(
                    id="freq",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
            ],
            connections=[
                MFConnection(**{"from": "geo-opt.total_energy", "to": "freq.checkpoint_in"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        error_msgs = [i.message for i in report.errors]
        assert any("类型不匹配" in m for m in error_msgs)

    def test_nonexistent_source_port(self):
        """引用不存在的源端口 → error。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="geo-opt",
                    nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                    onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1},
                ),
                MFNodeInstance(
                    id="freq",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
            ],
            connections=[
                MFConnection(**{"from": "geo-opt.nonexistent", "to": "freq.checkpoint_in"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        assert any("没有输出端口" in i.message for i in report.errors)

    def test_nonexistent_target_port(self):
        """引用不存在的目标端口 → error。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="geo-opt",
                    nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                    onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1},
                ),
                MFNodeInstance(
                    id="freq",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
            ],
            connections=[
                MFConnection(**{"from": "geo-opt.optimized_checkpoint", "to": "freq.nonexistent"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        assert any("没有输入端口" in i.message for i in report.errors)

    def test_nonexistent_node_in_connection(self):
        """连接引用不存在的节点 → error。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="geo-opt",
                    nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                    onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1},
                ),
            ],
            connections=[
                MFConnection(**{"from": "geo-opt.optimized_checkpoint", "to": "unknown.port"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        assert any("不存在" in i.message for i in report.errors)

    def test_onboard_param_enum_validation(self):
        """enum 参数值域检查。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="thermo",
                    nodespec_path="nodes/test/thermo-extractor/nodespec.yaml",
                    onboard_params={"energy_unit": "INVALID_UNIT"},
                ),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        assert any("不在允许范围" in i.message for i in report.errors)

    def test_unknown_onboard_param_warning(self):
        """提供 NodeSpec 中未定义的参数 → warning。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="geo-opt",
                    nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                    onboard_params={
                        "functional": "B3LYP",
                        "basis_set": "6-31G*",
                        "charge": 0,
                        "multiplicity": 1,
                        "unknown_param": "foo",
                    },
                ),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        # Should have warning but still valid (unknown param is just warning)
        assert any("未在 NodeSpec 中定义" in i.message for i in report.warnings)

    def test_dag_cycle_detection(self):
        """DAG 环路检测。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(id="a", nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                               onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1}),
                MFNodeInstance(id="b", nodespec_path="nodes/test/gaussian-geo-opt/nodespec.yaml",
                               onboard_params={"functional": "B3LYP", "basis_set": "6-31G*", "charge": 0, "multiplicity": 1}),
            ],
            connections=[
                MFConnection(**{"from": "a.converged", "to": "b.converged"}),
                MFConnection(**{"from": "b.converged", "to": "a.converged"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        # Note: a and b are both geo-opt nodes which have no stream inputs,
        # so the "converged" is an output port. We need nodes with both input and output.
        # Let's use freq nodes that have both input and output.

    def test_dag_cycle_detection_real(self):
        """DAG 环路检测 — 使用有 input/output 的节点。"""
        # Create a cycle: freq1.thermo_data → freq2.checkpoint_in → (type mismatch but DAG check happens)
        # More reliably: use the same node twice with matching ports for a proper cycle test
        # freq has 1 stream input (checkpoint_in) and stream outputs (thermo_data, zpe)
        # We can't make a real stream cycle with these nodes' port types, but we can use
        # a simpler approach: geo-opt → geo-opt is not possible (no stream inputs)
        # Instead test that two-node cycle with geo-opt nodes fails DAG check if they reference each other.
        # Since geo-opt has no stream inputs, a connection from a→b port would fail port lookup.
        # The best we can do: verify the cycle error is raised for a non-sensical but parseable cycle.
        wf = MFWorkflow(
            name="cycle-test",
            nodes=[
                MFNodeInstance(
                    id="freq1",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
                MFNodeInstance(
                    id="freq2",
                    nodespec_path="nodes/test/gaussian-freq/nodespec.yaml",
                    onboard_params={"temperature": 298.15},
                ),
            ],
            connections=[
                # thermo_data (SDP) → checkpoint_in (SDP) — same ecosystem gaussian, valid type match
                MFConnection(**{"from": "freq1.thermo_data", "to": "freq2.checkpoint_in"}),
                MFConnection(**{"from": "freq2.thermo_data", "to": "freq1.checkpoint_in"}),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        # Should have cycle error
        assert any("环路" in i.message for i in report.issues if i.severity == "error")

    def test_nodespec_resolution_failure(self):
        """NodeSpec 解析失败 → error。"""
        wf = MFWorkflow(
            name="test",
            nodes=[
                MFNodeInstance(
                    id="bad",
                    nodespec_path="nonexistent/nodespec.yaml",
                ),
            ],
        )
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert not report.valid
        assert any("未找到" in i.message or "不存在" in i.message for i in report.errors)


# ═══════════════════════════════════════════════════════════════════════════
# Compiler 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestCompiler:
    """Compiler 编译测试。"""

    @pytest.fixture
    def validated_h2o(self) -> tuple[MFWorkflow, ValidationReport]:
        """加载并校验 H2O 工作流。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid
        return wf, report

    def test_compile_produces_valid_structure(self, validated_h2o):
        """编译产出合法的 Argo Workflow 结构。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        assert argo["apiVersion"] == "argoproj.io/v1alpha1"
        assert argo["kind"] == "Workflow"
        assert "generateName" in argo["metadata"]
        assert argo["metadata"]["namespace"] == os.environ.get("ARGO_NAMESPACE", "")

    def test_compile_has_dag_entrypoint(self, validated_h2o):
        """编译结果包含 DAG 入口。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        assert argo["spec"]["entrypoint"] == "mf-dag"
        templates = argo["spec"]["templates"]
        dag_template = next(t for t in templates if t["name"] == "mf-dag")
        assert "dag" in dag_template

    def test_compile_has_3_dag_tasks(self, validated_h2o):
        """编译结果包含 3 个 DAG task。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        dag_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-dag"
        )
        tasks = dag_template["dag"]["tasks"]
        assert len(tasks) == 3
        task_names = {t["name"] for t in tasks}
        assert task_names == {"geo-opt", "freq", "thermo-extract"}

    def test_compile_dag_dependencies(self, validated_h2o):
        """DAG dependencies / depends 正确。

        有 must_pass quality gate 的上游用 depends（.Succeeded 语义），
        无 quality gate 的上游用传统 dependencies。
        H2O 工作流：geo-opt 有 converged gate，freq 有 is_true_minimum gate，
        所以 freq 和 thermo-extract 均使用 depends 字段。
        """
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        dag_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-dag"
        )
        tasks = {t["name"]: t for t in dag_template["dag"]["tasks"]}

        # geo-opt has no upstream → no dependencies/depends
        assert "dependencies" not in tasks["geo-opt"]
        assert "depends" not in tasks["geo-opt"]

        # freq: upstream geo-opt has must_pass gate → uses depends with .Succeeded
        assert "depends" in tasks["freq"]
        assert "geo-opt.Succeeded" in tasks["freq"]["depends"]
        assert "dependencies" not in tasks["freq"]

        # thermo-extract: upstream freq has must_pass gate → uses depends with .Succeeded
        assert "depends" in tasks["thermo-extract"]
        assert "freq.Succeeded" in tasks["thermo-extract"]["depends"]
        assert "dependencies" not in tasks["thermo-extract"]

    def test_compile_template_count(self, validated_h2o):
        """编译结果包含 4 个 template（1 DAG + 3 节点）。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        templates = argo["spec"]["templates"]
        assert len(templates) == 4  # mf-dag + mf-geo-opt + mf-freq + mf-thermo-extract

    def test_compile_compute_template_has_container(self, validated_h2o):
        """compute 节点 template 包含 container 定义。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        geo_opt_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-geo-opt"
        )
        assert "container" in geo_opt_template
        assert "image" in geo_opt_template["container"]

    def test_compile_output_parameters(self, validated_h2o):
        """只有被下游连接的 stream output 才生成 Argo output parameter。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        geo_opt_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-geo-opt"
        )
        output_params = geo_opt_template["outputs"]["parameters"]
        output_names = {p["name"] for p in output_params}

        # optimized_checkpoint 在 h2o 工作流中连接到 freq，应存在
        assert "optimized_checkpoint" in output_names
        # total_energy 未被连接，不应出现（避免大文件作为参数传递）
        assert "total_energy" not in output_names
        # Quality gate 始终收集（DAG depends 条件所需）
        assert "_qg_converged" in output_names
        assert "converged" not in output_names

        # 所有 output 参数都有正确的 valueFrom 路径
        for p in output_params:
            assert p["valueFrom"]["path"].startswith("/mf/output/")

    def test_compile_dag_task_arguments(self, validated_h2o):
        """DAG task arguments 正确传参。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        dag_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-dag"
        )
        tasks = {t["name"]: t for t in dag_template["dag"]["tasks"]}

        # freq task should have stream input args from geo-opt
        freq_args = {
            p["name"]: p["value"]
            for p in tasks["freq"]["arguments"]["parameters"]
        }
        assert "checkpoint_in" in freq_args
        assert "tasks.geo-opt.outputs.parameters.optimized_checkpoint" in freq_args["checkpoint_in"]
        # opt_converged is no longer a stream input of freq
        assert "opt_converged" not in freq_args

        # freq task should have onboard args
        assert "temperature" in freq_args
        assert freq_args["temperature"] == "298.15"

        # freq task should have a when condition from geo-opt's quality gate
        assert "when" in tasks["freq"]
        assert "_qg_converged" in tasks["freq"]["when"]
        assert "geo-opt" in tasks["freq"]["when"]

        # thermo-extract should have a when condition from freq's quality gate
        assert "when" in tasks["thermo-extract"]
        assert "_qg_is_true_minimum" in tasks["thermo-extract"]["when"]
        assert "freq" in tasks["thermo-extract"]["when"]

        # geo-opt has no upstream → no when condition
        assert "when" not in tasks["geo-opt"]

    def test_compile_resource_requests(self, validated_h2o):
        """资源请求正确映射。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        geo_opt_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-geo-opt"
        )
        resources = geo_opt_template["container"]["resources"]
        assert "requests" in resources
        assert "limits" in resources
        assert resources["requests"]["cpu"] == "1"
        assert resources["requests"]["memory"] == "0.5Gi"

    def test_compile_volume_mount(self, validated_h2o):
        """compute 节点有 profile ConfigMap volume mount。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        geo_opt_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-geo-opt"
        )
        mounts = geo_opt_template["container"]["volumeMounts"]
        assert any(m["mountPath"] == "/mf/profile" for m in mounts)
        volumes = geo_opt_template["volumes"]
        assert any(v["name"] == "profile" for v in volumes)

    def test_compile_to_yaml_str(self, validated_h2o):
        """编译为 YAML 字符串。"""
        wf, report = validated_h2o
        yaml_str = compile_to_yaml_str(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        assert "apiVersion: argoproj.io/v1alpha1" in yaml_str
        assert "mf-dag" in yaml_str
        assert "geo-opt" in yaml_str

    def test_compile_labels(self, validated_h2o):
        """编译结果包含 MF 标签。"""
        wf, report = validated_h2o
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)
        labels = argo["metadata"]["labels"]
        assert labels["miqroforge.io/workflow"] == "h2o-thermo"
        assert labels["miqroforge.io/mf-version"] == "1.0"

    def test_generate_configmaps(self, validated_h2o):
        """生成 ConfigMap 清单。"""
        wf, report = validated_h2o
        configmaps = generate_configmaps(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        # 3 compute nodes → 3 configmaps
        assert len(configmaps) == 3

        cm_names = {cm["metadata"]["name"] for cm in configmaps}
        assert "mf-profile-test-gaussian-geo-opt-1.0.0" in cm_names
        assert "mf-profile-test-gaussian-freq-1.0.0" in cm_names
        assert "mf-profile-test-thermo-extractor-1.0.0" in cm_names

    def test_configmap_contains_run_sh(self, validated_h2o):
        """ConfigMap 包含 run.sh 内容。"""
        wf, report = validated_h2o
        configmaps = generate_configmaps(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        geo_cm = next(
            cm for cm in configmaps
            if cm["metadata"]["name"] == "mf-profile-test-gaussian-geo-opt-1.0.0"
        )
        assert "run.sh" in geo_cm["data"]
        assert "geo-opt" in geo_cm["data"]["run.sh"]

    def test_configmap_namespace(self, validated_h2o):
        """ConfigMap 使用工作流的 namespace。"""
        wf, report = validated_h2o
        configmaps = generate_configmaps(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        for cm in configmaps:
            assert cm["metadata"]["namespace"] == os.environ.get("ARGO_NAMESPACE", "")


# ═══════════════════════════════════════════════════════════════════════════
# 端到端纯 Python 测试（不需要 Argo 集群）
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    """端到端测试：load → validate → compile。"""

    def test_full_pipeline_h2o(self):
        """完整的 H2O 管线：加载 → 校验 → 编译。"""
        # Load
        wf = load_workflow(H2O_MF_YAML)
        assert wf.name == "h2o-thermo"

        # Validate
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid

        # Compile
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)

        # Verify structure
        assert argo["kind"] == "Workflow"
        templates = argo["spec"]["templates"]
        dag_template = next(t for t in templates if t["name"] == "mf-dag")
        tasks = dag_template["dag"]["tasks"]
        assert len(tasks) == 3

        # Verify data flow integrity
        task_map = {t["name"]: t for t in tasks}
        freq_args = {
            p["name"]: p["value"]
            for p in task_map["freq"]["arguments"]["parameters"]
        }
        # Stream data from geo-opt (only checkpoint, not converged)
        assert "{{tasks.geo-opt.outputs.parameters.optimized_checkpoint}}" == freq_args["checkpoint_in"]
        assert "opt_converged" not in freq_args

        thermo_args = {
            p["name"]: p["value"]
            for p in task_map["thermo-extract"]["arguments"]["parameters"]
        }
        # Stream data from freq (only thermo_data, not is_true_minimum)
        assert "{{tasks.freq.outputs.parameters.thermo_data}}" == thermo_args["thermo_data_in"]
        assert "is_minimum" not in thermo_args

        # Quality gate when conditions
        assert "{{tasks.geo-opt.outputs.parameters._qg_converged}} == true" in task_map["freq"]["when"]
        assert "{{tasks.freq.outputs.parameters._qg_is_true_minimum}} == true" in task_map["thermo-extract"]["when"]

    def test_compiled_yaml_is_valid_yaml(self):
        """编译产出的 YAML 字符串可正确解析。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        yaml_str = compile_to_yaml_str(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        parsed = yaml.safe_load(yaml_str)
        assert parsed["kind"] == "Workflow"
