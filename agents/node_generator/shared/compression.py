"""agents/node_generator/compression.py — 上下文压缩（滑动窗口 + 摘要）。

使用 tiktoken 做 token 计数，当消息历史超过 context window 80% 时触发压缩：
  1. 保留 SystemMessage（不变）
  2. 保留最近 N 轮 tool call（AIMessage + ToolMessage）
  3. 更早的消息 → LLM 生成结构化摘要 → 替换为单条 SystemMessage

依赖：tiktoken（纯 C 扩展）
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    BaseMessage,
)

logger = logging.getLogger(__name__)

# 默认 token 限制（GPT-4o 128K context 的 80%）
DEFAULT_MAX_TOKENS = 100000
DEFAULT_KEEP_RECENT = 6  # 保留最近 6 轮 tool call


def _count_tokens(messages: list[BaseMessage], enc) -> int:
    """估算消息列表的 token 数。"""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(enc.encode(content))
        # tool_calls 的 JSON 也占 token
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                total += len(enc.encode(str(tc)))
        # 额外开销（role、格式等）
        total += 4
    return total


def _find_tool_call_boundaries(messages: list[BaseMessage]) -> list[int]:
    """找到所有 tool call 轮次的起始索引。
    一轮 = AIMessage(有 tool_calls) + 对应的 ToolMessage(s)。
    """
    boundaries = []
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            boundaries.append(i)
    return boundaries


def _compress_old_messages(
    old_messages: list[BaseMessage],
    llm: Any,
) -> str:
    """用 LLM 将旧消息压缩为结构化摘要。"""
    # 构建摘要请求
    history_text = []
    for msg in old_messages:
        role = msg.__class__.__name__.replace("Message", "")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            tool_names = [tc.get("name", "?") for tc in msg.tool_calls]
            history_text.append(f"[{role}] (called tools: {', '.join(tool_names)})")
            if content:
                history_text.append(f"  {content[:200]}")
        elif isinstance(msg, ToolMessage):
            history_text.append(f"[Tool Result] {content[:500]}")
        else:
            history_text.append(f"[{role}] {content[:500]}")

    history_str = "\n".join(history_text)

    # 截断到安全长度
    if len(history_str) > 30000:
        history_str = history_str[:30000] + "\n[... truncated ...]"

    summary_prompt = f"""Summarize the following tool call history concisely. Preserve:
1. What was tried and what worked/failed
2. Key findings from manual chapters or reference nodes — INCLUDE chapter names, section IDs, and page numbers
3. Current state of the generated nodespec/run.sh
4. Any unresolved issues or errors
5. Search trajectory — which chapters/sections were already searched (avoid re-searching)

History:
{history_str}

Respond with a structured summary in this format:
TRIED: [what approaches were attempted]
FOUND: [key findings with source references: chapter name, section ID, page]
CURRENT_STATE: [current state of generated artifacts]
ISSUES: [unresolved problems]"""

    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=summary_prompt)])
        return response.content
    except Exception as e:
        logger.warning(f"Compression summary failed: {e}")
        # Fallback: 简单截断
        return f"[Compression failed, history truncated. Last {len(old_messages)} messages discarded. Error: {e}]"


def compress_messages(
    messages: list[BaseMessage],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    llm: Any = None,
) -> list[BaseMessage]:
    """压缩消息历史，保持在 token 限制内。

    策略：
    1. 保留 SystemMessage
    2. 保留最近 keep_recent 轮 tool call
    3. 更早的消息 → LLM 摘要 → SystemMessage
    4. 如果仍然超限 → 减少 keep_recent
    """
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
    except Exception:
        # tiktoken 不可用，跳过压缩
        return messages

    current_tokens = _count_tokens(messages, enc)
    if current_tokens <= max_tokens:
        return messages

    logger.info(
        f"Context compression triggered: {current_tokens} tokens > {max_tokens} limit"
    )

    # 分离 SystemMessage 和其他消息
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if not non_system:
        return messages

    # 找到 tool call 轮次边界
    boundaries = _find_tool_call_boundaries(non_system)

    # 尝试逐步减少保留的轮次
    for keep in range(keep_recent, 0, -1):
        if len(boundaries) <= keep:
            # 轮次不够压缩
            continue

        # 旧消息：从开始到第 keep 个轮次之前
        cutoff_idx = boundaries[-keep]
        old_messages = non_system[:cutoff_idx]
        recent_messages = non_system[cutoff_idx:]

        if not old_messages:
            continue

        # 压缩旧消息
        if llm:
            summary_text = _compress_old_messages(old_messages, llm)
        else:
            summary_text = f"[History of {len(old_messages)} messages compressed without LLM]"

        summary_msg = SystemMessage(
            content=f"[Compressed History Summary]\n{summary_text}"
        )

        # 组装新消息列表
        compressed = system_msgs + [summary_msg] + recent_messages
        new_tokens = _count_tokens(compressed, enc)

        if new_tokens <= max_tokens:
            logger.info(
                f"Compressed: {current_tokens} → {new_tokens} tokens "
                f"(kept {keep} recent rounds, summarized {len(old_messages)} messages)"
            )
            return compressed

    # 所有轮次都保留仍然超限 → 强制截断
    logger.warning(f"Could not compress below {max_tokens} tokens, forcing truncation")
    # 保留 system + 最近一半消息
    half = len(non_system) // 2
    return system_msgs + non_system[half:]
