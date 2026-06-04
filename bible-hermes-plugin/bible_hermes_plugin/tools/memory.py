"""BiBLE Hermes Plugin — memory tools.

Three tools: bible_memory_search, bible_memory_save, bible_memory_get.
Mirrors src/tools/memory.ts from the OpenClaw plugin.
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

MEMORY_SEARCH_SCHEMA: dict = {
    "name": "bible_memory_search",
    "description": "Search BiBLE Atlas memories for relevant conversation context.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Search query string."},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum number of results to return (default 8)."},
            "search_type": {
                "type": "string",
                "enum": ["keyword", "title", "text", "vector", "hybrid"],
                "description": "Search strategy (default: hybrid).",
            },
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "description": "Minimum relevance score (0-1)."},
        },
    },
}

MEMORY_SAVE_SCHEMA: dict = {
    "name": "bible_memory_save",
    "description": "Save structured conversation material into BiBLE Atlas memory.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["messages"],
        "properties": {
            "messages": {
                "type": "array",
                "description": "Conversation messages to save. Each item must have role (user|assistant|tool) and content.",
                "items": {
                    "type": "object",
                    "required": ["role", "content"],
                    "properties": {
                        "role": {"type": "string", "enum": ["user", "assistant", "tool"]},
                        "content": {"type": "string"},
                    },
                },
            },
            "title": {"type": "string", "description": "Short title for the memory entry."},
            "abstract": {"type": "string", "description": "One-paragraph summary."},
            "overview": {"type": "string", "description": "Longer overview of the conversation."},
            "kb_index": {"type": "string", "description": "Knowledge base index to save into."},
            "task_ids": {"type": "array", "items": {"type": "string"}, "description": "Associated task IDs."},
            "feature_tags": {"type": "array", "items": {"type": "string"}},
            "domain_tags": {"type": "array", "items": {"type": "string"}},
            "component_tags": {"type": "array", "items": {"type": "string"}},
            "metadata": {"type": "object", "description": "Arbitrary metadata key/value pairs."},
            "wait": {"type": "boolean", "description": "If true, wait for the import task to complete."},
        },
    },
}

MEMORY_GET_SCHEMA: dict = {
    "name": "bible_memory_get",
    "description": "Get a BiBLE Atlas memory by ID.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["memory_id"],
        "properties": {
            "memory_id": {"type": "string", "description": "The memory ID to retrieve."},
        },
    },
}


# ── handlers ──────────────────────────────────────────────────────────────────

def make_memory_search_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            query = require_string(args, "query")
            top_k = optional_int(args, "top_k", 8, 1, 50)
            min_score = args.get("min_score")
            search_type = optional_search_type(args)
            log("info", "tool.memory_search start", {"query_len": len(query), "top_k": top_k, "search_type": search_type})
            payload = client.search_memory(query, top_k, min_score, search_type)
            hits = extract_hits("memory", payload)
            log("info", "tool.memory_search done", {"hits": len(hits)})
            return ok(summarize_hits("memory", payload), trim_details({"hits": hits, "raw": payload}))
        except Exception as exc:
            return fail(exc)
    return handler


def make_memory_save_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            raw_messages = args.get("messages")
            if not isinstance(raw_messages, list):
                raise ValueError("messages is required.")
            messages = [_normalize_message(m) for m in raw_messages]
            log("info", "tool.memory_save start", {"message_count": len(messages), "wait": args.get("wait")})
            payload = client.save_memory(
                messages=messages,
                title=args.get("title") if isinstance(args.get("title"), str) else None,
                abstract=args.get("abstract") if isinstance(args.get("abstract"), str) else None,
                overview=args.get("overview") if isinstance(args.get("overview"), str) else None,
                kb_index=args.get("kb_index") if isinstance(args.get("kb_index"), str) else None,
                task_ids=[t for t in (args.get("task_ids") or []) if isinstance(t, str)],
                feature_tags=[t for t in (args.get("feature_tags") or []) if isinstance(t, str)],
                domain_tags=[t for t in (args.get("domain_tags") or []) if isinstance(t, str)],
                component_tags=[t for t in (args.get("component_tags") or []) if isinstance(t, str)],
                metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
                wait=args.get("wait") is True,
            )
            log("info", "tool.memory_save done", {"memory_id": payload.get("memory_id") or payload.get("memoryId")})
            return ok("Saved BiBLE memory request.", trim_details({"result": payload}))
        except Exception as exc:
            return fail(exc)
    return handler


def make_memory_get_handler(client: BibleAtlasClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            args = as_object(args)
            memory_id = require_string(args, "memory_id")
            log("info", "tool.memory_get start", {"memory_id": memory_id})
            payload = client.get_memory(memory_id)
            title = payload.get("title") or memory_id
            log("info", "tool.memory_get done", {"memory_id": memory_id, "title": title})
            return ok(f"Loaded BiBLE memory: {title}.", trim_details({"memory": payload}))
        except Exception as exc:
            return fail(exc)
    return handler


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalize_message(message: object) -> dict:
    if not isinstance(message, dict):
        raise ValueError("Each message must be an object.")
    if message.get("role") not in ("user", "assistant", "tool"):
        raise ValueError("message.role must be user, assistant, or tool.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("message.content is required.")
    return {"role": message["role"], "content": content}
