#!/usr/bin/env bash
# =============================================================================
# MiQroForge 2.0 — Environment Check
# 检测 Phase 1 所需全部依赖是否已安装，输出彩色报告。
#
# 用法：
#   直接运行    ./scripts/check_env.sh          # 打印报告，缺失则退出码非 0
#   被 source   source ./scripts/check_env.sh   # 填充 MF_MISSING 数组供调用方使用
# =============================================================================
set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
PASS="${GREEN}✔${NC}"; FAIL="${RED}✘${NC}"; WARN="${YELLOW}⚠${NC}"

# ── 收集缺失项（key 供 setup 脚本判断，value 供显示） ──────────────────────
declare -A MF_MISSING   # key → 缺失原因描述

_ok()   { echo -e "  ${PASS} ${1}"; }
_fail() { echo -e "  ${FAIL} ${1}"; MF_MISSING["$2"]="${3:-$1}"; }
_warn() { echo -e "  ${WARN} ${1}"; }

# ── 各组件检测函数 ─────────────────────────────────────────────────────────

check_docker() {
    if command -v docker &>/dev/null; then
        local v; v=$(docker --version 2>/dev/null | grep -oP '[\d.]+' | head -1)
        if docker info &>/dev/null 2>&1; then
            _ok "Docker ${v} (daemon running)"
        else
            _warn "Docker ${v} installed — daemon not running (run: sudo systemctl start docker)"
            MF_MISSING["docker-daemon"]="Docker 已安装但 daemon 未启动"
        fi
    else
        _fail "Docker: not found" "docker" "Docker"
    fi
}

check_kubectl() {
    if command -v kubectl &>/dev/null; then
        local v; v=$(kubectl version --client -o json 2>/dev/null | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(d['clientVersion']['gitVersion'])" 2>/dev/null \
            || kubectl version --client --short 2>/dev/null | grep -oP 'v[\d.]+' | head -1)
        _ok "kubectl ${v}"
    else
        _fail "kubectl: not found" "kubectl" "kubectl"
    fi
}

check_k8s_cluster() {
    if ! command -v kubectl &>/dev/null; then return; fi
    if kubectl cluster-info &>/dev/null 2>&1; then
        local ctx; ctx=$(kubectl config current-context 2>/dev/null || echo "unknown")
        _ok "Kubernetes cluster reachable (context: ${ctx})"
    else
        _warn "Kubernetes cluster: kubectl 已安装但当前无可用集群"
        MF_MISSING["k8s-cluster"]="无可用 Kubernetes 集群"
    fi
}

check_argo_cli() {
    if command -v argo &>/dev/null; then
        local v; v=$(argo version --short 2>/dev/null | grep -oP 'v[\d.]+' | head -1 || echo "unknown")
        _ok "Argo CLI ${v}"
    else
        _fail "Argo CLI: not found" "argo-cli" "Argo CLI"
    fi
}

check_argo_server() {
    if ! command -v kubectl &>/dev/null; then return; fi
    if ! kubectl cluster-info &>/dev/null 2>&1; then return; fi
    if kubectl get namespace argo &>/dev/null 2>&1; then
        local pods; pods=$(kubectl get pods -n argo --no-headers 2>/dev/null | grep -c "Running" || echo 0)
        if [[ "$pods" -gt 0 ]]; then
            _ok "Argo Workflow Server (namespace: argo, running pods: ${pods})"
        else
            _warn "Argo namespace 存在但无 Running pods (可能正在启动)"
            MF_MISSING["argo-server"]="Argo Server pods 未 Running"
        fi
    else
        _fail "Argo Workflow Server: namespace 'argo' 不存在" "argo-server" "Argo Workflow Server"
    fi
}

check_python() {
    if command -v python3 &>/dev/null; then
        local major minor ver
        ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
        major=$(python3 -c "import sys; print(sys.version_info.major)")
        minor=$(python3 -c "import sys; print(sys.version_info.minor)")
        if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
            _ok "Python ${ver}"
        else
            _warn "Python ${ver} — 需要 >= 3.10"
            MF_MISSING["python"]="Python 版本低于 3.10 (当前 ${ver})"
        fi
    else
        _fail "Python3: not found" "python" "Python >= 3.10"
    fi
}

check_python_pkg() {
    local display="$1" import_expr="$2" key="$3"
    if python3 -c "$import_expr" &>/dev/null 2>&1; then
        local ver; ver=$(python3 -c "$import_expr; print(__ver__)" 2>/dev/null || echo "installed")
        _ok "${display}: ${ver}"
    else
        _fail "${display}: not installed" "$key" "$display"
    fi
}

check_python_deps() {
    # pydantic v2
    if python3 -c "import pydantic; assert int(pydantic.VERSION.split('.')[0]) >= 2" &>/dev/null 2>&1; then
        local v; v=$(python3 -c "import pydantic; print(pydantic.VERSION)")
        _ok "Pydantic ${v}"
    else
        _fail "Pydantic v2: not installed" "pydantic" "Pydantic >= 2.0"
    fi

    # pytest
    if command -v pytest &>/dev/null; then
        local v; v=$(pytest --version 2>&1 | grep -oP '[\d.]+' | head -1)
        _ok "pytest ${v}"
    else
        _fail "pytest: not found" "pytest" "pytest"
    fi

    # pyyaml
    if python3 -c "import yaml; __ver__ = yaml.__version__" &>/dev/null 2>&1; then
        local v; v=$(python3 -c "import yaml; print(yaml.__version__)")
        _ok "PyYAML ${v}"
    else
        _fail "PyYAML: not installed" "pyyaml" "PyYAML"
    fi

    # python-dotenv
    if python3 -c "import dotenv" &>/dev/null 2>&1; then
        local v; v=$(python3 -c "import dotenv; print(dotenv.__version__)" 2>/dev/null || echo "installed")
        _ok "python-dotenv ${v}"
    else
        _fail "python-dotenv: not installed" "python-dotenv" "python-dotenv"
    fi
}

# ── 主逻辑 ────────────────────────────────────────────────────────────────────

run_checks() {
    echo -e "\n${BLUE}${BOLD}══════════════════════════════════════════════${NC}"
    echo -e "${BLUE}${BOLD}   MiQroForge 2.0 — Phase 1 Environment Check  ${NC}"
    echo -e "${BLUE}${BOLD}══════════════════════════════════════════════${NC}\n"

    echo -e "${BOLD}[ 容器与编排 ]${NC}"
    check_docker
    check_kubectl
    check_k8s_cluster

    echo
    echo -e "${BOLD}[ Argo Workflow ]${NC}"
    check_argo_cli
    check_argo_server

    echo
    echo -e "${BOLD}[ Python 环境 ]${NC}"
    check_python
    check_python_deps

    echo
    echo -e "${BOLD}[ 检测结果 ]${NC}"
    if [[ -z "${MF_MISSING[*]:-}" ]]; then
        echo -e "  ${GREEN}${BOLD}✔ 所有依赖已就绪，可以开始 Phase 1 开发！${NC}"
        echo
        return 0
    else
        echo -e "  ${YELLOW}以下组件缺失或未就绪：${NC}"
        for key in "${!MF_MISSING[@]}"; do
            echo -e "    ${RED}•${NC} [${key}] ${MF_MISSING[$key]}"
        done
        echo

        # 区分两类问题，分别给出指引
        local has_infra=false has_python=false
        for key in "docker" "docker-daemon" "kubectl" "k8s-cluster" "argo-cli" "argo-server"; do
            [[ -v MF_MISSING["$key"] ]] && has_infra=true && break
        done
        for key in "python" "pydantic" "pytest" "pyyaml" "python-dotenv"; do
            [[ -v MF_MISSING["$key"] ]] && has_python=true && break
        done

        $has_infra  && echo -e "  基础设施问题（需要 sudo）：${BLUE}sudo bash scripts/setup_infra.sh${NC}"
        $has_python && echo -e "  Python 依赖问题：          ${BLUE}bash scripts/setup_phase1.sh${NC}"
        echo
        return 1
    fi
}

# 直接执行时运行检测；被 source 时只定义函数和变量，不自动执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_checks
fi
