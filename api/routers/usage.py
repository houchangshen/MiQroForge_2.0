"""用量查询路由 — GET /usage/tokens, GET /usage/compute。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser
from api.dependencies import get_user_paths
from api.models.usage import ComputeUsageSummary, TokenUsageSummary
from api.user_paths import UserPaths

router = APIRouter(tags=["usage"])


def _load_billing_rates(settings) -> dict:
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
        
        llm_input: dict[str, float] = {}
        llm_output: dict[str, float] = {}
        models = models_cfg.get("models", {})
        for name, cfg in models.items():
            if isinstance(cfg, dict):
                inp_price = cfg.get("input_price_per_1m")
                out_price = cfg.get("output_price_per_1m")
                model_id = cfg.get("model_id", name)
                if inp_price is not None:
                    llm_input[model_id] = float(inp_price)
                if out_price is not None:
                    llm_output[model_id] = float(out_price)
        
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


# ── Token 用量 ─────────────────────────────────────────────────────────────

@router.get("/usage/tokens", response_model=TokenUsageSummary)
def get_token_usage(
    days: int = Query(default=30, ge=1, le=365),
    paths: UserPaths = Depends(get_user_paths),
):
    if paths is None:
        raise HTTPException(401, "Not authenticated")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = _read_jsonl(paths.usage_dir / "llm_usage.jsonl")

    summary = TokenUsageSummary(period_days=days)
    daily: dict[str, dict] = {}

    for r in records:
        try:
            ts = datetime.fromisoformat(r.get("finished_at", ""))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue

        inp = r.get("input_tokens", 0) or 0
        out = r.get("output_tokens", 0) or 0
        total = r.get("total_tokens", 0) or (inp + out)
        model = r.get("model", "unknown")
        purpose = r.get("purpose", "unknown")

        summary.total_calls += 1
        summary.total_input_tokens += inp
        summary.total_output_tokens += out
        summary.total_tokens += total

        # by model
        if model not in summary.by_model:
            summary.by_model[model] = {"calls": 0, "total_tokens": 0}
        summary.by_model[model]["calls"] += 1
        summary.by_model[model]["total_tokens"] += total

        # by purpose
        if purpose not in summary.by_purpose:
            summary.by_purpose[purpose] = {"calls": 0, "total_tokens": 0}
        summary.by_purpose[purpose]["calls"] += 1
        summary.by_purpose[purpose]["total_tokens"] += total

        # by day
        day_key = ts.strftime("%Y-%m-%d")
        if day_key not in daily:
            daily[day_key] = {"date": day_key, "calls": 0, "total_tokens": 0}
        daily[day_key]["calls"] += 1
        daily[day_key]["total_tokens"] += total

    summary.by_day = sorted(daily.values(), key=lambda d: d["date"])

    # Estimate cost
    rates = _load_billing_rates(global_settings())
    est = 0.0
    llm_input = rates.get("llm_per_1m_input_tokens", {})
    llm_output = rates.get("llm_per_1m_output_tokens", {})
    default_inp = llm_input.get("default", 1.0)
    default_out = llm_output.get("default", 4.0)
    for model_name, stats in summary.by_model.items():
        inp_rate = llm_input.get(model_name, default_inp)
        out_rate = llm_output.get(model_name, default_out)
        model_inp = stats.get("input_tokens", 0)
        model_out = stats.get("output_tokens", 0)
        est += (model_inp / 1_000_000) * inp_rate + (model_out / 1_000_000) * out_rate
    summary.estimated_cost = round(est, 4)

    return summary


# ── 计算用量 ───────────────────────────────────────────────────────────────

@router.get("/usage/compute", response_model=ComputeUsageSummary)
def get_compute_usage(
    days: int = Query(default=30, ge=1, le=365),
    paths: UserPaths = Depends(get_user_paths),
):
    if paths is None:
        raise HTTPException(401, "Not authenticated")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = _read_jsonl(paths.usage_dir / "compute_usage.jsonl")

    summary = ComputeUsageSummary(period_days=days)
    daily: dict[str, dict] = {}

    for r in records:
        try:
            ts = datetime.fromisoformat(r.get("recorded_at", ""))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue

        core_h = r.get("core_hours", 0) or 0
        gpu_h = r.get("gpu_hours", 0) or 0
        proj = r.get("project_id", "unknown")

        summary.total_core_hours += core_h
        summary.total_gpu_hours += gpu_h
        summary.total_workflows += 1

        # by project
        if proj not in summary.by_project:
            summary.by_project[proj] = {"core_hours": 0, "gpu_hours": 0, "workflows": 0}
        summary.by_project[proj]["core_hours"] += core_h
        summary.by_project[proj]["gpu_hours"] += gpu_h
        summary.by_project[proj]["workflows"] += 1

        # by day
        day_key = ts.strftime("%Y-%m-%d")
        if day_key not in daily:
            daily[day_key] = {"date": day_key, "core_hours": 0, "gpu_hours": 0}
        daily[day_key]["core_hours"] += core_h
        daily[day_key]["gpu_hours"] += gpu_h

    summary.by_day = sorted(daily.values(), key=lambda d: d["date"])

    rates = _load_billing_rates(global_settings())
    summary.estimated_cost = round(
        summary.total_core_hours * rates.get("compute_per_core_hour", 0.05)
        + summary.total_gpu_hours * rates.get("compute_per_gpu_hour", 0.50),
        4,
    )

    return summary


# ── 辅助 ──────────────────────────────────────────────────────────────────

def _global_settings():
    """延迟 import 避免循环依赖。"""
    from api.config import get_settings
    return get_settings()


def global_settings():
    return _global_settings()
