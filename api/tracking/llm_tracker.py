"""LLM Token 用量追踪 — LangChain callback handler。

用法：
    from api.tracking.llm_tracker import TokenUsageTracker

    tracker = TokenUsageTracker(user_paths, purpose="planner")
    model = LLMConfig.get_chat_model("planner")
    model.callbacks = [tracker]  # 或通过 with_config(callbacks=[tracker])

    # ... 运行 agent ...
    tracker.flush()  # 将记录写入 llm_usage.jsonl
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class TokenUsageTracker(BaseCallbackHandler):
    """捕获每次 LLM 调用的 token 用量并写入用户的使用量 JSONL。"""

    def __init__(self, user_paths: "UserPaths", purpose: str = "unknown", currency: str = "USD"):
        self._user_paths = user_paths
        self._purpose = purpose
        self._currency = currency
        self._current: dict | None = None
        self.records: list[dict] = []
        self._raise_error = False  # 不中断 LLM 调用

    @property
    def total_tokens(self) -> int:
        return sum(r.get("total_tokens", 0) for r in self.records)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.get("input_tokens", 0) for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.get("output_tokens", 0) for r in self.records)

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any
    ) -> None:
        # 从多种位置尝试提取模型名（兼容 LangChain 不同版本）
        model = "unknown"
        # v0.3+: invocation_params._model
        inv = kwargs.get("invocation_params", {}) or {}
        if isinstance(inv, dict):
            model = inv.get("model", inv.get("model_name", inv.get("_model", "")))
        if not model or model == "unknown":
            # v0.2: serialized.kwargs.model
            model = serialized.get("kwargs", {}).get("model", "")
        if not model:
            # fallback: class name
            model = serialized.get("name", "unknown")

        self._current = {
            "call_id": str(uuid.uuid4()),
            "purpose": self._purpose,
            "model": model or "unknown",
            "started_at": time.time(),
            "prompt_count": len(prompts),
        }

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        if self._current is None:
            return
        elapsed = time.time() - self._current["started_at"]
        token_usage = (
            response.llm_output.get("token_usage", {})
            if response.llm_output
            else {}
        )
        record = {
            **{k: v for k, v in self._current.items() if k != "started_at"},
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(elapsed, 3),
            "input_tokens": token_usage.get("input_tokens", 0),
            "output_tokens": token_usage.get("output_tokens", 0),
            "total_tokens": token_usage.get("total_tokens", 0),
            "currency": self._currency,
        }
        # OpenAI-compatible providers use prompt_tokens/completion_tokens
        if record["input_tokens"] == 0 and "prompt_tokens" in token_usage:
            record["input_tokens"] = token_usage.get("prompt_tokens", 0)
        if record["output_tokens"] == 0 and "completion_tokens" in token_usage:
            record["output_tokens"] = token_usage.get("completion_tokens", 0)
        # 如果 response 没有 token_usage，用 generation info 估算
        if record["total_tokens"] == 0:
            if hasattr(response, "generations") and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "generation_info"):
                            usage = gen.generation_info.get("usage_metadata", {})
                            if usage:
                                record["input_tokens"] = usage.get("input_tokens", 0)
                                record["output_tokens"] = usage.get("output_tokens", 0)
                                record["total_tokens"] = usage.get("total_tokens", 0)
                                break
        self.records.append(record)
        self._current = None

    def flush(self) -> None:
        """将所有累积的记录写入用户的使用量 JSONL 文件。"""
        if not self.records:
            return
        log_path = self._user_paths.usage_dir / "llm_usage.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for record in self.records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.records.clear()
