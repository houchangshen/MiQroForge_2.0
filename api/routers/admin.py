"""管理员用量路由 — GET /admin/usage (跨用户聚合)。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.auth import require_admin, CurrentUser
from api.config import get_settings

router = APIRouter(tags=["admin"])


# ── JSONL 读取 ──

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ── 响应模型 ──

class UserTokenUsage(BaseModel):
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0


class UserComputeUsage(BaseModel):
    total_core_hours: float = 0.0
    total_gpu_hours: float = 0.0
    total_workflows: int = 0
    estimated_cost: float = 0.0


class AdminUserUsage(BaseModel):
    username: str
    token_usage: UserTokenUsage = Field(default_factory=UserTokenUsage)
    compute_usage: UserComputeUsage = Field(default_factory=UserComputeUsage)


class AdminUsageSummary(BaseModel):
    period_days: int
    total_users: int
    total_core_hours: float = 0.0
    total_gpu_hours: float = 0.0
    total_tokens: int = 0
    total_estimated_cost: float = 0.0
    currency: str = "USD"
    users: list[AdminUserUsage] = Field(default_factory=list)


# ── 端点 ──

@router.get("/admin/usage", response_model=AdminUsageSummary)
def get_admin_usage(
    days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(require_admin),
):
    settings = get_settings()
    users_dir = settings.users_root
    if not users_dir.exists():
        return AdminUsageSummary(period_days=days, total_users=0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    billing = _load_billing(settings)
    summary = AdminUsageSummary(
        period_days=days,
        total_users=0,
        currency=billing.get("currency", "USD"),
    )

    for user_dir in sorted(users_dir.iterdir()):
        if not user_dir.is_dir():
            continue
        usage_dir = user_dir / "usage"
        if not usage_dir.exists():
            continue

        username = user_dir.name
        user_entry = AdminUserUsage(username=username)

        # ── Token usage ──
        token_records = _read_jsonl(usage_dir / "llm_usage.jsonl")
        for r in token_records:
            try:
                ts = datetime.fromisoformat(r.get("finished_at", ""))
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue
            inp = r.get("input_tokens", 0) or 0
            out = r.get("output_tokens", 0) or 0
            total = r.get("total_tokens", 0) or (inp + out)
            user_entry.token_usage.total_calls += 1
            user_entry.token_usage.total_input_tokens += inp
            user_entry.token_usage.total_output_tokens += out
            user_entry.token_usage.total_tokens += total

        # ── Compute usage ──
        compute_records = _read_jsonl(usage_dir / "compute_usage.jsonl")
        for r in compute_records:
            try:
                ts = datetime.fromisoformat(r.get("recorded_at", ""))
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue
            core_h = r.get("core_hours", 0) or 0
            gpu_h = r.get("gpu_hours", 0) or 0
            user_entry.compute_usage.total_core_hours += core_h
            user_entry.compute_usage.total_gpu_hours += gpu_h
            user_entry.compute_usage.total_workflows += 1

        # ── Estimate costs from billing.yaml ──
        billing = _load_billing(settings)
        user_entry.token_usage.estimated_cost = round(
            (user_entry.token_usage.total_input_tokens / 1_000_000)
            * billing.get("llm_per_1m_input_tokens", {}).get("default", 1.0)
            + (user_entry.token_usage.total_output_tokens / 1_000_000)
            * billing.get("llm_per_1m_output_tokens", {}).get("default", 4.0),
            4,
        )
        user_entry.compute_usage.estimated_cost = round(
            user_entry.compute_usage.total_core_hours
            * billing.get("compute_per_core_hour", 0.05)
            + user_entry.compute_usage.total_gpu_hours
            * billing.get("compute_per_gpu_hour", 0.50),
            4,
        )

        # Only include users with actual usage in the period
        if (
            user_entry.token_usage.total_tokens > 0
            or user_entry.compute_usage.total_core_hours > 0
        ):
            summary.users.append(user_entry)
            summary.total_users += 1
            summary.total_core_hours += user_entry.compute_usage.total_core_hours
            summary.total_gpu_hours += user_entry.compute_usage.total_gpu_hours
            summary.total_tokens += user_entry.token_usage.total_tokens
            summary.total_estimated_cost += (
                user_entry.token_usage.estimated_cost
                + user_entry.compute_usage.estimated_cost
            )

    # Round totals
    summary.total_core_hours = round(summary.total_core_hours, 4)
    summary.total_gpu_hours = round(summary.total_gpu_hours, 4)
    summary.total_estimated_cost = round(summary.total_estimated_cost, 4)

    return summary


def _load_billing(settings) -> dict:
    """Load pricing from models.yaml (LLM) and compute_pricing.yaml (compute).
    
    Falls back to billing.yaml (deprecated) if new pricing files don't exist.
    """
    import yaml
    
    result: dict = {}
    models_path = settings.shared_root / "models.yaml"
    compute_path = settings.shared_root / "compute_pricing.yaml"
    billing_path = settings.userdata_root / "billing.yaml"
    
    # ── LLM pricing from models.yaml ──
    if models_path.exists():
        with models_path.open("r", encoding="utf-8") as f:
            models_cfg = yaml.safe_load(f) or {}
        
        # Per-model pricing (per 1M tokens)
        llm_input: dict[str, float] = {}
        llm_output: dict[str, float] = {}
        models = models_cfg.get("models", {})
        for name, cfg in models.items():
            if isinstance(cfg, dict):
                inp_price = cfg.get("input_price_per_1m")
                out_price = cfg.get("output_price_per_1m")
                if inp_price is not None:
                    llm_input[cfg.get("model_id", name)] = float(inp_price)
                if out_price is not None:
                    llm_output[cfg.get("model_id", name)] = float(out_price)
        
        # Default pricing
        defaults = models_cfg.get("default_pricing", {})
        if defaults:
            llm_input["default"] = float(defaults.get("llm_input_per_1m", 1.0))
            llm_output["default"] = float(defaults.get("llm_output_per_1m", 4.0))
            result["currency"] = defaults.get("currency", "USD")
        
        result["llm_per_1m_input_tokens"] = llm_input
        result["llm_per_1m_output_tokens"] = llm_output
    
    # ── Compute pricing from compute_pricing.yaml ──
    if compute_path.exists():
        with compute_path.open("r", encoding="utf-8") as f:
            compute_cfg = yaml.safe_load(f) or {}
        result["compute_per_core_hour"] = float(compute_cfg.get("cpu_price_per_core_hour", 0.05))
        result["compute_per_gpu_hour"] = float(compute_cfg.get("gpu_price_per_gpu_hour", 0.50))
        if "currency" not in result:
            result["currency"] = compute_cfg.get("currency", "USD")
    
    # ── Deprecated billing.yaml fallback ──
    if not result and billing_path.exists():
        with billing_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    
    return result
