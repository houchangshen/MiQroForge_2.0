#!/usr/bin/env bash
# =============================================================================
# mf2 — MiQroForge 2.0 Developer CLI
#
# 用法：bash scripts/mf2.sh <command> [args]
#
# Commands:
#   status              检测本机开发环境（等同于 check_env.sh）
#   ui [options]        启动 MiQroForge WebUI（API + 前端），打印访问地址
#                         --prod         先构建前端，由 FastAPI 统一服务（单端口，适合远端）
#                         --api-port N   API 端口（默认 8000）
#                         --ui-port N    前端开发服务器端口（默认 5173，仅 dev 模式）
#   submit <yaml>       提交工作流到 miqroforge-v2 namespace
#   list                列出 miqroforge-v2 下的所有工作流
#   logs <name>         查看指定工作流的日志
#   validate <mf.yaml>  校验 MF 格式工作流（I/O 类型、参数、DAG）
#   compile <mf.yaml>   校验 + 编译为 Argo Workflow YAML
#   run <mf.yaml>       校验 + 编译 + 提交到 Argo + 流式日志
#   nodes list          列出所有已索引的节点（需先运行 nodes reindex）
#   nodes search <q>    按名称/标签/描述搜索节点
#   nodes info <name>   显示节点完整信息（端口、参数、资源）
#   nodes reindex       重新扫描生成 node_index.yaml
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auto-load .env if present (so users don't need to source it manually)
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

NAMESPACE="${ARGO_NAMESPACE:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

_info()  { echo -e "  ${BLUE}ℹ $1${NC}"; }
_ok()    { echo -e "  ${GREEN}✔ $1${NC}"; }
_warn()  { echo -e "  ${YELLOW}⚠ $1${NC}"; }
_error() { echo -e "  ${RED}✘ $1${NC}" >&2; exit 1; }

# ── status ────────────────────────────────────────────────────────────────────
cmd_status() {
    source "${SCRIPT_DIR}/check_env.sh"
    run_checks
}

# ── ui ────────────────────────────────────────────────────────────────────────
cmd_ui() {
    # 端口优先级：命令行参数 > 环境变量 > 默认值
    local api_port="${MF_API_PORT:-8100}"
    local ui_port="${MF_UI_PORT:-5173}"
    local prod_mode=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prod|--production) prod_mode=1; shift ;;
            --api-port) api_port="${2:?--api-port 需要值}"; shift 2 ;;
            --ui-port)  ui_port="${2:?--ui-port 需要值}";  shift 2 ;;
            *) shift ;;
        esac
    done

    # ── 端口检查：自己的进程就 kill，别人的就报错退出 ───────────────────────
    _check_port() {
        local port="$1"
        # 端口空闲则直接返回
        ss -tlnp 2>/dev/null | grep -q ":${port} " || return 0

        # 尝试用 fuser 找 PID（可能返回多个，空格分隔）
        local pids_str
        pids_str=$(fuser "${port}/tcp" 2>/dev/null || true)
        # fuser 输出末尾可能带空格，trim 一下
        pids_str=$(echo "$pids_str" | xargs)

        if [[ -n "$pids_str" ]]; then
            # fuser 可能返回多个 PID，逐个 kill
            local killed_any=0
            for pid in $pids_str; do
                _warn "端口 ${port} 被自身进程 PID ${pid} 占用，正在关闭..."
                kill "$pid" 2>/dev/null || true
                killed_any=1
            done

            if [[ $killed_any -eq 1 ]]; then
                sleep 1
                # 验证端口是否真的释放了
                if ! ss -tlnp 2>/dev/null | grep -q ":${port} "; then
                    _ok "端口 ${port} 已释放"
                    return 0
                fi
                _warn "端口 ${port} 未能完全释放，稍后重试..."
                sleep 2
            fi
        fi

        # 再次检查，仍被占用则报错
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            _error "端口 ${port} 无法释放。请在 .env 中设置 MF_API_PORT 或 MF_UI_PORT 换用其他端口，例如：
  MF_API_PORT=8200 bash scripts/mf2.sh ui --prod"
        fi
    }

    _check_port "$api_port"
    [[ $prod_mode -eq 0 ]] && _check_port "$ui_port"

    # ── prod 模式：先构建前端 ───────────────────────────────────────────────
    if [[ $prod_mode -eq 1 ]]; then
        _info "构建前端静态文件..."
        (cd "${SCRIPT_DIR}/../frontend" && npm run build 2>&1 | tail -5)
        _ok "前端构建完成 → frontend/dist/"
        echo
    fi

    # ── 判断是否远端 SSH 会话（只判断有无，不读地址） ───────────────────────
    local is_remote=0
    [[ -n "${SSH_CONNECTION:-}" ]] && is_remote=1

    # ── 打印访问地址 ────────────────────────────────────────────────────────
    echo
    echo -e "${BLUE}${BOLD}══ MiQroForge 2.0 WebUI ══${NC}"
    echo

    if [[ $is_remote -eq 1 ]]; then
        echo -e "  ${YELLOW}检测到远端 SSH 会话，请在本地电脑新开一个终端执行：${NC}"
        echo
        if [[ $prod_mode -eq 1 ]]; then
            echo -e "    ${GREEN}ssh -L ${api_port}:localhost:${api_port} -N <你的SSH别名>${NC}"
            echo
            echo -e "  端口转发建立后，打开："
            echo -e "  ${GREEN}➜  Local:   http://localhost:${api_port}/${NC}"
            echo -e "  ${GREEN}➜  API Doc: http://localhost:${api_port}/docs${NC}"
        else
            echo -e "    ${GREEN}ssh -L ${ui_port}:localhost:${ui_port} \\${NC}"
            echo -e "    ${GREEN}    -L ${api_port}:localhost:${api_port} \\${NC}"
            echo -e "    ${GREEN}    -N <你的SSH别名>${NC}"
            echo
            echo -e "  端口转发建立后，打开："
            echo -e "  ${GREEN}➜  Local:   http://localhost:${ui_port}/${NC}"
            echo -e "  ${GREEN}➜  API Doc: http://localhost:${api_port}/docs${NC}"
        fi
    else
        if [[ $prod_mode -eq 1 ]]; then
            echo -e "  ${GREEN}➜  Local:   http://localhost:${api_port}/${NC}"
            echo -e "  ${GREEN}➜  API Doc: http://localhost:${api_port}/docs${NC}"
        else
            echo -e "  ${GREEN}➜  Local:   http://localhost:${ui_port}/${NC}"
            echo -e "  ${GREEN}➜  API Doc: http://localhost:${api_port}/docs${NC}"
        fi
    fi

    echo
    echo -e "  ${YELLOW}按 Ctrl+C 停止服务${NC}"
    echo

    # ── 启动进程 ────────────────────────────────────────────────────────────
    cd "${SCRIPT_DIR}/.."
    local pids=()

    uvicorn api.main:app --host 0.0.0.0 --port "$api_port" --reload &
    pids+=($!)

    if [[ $prod_mode -eq 0 ]]; then
        (cd frontend && npm install && npm run dev -- --host 0.0.0.0 --port "$ui_port") &
        pids+=($!)
    fi

    cleanup() {
        echo
        _info "正在关闭服务..."
        for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
        wait 2>/dev/null || true
        _ok "已停止"
    }
    trap cleanup EXIT INT TERM
    wait
}

# ── submit ────────────────────────────────────────────────────────────────────
cmd_submit() {
    local yaml="${1:-}"
    [[ -z "$yaml" ]] && _error "用法：mf2 submit <workflow.yaml>"
    [[ -f "$yaml" ]] || _error "文件不存在：$yaml"
    argo submit "$yaml" --namespace "${NAMESPACE}"
}

# ── list ──────────────────────────────────────────────────────────────────────
cmd_list() {
    argo list --namespace "${NAMESPACE}"
}

# ── logs ──────────────────────────────────────────────────────────────────────
cmd_logs() {
    local name="${1:-}"
    [[ -z "$name" ]] && _error "用法：mf2 logs <workflow-name>"
    argo logs "$name" --namespace "${NAMESPACE}"
}

# ── validate (MF pipeline) ────────────────────────────────────────────────────
cmd_validate() {
    local yaml="${1:-}"
    [[ -z "$yaml" ]] && _error "用法：mf2 validate <mf-workflow.yaml>"
    [[ -f "$yaml" ]] || _error "文件不存在：$yaml"
    python -m workflows.pipeline.cli validate "$yaml"
}

# ── compile (MF pipeline) ────────────────────────────────────────────────────
cmd_compile() {
    local yaml="${1:-}"
    [[ -z "$yaml" ]] && _error "用法：mf2 compile <mf-workflow.yaml>"
    [[ -f "$yaml" ]] || _error "文件不存在：$yaml"
    python -m workflows.pipeline.cli compile "$yaml"
}

# ── run (MF pipeline) ────────────────────────────────────────────────────────
cmd_run_mf() {
    local yaml="${1:-}"
    [[ -z "$yaml" ]] && _error "用法：mf2 run <mf-workflow.yaml>"
    [[ -f "$yaml" ]] || _error "文件不存在：$yaml"
    python -m workflows.pipeline.cli run "$yaml"
}

# ── nodes (node index) ────────────────────────────────────────────────────────
cmd_nodes() {
    local subcmd="${1:-list}"
    shift || true
    case "$subcmd" in
        list)
            python -m node_index.cli list
            ;;
        search)
            [[ -z "${1:-}" ]] && _error "用法：mf2 nodes search <query>"
            python -m node_index.cli search "$@"
            ;;
        info)
            [[ -z "${1:-}" ]] && _error "用法：mf2 nodes info <name>"
            python -m node_index.cli info "$1"
            ;;
        reindex)
            python -m node_index.cli reindex
            ;;
        *)
            _error "未知子命令：mf2 nodes $subcmd  （可用：list|search|info|reindex）"
            ;;
    esac
}

# ── help ──────────────────────────────────────────────────────────────────────
cmd_help() {
    echo -e "
${BLUE}${BOLD}mf2 — MiQroForge 2.0 Developer CLI${NC}

${BOLD}用法：${NC}bash scripts/mf2.sh <command> [args]

${BOLD}Commands：${NC}
  ${GREEN}status${NC}                    检测开发环境状态
  ${GREEN}ui${NC}                        启动 MiQroForge WebUI（dev 模式，Vite HMR + API 双进程）
  ${GREEN}ui --prod${NC}                 先构建前端再启动（单端口，测试生产构建用）
  ${GREEN}ui --api-port N${NC}           指定 API 端口（默认 8100）
  ${GREEN}ui --ui-port N${NC}            指定前端开发服务器端口（默认 5173）
  ${GREEN}submit${NC} <yaml>             提交原生 Argo 工作流到 ${NAMESPACE} namespace
  ${GREEN}list${NC}                      列出所有工作流
  ${GREEN}logs${NC} <name>              查看工作流日志
  ${GREEN}validate${NC} <mf.yaml>        校验 MF 格式工作流（I/O 类型、参数、DAG）
  ${GREEN}compile${NC} <mf.yaml>         校验 + 编译为 Argo Workflow YAML
  ${GREEN}run${NC} <mf.yaml>             校验 + 编译 + 提交到 Argo + 流式日志
  ${GREEN}nodes list${NC}                列出所有已索引的节点
  ${GREEN}nodes search${NC} <q>          按名称/标签/描述搜索节点
  ${GREEN}nodes info${NC} <name>         显示节点完整信息（端口、参数、资源）
  ${GREEN}nodes reindex${NC}             重新扫描 nodes/ 目录并生成 node_index.yaml

${BOLD}WebUI 访问：${NC}
  启动后直接在浏览器打开输出的地址（VS Code 会自动转发端口）：
    dev 模式  → http://localhost:5173   （Vite HMR，修改代码立即生效）
    prod 模式 → http://localhost:8100   （构建产物，单端口）

${BOLD}Argo UI：${NC}
  通过 MiQroForge API 内置代理访问，无需额外端口转发：
    http://localhost:8100/argo/
  或点击前端顶部栏的「Argo UI ↗」链接。

${BOLD}示例：${NC}
  bash scripts/mf2.sh ui
  bash scripts/mf2.sh ui --prod
  bash scripts/mf2.sh ui --prod --api-port 9000
  bash scripts/mf2.sh validate workflows/examples/orca-h2o-thermo-mf.yaml
  bash scripts/mf2.sh run workflows/examples/orca-h2o-thermo-mf.yaml
  bash scripts/mf2.sh nodes reindex
  bash scripts/mf2.sh nodes search orca
  bash scripts/mf2.sh nodes info orca-geo-opt
"
}

# ── 分发命令 ──────────────────────────────────────────────────────────────────
case "${1:-help}" in
    status)   cmd_status ;;
    ui)       shift; cmd_ui "$@" ;;
    submit)   cmd_submit "${2:-}" ;;
    list)     cmd_list ;;
    logs)     cmd_logs "${2:-}" ;;
    validate) cmd_validate "${2:-}" ;;
    compile)  cmd_compile "${2:-}" ;;
    run)      cmd_run_mf "${2:-}" ;;
    nodes)    cmd_nodes "${2:-list}" "${3:-}" "${4:-}" ;;
    *)        cmd_help ;;
esac
