"""BiBLE Hermes Plugin — entry point.

Registers all features with the Hermes plugin context:

  - pre_llm_call  hook → BiBLE Atlas recall pipeline → inject <relevant-memories>
  - post_llm_call hook → session capture (async flush at thresholds)
  - on_session_start / on_session_end / on_session_reset hooks → lifecycle
  - 7 agent tools (bible_memory_*, bible_knowledge_*, bible_skill_*)
  - CLI command: hermes bible setup|status
  - Slash command: /bible [status]

Graceful degradation: if BIBLE_ATLAS_BASE_URL is not set, only the CLI command
is registered and a warning is logged. All hooks and tools are skipped until
the user runs `hermes bible setup --base-url <url> --write`.
"""

from __future__ import annotations

import logging
from copy import copy

from .bypass import is_bypassed_session
from .capture import SessionCaptureStore
from .cli import execute_status, handle_bible_cmd, setup_argparse
from .config import BibleConfigError, resolve_config
from .http_client import BibleAtlasClient
from .logging_utils import action_logger, log
from .recall import run_recall_pipeline
from .tools import register_tools

logger = logging.getLogger(__name__)

_PLUGIN_NAME = "bible-hermes-plugin"


def register(ctx) -> None:
    """Called exactly once at Hermes startup to wire in all plugin features."""
    al = action_logger("plugin.register")
    al.start()

    # Always register the CLI command so users can run `hermes bible setup`
    # even before the plugin is configured.
    _register_cli(ctx)
    _register_slash_command(ctx, config=None, client=None, capture_store=None)

    try:
        config = resolve_config(_get_hermes_config(ctx))
    except BibleConfigError as exc:
        logger.warning(
            "[%s] Plugin is not configured — hooks and tools are disabled until setup completes. "
            "Run: hermes bible setup --base-url <url> --write  (%s)",
            _PLUGIN_NAME, exc,
        )
        al.done({"skipped": "unconfigured"})
        return

    client = BibleAtlasClient(
        base_url=config.base_url,
        token=config.token,
        timeout_ms=config.timeout_ms,
        default_kb_index=config.default_kb_index,
        source_client=config.source_client,
    )

    capture_store = SessionCaptureStore(config=config, client=client)

    # ── lifecycle hooks ──────────────────────────────────────────────────────

    def on_session_start(session_id: str, model: str = "", platform: str = "", **kwargs) -> None:
        bypassed = is_bypassed_session(session_id, config.compiled_bypass_patterns)
        capture_store.start_session(session_id, bypassed=bypassed)
        log("info", "session.start", {"session_id": session_id, "bypassed": bypassed, "model": model})

    def on_session_end(session_id: str, completed: bool = True, interrupted: bool = False, **kwargs) -> None:
        log("info", "session.end", {"session_id": session_id, "completed": completed})
        capture_store.end_session(session_id, reason="session_end")

    def on_session_reset(session_id: str, platform: str = "", **kwargs) -> None:
        log("info", "session.reset", {"session_id": session_id})
        capture_store.reset_session(session_id)

    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_hook("on_session_reset", on_session_reset)

    # ── pre_llm_call: recall → context injection ─────────────────────────────

    def pre_llm_call(
        session_id: str = "",
        user_message: str = "",
        conversation_history: list | None = None,
        is_first_turn: bool = False,
        model: str = "",
        platform: str = "",
        **kwargs,
    ) -> dict | None:
        log("debug", "hook.pre_llm_call enter", {
            "session_id": session_id,
            "user_msg_len": len(user_message),
            "history_turns": len(conversation_history or []),
            "is_first_turn": is_first_turn,
            "force_injection": config.force_injection,
        })
        if is_bypassed_session(session_id, config.compiled_bypass_patterns):
            log("debug", "hook.pre_llm_call skipped (bypassed)", {"session_id": session_id})
            return None
        if not user_message:
            log("debug", "hook.pre_llm_call skipped (empty message)", {"session_id": session_id})
            return None

        try:
            # When force_injection is True, temporarily enable all recall domains
            recall_config = config
            if config.force_injection:
                log("info", "hook.pre_llm_call force_injection enabled", {"session_id": session_id})
                recall_config = copy(config)
                recall_config.enable_memory_recall = True
                recall_config.enable_skill_recall = True
                recall_config.enable_knowledge_recall = True

            rendered, warnings = run_recall_pipeline(
                user_message=user_message,
                conversation_history=conversation_history or [],
                config=recall_config,
                client=client,
            )
            if warnings:
                for w in warnings:
                    logger.debug("[%s] recall warning: %s", _PLUGIN_NAME, w)
            if rendered:
                log("debug", "hook.pre_llm_call done (context injected)", {
                    "session_id": session_id,
                    "rendered_chars": len(rendered),
                })
                return {"context": rendered}
            log("debug", "hook.pre_llm_call done (no results)", {"session_id": session_id})
        except Exception as exc:
            logger.warning("[%s] pre_llm_call recall failed (non-fatal): %s", _PLUGIN_NAME, exc)

        return None

    ctx.register_hook("pre_llm_call", pre_llm_call)

    # ── post_llm_call: session capture ───────────────────────────────────────

    def post_llm_call(
        session_id: str = "",
        user_message: str = "",
        assistant_response: str = "",
        conversation_history: list | None = None,
        model: str = "",
        platform: str = "",
        **kwargs,
    ) -> None:
        log("debug", "hook.post_llm_call enter", {
            "session_id": session_id,
            "user_msg_len": len(user_message),
            "assistant_msg_len": len(assistant_response),
            "capture_enabled": config.capture_enabled,
            "force_capture": config.force_capture,
        })
        if not config.capture_enabled:
            log("debug", "hook.post_llm_call skipped (capture disabled)", {"session_id": session_id})
            return
        if is_bypassed_session(session_id, config.compiled_bypass_patterns):
            log("debug", "hook.post_llm_call skipped (bypassed)", {"session_id": session_id})
            return

        try:
            # Extract tool call messages from conversation_history (role == "tool"
            # or entries with a "function_call" / "tool_calls" field).
            tool_calls = _extract_tool_calls(conversation_history or [])
            log("debug", "hook.post_llm_call tool_calls extracted", {
                "session_id": session_id,
                "tool_call_count": len(tool_calls or []),
            })
            capture_store.capture_turn(
                session_id=session_id,
                user_message=user_message,
                assistant_response=assistant_response,
                tool_calls=tool_calls,
                force_flush=config.force_capture,
            )
        except Exception as exc:
            logger.warning("[%s] post_llm_call capture failed (non-fatal): %s", _PLUGIN_NAME, exc)

    ctx.register_hook("post_llm_call", post_llm_call)

    # ── agent tools ──────────────────────────────────────────────────────────

    register_tools(ctx, client)

    # Re-register slash command with live config/client so status works
    _register_slash_command(ctx, config=config, client=client, capture_store=capture_store)

    al.done({
        "base_url": config.base_url,
        "memory_recall": config.enable_memory_recall,
        "skill_recall": config.enable_skill_recall,
        "knowledge_recall": config.enable_knowledge_recall,
        "capture_enabled": config.capture_enabled,
        "tools": 7,
        "hooks": 5,
    })
    log("info", "plugin.register done", {
        "base_url": config.base_url,
        "tools": 7,
    })


# ── private helpers ───────────────────────────────────────────────────────────

def _register_cli(ctx) -> None:
    """Register ``hermes bible setup|status`` CLI commands."""
    try:
        ctx.register_cli_command(
            name="bible",
            help="Manage BiBLE Atlas integration (setup, status).",
            setup_fn=setup_argparse,
            handler_fn=handle_bible_cmd,
        )
    except Exception as exc:
        logger.debug("[%s] register_cli_command failed (host may not support it): %s", _PLUGIN_NAME, exc)


def _register_slash_command(ctx, config, client, capture_store) -> None:
    """Register the ``/bible`` in-session slash command."""
    def handle_slash_bible(raw_args: str) -> str:
        raw_args = (raw_args or "").strip().lower()
        if raw_args in ("", "status"):
            status = execute_status(config=config, client=client)
            lines = [
                f"BiBLE Atlas ({_PLUGIN_NAME})",
                f"  configured: {'yes' if config else 'no'}",
                f"  base_url:   {status.get('base_url') or 'not set'}",
                f"  health:     {'ok' if status['health']['ok'] else 'failed'}",
                f"  memory recall: {'on' if status['recall']['memory'] else 'off'}",
                f"  capture:    {'on' if status['capture']['enabled'] else 'off'}",
                f"  tools:      {status['tools']['declared']} declared",
            ]
            if capture_store and config:
                lines.append("  pending turns: (session-dependent)")
            return "\n".join(lines)
        if raw_args == "help":
            return "Usage: /bible [status|help]"
        return f"Unknown subcommand '{raw_args}'. Try: /bible status"

    try:
        ctx.register_command(
            "bible",
            handler=handle_slash_bible,
            description="BiBLE Atlas status and setup",
        )
    except Exception as exc:
        logger.debug("[%s] register_command failed: %s", _PLUGIN_NAME, exc)


def _extract_tool_calls(history: list) -> list[dict] | None:
    """Extract tool-role messages from conversation_history for capture."""
    calls: list[dict] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        if role == "tool":
            calls.append({
                "name": msg.get("name") or msg.get("tool_name"),
                "content": str(msg.get("content") or "")[:1000],
            })
        elif role == "assistant":
            # OpenAI-style tool_calls array on assistant messages
            for tc in (msg.get("tool_calls") or []):
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    calls.append({
                        "name": fn.get("name") if isinstance(fn, dict) else None,
                        "content": fn.get("arguments", "")[:1000] if isinstance(fn, dict) else "",
                    })
    return calls or None


def _get_hermes_config(_ctx=None) -> dict:
    """Load the Hermes config dict via hermes_cli.config.load_config().

    PluginContext does not expose a ``.config`` attribute; the canonical
    way for plugins to read user config is through the public load_config()
    API which reads ~/.hermes/config.yaml (profile-aware, cached).
    """
    try:
        from hermes_cli.config import load_config

        return load_config()
    except Exception:
        return {}
