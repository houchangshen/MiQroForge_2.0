"""MF 工作流管线集成测试 — H2O 热力学全流程。

需要 Argo 集群运行。使用 pytest 标记 ``@pytest.mark.integration``
并通过 ``--argo-url`` 参数指定 Argo Server 地址。

测试流程：
1. load + validate → valid=True
2. compile → 3 个 DAG task + 正确 dependencies
3. argo submit + wait → Succeeded
4. 输出参数值正确
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from workflows.pipeline.loader import load_workflow
from workflows.pipeline.validator import validate_workflow
from workflows.pipeline.compiler import compile_to_argo, generate_configmaps


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
H2O_MF_YAML = PROJECT_ROOT / "workflows" / "examples" / "h2o-thermo-mf.yaml"
NAMESPACE = os.environ.get("ARGO_NAMESPACE", "")


def _argo_available() -> bool:
    """检查 argo CLI 是否可用。"""
    try:
        result = subprocess.run(
            ["argo", "version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _kubectl_available() -> bool:
    """检查 kubectl 是否可用。"""
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


skip_no_argo = pytest.mark.skipif(
    not _argo_available(),
    reason="argo CLI not available"
)
skip_no_kubectl = pytest.mark.skipif(
    not _kubectl_available(),
    reason="kubectl not available"
)


class TestH2OPipelineIntegration:
    """H2O 热力学全管线集成测试。"""

    # ── 纯 Python 阶段（无需集群）─────────────────────────────────────────

    def test_step1_validate(self):
        """Step 1: validate_workflow() 返回 valid=True。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid, (
            f"Validation failed: {[i.message for i in report.errors]}"
        )
        assert len(report.resolved_nodes) == 3

    def test_step2_compile_structure(self):
        """Step 2: compile 产出 3 个 DAG task + 正确 dependencies。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid

        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)

        # DAG tasks
        dag_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-dag"
        )
        tasks = dag_template["dag"]["tasks"]
        assert len(tasks) == 3

        task_map = {t["name"]: t for t in tasks}

        # Dependencies
        assert "dependencies" not in task_map["geo-opt"]
        assert "geo-opt" in task_map["freq"]["dependencies"]
        assert "freq" in task_map["thermo-extract"]["dependencies"]

    def test_step2_compile_connections(self):
        """Step 2: 连接参数传递正确。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        argo = compile_to_argo(wf, report.resolved_nodes, project_root=PROJECT_ROOT)

        dag_template = next(
            t for t in argo["spec"]["templates"] if t["name"] == "mf-dag"
        )
        task_map = {t["name"]: t for t in dag_template["dag"]["tasks"]}

        # geo-opt → freq
        freq_args = {
            p["name"]: p["value"]
            for p in task_map["freq"]["arguments"]["parameters"]
        }
        assert freq_args["checkpoint_in"] == "{{tasks.geo-opt.outputs.parameters.optimized_checkpoint}}"
        assert freq_args["opt_converged"] == "{{tasks.geo-opt.outputs.parameters.converged}}"

        # freq → thermo-extract
        thermo_args = {
            p["name"]: p["value"]
            for p in task_map["thermo-extract"]["arguments"]["parameters"]
        }
        assert thermo_args["thermo_data_in"] == "{{tasks.freq.outputs.parameters.thermo_data}}"
        assert thermo_args["is_minimum"] == "{{tasks.freq.outputs.parameters.is_true_minimum}}"

    def test_step2_configmaps(self):
        """Step 2: 生成 3 个 ConfigMap。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        configmaps = generate_configmaps(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        assert len(configmaps) == 3
        for cm in configmaps:
            assert "run.sh" in cm["data"]

    # ── Argo 集群阶段 ────────────────────────────────────────────────────

    @skip_no_kubectl
    @skip_no_argo
    def test_step3_argo_submit_and_succeed(self):
        """Step 3+4: Argo 提交 + 执行成功 + 输出参数正确。"""
        wf = load_workflow(H2O_MF_YAML)
        report = validate_workflow(wf, project_root=PROJECT_ROOT)
        assert report.valid

        argo_dict = compile_to_argo(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )

        # Apply ConfigMaps
        configmaps = generate_configmaps(
            wf, report.resolved_nodes, project_root=PROJECT_ROOT
        )
        for cm in configmaps:
            _apply_resource(cm)

        # Submit workflow
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="mf-test-"
        ) as f:
            yaml.dump(argo_dict, f, default_flow_style=False, allow_unicode=True)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["argo", "submit", tmp_path, "--namespace", NAMESPACE, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"argo submit failed: {result.stderr}"

            submit_data = json.loads(result.stdout)
            wf_name = submit_data["metadata"]["name"]

            # Wait for completion (timeout 5 min)
            completed = _wait_for_workflow(wf_name, timeout=300)
            assert completed, f"Workflow {wf_name} did not complete in time"

            # Get final status
            get_result = subprocess.run(
                ["argo", "get", wf_name, "--namespace", NAMESPACE, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert get_result.returncode == 0
            wf_status = json.loads(get_result.stdout)

            # Assert Succeeded
            phase = wf_status["status"]["phase"]
            assert phase == "Succeeded", f"Expected Succeeded, got {phase}"

            # Assert 3 pods
            nodes = wf_status["status"]["nodes"]
            pod_nodes = [
                n for n in nodes.values()
                if n.get("type") == "Pod"
            ]
            assert len(pod_nodes) == 3

            # Assert output values
            outputs = _extract_outputs(wf_status)

            # geo-opt outputs
            assert "geo-opt" in outputs
            assert outputs["geo-opt"].get("total_energy") == "-76.3908154"
            assert outputs["geo-opt"].get("converged") == "true"

            # freq outputs
            assert "freq" in outputs
            assert outputs["freq"].get("is_true_minimum") == "true"

            # thermo-extract outputs
            assert "thermo-extract" in outputs
            gibbs = outputs["thermo-extract"].get("gibbs_ev", "")
            assert gibbs != ""
            assert float(gibbs) < 0  # Gibbs energy should be negative

        finally:
            os.unlink(tmp_path)
            # Cleanup: delete the workflow
            subprocess.run(
                ["argo", "delete", wf_name, "--namespace", NAMESPACE],
                capture_output=True,
                timeout=10,
            )


# ═══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════


def _apply_resource(resource: dict) -> None:
    """通过 kubectl apply 创建资源。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(resource, f)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", tmp_path, "--namespace", NAMESPACE],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"kubectl apply failed: {result.stderr}"
    finally:
        os.unlink(tmp_path)


def _wait_for_workflow(name: str, timeout: int = 300) -> bool:
    """等待 Argo 工作流完成。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["argo", "get", name, "--namespace", NAMESPACE, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            phase = data.get("status", {}).get("phase", "")
            if phase in ("Succeeded", "Failed", "Error"):
                return phase == "Succeeded"
        time.sleep(5)
    return False


def _extract_outputs(wf_status: dict) -> dict[str, dict[str, str]]:
    """从 Argo workflow status 提取每个 task 的输出参数。"""
    outputs: dict[str, dict[str, str]] = {}
    for node_info in wf_status.get("status", {}).get("nodes", {}).values():
        display = node_info.get("displayName", "")
        params = node_info.get("outputs", {}).get("parameters", [])
        if params:
            outputs[display] = {
                p["name"]: p.get("value", "")
                for p in params
            }
    return outputs
