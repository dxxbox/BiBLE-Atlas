"""Tests for BibleAtlasClient error handling and helper functions."""

from __future__ import annotations

import pytest

from bible_hermes_plugin.http_client import (
    BibleAtlasError,
    _parse_json,
    _prune_none,
    _search_body,
    error_details,
)


# ── BibleAtlasError ───────────────────────────────────────────────────────────

def test_bible_atlas_error_attributes():
    err = BibleAtlasError("BIBLE_TIMEOUT", "Request timed out", status_code=504)
    assert err.code == "BIBLE_TIMEOUT"
    assert "Request timed out" in str(err)
    assert err.status_code == 504


def test_bible_atlas_error_default_status():
    err = BibleAtlasError("BIBLE_ERR", "msg")
    assert err.status_code is None


# ── error_details ─────────────────────────────────────────────────────────────

def test_error_details_from_bible_atlas_error():
    err = BibleAtlasError("BIBLE_NOT_FOUND", "missing")
    details = error_details(err)
    assert details["code"] == "BIBLE_NOT_FOUND"
    assert details["message"] == "missing"


def test_error_details_from_generic_error():
    details = error_details(ValueError("bad value"))
    assert "code" in details
    assert "message" in details
    assert "bad value" in details["message"]


# ── _prune_none ───────────────────────────────────────────────────────────────

def test_prune_none_removes_nones():
    assert _prune_none({"a": 1, "b": None, "c": "x"}) == {"a": 1, "c": "x"}


def test_prune_none_empty_dict():
    assert _prune_none({}) == {}


def test_prune_none_no_nones():
    d = {"a": 0, "b": False, "c": ""}
    assert _prune_none(d) == d  # 0, False, "" are kept


# ── _search_body ──────────────────────────────────────────────────────────────

def test_search_body_required_fields():
    body = _search_body("query text", "memory", 8, None, "hybrid")
    assert body["query"] == "query text"
    assert body["tag"] == "memory"
    assert body["top_k"] == 8
    assert body["search_type"] == "hybrid"


def test_search_body_omits_none_threshold():
    body = _search_body("q", "memory", 5, None, "hybrid")
    assert "threshold" not in body


def test_search_body_includes_threshold_when_set():
    body = _search_body("q", "memory", 5, 0.4, "hybrid")
    assert body["threshold"] == pytest.approx(0.4)


def test_search_body_defaults_search_type():
    body = _search_body("q", "skill", 8, None, "")
    assert body["search_type"] == "hybrid"


# ── _parse_json ───────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


def test_parse_json_valid_dict():
    r = _FakeResponse('{"ok": true, "count": 3}')
    assert _parse_json(r) == {"ok": True, "count": 3}  # type: ignore[arg-type]


def test_parse_json_empty_body():
    r = _FakeResponse("   ")
    assert _parse_json(r) == {}  # type: ignore[arg-type]


def test_parse_json_non_dict_wrapped():
    r = _FakeResponse("[1, 2, 3]")
    result = _parse_json(r)  # type: ignore[arg-type]
    assert "result" in result


def test_parse_json_invalid_json():
    r = _FakeResponse("{bad json}")
    assert _parse_json(r) == {}  # type: ignore[arg-type]
