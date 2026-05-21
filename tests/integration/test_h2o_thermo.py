"""
集成测试：H2O 热力学工作流骨架。

在 Argo 上提交 3 步 DAG 工作流（geo-opt → freq → thermo-extract），
用 shell 命令在容器内模拟计算流程验证：
  1. 工作流能成功完成
  2. DAG 依赖正确执行（3 个 Pod 按序启动）
  3. 参数在节点间正确传递
  4. 最终输出值符合预期

前提：
  - kubectl / argo CLI 可用
  - miqroforge-v2 namespace 存在且 RBAC 就绪

运行：
  pytest tests/integration/test_h2o_thermo.py -v
"""

import json
import os
import subprocess
import time

import pytest

NAMESPACE = os.environ.get("ARGO_NAMESPACE", "")
WORKFLOW_YAML = "workflows/examples/h2o-thermo.yaml"
TIMEOUT_SECONDS = 180


# ═══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _workflow_phase(name: str) -> str:
    """获取 workflow 当前 phase。"""
    r = _run([
        "kubectl", "get", "workflow", name,
        "-n", NAMESPACE,
        "-o", "jsonpath={.status.phase}",
    ])
    return r.stdout.strip()


def _workflow_nodes(name: str) -> dict:
    """获取 workflow 所有 node 信息。"""
    r = _run([
        "kubectl", "get", "workflow", name,
        "-n", NAMESPACE,
        "-o", "jsonpath={.status.nodes}",
    ])
    return json.loads(r.stdout or "{}")


def _wait_for_completion(name: str) -> str:
    """轮询等待 workflow 完成，返回最终 phase。"""
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        phase = _workflow_phase(name)
        if phase in ("Succeeded", "Failed", "Error"):
            return phase
        time.sleep(5)
    return _workflow_phase(name)


def _get_task_output_param(nodes: dict, task_display: str, param_name: str) -> str:
    """从 workflow nodes 中提取某个 DAG task 的输出参数值。

    task_display: DAG task 名，如 "geo-opt"。
                  在 nodes 中表现为 displayName 包含该字符串的 Pod 节点。
    """
    for node in nodes.values():
        if node.get("type") != "Pod":
            continue
        if task_display not in node.get("displayName", ""):
            continue
        for p in node.get("outputs", {}).get("parameters", []):
            if p["name"] == param_name:
                return p["value"]
    raise KeyError(
        f"未找到 task={task_display!r} 的输出参数 {param_name!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Fixture
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def workflow():
    """提交 h2o-thermo 工作流，等待完成，yield (name, nodes)，结束后清理。"""
    import re

    # 提交
    r = _run(["argo", "submit", WORKFLOW_YAML, "-n", NAMESPACE])
    assert r.returncode == 0, f"argo submit 失败:\n{r.stderr}\n{r.stdout}"

    match = re.search(r"Name:\s+(\S+)", r.stdout)
    assert match, f"无法解析 workflow 名称:\n{r.stdout}"
    name = match.group(1)

    # 等待完成
    final_phase = _wait_for_completion(name)
    nodes = _workflow_nodes(name)

    yield {
        "name": name,
        "phase": final_phase,
        "nodes": nodes,
    }

    # 清理
    _run(["kubectl", "delete", "workflow", name, "-n", NAMESPACE])


# ═══════════════════════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowCompletion:
    """工作流整体状态。"""

    def test_workflow_succeeds(self, workflow):
        assert workflow["phase"] == "Succeeded", (
            f"工作流以 {workflow['phase']} 结束，预期 Succeeded"
        )

    def test_three_pods_executed(self, workflow):
        """DAG 应执行 3 个 Pod（geo-opt, freq, thermo-extract）。"""
        pod_nodes = [
            n for n in workflow["nodes"].values()
            if n.get("type") == "Pod"
        ]
        assert len(pod_nodes) == 3, (
            f"预期 3 个 Pod 节点，实际 {len(pod_nodes)} 个: "
            f"{[n['displayName'] for n in pod_nodes]}"
        )


class TestGeoOptOutputs:
    """Step 1: geo-opt 输出验证。"""

    def test_total_energy(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "geo-opt", "total-energy")
        assert val == "-76.434000"

    def test_converged(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "geo-opt", "converged")
        assert val == "true"

    def test_checkpoint_stub_nonempty(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "geo-opt", "checkpoint-stub")
        assert len(val) > 0
        assert "CHECKPOINT" in val


class TestFreqOutputs:
    """Step 2: freq 输出验证。"""

    def test_no_imaginary_frequencies(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "freq", "n-imaginary")
        assert val == "0"

    def test_is_true_minimum(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "freq", "is-minimum")
        assert val == "true"

    def test_zpe(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "freq", "zpe")
        assert float(val) == pytest.approx(0.021375, rel=1e-4)

    def test_gibbs_ha(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "freq", "gibbs-ha")
        assert float(val) == pytest.approx(-76.432456, rel=1e-6)

    def test_enthalpy_ha(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "freq", "enthalpy-ha")
        assert float(val) == pytest.approx(-76.408901, rel=1e-6)


class TestThermoExtractOutputs:
    """Step 3: thermo-extract 输出验证（含单位转换）。"""

    def test_gibbs_ev(self, workflow):
        """G(Ha) * 27.211386 = G(eV)，验证转换正确。"""
        val = _get_task_output_param(workflow["nodes"], "thermo-extract", "gibbs-ev")
        expected_ev = -76.432456 * 27.211386
        assert float(val) == pytest.approx(expected_ev, rel=1e-4)

    def test_enthalpy_ev(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "thermo-extract", "enthalpy-ev")
        expected_ev = -76.408901 * 27.211386
        assert float(val) == pytest.approx(expected_ev, rel=1e-4)

    def test_summary_contains_key_info(self, workflow):
        val = _get_task_output_param(workflow["nodes"], "thermo-extract", "summary")
        assert "H2O" in val
        assert "eV" in val
        assert "minimum: true" in val


class TestDataFlowIntegrity:
    """验证数据在节点间正确流动。"""

    def test_checkpoint_flows_to_freq(self, workflow):
        """geo-opt 的 checkpoint-stub 被 freq 接收。"""
        # freq 容器日志应包含 checkpoint 内容
        pod_nodes = workflow["nodes"]
        for node in pod_nodes.values():
            if node.get("type") == "Pod" and "freq" in node.get("displayName", ""):
                # 检查 freq 的输入参数中包含了 checkpoint
                inputs = node.get("inputs", {}).get("parameters", [])
                chk_param = next(
                    (p for p in inputs if p["name"] == "checkpoint-stub"),
                    None,
                )
                assert chk_param is not None, "freq 节点缺少 checkpoint-stub 输入"
                assert "CHECKPOINT" in chk_param["value"]
                return
        pytest.fail("未找到 freq Pod 节点")

    def test_gibbs_flows_to_thermo_extract(self, workflow):
        """freq 的 gibbs-ha 被 thermo-extract 接收。"""
        pod_nodes = workflow["nodes"]
        for node in pod_nodes.values():
            if node.get("type") == "Pod" and "thermo-extract" in node.get("displayName", ""):
                inputs = node.get("inputs", {}).get("parameters", [])
                gibbs_param = next(
                    (p for p in inputs if p["name"] == "gibbs-ha"),
                    None,
                )
                assert gibbs_param is not None, "thermo-extract 缺少 gibbs-ha 输入"
                assert float(gibbs_param["value"]) == pytest.approx(-76.432456, rel=1e-6)
                return
        pytest.fail("未找到 thermo-extract Pod 节点")

    def test_dag_execution_order(self, workflow):
        """验证 DAG 执行顺序：geo-opt 先于 freq，freq 先于 thermo-extract。"""
        timestamps = {}
        for node in workflow["nodes"].values():
            if node.get("type") != "Pod":
                continue
            display = node["displayName"]
            started = node.get("startedAt", "")
            for key in ("geo-opt", "freq", "thermo-extract"):
                if key in display:
                    timestamps[key] = started

        assert len(timestamps) == 3, f"未找到全部 3 个任务时间戳: {timestamps}"
        assert timestamps["geo-opt"] <= timestamps["freq"], "geo-opt 应先于 freq"
        assert timestamps["freq"] <= timestamps["thermo-extract"], "freq 应先于 thermo-extract"
