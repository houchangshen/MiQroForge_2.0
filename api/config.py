"""API 环境配置。"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 启动时自动加载项目根目录的 .env 文件（若存在）
# override=False：已有系统环境变量优先，.env 只作补充
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env", override=False)


class Settings:
    """从环境变量读取 API 配置（.env 文件已在模块加载时写入 os.environ）。"""

    def __init__(self) -> None:
        # Argo 内部 API 地址（FastAPI 代理用，服务端到服务端）
        self.argo_server_url: str = os.environ.get(
            "ARGO_SERVER_URL", "https://localhost:2746"
        )
        self.argo_namespace: str = os.environ.get(
            "ARGO_NAMESPACE", ""
        )
        # PVC 名用 ARGO_NAMESPACE，方便开发版/稳定版并行
        self.argo_pvc_name: str = self.argo_namespace
        self.argo_token: str = os.environ.get("ARGO_TOKEN", "")

        # Argo UI 浏览器访问地址（返回给前端的链接）
        # 默认指向内置代理路径 /argo/，无需额外端口转发
        self.argo_ui_url: str = os.environ.get(
            "ARGO_UI_URL", "/argo/"
        )

        # 项目根目录（自动探测）
        self.project_root: Path = self._detect_project_root()

        # ── 多用户数据路径 ─────────────────────────────────────────────────
        # data_root: 所有用户数据的根目录（默认 userdata/）
        self.data_root: Path = Path(
            os.environ.get("MF_DATA_ROOT", str(self.project_root / "userdata"))
        )

        # 共享数据（所有用户可见）
        self.shared_root: Path = self.data_root / "shared"

        # 私有数据根目录
        self.users_root: Path = self.data_root / "users"

        # 认证数据
        self.auth_dir: Path = self.data_root / "auth"

        # 向后兼容：userdata_root 指向 data_root
        self.userdata_root: Path = self.data_root

        # Docker Hub 国内镜像加速（可选）
        self.docker_hub_mirror: str = os.environ.get("DOCKER_HUB_MIRROR", "")

        # ── LLM 配置（Phase 2）────────────────────────────────────────────────
        self.llm_provider: str = os.environ.get("MF_LLM_PROVIDER", "openai")
        self.llm_model: str = os.environ.get("MF_LLM_MODEL", "gpt-4o")

        # ── Argo TTL 策略 ───────────────────────────────────────────────────
        self.argo_ttl_success_seconds: int = int(
            os.environ.get("ARGO_TTL_SUCCESS_SECONDS", "2592000")  # 30 days
        )
        self.argo_ttl_failure_seconds: int = int(
            os.environ.get("ARGO_TTL_FAILURE_SECONDS", "5184000")  # 60 days
        )

        # 确保必要子目录存在
        self._ensure_userdata_dirs()
        self._init_auth()

    @staticmethod
    def _detect_project_root() -> Path:
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            if (parent / "CLAUDE.md").exists() or (parent / "nodes" / "schemas").exists():
                return parent
        return cwd

    def _ensure_userdata_dirs(self) -> None:
        """启动时自动创建必要的子目录（若不存在）。"""
        for sub in ["nodes", "workspace", "vectorstore", "projects"]:
            (self.data_root / sub).mkdir(parents=True, exist_ok=True)
        # 多用户结构
        self.shared_root.mkdir(parents=True, exist_ok=True)
        self.users_root.mkdir(parents=True, exist_ok=True)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        # 共享子目录
        (self.shared_root / "node_gen_memory").mkdir(parents=True, exist_ok=True)
        (self.shared_root / "vectorstore" / "chroma").mkdir(parents=True, exist_ok=True)

    def _init_auth(self) -> None:
        """初始化认证模块（生成 JWT 密钥 + 内部 token）。"""
        from api.auth import init_auth
        init_auth(self.auth_dir)
        # 自动生成内部 token（Pod 内 wrapper 脚本用），可选被 .env 覆盖
        if not os.environ.get("MF_INTERNAL_TOKEN"):
            token_file = self.auth_dir / "internal_token.key"
            if token_file.exists():
                os.environ["MF_INTERNAL_TOKEN"] = token_file.read_text().strip()
            else:
                token = secrets.token_hex(32)
                token_file.write_text(token)
                os.environ["MF_INTERNAL_TOKEN"] = token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
