#!/usr/bin/env bash
# =============================================================================
# MiQroForge 2.0 — 基础设施初始化
# 启动 Docker、安装 k3s、部署 Argo Workflow Server，最后写入环境检测 log。
#
# 用法：sudo bash scripts/setup_infra.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs/setup"
LOG_FILE="${LOG_DIR}/setup_infra_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "${LOG_DIR}"

# Auto-load .env if present（与 mf2.sh 保持一致）
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# 同时输出到终端和 log（去掉颜色码保证 log 可读）
exec > >(tee >(sed 's/\x1b\[[0-9;]*m//g' >> "${LOG_FILE}")) 2>&1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

section() { echo -e "\n${BLUE}${BOLD}── $1 ──${NC}"; }
success() { echo -e "  ${GREEN}✔ $1${NC}"; }
info()    { echo -e "  ${BLUE}ℹ $1${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠ $1${NC}"; }
error()   { echo -e "  ${RED}✘ $1${NC}" >&2; exit 1; }

echo -e "${BLUE}${BOLD}══════════════════════════════════════════════${NC}"
echo -e "${BLUE}${BOLD}   MiQroForge 2.0 — Infrastructure Setup      ${NC}"
echo -e "${BLUE}${BOLD}══════════════════════════════════════════════${NC}"
echo "  Started: $(date)"

# ── 1. Docker Daemon ──────────────────────────────────────────────────────────
section "1 / 4  Docker Daemon"
if systemctl is-active --quiet docker; then
    success "Docker daemon 已在运行，跳过。"
else
    info "启动 Docker daemon..."
    systemctl start docker
    systemctl enable docker
    success "Docker daemon 已启动并设为开机自启。"
fi

# ── 2 & 3. Kubernetes 集群 + kubeconfig ──────────────────────────────────────
section "2 / 4  Kubernetes 集群"
KUBE_DIR="/home/${SUDO_USER:-$USER}/.kube"
KUBE_CONFIG="${KUBE_DIR}/config"

# 优先检查常见的现有 kubeconfig 位置（kubeadm、云平台等）
EXISTING_KUBECONFIG=""
for candidate in /etc/kubernetes/admin.conf /root/.kube/config; do
    if [[ -f "$candidate" ]]; then
        EXISTING_KUBECONFIG="$candidate"
        break
    fi
done

if [[ -n "$EXISTING_KUBECONFIG" ]]; then
    info "检测到已有集群配置：${EXISTING_KUBECONFIG}"
    info "跳过 k3s 安装，直接使用现有集群。"
    section "3 / 4  配置 kubeconfig"
    mkdir -p "${KUBE_DIR}"
    cp "${EXISTING_KUBECONFIG}" "${KUBE_CONFIG}"
    chown "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "${KUBE_DIR}" "${KUBE_CONFIG}"
    chmod 600 "${KUBE_CONFIG}"
    success "kubeconfig 已从 ${EXISTING_KUBECONFIG} 写入 ${KUBE_CONFIG}"
elif command -v k3s &>/dev/null && systemctl is-active --quiet k3s; then
    success "k3s 已在运行，跳过。"
    section "3 / 4  配置 kubeconfig"
    mkdir -p "${KUBE_DIR}"
    cp /etc/rancher/k3s/k3s.yaml "${KUBE_CONFIG}"
    chown "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "${KUBE_DIR}" "${KUBE_CONFIG}"
    chmod 600 "${KUBE_CONFIG}"
    success "kubeconfig 已写入 ${KUBE_CONFIG}"
else
    warn "未检测到现有集群，将安装 k3s 单节点集群（仅适合开发/测试）。"
    warn "如果你有远程集群，请 Ctrl-C 中断，手动配置 kubeconfig 后重新运行。"
    sleep 5
    if curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh \
        | INSTALL_K3S_MIRROR=cn sh - ; then
        info "已通过国内镜像源安装。"
    else
        warn "国内镜像源失败，尝试官方源..."
        curl -sfL https://get.k3s.io | sh -
    fi
    info "等待 k3s 节点就绪..."
    for i in $(seq 1 30); do
        if k3s kubectl get node &>/dev/null 2>&1; then
            success "k3s 集群就绪。"
            break
        fi
        [[ $i -eq 30 ]] && error "k3s 启动超时，请检查 journalctl -u k3s"
        sleep 2
    done
    section "3 / 4  配置 kubeconfig"
    mkdir -p "${KUBE_DIR}"
    cp /etc/rancher/k3s/k3s.yaml "${KUBE_CONFIG}"
    chown "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "${KUBE_DIR}" "${KUBE_CONFIG}"
    chmod 600 "${KUBE_CONFIG}"
    success "kubeconfig 已写入 ${KUBE_CONFIG}"
fi

# ── 4. Argo Workflow Server ───────────────────────────────────────────────────
section "4 / 5  Argo Workflow Server"
export KUBECONFIG="${KUBE_CONFIG}"
bash "${SCRIPT_DIR}/install/install_argo.sh" --server-only

# ── 5. Workspace PVC ──────────────────────────────────────────────────────────
# 从 .env 已自动加载 ARGO_NAMESPACE，若未配置则使用默认值
ARGO_NAMESPACE="${ARGO_NAMESPACE:-miqroforge-v2}"

section "5 / 5  Workspace PVC（${ARGO_NAMESPACE}）"
# hostPath 路径与 namespace 动态替换后再 apply
if kubectl get pvc "${ARGO_NAMESPACE}" -n "${ARGO_NAMESPACE}" &>/dev/null 2>&1; then
    success "Workspace PVC ${ARGO_NAMESPACE} 已存在，跳过。"
else
    info "部署 Workspace PV/PVC（hostPath → ${PROJECT_ROOT}/userdata/workspace）..."
    mkdir -p "${PROJECT_ROOT}/userdata/workspace"
    sed "s|__MF_PROJECT_ROOT__|${PROJECT_ROOT}|g; s|__MF_NAMESPACE__|${ARGO_NAMESPACE}|g" \
        "${PROJECT_ROOT}/infrastructure/k8s/workspace.yaml" \
        | kubectl apply -f -
    # 等待 PVC 绑定
    for i in $(seq 1 15); do
        STATUS=$(kubectl get pvc "${ARGO_NAMESPACE}" -n "${ARGO_NAMESPACE}" \
            -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        if [[ "$STATUS" == "Bound" ]]; then
            success "${ARGO_NAMESPACE} PVC 已 Bound。"
            break
        fi
        [[ $i -eq 15 ]] && warn "PVC 未在 30s 内绑定，请手动检查：kubectl get pvc -n ${ARGO_NAMESPACE}"
        sleep 2
    done
fi

# ── 最终环境检测，结果写入 log ────────────────────────────────────────────────
echo
echo -e "${BOLD}══ 最终环境检测 ══${NC}"
source "${SCRIPT_DIR}/check_env.sh"
run_checks

echo
echo "  Completed: $(date)"
echo "  Log 已保存至: ${LOG_FILE}"
