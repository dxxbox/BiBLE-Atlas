"""Tool result helpers — ok()/fail(), validation, hit summarization.

Mirrors src/tools/helpers.ts from the OpenClaw plugin.
"""

from __future__ import annotations

import json
from typing import Any

from ..http_client import error_details
from ..logging_utils import log

# ── result builders ───────────────────────────────────────────────────────────

def ok(content: str, details: dict | None = None) -> str:
    """Return a successful tool result as a JSON string."""
    return json.dumps({"ok": True, "content": content, **(details or {})})


def fail(exc: Exception) -> str:
    """Return an error tool result as a JSON string."""
    d = error_details(exc)
    log("warning", "tool.fail", {"code": d.get("code"), "message": d.get("message")})
    return json.dumps({"ok": False, "error": True, "content": f"{d['code']}: {d['message']}", **d})


# ── argument validation ───────────────────────────────────────────────────────

def require_string(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required.")
    return value.strip()


def optional_int(args: dict, key: str, fallback: int, min_val: int, max_val: int) -> int:
    value = args.get(key)
    if value is None:
        return fallback
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer.")
    if value < min_val or value > max_val:
        raise ValueError(f"{key} must be between {min_val} and {max_val}.")
    return value


def optional_search_type(args: dict) -> str:
    value = args.get("search_type") or args.get("searchType")
    if value is None:
        return "hybrid"
    valid = ("keyword", "title", "text", "vector", "hybrid")
    if value not in valid:
        raise ValueError(f"search_type must be one of: {', '.join(valid)}.")
    return value


def as_object(input_: Any) -> dict:
    if not isinstance(input_, dict):
        raise ValueError("Tool input must be an object.")
    return input_


# ── hit summarization ─────────────────────────────────────────────────────────

def summarize_hits(domain: str, payload: dict) -> str:
    hits = extract_hits(domain, payload)
    if not hits:
        return f"Found 0 BiBLE {domain} hits."
    top = hits[0]
    title = (
        top.get("title") or top.get("name") or top.get("memory_id") or "untitled"
    )
    score = top.get("score")
    score_str = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
    return f"Found {len(hits)} BiBLE {domain} hits. Top hit: {title}{score_str}."


def extract_hits(domain: str, payload: dict, aliases: tuple[str, ...] = ()) -> list[dict]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return []
    for key in (domain, *aliases):
        items = results.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


# ── details trimming ──────────────────────────────────────────────────────────

def trim_details(details: dict) -> dict:
    serialized = json.dumps(details)
    if len(serialized) <= 20_000:
        return details
    return {"truncated": True, "preview": serialized[:20_000]}
