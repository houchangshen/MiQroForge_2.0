"""Argo UI 反向代理。

将 /argo/{path} 的请求透明转发到 Argo server（忽略自签名证书）。
这样用户只需要对外暴露一个端口（MF_API_PORT），无需单独为 Argo 做端口转发。

挂载路径：/argo
转发目标：settings.argo_server_url（去掉 /argo 前缀后）

HTML 处理：
    Argo UI 的 HTML 中有 <base href="/">，导致它的 JS/CSS/API 路径都从根路径解析，
    与我们的 /api/v1/ 路由冲突，资源也无法加载。
    代理层将 HTML 响应中的 <base href="/"> 替换为 <base href="/argo/">，
    使 Argo UI 的所有相对路径都正确解析到 /argo/* 下，再由代理转发到 Argo server。
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request, Response

from api.config import get_settings

router = APIRouter(tags=["argo-proxy"])

_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

# 代理时需要剔除的逐跳首部
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-encoding",   # httpx 已解码，不要把 gzip 声明转发给客户端
    "content-length",     # 重新计算
    # 代理场景下需要剥离的安全头，避免浏览器端策略冲突
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
}


@router.api_route(
    "/argo",
    methods=list(_METHODS),
    include_in_schema=False,
)
@router.api_route(
    "/argo/{path:path}",
    methods=list(_METHODS),
    include_in_schema=False,
)
async def argo_proxy(request: Request, path: str = "") -> Response:
    """透明代理：将 /argo[/...] 转发到 Argo server，并修复 HTML base href。"""
    settings = get_settings()
    base = settings.argo_server_url.rstrip("/")

    # 拼装目标 URL（含 query string）
    target_path = f"/{path}" if path else "/"
    target_url = base + target_path
    if request.url.query:
        target_url += f"?{request.url.query}"

    # 过滤请求头
    req_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    body = await request.body()

    try:
        async with httpx.AsyncClient(
            verify=False,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=req_headers,
                content=body,
            )
    except httpx.ConnectError:
        return Response(
            content=b"Argo server unreachable. Check ARGO_SERVER_URL in .env.",
            status_code=502,
            media_type="text/plain",
        )
    except httpx.TimeoutException:
        return Response(content=b"Argo proxy timeout.", status_code=504, media_type="text/plain")

    # 过滤响应头
    resp_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    # ── HTML 修复 ────────────────────────────────────────────────────────────
    # Argo UI 的 HTML 包含 <base href="/">，导致所有资源路径从根解析而非 /argo/。
    # 替换为 <base href="/argo/"> 后，相对路径（JS/CSS/API）都正确归到 /argo/* 下，
    # 再由本代理转发给 Argo server。
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type and resp.content:
        html = resp.content.decode("utf-8", errors="replace")
        html = html.replace('<base href="/">', '<base href="/argo/">')
        return Response(
            content=html.encode("utf-8"),
            status_code=resp.status_code,
            headers=resp_headers,
            media_type="text/html; charset=utf-8",
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
    )
