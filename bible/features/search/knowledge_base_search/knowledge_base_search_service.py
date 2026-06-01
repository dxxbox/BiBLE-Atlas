from __future__ import annotations

import logging
from typing import Any

from bible.config.configure import SearchConfig
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    KnowledgeBaseSearcher,
    SearchInternalError,
)
from bible.infrastructure.database.factory import DatabaseFactory
from bible.infrastructure.vector.vector_tool import VectorTool

logger = logging.getLogger(__name__)

_DOMAIN = "KNOWLEDGE_BASE"
_DEFAULT_SEARCH_TYPE = "text"

class IndexNotBoundError(LookupError):
    """Raised when no active binding exists for (KNOWLEDGE_BASE, tag).

    Maps to INDEX_NOT_BOUND / HTTP 404 at the API layer.
    """

    def __init__(self, tag: str) -> None:
        super().__init__(
            f"No active KNOWLEDGE_BASE binding found for tag='{tag}'."
        )
        self.tag = tag

class VectorModelConflictError(ValueError):
    """Raised when the caller requests a vector_model that differs from the binding.

    Maps to VECTOR_MODEL_CONFLICT / HTTP 409 at the API layer.
    """

    def __init__(self, requested: str, bound: str) -> None:
        super().__init__(
            f"Requested vector_model '{requested}' conflicts with the bound "
            f"model '{bound}'.  Only the binding's model may be used."
        )
        self.requested = requested
        self.bound = bound



class KnowledgeBaseSearchService():

    def __init__(
        self,
        db_factory: DatabaseFactory,
        vector_tool: VectorTool,
        search_cfg: SearchConfig | None = None,
        searcher: KnowledgeBaseSearcher | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._vector_tool = vector_tool
        self._search_cfg = search_cfg or SearchConfig()
        self._searcher = searcher

    def search(
        self,
        query: str,
        tag: str,
        search_type: str | None,
        top_k: int | None,
        vector_model: str | None,
        vector_weight: float | None,
    ) -> dict[str, Any]:

        db_writer = self._db_factory.get_writer(domain=_DOMAIN)
        binding = db_writer.get_binding_by_domain_tag(_DOMAIN, tag)
        if binding is None:
            raise IndexNotBoundError(tag)

        effective_search_type = search_type or _DEFAULT_SEARCH_TYPE
        effective_top_k = self._normalise_top_k(top_k)
        effective_vector_weight = self._normalise_vector_weight(
            vector_weight, effective_search_type, binding.search_profile_json
        )

        bound_model: str | None = binding.vector_model
        if vector_model and bound_model and vector_model != bound_model:
            raise VectorModelConflictError(
                requested=vector_model, bound=bound_model
            )

        effective_vector_model = bound_model

        searcher = self._get_searcher(db_writer)
        search_result = searcher.search(
            kb_index=binding.kb_index,
            query=query,
            search_type=effective_search_type,
            top_k=effective_top_k,
            search_profile=binding.search_profile_json,
            vector_model=effective_vector_model,
            vector_weight=effective_vector_weight,
        )

        return self._build_response(
            tag=tag,
            kb_index=search_result["kb_index"],
            total=search_result["total"],
            items=search_result["items"],
        )

    def _normalise_top_k(self, top_k: int | None) -> int:
        cfg = self._search_cfg
        effective = top_k if top_k is not None else cfg.default_top_k
        return min(effective, cfg.max_top_k)

    @staticmethod
    def _normalise_vector_weight(
        vector_weight: float | None,
        search_type: str,
        search_profile: dict[str, Any],
    ) -> float | None:
        if search_type not in ("vector", "hybrid"):
            return None
        if vector_weight is not None:
            return vector_weight
        # Try to read default from the binding profile
        stp = search_profile.get("search_type_profile", {})
        hybrid_cfg = stp.get("hybrid", search_profile)
        return hybrid_cfg.get("default_vector_weight", 0.6)

    def _get_searcher(self, db_writer: Any) -> KnowledgeBaseSearcher:
        """Return the injected searcher or create one from the current writer."""
        if self._searcher is not None:
            return self._searcher
        return KnowledgeBaseSearcher(
            db_writer=db_writer,
            vector_tool=self._vector_tool,
        )

    @staticmethod
    def _build_response(
        tag: str,
        kb_index: str,
        total: int,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "success": True,
            "domain": _DOMAIN,
            "kb_index": kb_index,
            "tag": tag,
            "total": total,
            "results": {"knowledge_base": items},
        }                
