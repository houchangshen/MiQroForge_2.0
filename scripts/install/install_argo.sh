#!/usr/bin/env bash
# =============================================================================
# MiQroForge 2.0 — Install Argo Workflow
#
# 用法：
#   ./install_argo.sh              # 安装 CLI + 部署 Server
#   ./install_argo.sh --cli-only   # 仅安装 Argo CLI
#   ./install_argo.sh --server-only # 仅部署 Argo Server 到集群
#
# 版本变量可通过环境变量覆盖：
#   ARGO_VERSION=v3.6.2 ./install_argo.sh
# =============================================================================
set -euo pipefail

ARGO_VERSION="${ARGO_VERSION:-v3.6.2}"
ARGO_NAMESPACE="argo"
MF_NAMESPACE="miqroforge"

CLI_ONLY=false
SERVER_ONLY=false
for arg in "$@"; do
    [[ "$arg" == "--cli-only" ]]    && CLI_ONLY=true
    [[ "$arg" == "--server-only" ]] && SERVER_ONLY=true
done

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "  ${BLUE}ℹ $1${NC}"; }
success() { echo -e "  ${GREEN}✔ $1${NC}"; }
warn()    { echo -e "  ${YELLOW}⚠ $1${NC}"; }
error()   { echo -e "  ${RED}✘ $1${NC}" >&2; exit 1; }

# ── 1. 安装 Argo CLI ──────────────────────────────────────────────────────────
install_cli() {
    if command -v argo &>/dev/null; then
        success "Argo CLI 已安装 ($(argo version --short 2>/dev/null | head -1))，跳过。"
        return
    fi

    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case "${ARCH}" in
        x86_64)        ARCH="amd64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *) error "不支持的架构: ${ARCH}" ;;
    esac

    info "下载 Argo CLI ${ARGO_VERSION} (${OS}/${ARCH})..."
    local filename="argo-${OS}-${ARCH}.gz"
    local url="https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/${filename}"

    curl -fsSLo "/tmp/${filename}" "${url}"
    gunzip -f "/tmp/${filename}"
    local binary="/tmp/argo-${OS}-${ARCH}"
    chmod +x "${binary}"
    sudo mv "${binary}" /usr/local/bin/argo

    success "Argo CLI 安装完成：$(argo version --short 2>/dev/null | head -1)"
}

# ── 2. 部署 Argo Workflow Server 到集群 ───────────────────────────────────────
install_server() {
    if ! command -v kubectl &>/dev/null; then
        error "kubectl 未安装，无法部署 Argo Server。"
    fi
    if ! kubectl cluster-info &>/dev/null 2>&1; then
        error "当前无可用 Kubernetes 集群，请先配置 kubeconfig。"
    fi

    # 创建 argo 命名空间
    if kubectl get namespace "${ARGO_NAMESPACE}" &>/dev/null 2>&1; then
        info "namespace '${ARGO_NAMESPACE}' 已存在，跳过创建。"
    else
        info "创建 namespace '${ARGO_NAMESPACE}'..."
        kubectl create namespace "${ARGO_NAMESPACE}"
    fi

    # 创建 miqroforge 命名空间
    if kubectl get namespace "${MF_NAMESPACE}" &>/dev/null 2>&1; then
        info "namespace '${MF_NAMESPACE}' 已存在，跳过创建。"
    else
        info "创建 namespace '${MF_NAMESPACE}'..."
        kubectl create namespace "${MF_NAMESPACE}"
    fi

    # 部署 Argo Workflow
    info "部署 Argo Workflow ${ARGO_VERSION} 到集群..."
    local manifest_url="https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/install.yaml"

    local argo_exists=false
    if kubectl get deployment -n "${ARGO_NAMESPACE}" workflow-controller &>/dev/null 2>&1; then
        argo_exists=true
        warn "检测到已有 Argo Workflow Controller，跳过官方 manifest 安装。"
        warn "如需升级 Argo 版本，请手动执行："
        warn "  kubectl apply -n ${ARGO_NAMESPACE} -f ${manifest_url}"
    else
        kubectl apply -n "${ARGO_NAMESPACE}" -f "${manifest_url}"
    fi

    # 应用项目自定义配置
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local infra_dir="${SCRIPT_DIR}/../../infrastructure"

    if [[ -f "${infra_dir}/k8s/namespace.yaml" ]]; then
        info "应用 k8s 命名空间配置..."
        kubectl apply -f "${infra_dir}/k8s/namespace.yaml"
    fi
    if [[ -f "${infra_dir}/k8s/rbac.yaml" ]]; then
        info "应用 RBAC 配置..."
        kubectl apply -f "${infra_dir}/k8s/rbac.yaml"
    fi
    if [[ -f "${infra_dir}/argo/config/workflow-controller-configmap.yaml" ]]; then
        if $argo_exists; then
            warn "Argo 已安装，跳过 configmap 覆盖（保留现有配置）。"
            info "如需更新 configmap，请手动执行："
            info "  kubectl apply -n ${ARGO_NAMESPACE} -f ${infra_dir}/argo/config/workflow-controller-configmap.yaml"
        else
            info "应用 Argo 控制器配置..."
            kubectl apply -n "${ARGO_NAMESPACE}" \
                -f "${infra_dir}/argo/config/workflow-controller-configmap.yaml"
        fi
    fi

    # 等待 Argo Server pod 就绪（最多 120 秒）
    info "等待 Argo Server 就绪..."
    kubectl wait --for=condition=available deployment/argo-server \
        -n "${ARGO_NAMESPACE}" --timeout=120s \
        || warn "等待超时，Argo Server 可能仍在启动中，请稍后用 kubectl get pods -n argo 检查。"

    success "Argo Workflow Server 部署完成。"
    info "访问 UI：kubectl -n argo port-forward deployment/argo-server 2746:2746"
    info "然后打开 https://localhost:2746"
}

# ── 主逻辑 ────────────────────────────────────────────────────────────────────
if $SERVER_ONLY; then
    install_server
elif $CLI_ONLY; then
    install_cli
else
    install_cli
    install_server
fi
