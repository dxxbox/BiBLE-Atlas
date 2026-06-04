"""BiBLE Hermes Plugin — session capture store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import threading

from .config import BibleHermesConfig
from .http_client import BibleAtlasClient
from .logging_utils import action_logger, log

logger = logging.getLogger(__name__)


# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class CapturedTurn:
    timestamp: str
    user_message: str | None = None
    assistant_message: str | None = None
    tool_calls: list[dict] | None = None
    turn_id: str | None = None
    run_id: str | None = None


@dataclass
class _SessionState:
    session_id: str
    started_at: str
    turn_count: int = 0
    buffered_chars: int = 0
    pending_turns: list[CapturedTurn] = field(default_factory=list)
    last_compaction_summary: str | None = None
    last_commit_hash: str | None = None
    bypassed: bool = False
    _flush_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# ── public class ──────────────────────────────────────────────────────────────

class SessionCaptureStore:
    """Thread-safe capture buffer. One instance shared across all hook calls."""

    def __init__(self, config: BibleHermesConfig, client: BibleAtlasClient) -> None:
        self._config = config
        self._client = client
        self._sessions: dict[str, _SessionState] = {}
        self._global_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start_session(self, session_id: str, bypassed: bool) -> None:
        al = action_logger("capture.start_session", {"session_id": session_id, "bypassed": bypassed})
        al.start()
        with self._global_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _SessionState(
                    session_id=session_id,
                    started_at=_iso_now(),
                    bypassed=bypassed,
                )
        al.done()

    def end_session(
        self,
        session_id: str,
        reason: str = "session_end",
        extra_messages: list[dict] | None = None,
    ) -> None:
        """Flush (blocking) and remove the session state."""
        al = action_logger("capture.end_session", {"session_id": session_id, "reason": reason})
        al.start()
        state = self._sessions.get(session_id)
        if state and not state.bypassed:
            self._flush(state, reason, blocking=True, extra_messages=extra_messages)
        with self._global_lock:
            self._sessions.pop(session_id, None)
        al.done()

    def reset_session(
        self,
        session_id: str,
        extra_messages: list[dict] | None = None,
    ) -> None:
        """Flush (blocking) but keep session state (continues after reset)."""
        al = action_logger("capture.reset_session", {"session_id": session_id})
        al.start()
        state = self._sessions.get(session_id)
        if state and not state.bypassed:
            self._flush(state, "before_reset", blocking=True, extra_messages=extra_messages)
        al.done()

    def set_compaction_summary(self, session_id: str, summary: str) -> None:
        """Store an auto-compaction summary to use as the next commit abstract."""
        state = self._sessions.get(session_id)
        if state:
            with state._state_lock:
                state.last_compaction_summary = summary.strip() or None

    # ── turn capture ─────────────────────────────────────────────────────────

    def capture_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        tool_calls: list[dict] | None = None,
        turn_id: str | None = None,
        run_id: str | None = None,
        force_flush: bool = False,
    ) -> None:
        """Buffer a completed turn. Triggers async flush at threshold, or immediately if force_flush=True."""
        if not self._config.capture_enabled:
            return

        state = self._ensure_state(session_id)
        if state.bypassed:
            return

        turn = CapturedTurn(
            timestamp=_iso_now(),
            user_message=user_message or None,
            assistant_message=assistant_response or None,
            tool_calls=_normalize_tool_calls(tool_calls),
            turn_id=turn_id,
            run_id=run_id,
        )

        has_content = (
            turn.user_message
            or turn.assistant_message
            or (turn.tool_calls and len(turn.tool_calls) > 0)
        )
        if not has_content:
            log("debug", "capture.turn skipped (empty)", {"session_id": session_id})
            return

        should_flush = False
        with state._state_lock:
            state.pending_turns.append(turn)
            state.turn_count += 1
            state.buffered_chars += _turn_size(turn)
            self._enforce_hard_cap(state)
            should_flush = (
                force_flush
                or len(state.pending_turns) >= self._config.capture_commit_threshold_turns
                or state.buffered_chars >= self._config.capture_commit_threshold_chars
            )

        flush_reason = "force" if force_flush else "threshold"
        log("debug", "capture.turn buffered", {
            "session_id": session_id,
            "turn_count": state.turn_count,
            "pending_turns": len(state.pending_turns),
            "buffered_chars": state.buffered_chars,
            "should_flush": should_flush,
            "force_flush": force_flush,
        })

        if should_flush:
            log("info", f"capture.{flush_reason} triggered", {
                "session_id": session_id,
                "pending_turns": len(state.pending_turns),
                "buffered_chars": state.buffered_chars,
            })
            t = threading.Thread(
                target=self._flush,
                args=(state, flush_reason),
                kwargs={"blocking": False},
                daemon=True,
                name=f"bible-flush-{session_id[:8]}",
            )
            t.start()

    def get_pending_count(self, session_id: str) -> int:
        state = self._sessions.get(session_id)
        return len(state.pending_turns) if state else 0

    def fallback_summary(self, session_id: str) -> str:
        state = self._sessions.get(session_id)
        snippets = [
            t.user_message or t.assistant_message
            for t in (state.pending_turns if state else [])
            if t.user_message or t.assistant_message
        ][:8]
        first_goal = snippets[0] if snippets else "No explicit goal captured."
        return "\n".join([
            "Summary:",
            f"- User goals: {first_goal}",
            "- Decisions: See recent conversation context.",
            "- Open tasks: Continue from the latest user request.",
            "- Important files/symbols: Not extracted by local fallback.",
            "- Tool outcomes: Not extracted by local fallback.",
        ])

    # ── flush logic ───────────────────────────────────────────────────────────

    def _flush(
        self,
        state: _SessionState,
        reason: str,
        *,
        blocking: bool,
        extra_messages: list[dict] | None = None,
    ) -> None:
        """Flush pending turns to BiBLE Atlas."""
        acquired = state._flush_lock.acquire(blocking=blocking)
        if not acquired:
            log("info", "capture.flush skipped", {"session_id": state.session_id, "reason": "commit_in_flight"})
            return

        al = action_logger("capture.flush", {"session_id": state.session_id, "reason": reason})
        al.start()
        try:
            with state._state_lock:
                turns = list(state.pending_turns)
                pending_count = len(turns)
                compaction_summary = state.last_compaction_summary

            # Append any extra messages (e.g., messages passed on session-end)
            extra_turns = _messages_to_turns(extra_messages or [])
            all_turns = turns + extra_turns

            if not all_turns:
                al.done({"skipped": "empty_buffer"})
                return

            commit_hash = _commit_hash(all_turns)
            if state.last_commit_hash == commit_hash:
                al.done({"skipped": "duplicate_hash"})
                return

            abstract = (compaction_summary or _derive_abstract(all_turns))[:500]
            overview = _derive_overview(all_turns)[:2000]
            title = _make_title(state.session_id, all_turns)
            messages = _turns_to_messages(all_turns)
            wait_for_task = reason in ("compact", "before_reset", "session_end")

            raw = self._client.save_memory(
                messages=messages,
                title=title,
                abstract=abstract,
                overview=overview,
                metadata={
                    "source": "hermes",
                    "plugin_id": "bible-hermes-plugin",
                    "session_id": state.session_id,
                    "turn_count": len(all_turns),
                    "reason": reason,
                    "started_at": state.started_at,
                },
                wait=wait_for_task,
            )

            # Extract structured response fields
            memory_id = (
                raw.get("memory_id") or raw.get("memoryId") or raw.get("id")
            )
            task_id = raw.get("task_id") or raw.get("taskId")

            # Splice only the buffered turns we committed (not the extra_turns)
            with state._state_lock:
                del state.pending_turns[:pending_count]
                state.buffered_chars = sum(_turn_size(t) for t in state.pending_turns)
                state.last_commit_hash = commit_hash

            al.done({
                "memory_id": memory_id,
                "task_id": task_id,
                "committed_turns": pending_count,
                "extra_turns": len(extra_turns),
                "remaining_turns": len(state.pending_turns),
            })

        except Exception as exc:
            al.fail(exc)
            logger.warning("[bible-hermes-plugin] capture flush failed (%s): %s", reason, exc)
        finally:
            state._flush_lock.release()

    def _ensure_state(self, session_id: str) -> _SessionState:
        with self._global_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _SessionState(
                    session_id=session_id,
                    started_at=_iso_now(),
                )
            return self._sessions[session_id]

    def _enforce_hard_cap(self, state: _SessionState) -> None:
        """Drop oldest turns when buffer exceeds hard cap (must hold state._state_lock)."""
        hard_cap = self._config.capture_commit_threshold_chars * 4
        dropped_count = 0
        while state.buffered_chars > hard_cap and len(state.pending_turns) > 1:
            dropped = state.pending_turns.pop(0)
            state.buffered_chars -= _turn_size(dropped)
            dropped_count += 1
        if dropped_count > 0:
            log("warning", "capture.hard_cap dropped turns", {
                "session_id": state.session_id,
                "dropped": dropped_count,
                "remaining_turns": len(state.pending_turns),
                "remaining_chars": state.buffered_chars,
                "hard_cap": hard_cap,
            })


# ── helpers ───────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _turn_size(turn: CapturedTurn) -> int:
    return len(json.dumps({
        "u": turn.user_message,
        "a": turn.assistant_message,
        "tc": len(turn.tool_calls or []),
    }))


def _commit_hash(turns: list[CapturedTurn]) -> str:
    data = json.dumps([
        [t.turn_id, t.timestamp, t.user_message, t.assistant_message,
         [c.get("name") for c in (t.tool_calls or [])]]
        for t in turns
    ], sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _derive_abstract(turns: list[CapturedTurn]) -> str:
    for t in turns:
        if t.user_message:
            return t.user_message
    return ""


def _derive_overview(turns: list[CapturedTurn]) -> str:
    lines: list[str] = []
    for t in turns:
        if t.user_message:
            lines.append(f"user: {t.user_message}")
        if t.assistant_message:
            lines.append(f"assistant: {t.assistant_message}")
    return "\n".join(lines)


def _make_title(session_id: str, turns: list[CapturedTurn]) -> str:
    for t in turns:
        if t.user_message:
            return t.user_message[:80]
    return f"Hermes session {session_id}"


def _turns_to_messages(turns: list[CapturedTurn]) -> list[dict]:
    messages: list[dict] = []
    for t in turns:
        if t.user_message:
            messages.append({"role": "user", "content": t.user_message, "timestamp": t.timestamp})
        if t.assistant_message:
            messages.append({"role": "assistant", "content": t.assistant_message, "timestamp": t.timestamp})
        for call in t.tool_calls or []:
            content = call.get("content") or call.get("result") or ""
            if content:
                messages.append({
                    "role": "tool",
                    "content": str(content)[:2000],
                    "timestamp": t.timestamp,
                })
    return messages


def _messages_to_turns(messages: list[dict]) -> list[CapturedTurn]:
    """Convert raw OpenAI-style messages into CapturedTurns for flush."""
    turns: list[CapturedTurn] = []
    for msg in messages:
        role = msg.get("role", "")
        content = _extract_content(msg)
        if not content:
            continue
        ts = msg.get("timestamp") or _iso_now()
        if role == "user":
            turns.append(CapturedTurn(timestamp=ts, user_message=content))
        elif role == "assistant":
            turns.append(CapturedTurn(timestamp=ts, assistant_message=content))
        elif role == "tool":
            turns.append(CapturedTurn(timestamp=ts, tool_calls=[{"content": content[:2000]}]))
    return turns


def _extract_content(msg: dict) -> str:
    content = msg.get("content") or msg.get("text") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text") or item.get("content") or ""
            for item in content
            if isinstance(item, dict)
        )
    return ""


def _normalize_tool_calls(raw: list[dict] | None) -> list[dict] | None:
    """Normalize up to 10 tool calls from a Hermes post_llm_call conversation_history."""
    if not raw:
        return None
    result: list[dict] = []
    for call in raw[:10]:
        if not isinstance(call, dict):
            continue
        fn = call.get("function")
        name = call.get("name") or (fn.get("name") if isinstance(fn, dict) else None)
        content = call.get("content") or call.get("result") or ""
        result.append({"name": name, "content": str(content)[:1000]})
    return result or None
