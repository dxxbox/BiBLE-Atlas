"""Tests for tool helpers, schemas, and handlers."""

from __future__ import annotations

import json

import pytest

from bible_hermes_plugin.tools.helpers import (
    as_object,
    extract_hits,
    fail,
    ok,
    optional_int,
    optional_search_type,
    require_string,
    summarize_hits,
    trim_details,
)


# ── ok / fail ─────────────────────────────────────────────────────────────────

def test_ok_returns_json():
    result = json.loads(ok("all good"))
    assert result["ok"] is True
    assert result["content"] == "all good"


def test_ok_includes_extra_fields():
    result = json.loads(ok("done", {"count": 3}))
    assert result["count"] == 3


def test_fail_returns_json_error():
    result = json.loads(fail(ValueError("bad input")))
    assert result["ok"] is False
    assert result["error"] is True
    assert "content" in result


# ── require_string ────────────────────────────────────────────────────────────

def test_require_string_ok():
    assert require_string({"key": "value"}, "key") == "value"


def test_require_string_strips_whitespace():
    assert require_string({"key": "  hello  "}, "key") == "hello"


def test_require_string_missing_raises():
    with pytest.raises(ValueError, match="key is required"):
        require_string({}, "key")


def test_require_string_empty_raises():
    with pytest.raises(ValueError):
        require_string({"key": "   "}, "key")


def test_require_string_non_string_raises():
    with pytest.raises(ValueError):
        require_string({"key": 42}, "key")


# ── optional_int ──────────────────────────────────────────────────────────────

def test_optional_int_missing_returns_fallback():
    assert optional_int({}, "k", fallback=7, min_val=1, max_val=50) == 7


def test_optional_int_valid():
    assert optional_int({"k": 10}, "k", fallback=7, min_val=1, max_val=50) == 10


def test_optional_int_too_low_raises():
    with pytest.raises(ValueError):
        optional_int({"k": 0}, "k", fallback=7, min_val=1, max_val=50)


def test_optional_int_too_high_raises():
    with pytest.raises(ValueError):
        optional_int({"k": 51}, "k", fallback=7, min_val=1, max_val=50)


def test_optional_int_bool_rejected():
    with pytest.raises(ValueError):
        optional_int({"k": True}, "k", fallback=7, min_val=1, max_val=50)


# ── optional_search_type ──────────────────────────────────────────────────────

def test_search_type_default_hybrid():
    assert optional_search_type({}) == "hybrid"


def test_search_type_valid_values():
    for v in ("keyword", "title", "text", "vector", "hybrid"):
        assert optional_search_type({"search_type": v}) == v


def test_search_type_invalid_raises():
    with pytest.raises(ValueError, match="search_type must be one of"):
        optional_search_type({"search_type": "fuzzy"})


def test_search_type_camel_case_alias():
    assert optional_search_type({"searchType": "vector"}) == "vector"


# ── as_object ─────────────────────────────────────────────────────────────────

def test_as_object_dict():
    d = {"a": 1}
    assert as_object(d) is d


def test_as_object_non_dict_raises():
    with pytest.raises(ValueError, match="must be an object"):
        as_object("string")


# ── extract_hits ──────────────────────────────────────────────────────────────

def test_extract_hits_direct_key():
    payload = {"results": {"memory": [{"id": "m1"}, {"id": "m2"}]}}
    assert len(extract_hits("memory", payload)) == 2


def test_extract_hits_alias_fallback():
    payload = {"results": {"knowledge_base": [{"id": "k1"}]}}
    hits = extract_hits("missing_tag", payload, aliases=("knowledge_base",))
    assert len(hits) == 1


def test_extract_hits_no_results():
    assert extract_hits("memory", {}) == []


def test_extract_hits_filters_non_dicts():
    payload = {"results": {"memory": [{"id": "ok"}, "not-a-dict", 99]}}
    assert len(extract_hits("memory", payload)) == 1


def test_extract_hits_results_not_dict():
    assert extract_hits("memory", {"results": "oops"}) == []


# ── summarize_hits ────────────────────────────────────────────────────────────

def test_summarize_hits_empty():
    assert "0" in summarize_hits("memory", {})


def test_summarize_hits_with_results():
    payload = {"results": {"memory": [{"id": "m1", "title": "My Memory", "score": 0.9}]}}
    summary = summarize_hits("memory", payload)
    assert "1" in summary
    assert "My Memory" in summary


def test_summarize_hits_includes_score():
    payload = {"results": {"memory": [{"score": 0.87, "title": "T"}]}}
    assert "0.87" in summarize_hits("memory", payload)


# ── trim_details ──────────────────────────────────────────────────────────────

def test_trim_details_small_passthrough():
    d = {"key": "value"}
    assert trim_details(d) == d


def test_trim_details_large_truncated():
    d = {"data": "x" * 25_000}
    result = trim_details(d)
    assert result.get("truncated") is True
    assert len(result["preview"]) <= 20_000
