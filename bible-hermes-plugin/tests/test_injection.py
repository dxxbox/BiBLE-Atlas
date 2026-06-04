"""Tests for context injection rendering."""

from __future__ import annotations

import pytest

from bible_hermes_plugin.injection import (
    _escape_attr,
    _sanitize,
    estimate_tokens,
    render_relevant_memories,
)
from bible_hermes_plugin.ranking import RecallHit


def _hit(id: str = "h1", score: float = 0.9, title: str = "Test title",
         summary: str = "Test summary", domain: str = "memory") -> RecallHit:
    return RecallHit(id=id, domain=domain, score=score, title=title, summary=summary)


# ── estimate_tokens ───────────────────────────────────────────────────────────

def test_estimate_tokens_basic():
    assert estimate_tokens("") == 1   # max(1, ...)
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


# ── render_relevant_memories ──────────────────────────────────────────────────

def test_renders_single_hit():
    output = render_relevant_memories([_hit()], budget_tokens=1000)
    assert "<relevant-memories>" in output
    assert "</relevant-memories>" in output
    assert "Test title" in output
    assert "Test summary" in output


def test_empty_hits_returns_empty():
    assert render_relevant_memories([], budget_tokens=1000) == ""


def test_zero_budget_returns_empty():
    assert render_relevant_memories([_hit()], budget_tokens=0) == ""


def test_negative_budget_returns_empty():
    assert render_relevant_memories([_hit()], budget_tokens=-100) == ""


def test_multiple_hits_ordered():
    hits = [_hit("a", 0.9, "Title A"), _hit("b", 0.7, "Title B")]
    output = render_relevant_memories(hits, budget_tokens=2000)
    assert "Title A" in output
    assert "Title B" in output
    assert output.index("Title A") < output.index("Title B")


def test_budget_limits_output():
    big_hits = [_hit(str(i), 0.9, "T", "S" * 500) for i in range(50)]
    output = render_relevant_memories(big_hits, budget_tokens=100)
    assert len(output) <= 100 * 4 + 30  # slight tolerance


def test_injection_risk_flag_adds_safety_note():
    h = _hit()
    h.prompt_injection_risk = True
    output = render_relevant_memories([h], budget_tokens=2000)
    assert "Safety" in output


def test_no_injection_risk_no_safety_note():
    h = _hit()
    h.prompt_injection_risk = False
    output = render_relevant_memories([h], budget_tokens=2000)
    assert "Safety" not in output


def test_hit_without_content_renders_wrapper():
    # The renderer does not filter — content-free filtering happens upstream in
    # filter_rank_and_trim. A bare hit still produces the outer wrapper tags.
    h = RecallHit(id="empty", domain="memory", score=0.9)
    output = render_relevant_memories([h], budget_tokens=1000)
    assert "<relevant-memories>" in output
    assert 'id="empty"' in output
    # No title / summary / content lines expected
    assert "Title:" not in output
    assert "Summary:" not in output


def test_score_in_output():
    output = render_relevant_memories([_hit(score=0.87)], budget_tokens=1000)
    assert "0.87" in output


# ── _sanitize ─────────────────────────────────────────────────────────────────

def test_sanitize_removes_control_chars():
    result = _sanitize("hello\x01\x07world")
    assert "\x01" not in result
    assert "hello" in result and "world" in result


def test_sanitize_strips_relevant_memories_tags():
    result = _sanitize("before<relevant-memories>inside</relevant-memories>after")
    assert "<relevant-memories>" not in result
    assert "[tag removed]" in result


def test_sanitize_truncates_at_1200():
    result = _sanitize("x" * 2000)
    assert len(result) == 1200


# ── _escape_attr ──────────────────────────────────────────────────────────────

def test_escape_attr_ampersand():
    assert _escape_attr("a&b") == "a&amp;b"


def test_escape_attr_quote():
    assert _escape_attr('say "hi"') == "say &quot;hi&quot;"


def test_escape_attr_lt():
    assert _escape_attr("<tag>") == "&lt;tag>"


def test_escape_attr_clean():
    assert _escape_attr("clean-id-123") == "clean-id-123"
