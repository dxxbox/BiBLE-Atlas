"""KnowledgeBaseSearcher — executes a single knowledge-base search request.

Orchestration order (per PUML knowledge_base_search_flow):
  1. (vector / hybrid only) ensure_model_ready → embed_query   (VectorTool)
  2. compile DSL                                                (QueryProfileCompiler)
  3. search_content_docs                                        (IDatabaseWriter)
  4. map_hits → return result dict
"""

from __future__ import annotations

import logging
from typing import Any

from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.vector.vector_tool import VectorTool

logger = logging.getLogger(__name__)

_VECTOR_TYPES = frozenset({"vector", "hybrid"})


class SearchInternalError(RuntimeError):
    """Wraps unexpected database / encoding failures.

    Maps to INTERNAL_ERROR (HTTP 500) at the API layer.
    """


class KnowledgeBaseSearcher:
    """Searcher for the KNOWLEDGE_BASE domain.

    Dependencies are injected at construction time so the class is fully
    testable without touching real databases or embedding models.
    """

    def __init__(
        self,
        db_writer: IDatabaseWriter,
        vector_tool: VectorTool,
        compiler: QueryProfileCompiler | None = None,
    ) -> None:
        self._db_writer = db_writer
        self._vector_tool = vector_tool
        self._compiler = compiler or QueryProfileCompiler()

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def search(
        self,
        kb_index: str,
        query: str,
        search_type: str,
        top_k: int,
        search_profile: dict[str, Any],
        vector_model: str | None,
        vector_weight: float | None,
    ) -> dict[str, Any]:
        """Execute a knowledge-base search and return a normalised result dict.

        Parameters
        ----------
        kb_index:
            OpenSearch index name to search.
        query:
            Raw user query string.
        search_type:
            Effective search type (already normalised by the Service layer).
        top_k:
            Maximum number of results to return.
        search_profile:
            The full ``search_profile_json`` dict from the index binding.
        vector_model:
            Name of the embedding model from the binding.  Required when
            *search_type* is ``vector`` or ``hybrid``.
        vector_weight:
            kNN vs BM25 balance for hybrid search (0 < w ≤ 1).

        Returns
        -------
        dict with keys: ``kb_index``, ``total``, ``items`` (list of hit dicts).

        Raises
        ------
        SearchProfileInvalidError
            Re-raised from QueryProfileCompiler; the caller maps it to 422.
        SearchInternalError
            Wraps database or embedding failures; the caller maps it to 500.
        """
        # ── Step 1: vector embedding (vector / hybrid only) ───────────────
        query_vector: list[float] | None = None
        if search_type in _VECTOR_TYPES:
            if not vector_model:
                raise SearchProfileInvalidError(
                    "vector_model is required for search_type='%s' but the "
                    "binding has no vector_model set." % search_type
                )
            try:
                self._vector_tool.ensure_model_ready(vector_model)
                query_vector = self._vector_tool.embed_query(query, vector_model)
            except Exception as exc:
                logger.error(
                    "Failed to produce query vector for model '%s': %s",
                    vector_model,
                    exc,
                )
                raise SearchInternalError(
                    "Vector embedding failed: %s" % exc
                ) from exc

        # ── Step 2: compile DSL ───────────────────────────────────────────
        # SearchProfileInvalidError is intentionally allowed to propagate.
        dsl, response_fields = self._compiler.compile(
            search_type=search_type,
            query=query,
            top_k=top_k,
            search_profile=search_profile,
            vector_weight=vector_weight,
            query_vector=query_vector,
        )

        # ── Step 3: execute search ────────────────────────────────────────
        try:
            raw = self._db_writer.search_content_docs(index=kb_index, dsl=dsl)
        except Exception as exc:
            logger.error(
                "search_content_docs failed for index '%s': %s", kb_index, exc
            )
            raise SearchInternalError(
                "Database search failed: %s" % exc
            ) from exc

        # ── Step 4: map hits ──────────────────────────────────────────────
        items = self._map_hits(raw.get("hits", []), response_fields)
        return {
            "kb_index": kb_index,
            "total": raw.get("total", len(items)),
            "items": items,
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _map_hits(
        hits: list[dict[str, Any]],
        response_fields: list[str],
    ) -> list[dict[str, Any]]:
        """Convert raw OpenSearch hits into clean result dicts.

        Rules:
        - Only include fields listed in *response_fields* from ``_source``.
        - ``score`` is taken from ``_score`` (never from ``_source``).
        - ``chunk_id`` and ``took_ms`` are explicitly excluded even if present
          in *response_fields*.

        When *response_fields* is empty every ``_source`` field is included
        (except the two excluded names above) so callers always get usable
        output even when a profile omits the field list.
        """
        _excluded = frozenset({"chunk_id", "took_ms"})
        result: list[dict[str, Any]] = []

        for hit in hits:
            source: dict[str, Any] = hit.get("_source", {})
            score: float = hit.get("_score", 0.0)

            if response_fields:
                item = {
                    field: source[field]
                    for field in response_fields
                    if field not in _excluded and field in source
                }
            else:
                item = {
                    k: v for k, v in source.items() if k not in _excluded
                }

            item["score"] = score
            result.append(item)

        return result
