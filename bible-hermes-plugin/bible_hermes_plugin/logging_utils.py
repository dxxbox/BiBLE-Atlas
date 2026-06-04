"""BiBLE Hermes Plugin — structured action logging with secret redaction.

Mirrors src/logging.ts from the OpenClaw plugin.

Logging output goes to $HERMES_HOME/logs/bible-hermes-plugin.log (for
``hermes logs -f`` compatibility when the session itself is the tail target,
and for ``tail -f`` on the dedicated file otherwise).
A FileHandler is attached to the plugin's logger at module import time if no
handler is already present, with the level inherited from the root logger
(defaulting to DEBUG when the root logger is unconfigured).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_PLUGIN_ID = "bible-hermes-plugin"
_SECRET_PATTERN = frozenset(["token", "authorization", "api_key", "apikey", "api-key", "secret", "password"])

logger = logging.getLogger(__name__)

# ── ensure file-based log output ───────────────────────────────────────────────

def _ensure_log_handler() -> None:
    """Attach a FileHandler writing to $HERMES_HOME/logs/bible-hermes-plugin.log.

    The handler inherits the root logger's effective level. If the root logger
    is completely unconfigured (no handlers), we default to DEBUG so that all
    bible-hermes-plugin log messages are visible during development/debugging.

    Logs go to a dedicated file so they never pollute the Hermes session window.
    Use ``tail -f $HERMES_HOME/logs/bible-hermes-plugin.log`` or
    ``hermes logs -f`` to watch them.
    """
    if logger.handlers:
        return

    # Force DEBUG level on the plugin logger so our messages are never silently
    # dropped by the logger's own level filter. The actual verbosity is
    # controlled by the handler level (which inherits from root).
    logger.setLevel(logging.DEBUG)

    root = logging.getLogger()
    if root.handlers:
        # Inherit the most permissive (lowest) level among root handlers
        levels = [h.level for h in root.handlers if h.level != logging.NOTSET]
        effective_level = min(level for level in levels) if levels else logging.DEBUG
    else:
        # Root logger is unconfigured — default to DEBUG so plugin messages
        # are visible during development / log-file debugging.
        effective_level = logging.DEBUG

    hermes_home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    logs_dir = Path(hermes_home) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "bible-hermes-plugin.log"
    handler = logging.FileHandler(str(log_file))
    handler.setLevel(effective_level)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.propagate = False  # avoid duplicate output when root has handlers too

_ensure_log_handler()


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
    # Inline meta as JSON so it appears in plain-text log output (no custom
    # formatter required). This ensures hermes logs -f shows all context.
    meta_str = _json_compact(sanitized)
    full_message = f"[{_PLUGIN_ID}] {message} {meta_str}"
    getattr(logger, level, logger.info)(full_message)


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


def _json_compact(obj: Any) -> str:
    """Serialize to a single-line JSON string (no extra spaces) for log output."""
    try:
        return json.dumps(obj, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(obj)


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
