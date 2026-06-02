"""hit_mapper — shared hit-mapping utilities for all Search domain searchers.

Both :class:`SkillSearcher` and :class:`MemorySearcher` (and any future
domain searcher) share identical logic for converting raw OpenSearch hits
into clean result dicts.  This module centralises that logic so it can be
tested once and reused without duplication.

Public API
----------
MISSING
    Sentinel object returned by :func:`resolve_dot_path` when a field path
    cannot be resolved.  Lets callers distinguish *not found* from legitimate
    falsy values such as ``[]``, ``0``, or ``False``.

resolve_dot_path(source, path)
    Traverse a nested dict following a dot-separated key path.

map_hits(hits, response_fields)
    Convert a list of raw OpenSearch hit dicts into clean result dicts.
"""

from __future__ import annotations

from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

MISSING: Any = object()
"""Sentinel used by :func:`resolve_dot_path` to signal a missing path."""

EXCLUDED_FIELDS: frozenset[str] = frozenset({"chunk_id", "took_ms"})
"""Fields that are never exposed in search results, even if listed in
``response_fields``."""

SCORE_FIELD: str = "score"
"""Output key for the relevance score (sourced from ``_score``, not
``_source``)."""


# ── Public helpers ────────────────────────────────────────────────────────────


def resolve_dot_path(source: dict[str, Any], path: str) -> tuple[str, Any]:
    """Traverse *source* following *path* (dot-separated key segments).

    Parameters
    ----------
    source:
        The top-level ``_source`` dict from an OpenSearch hit.
    path:
        A dot-separated field path such as ``"metadata.related_storage_paths"``.

    Returns
    -------
    tuple[str, Any]
        ``(leaf_key, value)`` where *leaf_key* is the last segment of *path*
        and *value* is the resolved value or :data:`MISSING` when the path
        cannot be followed (key absent or an intermediate value is not a dict).

    Examples
    --------
    >>> src = {"metadata": {"related_storage_paths": ["/mnt/x"]}}
    >>> resolve_dot_path(src, "metadata.related_storage_paths")
    ('related_storage_paths', ['/mnt/x'])

    >>> resolve_dot_path(src, "metadata.nonexistent")
    ('nonexistent', <MISSING>)
    """
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
    """Convert raw OpenSearch hits into clean result dicts.

    Rules
    -----
    * When *response_fields* is non-empty, only those fields are included
      from ``_source``.  When it is empty, every field is included.
    * Dot-path fields (e.g. ``"metadata.related_storage_paths"``) are
      resolved via :func:`resolve_dot_path` and stored under the **leaf key
      name** (``"related_storage_paths"``).
    * :data:`EXCLUDED_FIELDS` (``chunk_id``, ``took_ms``) are always
      omitted, even when listed in *response_fields*.
    * ``score`` is always sourced from the hit's ``_score`` field — never
      from ``_source`` — and is written last so it cannot be overridden.

    Parameters
    ----------
    hits:
        The ``hits`` list from a raw ``search_content_docs`` return value.
        Each element must have ``_score`` (float) and ``_source`` (dict).
    response_fields:
        Ordered list of field names to include.  May contain dot-path
        entries.  Pass an empty list to include all non-excluded fields.

    Returns
    -------
    list[dict[str, Any]]
        One cleaned dict per input hit.
    """
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
