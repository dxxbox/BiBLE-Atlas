"""SkillSearcher — executes a single SKILL domain search request.

Orchestration order (per PUML skill_search_flow, steps 94-135):
  1. (vector / hybrid only) ensure_model_ready → embed_query   (VectorTool)
  2. compile DSL                                                (QueryProfileCompiler)
  3. search_content_docs                                        (IDatabaseWriter)
  4. map_hits → return result dict

Hit mapping (dot-path, exclusions, score sourcing) is handled by the shared
:mod:`bible.features.search.common.hit_mapper` module.
"""

from __future__ import annotations

import logging
from typing import Any

from bible.features.search.common.hit_mapper import (
    MISSING as _MISSING,
    map_hits as _map_hits_fn,
    resolve_dot_path as _resolve_dot_path,
)
from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)

# SearchInternalError is shared across domains; reuse from the KB searcher
# module rather than redefining it.  See task-doc §3 (error class strategy).
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.vector.vector_tool import VectorTool

logger = logging.getLogger(__name__)

_VECTOR_TYPES = frozenset({"vector", "hybrid"})


class SkillSearcher:
    """Searcher for the SKILL domain.

    Dependencies are injected at construction time so the class is fully
    testable without touching real databases or embedding models.

    Parameters
    ----------
    db_writer:
        Concrete :class:`IDatabaseWriter` instance for the SKILL domain.
    vector_tool:
        Shared embedding tool.
    compiler:
        Optional pre-built :class:`QueryProfileCompiler`.  A new instance
        is created when *None* (the production default).
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
        """Execute a SKILL search and return a normalised result dict.

        Parameters
        ----------
        kb_index:
            OpenSearch index name to search.
        query:
            Raw user query string (already validated non-empty by the API layer).
        search_type:
            Effective search type, normalised by the Service layer.
            One of ``keyword | title | text | vector | hybrid``.
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
        dict with keys ``kb_index``, ``total``, ``items`` (list of hit dicts).

        Raises
        ------
        SearchProfileInvalidError
            Re-raised from :class:`QueryProfileCompiler`; maps to HTTP 422.
        SearchInternalError
            Wraps database or embedding failures; maps to HTTP 500.
        """
        # ── Step 1: vector embedding (vector / hybrid only) ───────────────
        query_vector: list[float] | None = None
        if search_type in _VECTOR_TYPES:
            if not vector_model:
                raise SearchProfileInvalidError(
                    "vector_model is required for search_type='%s' but the "
                    "SKILL binding has no vector_model set." % search_type
                )
            try:
                self._vector_tool.ensure_model_ready(vector_model)
                query_vector = self._vector_tool.embed_query(query, vector_model)
            except Exception as exc:
                logger.error(
                    "SKILL: failed to produce query vector for model '%s': %s",
                    vector_model,
                    exc,
                )
                raise SearchInternalError(
                    "Vector embedding failed: %s" % exc
                ) from exc

        # ── Step 2: compile DSL ───────────────────────────────────────────
        # SearchProfileInvalidError is allowed to propagate so the API layer
        # can return the correct 422 response.
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
                "SKILL: search_content_docs failed for index '%s': %s",
                kb_index,
                exc,
            )
            raise SearchInternalError(
                "Database search failed: %s" % exc
            ) from exc

        # ── Step 4: map hits ──────────────────────────────────────────────
        items = _map_hits_fn(raw.get("hits", []), response_fields)
        return {
            "kb_index": kb_index,
            "total": raw.get("total", len(items)),
            "items": items,
        }
