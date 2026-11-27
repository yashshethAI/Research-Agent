from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from typing import Any

_conv_id_ctx: ContextVar[str] = ContextVar("conv_id", default="-")
_res_id_ctx: ContextVar[str] = ContextVar("res_id", default="-")
_node_ctx: ContextVar[str] = ContextVar("node", default="-")
_tier_ctx: ContextVar[str] = ContextVar("tier", default="-")

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


class CorrelationFilter(logging.Filter):
    """Injects conversation, research, node, and tier context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        conv = _conv_id_ctx.get() or "-"
        res = _res_id_ctx.get() or "-"
        node = _node_ctx.get() or "-"
        tier = _tier_ctx.get() or "-"
        record.correlation = f"conv={conv[:8]} res={res[:8]} node={node} tier={tier}"
        return True


def configure_correlated_logging(level_name: str = "INFO") -> None:
    """Configures root logging with correlation fields without duplicating handlers."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    fmt = "%(asctime)s [%(levelname)s] [%(correlation)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)
    corr_filter = CorrelationFilter()

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.addFilter(corr_filter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)
            if not any(isinstance(f, CorrelationFilter) for f in handler.filters):
                handler.addFilter(corr_filter)


def set_log_context(
    *,
    conversation_id: str | None = None,
    research_id: str | None = None,
    node: str | None = None,
    tier: str | None = None,
) -> dict[str, Token[str]]:
    """Sets correlation context variables and returns reset tokens."""
    tokens: dict[str, Token[str]] = {}
    if conversation_id is not None:
        tokens["conv"] = _conv_id_ctx.set(conversation_id or "-")
    if research_id is not None:
        tokens["res"] = _res_id_ctx.set(research_id or "-")
    if node is not None:
        tokens["node"] = _node_ctx.set(node or "-")
    if tier is not None:
        tokens["tier"] = _tier_ctx.set(tier or "-")
    return tokens


def reset_log_context(tokens: dict[str, Token[str]]) -> None:
    """Restores previous correlation context variables."""
    var_map = {
        "conv": _conv_id_ctx,
        "res": _res_id_ctx,
        "node": _node_ctx,
        "tier": _tier_ctx,
    }
    for key, token in tokens.items():
        if key in var_map:
            var_map[key].reset(token)


def strip_thinking_tags(text: str) -> tuple[str, int]:
    """Strips <think>...</think> blocks from small reasoning models and reports removed length."""
    if not text:
        return "", 0
    original_len = len(text)
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_UNCLOSED_RE.sub("", cleaned).strip()
    removed = max(0, original_len - len(cleaned))
    return cleaned, removed


def make_node_error(
    node: str,
    substep: str,
    exc: BaseException | str,
    target: str = "",
) -> dict[str, Any]:
    """Builds a structured, pinpoint error record for state.node_errors."""
    if isinstance(exc, BaseException):
        error_type = type(exc).__name__
        detail = str(exc) or repr(exc)
    else:
        error_type = "Error"
        detail = str(exc)

    return {
        "node": node,
        "substep": substep,
        "target": target,
        "error_type": error_type,
        "detail": detail[:500],
    }


def make_trace_entry(
    node: str,
    tier: str,
    status: str,
    duration_ms: int,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Builds a compact per-node execution trace entry."""
    return {
        "node": node,
        "tier": tier,
        "status": status,
        "duration_ms": duration_ms,
        "summary": summary or {},
        "error": error,
    }
