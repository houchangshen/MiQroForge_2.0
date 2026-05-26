"""MiQroForge 2.0 — FastAPI 网关。

路由版本前缀：/api/v1/

启动方式（开发）：
    uvicorn api.main:app --reload --port 8000

启动方式（生产，同时服务前端静态文件）：
    cd /path/to/MiQroForge_2.0/frontend && npm run build
    uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import get_settings
from api.routers import nodes, runs, workflows
from api.routers import files
from api.routers import agents
from api.routers import admin, auth, usage
from api.routers import projects

logger = logging.getLogger(__name__)

# 构建好的前端目录（npm run build 输出）
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
_serve_static = FRONTEND_DIST.exists()


def _sync_argo_ttl() -> None:
    """启动时同步 TTL 策略到 Argo workflow-controller ConfigMap（best-effort）。"""
    settings = get_settings()
    ns = "argo"  # Argo controller ConfigMap 始终在 argo namespace 中
    ttl_success = settings.argo_ttl_success_seconds
    ttl_failure = settings.argo_ttl_failure_seconds

    patch = {
        "data": {
            "workflowDefaults": json.dumps({
                "spec": {
                    "ttlStrategy": {
                        "secondsAfterSuccess": ttl_success,
                        "secondsAfterFailure": ttl_failure,
                    }
                }
            })
        }
    }

    try:
        result = subprocess.run(
            [
                "kubectl", "patch", "configmap", "workflow-controller-configmap",
                "--namespace", ns,
                "--type", "merge",
                "-p", json.dumps(patch),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info(
                "Argo TTL synced: success=%ds, failure=%ds", ttl_success, ttl_failure
            )
        else:
            logger.warning(
                "Argo TTL sync failed (non-fatal): %s", result.stderr.strip()
            )
    except Exception as exc:
        logger.warning("Argo TTL sync failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _sync_argo_ttl()
    yield


# ── 应用实例 ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MiQroForge 2.0 API",
    description=(
        "MiQroForge 2.0 科学计算平台 API。\n\n"
        "提供节点目录查询、工作流校验/编译/提交、运行监控、Agent 智能编排等功能。\n\n"
        "Phase 2 Agent 端点：\n"
        "- `POST /api/v1/agents/plan` — Planner Agent（意图 → 语义工作流）\n"
        "- `POST /api/v1/agents/yaml` — YAML Coder Agent（语义 → MF YAML）\n"
        "- `POST /api/v1/agents/node` — Node Generator Agent（生成新节点）"
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API 路由注册 ──────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(nodes.router, prefix=API_PREFIX)
app.include_router(workflows.router, prefix=API_PREFIX)
app.include_router(runs.router, prefix=API_PREFIX)
app.include_router(files.router, prefix=API_PREFIX)
app.include_router(agents.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(usage.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
from api.routers import memory
app.include_router(memory.router, prefix=API_PREFIX)


# ── 系统端点 ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "miqroforge-api",
        "version": "0.1.0",
        "serving_frontend": _serve_static,
    }


@app.get("/api/v1/config", tags=["system"])
def get_config() -> dict:
    """返回前端所需的运行时配置。"""
    return {}


# 仅在没有静态文件服务时注册 JSON 根路由，
# 避免覆盖 SPA 的 index.html
if not _serve_static:
    @app.get("/", tags=["system"])
    def root() -> dict:
        return {
            "service": "MiQroForge 2.0 API",
            "docs": "/docs",
            "health": "/health",
            "api_prefix": API_PREFIX,
        }


# ── 前端静态文件（prod 模式）─────────────────────────────────────────────────
# 必须在所有 API 路由之后挂载，API 路由优先匹配。
if _serve_static:
    from fastapi.responses import FileResponse

    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """SPA fallback：非 API / 非静态资源的路径返回 index.html。"""
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    # 根路径
    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(str(FRONTEND_DIST / "index.html"))
