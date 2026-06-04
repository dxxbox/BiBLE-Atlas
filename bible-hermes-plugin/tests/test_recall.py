"""Tests for the recall query builder and text extraction helpers."""

from __future__ import annotations

from bible_hermes_plugin.recall import (
    _clean_for_query,
    _text_from_item,
    _text_from_message,
    build_recall_query,
)


# ── build_recall_query ────────────────────────────────────────────────────────

def test_basic_query():
    q = build_recall_query("What is FastAPI?", [])
    assert "What is FastAPI?" in q


def test_query_appends_recent_history():
    history = [
        {"role": "user", "content": "Tell me about async"},
        {"role": "assistant", "content": "Async allows concurrency"},
    ]
    q = build_recall_query("What about FastAPI?", history)
    assert "Tell me about async" in q
    assert "What about FastAPI?" in q


def test_query_capped_at_2000_chars():
    long_msg = "a" * 3000
    q = build_recall_query(long_msg, [])
    assert len(q) <= 2000


def test_query_uses_last_6_history_messages():
    history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    q = build_recall_query("final", history)
    assert "msg 4" in q  # only last 6 (4..9)
    assert "msg 0" not in q


def test_empty_message_with_history():
    history = [{"role": "user", "content": "context info"}]
    q = build_recall_query("", history)
    assert "context info" in q


def test_empty_everything_returns_empty():
    assert build_recall_query("", []) == ""


# ── _clean_for_query ──────────────────────────────────────────────────────────

def test_clean_omits_large_code_blocks():
    text = "before\n```python\n" + "x = 1\n" * 200 + "```\nafter"
    result = _clean_for_query(text)
    assert "[code block omitted]" in result
    assert "before" in result and "after" in result


def test_clean_keeps_small_code_blocks():
    text = "```x = 1```"
    result = _clean_for_query(text)
    assert "x = 1" in result
    assert "[code block omitted]" not in result


def test_clean_omits_encoded_blobs():
    blob = "A" * 150
    result = _clean_for_query(f"before {blob} after")
    assert "[encoded blob omitted]" in result
    assert "before" in result


def test_clean_collapses_excess_newlines():
    text = "line1\n\n\n\n\nline2"
    result = _clean_for_query(text)
    assert "\n\n\n" not in result
    assert "line1" in result and "line2" in result


# ── _text_from_message ────────────────────────────────────────────────────────

def test_text_from_string_content():
    assert _text_from_message({"content": "hello"}) == "hello"


def test_text_from_text_key():
    assert _text_from_message({"text": "hello"}) == "hello"


def test_text_from_list_content():
    msg = {"content": [{"text": "part A"}, {"text": "part B"}]}
    result = _text_from_message(msg)
    assert "part A" in result and "part B" in result


def test_text_from_missing_content():
    assert _text_from_message({}) == ""


def test_text_from_non_string_content():
    assert _text_from_message({"content": 42}) == ""


# ── _text_from_item ───────────────────────────────────────────────────────────

def test_text_from_item_string():
    assert _text_from_item("hello") == "hello"


def test_text_from_item_dict_text():
    assert _text_from_item({"text": "hi"}) == "hi"


def test_text_from_item_dict_content():
    assert _text_from_item({"content": "bye"}) == "bye"


def test_text_from_item_unknown():
    assert _text_from_item(42) == ""
