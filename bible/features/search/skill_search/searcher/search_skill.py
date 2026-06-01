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
        pass

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

        dsl, response_fields = self._compiler.compile(
            search_type=search_type,
            query=query,
            top_k=top_k,
            search_profile=search_profile,
            vector_weight=vector_weight,
            query_vector=query_vector,
        )

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

        items = _map_hits_fn(raw.get("hits", []), response_fields)
        return {
            "kb_index": kb_index,
            "total": raw.get("total", len(items)),
            "items": items,
        }

