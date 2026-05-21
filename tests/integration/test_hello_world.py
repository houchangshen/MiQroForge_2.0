"""
集成测试：提交 hello-world 工作流，验证其成功完成。

前提：
  - kubectl 已配置好 kubeconfig
  - argo CLI 可用
  - miqroforge-v2 namespace 存在且 RBAC 就绪

运行：
  pytest tests/integration/test_hello_world.py -v
"""
import os
import re
import subprocess
import time

import pytest

NAMESPACE = os.environ.get("ARGO_NAMESPACE", "")
WORKFLOW_YAML = "workflows/examples/hello-world.yaml"
TIMEOUT_SECONDS = 120


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _workflow_status(name: str) -> str:
    r = _run([
        "kubectl", "get", "workflow", name,
        "-n", NAMESPACE,
        "-o", "jsonpath={.status.phase}",
    ])
    return r.stdout.strip()


@pytest.fixture(scope="module")
def submitted_workflow():
    """提交 workflow，yield 名称，测试结束后自动清理。"""
    r = _run(["argo", "submit", WORKFLOW_YAML])
    assert r.returncode == 0, f"argo submit 失败:\n{r.stderr}"

    match = re.search(r"Name:\s+(\S+)", r.stdout)
    assert match, f"无法从输出中解析 workflow 名称:\n{r.stdout}"
    name = match.group(1)

    yield name

    # 清理：测试完成后删除 workflow（无论成败）
    _run(["kubectl", "delete", "workflow", name, "-n", NAMESPACE])


def test_hello_world_succeeds(submitted_workflow):
    """Workflow 应在规定时间内以 Succeeded 状态完成。"""
    name = submitted_workflow
    deadline = time.time() + TIMEOUT_SECONDS

    while time.time() < deadline:
        status = _workflow_status(name)
        if status == "Succeeded":
            return
        if status in ("Failed", "Error"):
            pytest.fail(f"Workflow {name} 以 {status} 状态结束")
        time.sleep(5)

    pytest.fail(
        f"Workflow {name} 在 {TIMEOUT_SECONDS}s 内未完成，"
        f"当前状态：{_workflow_status(name)}"
    )


def test_hello_world_step_count(submitted_workflow):
    """Workflow 应包含恰好两个节点（两个 step）。"""
    name = submitted_workflow
    r = _run([
        "kubectl", "get", "workflow", name,
        "-n", NAMESPACE,
        "-o", "jsonpath={.status.nodes}",
    ])
    # nodes 是一个 map，包含 workflow 本身 + 各 step pod
    # 去掉 workflow 本身那个节点，剩下的是实际执行节点
    import json
    nodes = json.loads(r.stdout or "{}")
    step_nodes = [n for n in nodes.values() if n.get("type") == "Pod"]
    assert len(step_nodes) == 2, (
        f"预期 2 个执行节点，实际 {len(step_nodes)} 个"
    )
