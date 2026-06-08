"""MemorySearcher — executes a single MEMORY domain search request.

Orchestration order (per PUML memory_search_flow, steps 94-135):
  1. (vector / hybrid only) ensure_model_ready → embed_query   (VectorTool)
  2. compile DSL                                                (QueryProfileCompiler)
  3. search_content_docs                                        (IDatabaseWriter)
  4. map_hits → return result dict

MEMORY-specific field conventions
----------------------------------
* ``keyword`` search targets **multiple** term fields:
  ``memory_id.keyword``, ``task_ids.keyword``, ``feature_tags.keyword``,
  ``domain_tags.keyword``, ``component_tags.keyword``.
  The :class:`QueryProfileCompiler` produces a ``bool.should + term``
  clause when ``term_fields`` contains more than one entry.

* ``text`` search spans four fields: ``title``, ``abstract``, ``overview``,
  ``content``.

* ``vector`` / ``hybrid`` embed the query and use ``content_vector``.

* Hit mapping (dot-path resolution, exclusions, score sourcing) is handled
  by :func:`bible.features.search.common.hit_mapper.map_hits`.

Important — hybrid profile completeness
----------------------------------------
The MEMORY binding's ``search_profile_json["search_type_profile"]["hybrid"]``
**must** include ``vector_field`` (e.g. ``"content_vector"``),
``num_candidates``, and ``fields``.
The :class:`QueryProfileCompiler` raises :class:`SearchProfileInvalidError`
if ``vector_field`` is absent.  See memory_search_v4_tasks.md §2 for the
recommended complete profile.
"""

from __future__ import annotations

from typing import Any

from bible.common.logger import get_logger
from bible.features.search.common.hit_mapper import map_hits as _map_hits_fn
from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)

# SearchInternalError is shared across all search domains.
# Reuse the definition from the KB searcher module (see task-doc §4).
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.vector.vector_tool import VectorTool

logger = get_logger(__name__)

_VECTOR_TYPES = frozenset({"vector", "hybrid"})


class MemorySearcher:
    """Searcher for the MEMORY domain.

    All infrastructure dependencies are injected at construction time so the
    class is fully testable without a real database or embedding model.

    Parameters
    ----------
    db_writer:
        Concrete :class:`IDatabaseWriter` instance for the MEMORY domain.
    vector_tool:
        Shared embedding tool (``ensure_model_ready`` + ``embed_query``).
    compiler:
        Optional pre-built :class:`QueryProfileCompiler`.  A fresh instance
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
        """Execute a MEMORY search and return a normalised result dict.

        Parameters
        ----------
        kb_index:
            OpenSearch index name to search.
        query:
            Raw user query string (already validated non-empty by the API
            layer).
        search_type:
            Effective search type, normalised by the Service layer.
            One of ``keyword | title | text | vector | hybrid``.
        top_k:
            Maximum number of results to return.
        search_profile:
            The full ``search_profile_json`` dict from the index binding.
            For ``hybrid`` search this must include ``vector_field``; see
            the module docstring for details.
        vector_model:
            Name of the embedding model from the binding.  Required when
            *search_type* is ``vector`` or ``hybrid``.
        vector_weight:
            kNN vs BM25 balance for hybrid search (0 < w ≤ 1).  When
            *None* the compiler falls back to the profile default.

        Returns
        -------
        dict with keys ``kb_index``, ``total``, ``items`` (list of hit dicts).

        Raises
        ------
        SearchProfileInvalidError
            Re-raised from :class:`QueryProfileCompiler` or raised directly
            when ``vector_model`` is absent for vector/hybrid search.
            Maps to HTTP 422 at the API layer.
        SearchInternalError
            Wraps database or embedding failures.
            Maps to HTTP 500 at the API layer.
        """
        logger.info(
            "MEMORY searcher started index=%s search_type=%s top_k=%d vector_model=%s query_len=%d",
            kb_index,
            search_type,
            top_k,
            vector_model or "<none>",
            len(query),
        )

        # ── Step 1: vector embedding (vector / hybrid only) ───────────────
        query_vector: list[float] | None = None
        if search_type in _VECTOR_TYPES:
            if not vector_model:
                raise SearchProfileInvalidError(
                    "vector_model is required for search_type='%s' but the "
                    "MEMORY binding has no vector_model set." % search_type
                )
            try:
                logger.info("MEMORY searcher preparing query vector index=%s model=%s", kb_index, vector_model)
                self._vector_tool.ensure_model_ready(vector_model)
                query_vector = self._vector_tool.embed_query(query, vector_model)
                logger.info(
                    "MEMORY searcher query vector ready index=%s model=%s dims=%d",
                    kb_index,
                    vector_model,
                    len(query_vector),
                )
            except Exception as exc:
                logger.error(
                    "MEMORY: failed to produce query vector for model '%s': %s",
                    vector_model,
                    exc,
                )
                raise SearchInternalError(
                    "Vector embedding failed: %s" % exc
                ) from exc

        # ── Step 2: compile DSL ───────────────────────────────────────────
        # SearchProfileInvalidError propagates to the API layer → HTTP 422.
        logger.info("MEMORY searcher compiling DSL index=%s search_type=%s", kb_index, search_type)
        dsl, response_fields = self._compiler.compile(
            search_type=search_type,
            query=query,
            top_k=top_k,
            search_profile=search_profile,
            vector_weight=vector_weight,
            query_vector=query_vector,
        )
        logger.info(
            "MEMORY searcher DSL compiled index=%s search_type=%s response_fields=%d",
            kb_index,
            search_type,
            len(response_fields),
        )

        # ── Step 3: execute search ────────────────────────────────────────
        try:
            logger.info("MEMORY searcher querying database index=%s", kb_index)
            raw = self._db_writer.search_content_docs(index=kb_index, dsl=dsl)
        except Exception as exc:
            logger.error(
                "MEMORY: search_content_docs failed for index '%s': %s",
                kb_index,
                exc,
            )
            raise SearchInternalError(
                "Database search failed: %s" % exc
            ) from exc

        # ── Step 4: map hits ──────────────────────────────────────────────
        items = _map_hits_fn(raw.get("hits", []), response_fields)
        logger.info(
            "MEMORY searcher mapped results index=%s total=%s raw_hits=%d items=%d",
            kb_index,
            raw.get("total"),
            len(raw.get("hits", [])),
            len(items),
        )
        return {
            "kb_index": kb_index,
            "total": raw.get("total", len(items)),
            "items": items,
        }
