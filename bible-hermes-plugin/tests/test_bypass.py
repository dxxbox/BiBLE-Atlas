"""Tests for session bypass logic."""

from __future__ import annotations

import re

from bible_hermes_plugin.bypass import is_bypassed_session


def _patterns(*regexes: str) -> list[re.Pattern[str]]:
    return [re.compile(r) for r in regexes]


def test_empty_patterns_never_bypass():
    assert is_bypassed_session("any-session", []) is False


def test_empty_session_id_never_bypass():
    assert is_bypassed_session("", _patterns(r".*")) is False


def test_exact_prefix_match():
    assert is_bypassed_session("scratch-abc", _patterns(r"^scratch-")) is True


def test_non_matching_session():
    assert is_bypassed_session("prod-session-42", _patterns(r"^scratch-")) is False


def test_multiple_patterns_any_match():
    patterns = _patterns(r"^test-", r"^scratch-", r"-tmp$")
    assert is_bypassed_session("work-tmp", patterns) is True
    assert is_bypassed_session("test-session", patterns) is True
    assert is_bypassed_session("prod-session", patterns) is False


def test_numeric_pattern():
    assert is_bypassed_session("session-0042", _patterns(r"\d{4}")) is True


def test_full_string_match():
    assert is_bypassed_session("exactly-this", _patterns(r"^exactly-this$")) is True
    assert is_bypassed_session("exactly-this-plus", _patterns(r"^exactly-this$")) is False
