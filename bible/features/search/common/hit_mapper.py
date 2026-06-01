from __future__ import annotations

from typing import Any

MISSING: Any = object()
"""Sentinel used by :func:`resolve_dot_path` to signal a missing path."""

EXCLUDED_FIELDS: frozenset[str] = frozenset({"chunk_id", "took_ms"})
"""Fields that are never exposed in search results, even if listed in
``response_fields``."""

SCORE_FIELD: str = "score"
"""Output key for the relevance score (sourced from ``_score``, not
``_source``)."""

def resolve_dot_path(source: dict[str, Any], path: str) -> tuple[str, Any]:
    parts = path.split(".")
    val: Any = source
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part, MISSING)
        else:
            return parts[-1], MISSING
        if val is MISSING:
            return parts[-1], MISSING
    return parts[-1], val

def map_hits(
    hits: list[dict[str, Any]],
    response_fields: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for hit in hits:
        source: dict[str, Any] = hit.get("_source", {})
        score: float = hit.get("_score", 0.0)

        if response_fields:
            item: dict[str, Any] = {}
            for field in response_fields:
                if field in EXCLUDED_FIELDS or field == SCORE_FIELD:
                    continue
                if "." in field:
                    leaf, value = resolve_dot_path(source, field)
                    if value is not MISSING:
                        item[leaf] = value
                else:
                    if field in source:
                        item[field] = source[field]
        else:
            item = {k: v for k, v in source.items() if k not in EXCLUDED_FIELDS}

        item[SCORE_FIELD] = score
        result.append(item)

    return result    