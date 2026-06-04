"""BiBLE Hermes Plugin — skill tools.

Two tools: bible_skill_search, bible_skill_get.
Mirrors src/tools/skill.ts from the OpenClaw plugin.
"""

from __future__ import annotations

from ..http_client import BibleAtlasClient
from ..logging_utils import log
from .helpers import (
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

# ── schemas ───────────────────────────────────────────────────────────────────

SKILL_SEARCH_SCHEMA: dict = {
    "name": "bible_skill_search",
    "description": "Search BiBLE Atlas skills.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Search query string."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum results (default 8)."},
            "search_type": {
                "type": "string",
                "enum": ["text", "vector", "hybrid"],
                "description": "Search strategy (default: hybrid).",
            },
        },
    },
}

SKILL_GET_SCHEMA: dict = {
    "name": "bible_skill_get",
    "description": "Get a BiBLE Atlas skill by ID or name.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            "skill_id": {"type": "string", "description": "Skill ID to retrieve."},
            "name": {"type": "string", "description": "Skill name to retrieve (alternative to skill_id)."},
        },
    },
}


# ── handlers ──────────────────────────────────────────────────────────────────

def make_skill_search_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            query = require_string(args, "query")
            top_k = optional_int(args, "top_k", 8, 1, 50)
            search_type = optional_search_type(args)
            log("info", "tool.skill_search start", {"query_len": len(query), "top_k": top_k, "search_type": search_type})
            payload = client.search_skill(query, top_k, search_type=search_type)
            hits = extract_hits("skill", payload)
            log("info", "tool.skill_search done", {"hits": len(hits)})
            return ok(summarize_hits("skill", payload), trim_details({"hits": hits, "raw": payload}))
        except Exception as exc:
            return fail(exc)
    return handler


def make_skill_get_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            skill_id = args.get("skill_id") if isinstance(args.get("skill_id"), str) else None
            name = args.get("name") if isinstance(args.get("name"), str) else None
            if not skill_id and not name:
                raise ValueError("skill_id or name is required.")
            log("info", "tool.skill_get start", {"skill_id": skill_id, "name": name})
            payload = client.get_skill(skill_id, name)
            label = payload.get("name") or skill_id or name or "?"
            log("info", "tool.skill_get done", {"label": label})
            return ok(f"Loaded BiBLE skill: {label}.", trim_details({"skill": payload}))
        except Exception as exc:
            return fail(exc)
    return handler
