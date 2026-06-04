"""BiBLE Hermes Plugin — structured action logging with secret redaction.

Mirrors src/logging.ts from the OpenClaw plugin.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_PLUGIN_ID = "bible-hermes-plugin"
_SECRET_PATTERN = frozenset(["token", "authorization", "api_key", "apikey", "api-key", "secret", "password"])

logger = logging.getLogger(__name__)


# ── public interface ──────────────────────────────────────────────────────────

class ActionLogger:
    """Tracks start/done/fail for a named action."""

    def __init__(self, action: str, base_meta: dict | None = None) -> None:
        self._action = action
        self._base_meta = base_meta or {}
        self._started_at = time.monotonic()

    def start(self, meta: dict | None = None) -> None:
        _log("info", f"{self._action} start", {**self._base_meta, **(meta or {}), "action": self._action})

    def done(self, meta: dict | None = None) -> None:
        elapsed = int((time.monotonic() - self._started_at) * 1000)
        _log("info", f"{self._action} done", {
            **self._base_meta,
            **(meta or {}),
            "action": self._action,
            "duration_ms": elapsed,
        })

    def fail(self, exc: Exception | Any, meta: dict | None = None) -> None:
        elapsed = int((time.monotonic() - self._started_at) * 1000)
        _log("error", f"{self._action} failed", {
            **self._base_meta,
            **(meta or {}),
            "action": self._action,
            "duration_ms": elapsed,
            "error": _error_meta(exc),
        })


def action_logger(action: str, base_meta: dict | None = None) -> ActionLogger:
    return ActionLogger(action, base_meta)


def log(level: str, message: str, meta: dict | None = None) -> None:
    _log(level, message, meta or {})


# ── internal helpers ──────────────────────────────────────────────────────────

def _log(level: str, message: str, meta: dict) -> None:
    sanitized = _sanitize_meta({"plugin_id": _PLUGIN_ID, **meta})
    getattr(logger, level, logger.info)(f"[{_PLUGIN_ID}] {message}", extra={"bible_meta": sanitized})


def _error_meta(exc: Any) -> dict:
    if isinstance(exc, Exception):
        result: dict = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        for attr in ("code", "status_code", "server_error_code"):
            val = getattr(exc, attr, None)
            if val is not None:
                result[attr] = val
        return result
    return {"message": str(exc)}


def _sanitize_meta(meta: dict) -> dict:
    out: dict = {}
    for key, value in meta.items():
        if value is None:
            continue
        if _is_secret_key(key):
            out[key] = "[redacted]"
        else:
            out[key] = _sanitize_value(value)
    return out


def _is_secret_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return any(s in lower for s in _SECRET_PATTERN)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:500] + "..." if len(value) > 500 else value
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value[:20]]
    if isinstance(value, dict):
        return _sanitize_meta(value)
    return value
