"""计算资源用量追踪 — Argo Workflow 完成后记录核时。

用法：
    from api.tracking.compute_tracker import ComputeUsageTracker

    tracker = ComputeUsageTracker(user_paths, namespace)
    tracker.record_workflow(workflow_name, project_id)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ComputeUsageTracker:
    """从 Argo workflow status 提取资源用量并记录到用户的使用量 JSONL。"""

    def __init__(self, user_paths: "UserPaths", namespace: str = ""):
        self._paths = user_paths
        self._ns = namespace
        self._log_path = user_paths.usage_dir / "compute_usage.jsonl"

    def record_workflow(
        self,
        workflow_json: dict[str, Any],
        project_id: str = "unknown",
    ) -> None:
        """从 Argo workflow JSON 中提取每个 node 的资源用量并写入 JSONL。

        Parameters
        ----------
        workflow_json: argo get <name> -o json 的完整输出
        project_id: 关联的项目 ID
        """
        status = workflow_json.get("status", {})
        nodes = status.get("nodes", {})
        if not nodes:
            return

        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._log_path, "a", encoding="utf-8") as f:
            for node_id, node_data in nodes.items():
                if node_data.get("type") != "Pod":
                    continue
                phase = node_data.get("phase", "Unknown")

                # 只记录成功/失败的实际执行
                if phase not in ("Succeeded", "Failed"):
                    continue

                started = node_data.get("startedAt", "")
                finished = node_data.get("finishedAt", "")
                duration = self._compute_duration(started, finished)

                # 从 template 提取资源声明
                resources = self._extract_resources(node_data.get("templateName", ""), workflow_json)

                core_hours = round(resources.get("cpu", 0) * duration / 3600, 4)
                gpu_hours = round(resources.get("gpu", 0) * duration / 3600, 4)

                record = {
                    "workflow": workflow_json.get("metadata", {}).get("name", ""),
                    "project_id": project_id,
                    "node_name": node_id,
                    "template": node_data.get("templateName", ""),
                    "display_name": node_data.get("displayName", ""),
                    "cpu_cores": resources.get("cpu", 0),
                    "memory_gb": resources.get("memory", 0),
                    "gpu_count": resources.get("gpu", 0),
                    "duration_seconds": duration,
                    "core_hours": core_hours,
                    "gpu_hours": gpu_hours,
                    "phase": phase,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _compute_duration(started: str, finished: str) -> float:
        try:
            s = datetime.fromisoformat(started.replace("Z", "+00:00"))
            f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            return (f - s).total_seconds()
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _extract_resources(
        template_name: str, workflow_json: dict
    ) -> dict[str, float]:
        """从 workflow spec 中提取 template 的资源声明。"""
        templates = (
            workflow_json.get("spec", {}).get("templates", [])
        )
        for t in templates:
            if t.get("name") == template_name:
                container = t.get("container", {}) or t.get("script", {})
                res = container.get("resources", {})
                requests = res.get("requests", {})
                limits = res.get("limits", {})
                cpu_req = requests.get("cpu", limits.get("cpu", "0"))
                mem_req = requests.get("memory", limits.get("memory", "0"))
                gpu_req = limits.get("nvidia.com/gpu", requests.get("nvidia.com/gpu", "0"))

                return {
                    "cpu": _parse_cpu(cpu_req),
                    "memory": _parse_memory(mem_req),
                    "gpu": _parse_gpu(gpu_req),
                }
        return {"cpu": 0, "memory": 0, "gpu": 0}


def _parse_cpu(cpu_str: str) -> float:
    """K8s CPU 单位 → 核数。"""
    s = str(cpu_str).strip()
    if not s:
        return 0.0
    if s.endswith("m"):
        return float(s[:-1]) / 1000
    return float(s)


def _parse_memory(mem_str: str) -> float:
    """K8s 内存单位 → GB。"""
    s = str(mem_str).strip()
    if not s:
        return 0.0
    s = s.upper()
    if s.endswith("KI"):
        return float(s[:-2]) / (1024 * 1024)
    if s.endswith("MI"):
        return float(s[:-2]) / 1024
    if s.endswith("GI"):
        return float(s[:-2])
    if s.endswith("G"):
        return float(s[:-1])
    # 纯数字默认为字节
    try:
        return float(s) / (1024 ** 3)
    except ValueError:
        return 0.0


def _parse_gpu(gpu_str: str) -> int:
    try:
        return int(gpu_str)
    except (ValueError, TypeError):
        return 0
