"""BiBLE Hermes Plugin — recall pipeline.

Runs parallel searches across memory / skill / knowledge domains and returns
ranked hits ready for context injection.

Mirrors src/context/recall.ts from the OpenClaw plugin. Adapted for the
Hermes pre_llm_call hook signature: receives user_message + conversation_history.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import re

from .config import BibleHermesConfig
from .http_client import BibleAtlasClient
from .injection import render_relevant_memories
from .logging_utils import action_logger, log
from .ranking import RecallHit, filter_rank_and_trim, normalize_hits

# ── public API ────────────────────────────────────────────────────────────────

def run_recall_pipeline(
    user_message: str,
    conversation_history: list[dict],
    config: BibleHermesConfig,
    client: BibleAtlasClient,
) -> tuple[str, list[str]]:
    """Run the BiBLE Atlas recall pipeline.

    Returns (rendered_context_string, warnings_list).
    rendered_context_string is empty when nothing was found or all domains
    are disabled. The caller injects it into the Hermes pre_llm_call context.
    """
    query = _build_recall_query(user_message, conversation_history)
    al = action_logger("recall.pipeline", {
        "query_len": len(query),
        "memory": config.enable_memory_recall,
        "skill": config.enable_skill_recall,
        "knowledge": config.enable_knowledge_recall,
    })
    al.start()

    if not query:
        al.done({"skipped": "empty_query"})
        return "", []

    warnings: list[str] = []
    tasks: list[tuple[str, str | None]] = []  # (domain, tag)

    if config.enable_memory_recall:
        tasks.append(("memory", None))
    if config.enable_skill_recall:
        tasks.append(("skill", None))
    if config.enable_knowledge_recall:
        for tag in config.knowledge_tags:
            tasks.append(("knowledge", tag))

    if not tasks:
        al.done({"skipped": "no_domains"})
        return "", warnings

    hits = _run_parallel_searches(tasks, query, config, client, warnings)
    ranked = filter_rank_and_trim(hits, query, config.recall_min_score, config.recall_top_k)
    budget = min(
        config.injection_token_budget,
        config.injection_token_budget,  # same — no runtime context budget in Hermes hook
    )
    rendered = render_relevant_memories(ranked, budget)
    al.done({
        "domains": len(tasks),
        "raw_hits": len(hits),
        "ranked_hits": len(ranked),
        "rendered_chars": len(rendered),
        "warnings": len(warnings),
    })
    return rendered, warnings


def build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    return _build_recall_query(user_message, conversation_history)


# ── internal ──────────────────────────────────────────────────────────────────

def _build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    recent_text = "\n".join(
        _text_from_message(m)
        for m in conversation_history[-6:]
        if _text_from_message(m)
    )
    raw = "\n".join(filter(None, [recent_text, user_message]))
    query = _clean_for_query(raw)[:2000].strip()
    log("debug", "recall.query built", {
        "user_msg_len": len(user_message),
        "history_turns": len(conversation_history),
        "recent_text_len": len(recent_text),
        "final_query_len": len(query),
    })
    return query


def _run_parallel_searches(
    tasks: list[tuple[str, str | None]],
    query: str,
    config: BibleHermesConfig,
    client: BibleAtlasClient,
    warnings: list[str],
) -> list[RecallHit]:
    """Run domain searches concurrently using a thread pool."""
    all_hits: list[RecallHit] = []

    def search_one(domain: str, tag: str | None) -> list[RecallHit]:
        al = action_logger("recall.domain", {"domain": domain, "tag": tag})
        al.start()
        try:
            if domain == "memory":
                payload = client.search_memory(query, config.recall_top_k, config.recall_min_score)
            elif domain == "skill":
                payload = client.search_skill(query, config.recall_top_k, config.recall_min_score)
            else:
                payload = client.search_knowledge(query, tag or "", config.recall_top_k, config.recall_min_score)
            hits = normalize_hits(domain, payload, tag)
            al.done({"hits": len(hits)})
            return hits
        except Exception as exc:
            msg = f"{domain} recall failed: {exc}"
            warnings.append(msg)
            log("warning", f"recall.domain warning: {msg}", {"domain": domain, "tag": tag})
            al.done({"failed": True, "hits": 0})
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {pool.submit(search_one, domain, tag): (domain, tag) for domain, tag in tasks}
        for future in concurrent.futures.as_completed(futures):
            with contextlib.suppress(Exception):  # warning already added inside search_one
                all_hits.extend(future.result())

    return all_hits


def _text_from_message(message: dict) -> str:
    content = message.get("content") or message.get("text") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_from_item(item) for item in content if _text_from_item(item))
    return ""


def _text_from_item(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("text") or item.get("content") or ""
    return ""


def _clean_for_query(text: str) -> str:
    # Omit large code blocks
    text = re.sub(r"```[\s\S]*?```", lambda m: " [code block omitted] " if len(m.group()) > 500 else m.group(), text)
    # Omit encoded blobs
    text = re.sub(r"[A-Za-z0-9+/=]{120,}", " [encoded blob omitted] ", text)
    # Collapse excess newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
