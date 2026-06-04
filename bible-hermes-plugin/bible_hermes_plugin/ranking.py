"""BiBLE Hermes Plugin — hit normalization, deduplication, and scoring.

Mirrors src/context/ranking.ts from the OpenClaw plugin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from .logging_utils import log

RecallDomain = Literal["memory", "skill", "knowledge"]

_DOMAIN_BOOST: dict[str, float] = {"memory": 0.08, "skill": 0.04, "knowledge": 0.0}
_DOMAIN_PRIORITY: dict[str, int] = {"memory": 3, "skill": 2, "knowledge": 1}


@dataclass
class RecallHit:
    id: str
    domain: str
    score: float
    title: str | None = None
    summary: str | None = None
    content_preview: str | None = None
    source_ref: str | None = None
    tag: str | None = None
    updated_at: str | None = None
    metadata: dict = field(default_factory=dict, repr=False)
    final_score: float | None = None
    prompt_injection_risk: bool = False


def normalize_hits(domain: str, payload: dict, tag: str | None = None) -> list[RecallHit]:
    """Extract and normalise raw API hits into RecallHit objects."""
    raw_hits = _extract_hits(domain, payload, tag)
    log("debug", "ranking.normalize_hits start", {"domain": domain, "tag": tag, "raw_count": len(raw_hits)})
    hits: list[RecallHit] = []
    for idx, raw in enumerate(raw_hits):
        hit = _normalize_hit(domain, raw, idx, tag)
        if hit is not None:
            hits.append(hit)
    log("debug", "ranking.normalize_hits done", {"domain": domain, "tag": tag, "normalized_count": len(hits)})
    return hits


def filter_rank_and_trim(
    hits: list[RecallHit],
    query: str,
    min_score: float,
    top_k: int,
) -> list[RecallHit]:
    """Deduplicate, filter by min_score, score, sort, and slice to top_k."""
    log("debug", "ranking.filter_rank start", {"input_count": len(hits), "min_score": min_score, "top_k": top_k})
    deduped = _dedupe_hits(hits)
    filtered = [
        h for h in deduped
        if h.score >= min_score and (h.title or h.summary or h.content_preview)
    ]
    result: list[RecallHit] = []
    for h in filtered:
        h.prompt_injection_risk = _has_prompt_injection_risk(h)
        h.final_score = _compute_final_score(h, query)
        result.append(h)
    result.sort(key=lambda h: h.final_score or 0.0, reverse=True)
    trimmed = result[:top_k]
    log("debug", "ranking.filter_rank done", {
        "input_count": len(hits),
        "after_dedup": len(deduped),
        "after_filter": len(filtered),
        "final_count": len(trimmed),
    })
    return trimmed


# ── internal ──────────────────────────────────────────────────────────────────

def _normalize_hit(domain: str, raw: dict, index: int, tag: str | None) -> RecallHit | None:
    hit_id = (
        _first_str(raw, ["memory_id", "memoryId", "doc_id", "chunk_id", "skill_id", "id", "name"])
        or f"{domain}_{index}"
    )
    title = _first_str(raw, ["title", "name", "heading"])
    summary = _first_str(raw, ["abstract", "summary", "description", "overview"])
    content_preview = _first_str(raw, ["matched_message_preview", "preview", "text", "content", "excerpt"])
    raw_score = _first_num(raw, ["score", "similarity", "relevance"])
    return RecallHit(
        id=hit_id,
        domain=domain,
        title=title,
        summary=summary,
        content_preview=content_preview,
        source_ref=_first_str(raw, ["source", "source_ref", "path", "storage_path"]),
        score=_normalize_score(raw_score if raw_score is not None else 1.0),
        tag=tag or _first_str(raw, ["tag", "kb_tag"]),
        updated_at=_first_str(raw, ["updated_at", "updatedAt", "timestamp"]),
        metadata=raw,
    )


def _extract_hits(domain: str, payload: dict, tag: str | None) -> list[dict]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return []
    if domain == "knowledge":
        for key in (tag, "knowledge_base", "knowledge"):
            if key:
                items = results.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
        return []
    items = results.get(domain, [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _dedupe_hits(hits: list[RecallHit]) -> list[RecallHit]:
    by_key: dict[str, RecallHit] = {}
    for hit in hits:
        strong_key = f"{hit.domain}:{hit.id or hit.source_ref}"
        weak_key = _fingerprint(f"{hit.title or ''}\n{hit.content_preview or hit.summary or ''}")
        key = strong_key if (hit.id or hit.source_ref) else weak_key
        existing = by_key.get(key)
        if existing is None or hit.score > existing.score or (hit.score == existing.score and _DOMAIN_PRIORITY.get(hit.domain, 0) > _DOMAIN_PRIORITY.get(existing.domain, 0)):
            by_key[key] = hit
    return list(by_key.values())


def _compute_final_score(hit: RecallHit, query: str) -> float:
    recency_boost = 0.0
    if hit.updated_at:
        try:
            from datetime import datetime, timezone
            updated = datetime.fromisoformat(hit.updated_at.replace("Z", "+00:00"))
            age_ms = (datetime.now(timezone.utc) - updated).total_seconds() * 1000
            if age_ms < 30 * 24 * 3600 * 1000:
                recency_boost = 0.1
        except Exception:
            pass
    text = " ".join(filter(None, [hit.title, hit.summary, hit.content_preview]))
    overlap = _query_term_overlap(query, text) * 0.1
    symbol_boost = 0.05 if _exact_symbol_boost(query, hit) else 0.0
    domain_boost = _DOMAIN_BOOST.get(hit.domain, 0.0)
    return hit.score * 0.55 + recency_boost + domain_boost + overlap + symbol_boost


def _query_term_overlap(query: str, text: str) -> float:
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return 0.0
    t_tokens = set(_tokens(text))
    matches = sum(1 for t in q_tokens if t in t_tokens)
    return min(1.0, matches / len(q_tokens))


def _exact_symbol_boost(query: str, hit: RecallHit) -> bool:
    symbols = re.findall(r"[A-Za-z0-9_./-]{6,}", query)
    haystack = f"{hit.title or ''} {hit.summary or ''} {hit.content_preview or ''}"
    return any(s in haystack for s in symbols)


def _has_prompt_injection_risk(hit: RecallHit) -> bool:
    text = f"{hit.title or ''}\n{hit.summary or ''}\n{hit.content_preview or ''}".lower()
    return bool(re.search(
        r"ignore (all )?(previous|above) instructions|system prompt|developer message|you are now",
        text,
    ))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w_./-]{2,}", text.lower())


def _normalize_score(score: float) -> float:
    if not isinstance(score, (int, float)) or score != score:  # NaN check
        return 0.0
    if score > 1:
        return max(0.0, min(1.0, score / 100))
    return max(0.0, min(1.0, score))


def _fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()[:256]


def _first_str(raw: dict, keys: list[str]) -> str | None:
    for key in keys:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _first_num(raw: dict, keys: list[str]) -> float | None:
    for key in keys:
        val = raw.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
    return None
