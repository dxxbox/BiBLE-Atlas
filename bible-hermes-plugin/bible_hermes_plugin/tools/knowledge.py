"""BiBLE Hermes Plugin — knowledge tools.

Two tools: bible_knowledge_search, bible_knowledge_list.
Mirrors src/tools/knowledge.ts from the OpenClaw plugin.
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
    trim_details,
)

# ── schemas ───────────────────────────────────────────────────────────────────

KNOWLEDGE_SEARCH_SCHEMA: dict = {
    "name": "bible_knowledge_search",
    "description": "Search a tagged BiBLE Atlas knowledge base.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query", "tag"],
        "properties": {
            "query": {"type": "string", "description": "Search query string."},
            "tag": {"type": "string", "description": "Knowledge base tag to search within."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum results (default 8)."},
            "search_type": {
                "type": "string",
                "enum": ["text", "vector", "hybrid"],
                "description": "Search strategy (default: hybrid).",
            },
        },
    },
}

KNOWLEDGE_LIST_SCHEMA: dict = {
    "name": "bible_knowledge_list",
    "description": "List BiBLE Atlas knowledge bases or tags.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
}


# ── handlers ──────────────────────────────────────────────────────────────────

def make_knowledge_search_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            query = require_string(args, "query")
            tag = require_string(args, "tag")
            top_k = optional_int(args, "top_k", 8, 1, 50)
            search_type = optional_search_type(args)
            log("info", "tool.knowledge_search start", {"query_len": len(query), "tag": tag, "top_k": top_k})
            payload = client.search_knowledge(query, tag, top_k, search_type=search_type)
            hits = extract_hits(tag, payload, aliases=("knowledge_base", "knowledge"))
            log("info", "tool.knowledge_search done", {"tag": tag, "hits": len(hits)})
            summary = _summarize(tag, hits)
            return ok(summary, trim_details({"hits": hits, "raw": payload}))
        except Exception as exc:
            return fail(exc)
    return handler


def _summarize(tag: str, hits: list[dict]) -> str:
    if not hits:
        return f"Found 0 BiBLE knowledge hits for tag '{tag}'."
    top = hits[0]
    title = top.get("title") or top.get("name") or top.get("memory_id") or "untitled"
    score = top.get("score")
    score_str = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
    return f"Found {len(hits)} BiBLE knowledge hits for tag '{tag}'. Top hit: {title}{score_str}."


def make_knowledge_list_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            log("info", "tool.knowledge_list start", {})
            payload = client.list_knowledge()
            log("info", "tool.knowledge_list done", {})
            return ok("Loaded BiBLE knowledge list.", trim_details({"knowledge": payload}))
        except Exception as exc:
            return fail(exc)
    return handler
