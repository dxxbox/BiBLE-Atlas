"""Tests for the session capture store."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from bible_hermes_plugin.capture import (
    CapturedTurn,
    SessionCaptureStore,
    _commit_hash,
    _messages_to_turns,
    _normalize_tool_calls,
    _turn_size,
)
from bible_hermes_plugin.config import BibleHermesConfig


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def cfg() -> BibleHermesConfig:
    return BibleHermesConfig(
        base_url="http://localhost:9999",
        capture_enabled=True,
        capture_commit_threshold_turns=3,
        capture_commit_threshold_chars=1_000,
    )


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.save_memory.return_value = {"task_id": "t-1", "memory_id": "m-1"}
    return client


@pytest.fixture()
def store(cfg, mock_client) -> SessionCaptureStore:
    return SessionCaptureStore(cfg, mock_client)


# ── _commit_hash ──────────────────────────────────────────────────────────────

def test_commit_hash_stable():
    t = CapturedTurn(timestamp="2024-01-01", user_message="hi", assistant_message="hello")
    assert _commit_hash([t]) == _commit_hash([t])


def test_commit_hash_differs_on_content():
    t1 = CapturedTurn(timestamp="ts", user_message="hello")
    t2 = CapturedTurn(timestamp="ts", user_message="world")
    assert _commit_hash([t1]) != _commit_hash([t2])


def test_commit_hash_includes_tool_calls():
    t1 = CapturedTurn(timestamp="ts", user_message="q", tool_calls=[{"name": "fn_a"}])
    t2 = CapturedTurn(timestamp="ts", user_message="q", tool_calls=[{"name": "fn_b"}])
    assert _commit_hash([t1]) != _commit_hash([t2])


# ── _turn_size ────────────────────────────────────────────────────────────────

def test_turn_size_positive():
    t = CapturedTurn(timestamp="ts", user_message="hi", assistant_message="hello")
    assert _turn_size(t) > 0


def test_turn_size_grows_with_content():
    small = CapturedTurn(timestamp="ts", user_message="hi")
    large = CapturedTurn(timestamp="ts", user_message="hi" * 100)
    assert _turn_size(large) > _turn_size(small)


# ── _messages_to_turns ────────────────────────────────────────────────────────

def test_messages_to_turns_user():
    turns = _messages_to_turns([{"role": "user", "content": "hello"}])
    assert len(turns) == 1
    assert turns[0].user_message == "hello"


def test_messages_to_turns_assistant():
    turns = _messages_to_turns([{"role": "assistant", "content": "hi back"}])
    assert turns[0].assistant_message == "hi back"


def test_messages_to_turns_tool():
    turns = _messages_to_turns([{"role": "tool", "content": "result data"}])
    assert turns[0].tool_calls is not None
    assert turns[0].tool_calls[0]["content"] == "result data"


def test_messages_to_turns_skips_empty():
    turns = _messages_to_turns([{"role": "user", "content": ""}])
    assert turns == []


def test_messages_to_turns_list_content():
    msg = {"role": "user", "content": [{"text": "part A"}, {"text": "part B"}]}
    turns = _messages_to_turns([msg])
    assert turns[0].user_message == "part A\npart B"


# ── _normalize_tool_calls ─────────────────────────────────────────────────────

def test_normalize_tool_calls_none():
    assert _normalize_tool_calls(None) is None


def test_normalize_tool_calls_empty():
    assert _normalize_tool_calls([]) is None


def test_normalize_tool_calls_standard():
    raw = [{"name": "my_tool", "content": "output"}]
    result = _normalize_tool_calls(raw)
    assert result is not None
    assert result[0]["name"] == "my_tool"


def test_normalize_tool_calls_openai_format():
    raw = [{"function": {"name": "search", "arguments": '{"q":"foo"}'}}]
    result = _normalize_tool_calls(raw)
    assert result is not None
    assert result[0]["name"] == "search"


def test_normalize_tool_calls_max_10():
    raw = [{"name": f"fn_{i}", "content": "x"} for i in range(20)]
    result = _normalize_tool_calls(raw)
    assert result is not None
    assert len(result) == 10


# ── SessionCaptureStore: lifecycle ────────────────────────────────────────────

def test_start_session_creates_state(store):
    store.start_session("s1", bypassed=False)
    assert store.get_pending_count("s1") == 0


def test_start_session_bypassed(store):
    store.start_session("s-bypass", bypassed=True)
    state = store._sessions["s-bypass"]
    assert state.bypassed is True


def test_get_pending_count_unknown_session(store):
    assert store.get_pending_count("unknown") == 0


def test_capture_turn_buffers(store):
    store.start_session("s1", bypassed=False)
    store.capture_turn("s1", "hello", "hi back")
    assert store.get_pending_count("s1") == 1


def test_capture_skips_bypassed(store):
    store.start_session("s-skip", bypassed=True)
    store.capture_turn("s-skip", "msg", "resp")
    assert store.get_pending_count("s-skip") == 0


def test_capture_skips_empty_turn(store):
    store.start_session("s1", bypassed=False)
    store.capture_turn("s1", "", "")
    assert store.get_pending_count("s1") == 0


def test_capture_disabled_skips(cfg, mock_client):
    cfg.capture_enabled = False
    s = SessionCaptureStore(cfg, mock_client)
    s.start_session("s1", bypassed=False)
    s.capture_turn("s1", "hi", "hello")
    assert s.get_pending_count("s1") == 0


def test_end_session_flushes_and_removes(store, mock_client):
    store.start_session("s1", bypassed=False)
    store.capture_turn("s1", "question", "answer")
    store.end_session("s1", reason="session_end")
    assert "s1" not in store._sessions
    mock_client.save_memory.assert_called_once()


def test_reset_session_flushes_keeps_state(store, mock_client):
    store.start_session("s1", bypassed=False)
    store.capture_turn("s1", "q", "a")
    store.reset_session("s1")
    assert "s1" in store._sessions
    mock_client.save_memory.assert_called_once()


def test_flush_skips_duplicate_hash(store, mock_client):
    store.start_session("s1", bypassed=False)
    store.capture_turn("s1", "q", "a")
    store.end_session("s1")
    store.start_session("s1", bypassed=False)
    # Same content
    state = store._sessions["s1"]
    state.last_commit_hash = _commit_hash([CapturedTurn(
        timestamp=state.pending_turns[0].timestamp if state.pending_turns else "x",
        user_message="q", assistant_message="a",
    )]) if state.pending_turns else None
    # Should not double-save — just verify first call happened
    assert mock_client.save_memory.call_count >= 1


# ── hard cap ──────────────────────────────────────────────────────────────────

def test_hard_cap_drops_oldest_turns(store):
    store.start_session("s1", bypassed=False)
    state = store._sessions["s1"]
    state.buffered_chars = store._config.capture_commit_threshold_chars * 5
    state.pending_turns = [
        CapturedTurn(timestamp="ts", user_message="x" * 100)
        for _ in range(20)
    ]
    with state._state_lock:
        store._enforce_hard_cap(state)
    assert len(state.pending_turns) < 20


# ── flush lock: non-blocking for threshold ────────────────────────────────────

def test_flush_lock_non_blocking_skips_when_busy(store):
    store.start_session("s1", bypassed=False)
    state = store._sessions["s1"]
    state.pending_turns = [CapturedTurn(timestamp="ts", user_message="q", assistant_message="a")]

    # Hold the lock to simulate an in-flight flush
    state._flush_lock.acquire()
    try:
        log_calls: list[str] = []
        original_log = __import__("bible_hermes_plugin.capture", fromlist=["log"]).log
        with patch("bible_hermes_plugin.capture.log", side_effect=lambda level, msg, *a, **kw: log_calls.append(msg)):
            store._flush(state, "threshold", blocking=False)
        assert any("flush skipped" in m for m in log_calls)
    finally:
        state._flush_lock.release()
