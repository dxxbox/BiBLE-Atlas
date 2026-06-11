"""BiBLE CC Plugin — recall pipeline.

Runs parallel searches across memory / knowledge domains and returns
ranked hits ready for context injection.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import re

from .config import BibleCCConfig
from .client import BibleAtlasClient
from .injection import render_relevant_memories
from .logging_utils import action_logger, log
from .ranking import RecallHit, filter_rank_and_trim, normalize_hits


def run_recall_pipeline(
    user_message: str,
    conversation_history: list[dict],
    config: BibleCCConfig,
    client: BibleAtlasClient,
) -> tuple[str, list[str]]:
    """Run the BiBLE Atlas recall pipeline for memory + knowledge domains.

    Returns (rendered_context_string, warnings_list).
    """
    query = _build_recall_query(user_message, conversation_history)
    if not query:
        return "", []

    warnings: list[str] = []
    tasks: list[tuple[str, str | None]] = []

    if config.enable_memory_recall:
        tasks.append(("memory", None))
    if config.enable_knowledge_recall:
        for tag in config.knowledge_tags:
            tasks.append(("knowledge", tag))

    if not tasks:
        return "", warnings

    hits = _run_parallel_searches(tasks, query, config, client, warnings)
    ranked = filter_rank_and_trim(hits, query, config.recall_min_score, config.recall_top_k)
    rendered = render_relevant_memories(ranked, config.injection_token_budget)
    return rendered, warnings


def build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    return _build_recall_query(user_message, conversation_history)


def _build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    recent_text = "\n".join(
        _text_from_message(m)
        for m in conversation_history[-6:]
        if _text_from_message(m)
    )
    raw = "\n".join(filter(None, [recent_text, user_message]))
    return _clean_for_query(raw)[:2000].strip()


def _run_parallel_searches(
    tasks: list[tuple[str, str | None]],
    query: str,
    config: BibleCCConfig,
    client: BibleAtlasClient,
    warnings: list[str],
) -> list[RecallHit]:
    all_hits: list[RecallHit] = []

    def search_one(domain: str, tag: str | None) -> list[RecallHit]:
        try:
            if domain == "memory":
                payload = client.search_memory(query, config.recall_top_k, config.recall_min_score)
            else:
                payload = client.search_knowledge(query, tag or "", config.recall_top_k, config.recall_min_score)
            return normalize_hits(domain, payload, tag)
        except Exception as exc:
            warnings.append(f"{domain} recall failed: {exc}")
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {pool.submit(search_one, domain, tag): (domain, tag) for domain, tag in tasks}
        for future in concurrent.futures.as_completed(futures):
            with contextlib.suppress(Exception):
                all_hits.extend(future.result())

    return all_hits


def _text_from_message(message: dict) -> str:
    content = message.get("content") or message.get("text") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text") or item.get("content") or ""
            for item in content
            if isinstance(item, dict)
        )
    return ""


def _clean_for_query(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", lambda m: " [code block omitted] " if len(m.group()) > 500 else m.group(), text)
    text = re.sub(r"[A-Za-z0-9+/=]{120,}", " [encoded blob omitted] ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
