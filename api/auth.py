"""认证模块 — JWT 创建/验证 + 密码哈希 + get_current_user 依赖。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
import yaml
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_SECRET_KEY_PATH: Path | None = None
_SECRET_KEY: str | None = None

ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer(auto_error=False)


def _get_secret_key_path() -> Path:
    global _SECRET_KEY_PATH
    if _SECRET_KEY_PATH is None:
        raise RuntimeError("auth module not initialized — call init_auth(auth_dir) first")
    return _SECRET_KEY_PATH


def init_auth(auth_dir: Path) -> None:
    """初始化认证模块。在 FastAPI startup 时调用一次。"""
    global _SECRET_KEY_PATH, _SECRET_KEY
    auth_dir.mkdir(parents=True, exist_ok=True)
    _SECRET_KEY_PATH = auth_dir / "jwt_secret.key"
    if _SECRET_KEY_PATH.exists():
        _SECRET_KEY = _SECRET_KEY_PATH.read_text().strip()
    else:
        _SECRET_KEY = secrets.token_hex(32)
        _SECRET_KEY_PATH.write_text(_SECRET_KEY)


def _load_secret() -> str:
    if _SECRET_KEY is None:
        p = _get_secret_key_path()
        if not p.exists():
            raise RuntimeError("jwt_secret.key not found — call init_auth() first")
        return p.read_text().strip()
    return _SECRET_KEY


def hash_password(password: str) -> str:
    """返回 bcrypt 哈希字符串（可直接存入 YAML）。"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码是否匹配已存储的哈希。"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_jwt(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, _load_secret(), algorithm=ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, _load_secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None


# ─── 用户账户存储（userdata/auth/users.yaml）───────────────────────────────

@dataclass
class CurrentUser:
    username: str
    role: str  # "admin" | "user"


def _load_users_yaml(auth_dir: Path) -> dict:
    users_file = auth_dir / "users.yaml"
    if not users_file.exists():
        return {"users": {}}
    with users_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"users": {}}


def authenticate_user(username: str, password: str, auth_dir: Path) -> CurrentUser | None:
    """验证用户名密码，成功返回 CurrentUser，失败返回 None。"""
    data = _load_users_yaml(auth_dir)
    users = data.get("users", {})
    entry = users.get(username)
    if entry is None:
        return None
    if not verify_password(password, entry["password_hash"]):
        return None
    return CurrentUser(username=username, role=entry.get("role", "user"))


def create_user_yaml(username: str, password_hash: str, role: str, display_name: str,
                     auth_dir: Path) -> None:
    """向 users.yaml 添加新用户（或更新已有用户密码）。"""
    data = _load_users_yaml(auth_dir)
    if "users" not in data:
        data["users"] = {}
    now = datetime.now(timezone.utc).isoformat()
    data["users"][username] = {
        "password_hash": password_hash,
        "display_name": display_name or username,
        "role": role,
        "created_at": now,
    }
    users_file = auth_dir / "users.yaml"
    users_file.parent.mkdir(parents=True, exist_ok=True)
    with open(users_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def user_exists(username: str, auth_dir: Path) -> bool:
    data = _load_users_yaml(auth_dir)
    return username in data.get("users", {})


def _check_internal_token(request) -> CurrentUser | None:
    """检查 X-Internal-Token + X-MF-User 头（Pod 内 wrapper 脚本使用）。"""
    if not isinstance(request, Request):
        return None
    token = request.headers.get("X-Internal-Token", "")
    username = request.headers.get("X-MF-User", "")
    if not token or not username:
        return None
    import os
    expected = os.environ.get("MF_INTERNAL_TOKEN", "")
    if not expected:
        return None
    if token == expected:
        return CurrentUser(username=username, role="user")
    return None


# ─── FastAPI 依赖 ──────────────────────────────────────────────────────────

async def get_current_user(
    request: "Request",
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser | None:
    """从 JWT 或 X-Internal-Token 提取当前用户。"""
    # 1. JWT
    if credentials is not None:
        payload = verify_jwt(credentials.credentials)
        if payload is not None:
            username = payload.get("sub")
            if username is not None:
                return CurrentUser(username=username, role=payload.get("role", "user"))
    # 2. Internal token（Pod 内 wrapper 脚本）
    return _check_internal_token(request)


async def require_user(
    user: CurrentUser | None = Depends(get_current_user),
) -> CurrentUser:
    """与 get_current_user 相同，但未认证时直接抛 401。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: CurrentUser = Depends(require_user),
) -> CurrentUser:
    """与 require_user 相同，但要求 role == 'admin'。"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
