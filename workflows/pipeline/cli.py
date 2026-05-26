"""MF 工作流管线 CLI。

用法::

    python -m workflows.pipeline.cli validate <mf-workflow.yaml>
    python -m workflows.pipeline.cli compile  <mf-workflow.yaml>
    python -m workflows.pipeline.cli run      <mf-workflow.yaml>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 自动加载项目根目录的 .env（使 ARGO_NAMESPACE、DOCKER_HUB_MIRROR 等变量生效）
_root = Path(__file__).parent.parent.parent
load_dotenv(_root / ".env", override=False)

from .compiler import compile_to_argo, compile_to_yaml_str, generate_configmaps
from .loader import load_workflow
from .validator import ValidationReport, validate_workflow

# ── 颜色 ──
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def _info(msg: str) -> None:
    print(f"  {BLUE}i {msg}{NC}")


def _ok(msg: str) -> None:
    print(f"  {GREEN}✔ {msg}{NC}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ {msg}{NC}")


def _error(msg: str) -> None:
    print(f"  {RED}✘ {msg}{NC}", file=sys.stderr)


def _print_report(report: ValidationReport) -> None:
    """打印校验报告。"""
    print()
    print(f"{BLUE}{BOLD}══ MF Validation Report ══{NC}")
    print()

    for issue in report.issues:
        if issue.severity == "error":
            _error(f"[{issue.location}] {issue.message}")
        elif issue.severity == "warning":
            _warn(f"[{issue.location}] {issue.message}")
        else:
            _info(f"[{issue.location}] {issue.message}")

    print()
    n_err = len(report.errors)
    n_warn = len(report.warnings)
    n_info = len(report.infos)

    if report.valid:
        _ok(f"Validation passed  (errors={n_err}, warnings={n_warn}, info={n_info})")
    else:
        _error(f"Validation failed  (errors={n_err}, warnings={n_warn}, info={n_info})")

    # 显示解析的节点
    if report.resolved_nodes:
        print()
        _info("Resolved nodes:")
        for nid, spec in report.resolved_nodes.items():
            _info(
                f"  {nid} → {spec.metadata.name} v{spec.metadata.version} "
                f"({spec.metadata.node_type.value})"
            )
    print()


def _detect_project_root() -> Path:
    """探测项目根目录（查找 CLAUDE.md 或 nodes/ 目录）。"""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "CLAUDE.md").exists() or (parent / "nodes" / "schemas").exists():
            return parent
    return cwd


# ═══════════════════════════════════════════════════════════════════════════
# 命令实现
# ═══════════════════════════════════════════════════════════════════════════


def cmd_validate(yaml_path: str) -> int:
    """校验 MF 工作流。"""
    project_root = _detect_project_root()

    try:
        workflow = load_workflow(yaml_path)
    except Exception as e:
        _error(f"加载工作流失败: {e}")
        return 1

    report = validate_workflow(workflow, project_root=project_root)
    _print_report(report)

    return 0 if report.valid else 1


def cmd_compile(yaml_path: str) -> int:
    """校验 + 编译 MF 工作流，输出 Argo YAML。"""
    project_root = _detect_project_root()
    docker_hub_mirror = os.environ.get("DOCKER_HUB_MIRROR", "")

    try:
        workflow = load_workflow(yaml_path)
    except Exception as e:
        _error(f"加载工作流失败: {e}")
        return 1

    report = validate_workflow(workflow, project_root=project_root)
    _print_report(report)

    if not report.valid:
        _error("校验失败，无法编译。")
        return 1

    try:
        yaml_str = compile_to_yaml_str(
            workflow, report.resolved_nodes,
            project_root=project_root,
            docker_hub_mirror=docker_hub_mirror,
        )
    except Exception as e:
        _error(f"编译失败: {e}")
        return 1

    print(f"{BLUE}{BOLD}══ Compiled Argo Workflow YAML ══{NC}")
    print()
    print(yaml_str)

    # 也输出 ConfigMaps
    configmaps = generate_configmaps(
        workflow, report.resolved_nodes, project_root=project_root
    )
    if configmaps:
        print(f"{BLUE}{BOLD}══ ConfigMaps ══{NC}")
        print()
        for cm in configmaps:
            print("---")
            print(yaml.dump(cm, default_flow_style=False, allow_unicode=True, sort_keys=False))

    return 0


def cmd_run(yaml_path: str) -> int:
    """校验 + 编译 + 提交 + 流式日志 + 生成报告。"""
    project_root = _detect_project_root()
    namespace = os.environ.get("ARGO_NAMESPACE", "")
    docker_hub_mirror = os.environ.get("DOCKER_HUB_MIRROR", "")

    # Step 1: Load + Validate
    try:
        workflow = load_workflow(yaml_path)
    except Exception as e:
        _error(f"加载工作流失败: {e}")
        return 1

    report = validate_workflow(workflow, project_root=project_root)
    _print_report(report)

    if not report.valid:
        _error("校验失败，无法提交。")
        return 1

    # Step 2: Compile
    try:
        argo_dict = compile_to_argo(
            workflow, report.resolved_nodes,
            project_root=project_root,
            docker_hub_mirror=docker_hub_mirror,
        )
    except Exception as e:
        _error(f"编译失败: {e}")
        return 1

    # Step 3: Create/update ConfigMaps
    configmaps = generate_configmaps(
        workflow, report.resolved_nodes, project_root=project_root
    )
    for cm in configmaps:
        cm_name = cm["metadata"]["name"]
        _info(f"Creating ConfigMap: {cm_name}")
        try:
            _apply_configmap(cm, namespace)
            _ok(f"ConfigMap {cm_name} applied")
        except Exception as e:
            _error(f"ConfigMap {cm_name} 创建失败: {e}")
            return 1

    # Step 4: Submit to Argo
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="mf-argo-"
    ) as f:
        yaml.dump(argo_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp_path = f.name

    run_started_at = datetime.now(timezone.utc)

    try:
        _info(f"Submitting workflow to Argo (namespace={namespace})...")
        result = subprocess.run(
            ["argo", "submit", tmp_path, "--namespace", namespace, "-o", "json"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _error(f"argo submit 失败:\n{result.stderr}")
            return 1

        submit_output = json.loads(result.stdout)
        wf_name = submit_output["metadata"]["name"]
        _ok(f"Workflow submitted: {wf_name}")

        # Step 5: Watch
        _info(f"Watching workflow {wf_name}...")
        print()
        subprocess.run(
            ["argo", "watch", wf_name, "--namespace", namespace],
        )

        # Step 6: Get final status and outputs
        print()
        _info("Fetching workflow results...")
        get_result = subprocess.run(
            ["argo", "get", wf_name, "--namespace", namespace, "-o", "json"],
            capture_output=True,
            text=True,
        )
        if get_result.returncode != 0:
            _warn("无法获取工作流最终状态")
            return 1

        wf_status = json.loads(get_result.stdout)
        phase = wf_status.get("status", {}).get("phase", "Unknown")

        if phase == "Succeeded":
            _ok(f"Workflow {wf_name} completed: {phase}")
        else:
            _error(f"Workflow {wf_name} ended: {phase}")
            # 仍然生成报告以便排查
            _warn("仍将生成报告以便排查问题")

        _print_outputs(wf_status)

        # Step 7: Generate run report
        print()
        _info("Generating run report...")
        report_dir = _generate_run_report(
            workflow=workflow,
            wf_name=wf_name,
            wf_status=wf_status,
            namespace=namespace,
            project_root=project_root,
            source_yaml=yaml_path,
            run_started_at=run_started_at,
        )
        _ok(f"Report saved to: {report_dir}")

        return 0 if phase == "Succeeded" else 1

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _apply_configmap(cm: dict, namespace: str) -> None:
    """通过 kubectl apply 创建/更新 ConfigMap。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="mf-cm-"
    ) as f:
        yaml.dump(cm, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", tmp_path, "--namespace", namespace],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _print_outputs(wf_status: dict) -> None:
    """从 Argo workflow status 中提取并打印输出参数。"""
    nodes = wf_status.get("status", {}).get("nodes", {})
    for node_name, node_info in nodes.items():
        outputs = node_info.get("outputs", {})
        params = outputs.get("parameters", [])
        if params:
            display = node_info.get("displayName", node_name)
            _info(f"Outputs from {display}:")
            for p in params:
                _info(f"  {p['name']} = {p.get('value', 'N/A')}")


# ═══════════════════════════════════════════════════════════════════════════
# 运行报告生成
# ═══════════════════════════════════════════════════════════════════════════


def _fetch_node_log(wf_name: str, node_id: str, node_info: dict, namespace: str) -> str:
    """通过 kubectl logs 获取单个节点的 main 容器日志。

    尝试多种 Pod 命名规则，兼容不同版本的 Argo Workflow：
      1. 直接使用 node_id 作为 Pod 名（Argo v3.3+ 默认）
      2. 从 node_info["hostNodeName"] 和 Pod 名反推
      3. 通过 kubectl get pods -l 标签选择器查找

    Argo v3.x Pod 命名规则：
      - DAG template：{wf_name}-{templateName}-{random_hash}
      - 实际 Pod 名存于 node_info["id"]（即 node_id 本身）
    """
    # 方法 1: node_id 即 Pod 名（Argo v3.x 最常见）
    pod_name = node_id

    result = subprocess.run(
        [
            "kubectl", "logs", pod_name,
            "-c", "main",
            "--namespace", namespace,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout

    # 方法 2: 去掉 workflow 名前缀后重组
    template_name = node_info.get("templateName", "")
    if template_name:
        hash_suffix = node_id.removeprefix(f"{wf_name}-")
        alt_pod_name = f"{wf_name}-{template_name}-{hash_suffix}"
        if alt_pod_name != pod_name:
            result2 = subprocess.run(
                [
                    "kubectl", "logs", alt_pod_name,
                    "-c", "main",
                    "--namespace", namespace,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result2.returncode == 0 and result2.stdout.strip():
                return result2.stdout

    # 方法 3: 通过标签选择器查找
    label_result = subprocess.run(
        [
            "kubectl", "get", "pods",
            "-l", f"workflows.argoproj.io/workflow={wf_name}",
            "--namespace", namespace,
            "-o", "jsonpath={.items[*].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if label_result.returncode == 0:
        display_name = node_info.get("displayName", "")
        for candidate in label_result.stdout.split():
            if template_name and template_name in candidate:
                r = subprocess.run(
                    ["kubectl", "logs", candidate, "-c", "main",
                     "--namespace", namespace],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout

    if result.stderr.strip():
        return f"(log unavailable: {result.stderr.strip()})"
    return "(no log available)"


def _parse_argo_timestamp(ts: str | None) -> datetime | None:
    """解析 Argo 时间戳（ISO 8601）。"""
    if not ts:
        return None
    try:
        # Python 3.10 兼容写法
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_duration(seconds: float) -> str:
    """格式化秒数为人类可读时长。"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def _generate_run_report(
    workflow,
    wf_name: str,
    wf_status: dict,
    namespace: str,
    project_root: Path,
    source_yaml: str,
    run_started_at: datetime,
) -> Path:
    """生成运行报告并返回报告目录。

    报告目录结构::

        userdata/runs/<wf-name>/
            report.md          # Markdown 摘要报告
            logs/
                <node-id>.log  # 每个节点的原始日志
    """
    # 创建目录
    runs_dir = project_root / "userdata" / "runs" / wf_name
    logs_dir = runs_dir / "logs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    status_block = wf_status.get("status", {})
    phase = status_block.get("phase", "Unknown")
    nodes = status_block.get("nodes", {})

    # 解析时间
    wf_start = _parse_argo_timestamp(status_block.get("startedAt"))
    wf_finish = _parse_argo_timestamp(status_block.get("finishedAt"))
    duration_str = "—"
    if wf_start and wf_finish:
        duration_str = _format_duration((wf_finish - wf_start).total_seconds())

    def fmt_ts(dt: datetime | None) -> str:
        if dt is None:
            return "—"
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    # 按节点类型分类：DAG 节点 vs Pod 节点
    # Argo 节点树中，type=DAG 是顶级 DAG，type=Pod 是实际执行节点
    pod_nodes = {
        k: v for k, v in nodes.items()
        if v.get("type") == "Pod"
    }

    # ── 收集每个节点的日志 ────────────────────────────────────────────────
    node_logs: dict[str, str] = {}
    for node_id, node_info in pod_nodes.items():
        display = node_info.get("displayName", node_id)
        log_text = _fetch_node_log(wf_name, node_id, node_info, namespace)
        node_logs[display] = log_text
        # 写入独立日志文件
        safe_name = display.replace("/", "_").replace(" ", "-")
        log_file = logs_dir / f"{safe_name}.log"
        log_file.write_text(log_text, encoding="utf-8")

    # ── 收集每个节点的输出参数 ────────────────────────────────────────────
    node_outputs: dict[str, list[dict]] = {}
    for node_id, node_info in pod_nodes.items():
        display = node_info.get("displayName", node_id)
        params = node_info.get("outputs", {}).get("parameters", [])
        if params:
            node_outputs[display] = params

    # ── 生成 Markdown 报告 ─────────────────────────────────────────────────
    phase_badge = "✅ Succeeded" if phase == "Succeeded" else f"❌ {phase}"

    lines: list[str] = []

    lines += [
        f"# MiQroForge Run Report",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Workflow** | `{workflow.name}` |",
        f"| **Argo Name** | `{wf_name}` |",
        f"| **Namespace** | `{namespace}` |",
        f"| **Status** | {phase_badge} |",
        f"| **Started** | {fmt_ts(wf_start)} |",
        f"| **Finished** | {fmt_ts(wf_finish)} |",
        f"| **Duration** | {duration_str} |",
        f"| **Source** | `{source_yaml}` |",
        f"| **Report Generated** | {run_started_at.strftime('%Y-%m-%d %H:%M:%S UTC')} |",
        f"",
        f"---",
        f"",
    ]

    # 节点汇总表
    lines += [
        f"## Nodes",
        f"",
        f"| Node | Status | Started | Duration |",
        f"|------|--------|---------|----------|",
    ]
    for node_id, node_info in pod_nodes.items():
        display = node_info.get("displayName", node_id)
        n_phase = node_info.get("phase", "—")
        n_badge = "✅" if n_phase == "Succeeded" else ("❌" if n_phase == "Failed" else "⏳")
        n_start = _parse_argo_timestamp(node_info.get("startedAt"))
        n_finish = _parse_argo_timestamp(node_info.get("finishedAt"))
        n_dur = "—"
        if n_start and n_finish:
            n_dur = _format_duration((n_finish - n_start).total_seconds())
        lines.append(
            f"| `{display}` | {n_badge} {n_phase} | {fmt_ts(n_start)} | {n_dur} |"
        )

    lines += ["", "---", ""]

    # 输出参数
    lines += ["## Outputs", ""]
    if node_outputs:
        for display, params in node_outputs.items():
            lines += [f"### `{display}`", ""]
            lines += ["| Parameter | Value |", "|-----------|-------|"]
            for p in params:
                val = p.get("value", "N/A")
                # 只有 dict/list 才折叠显示，原始值直接展示
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, (dict, list)):
                        val = f"`(json, {len(val)} chars)`"
                except (json.JSONDecodeError, TypeError):
                    pass
                lines.append(f"| `{p['name']}` | `{val}` |")
            lines.append("")
    else:
        lines += ["*(no output parameters)*", ""]

    # 如果有 JSON 输出，展开显示
    for node_id, node_info in pod_nodes.items():
        display = node_info.get("displayName", node_id)
        params = node_info.get("outputs", {}).get("parameters", [])
        for p in params:
            val = p.get("value", "")
            try:
                parsed = json.loads(val)
                if isinstance(parsed, (dict, list)):
                    lines += [
                        f"#### `{display}` → `{p['name']}` (expanded)",
                        "",
                        "```json",
                        json.dumps(parsed, indent=2, ensure_ascii=False),
                        "```",
                        "",
                    ]
            except (json.JSONDecodeError, TypeError):
                pass

    lines += ["---", ""]

    # 日志
    lines += ["## Logs", ""]
    for display, log_text in node_logs.items():
        lines += [
            f"### `{display}`",
            "",
            "```",
            log_text.strip() or "(empty)",
            "```",
            "",
        ]

    lines += [
        "---",
        "",
        f"*Generated by MiQroForge 2.0 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
    ]

    report_text = "\n".join(lines)
    report_file = runs_dir / "report.md"
    report_file.write_text(report_text, encoding="utf-8")

    return runs_dir


# ═══════════════════════════════════════════════════════════════════════════
# __main__ 入口
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    """CLI 入口点。"""
    if len(sys.argv) < 2:
        print(f"""
{BLUE}{BOLD}mf2 pipeline — MiQroForge 2.0 Workflow Pipeline{NC}

{BOLD}Usage:{NC}
  python -m workflows.pipeline.cli validate <mf-workflow.yaml>
  python -m workflows.pipeline.cli compile  <mf-workflow.yaml>
  python -m workflows.pipeline.cli run      <mf-workflow.yaml>

{BOLD}Commands:{NC}
  {GREEN}validate{NC}   校验 MF 工作流（I/O 类型、参数、DAG）
  {GREEN}compile{NC}    校验 + 编译为 Argo Workflow YAML
  {GREEN}run{NC}        校验 + 编译 + 提交到 Argo + 流式日志 + 生成报告
""")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd in ("validate", "compile", "run"):
        if len(sys.argv) < 3:
            _error(f"用法: python -m workflows.pipeline.cli {cmd} <mf-workflow.yaml>")
            sys.exit(1)
        yaml_path = sys.argv[2]

        dispatch = {
            "validate": cmd_validate,
            "compile": cmd_compile,
            "run": cmd_run,
        }
        sys.exit(dispatch[cmd](yaml_path))
    else:
        _error(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
