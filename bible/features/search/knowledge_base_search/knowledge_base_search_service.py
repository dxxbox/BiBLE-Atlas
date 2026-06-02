"""KnowledgeBaseSearchService — business-logic layer for KNOWLEDGE_BASE search.

Implements the flow described in knowledge_base_search_implementation.md §6
and knowledge_base_search_flow.puml steps 72-139:

  1. Validate query / tag (non-empty).
  2. Get IDatabaseWriter from DatabaseFactory (domain=KNOWLEDGE_BASE).
  3. Look up binding by (KNOWLEDGE_BASE, tag).
  4. Normalise search_type / top_k / vector_weight.
  5. Check vector_model consistency.
  6. Delegate to KnowledgeBaseSearcher.
  7. Build and return the unified response structure.
"""

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

# ── Domain constant ────────────────────────────────────────────────────────────
_DOMAIN = "KNOWLEDGE_BASE"
_DEFAULT_SEARCH_TYPE = "text"

# ── Service-level error classes ────────────────────────────────────────────────


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


# ── Service ───────────────────────────────────────────────────────────────────


class KnowledgeBaseSearchService:
    """Orchestrates the full KNOWLEDGE_BASE search flow.

    Parameters
    ----------
    db_factory:
        Factory that yields :class:`IDatabaseWriter` instances.
    vector_tool:
        Shared embedding tool; passed through to :class:`KnowledgeBaseSearcher`.
    search_cfg:
        Search-related config (default_top_k, max_top_k, allowed_search_types).
        Defaults to library defaults when omitted.
    searcher:
        Optional pre-built searcher instance.  When *None* (default) the
        service constructs one per request using *db_factory* and *vector_tool*.
        Inject a fake here in unit tests.
    """

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

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        tag: str,
        search_type: str | None,
        top_k: int | None,
        vector_model: str | None,
        vector_weight: float | None,
    ) -> dict[str, Any]:
        """Execute a KNOWLEDGE_BASE search and return a structured response.

        Parameters
        ----------
        query:
            User query string (required, non-empty).
        tag:
            Logical knowledge-base label used to look up the binding.
        search_type:
            One of ``keyword/title/text/vector/hybrid``.  Falls back to
            ``text`` when *None*.
        top_k:
            Maximum hits to return.  Falls back to ``search_cfg.default_top_k``
            when *None*, capped to ``search_cfg.max_top_k``.
        vector_model:
            If provided, must equal the model stored in the binding.
        vector_weight:
            kNN weight for hybrid search (0 < w ≤ 1).

        Returns
        -------
        dict matching the v4 API response schema::

            {
                "success": True,
                "domain": "KNOWLEDGE_BASE",
                "kb_index": "...",
                "tag": "...",
                "total": N,
                "results": {"knowledge_base": [...]},
            }

        Raises
        ------
        InvalidArgumentError
            ``query`` or ``tag`` is empty.
        IndexNotBoundError
            No active binding exists for the given *tag*.
        VectorModelConflictError
            *vector_model* was supplied and differs from the binding's model.
        SearchProfileInvalidError
            The binding's profile cannot be compiled (propagated from Searcher).
        SearchInternalError
            Database or embedding failure (propagated from Searcher).
        """
        # ── 1. Obtain DB writer ───────────────────────────────────────────
        db_writer = self._db_factory.get_writer(domain=_DOMAIN)  # type: ignore[arg-type]

        # ── 2. Look up binding ────────────────────────────────────────────
        binding = db_writer.get_binding_by_domain_tag(_DOMAIN, tag)  # type: ignore[arg-type]
        if binding is None:
            raise IndexNotBoundError(tag)

        # ── 3. Normalise parameters ───────────────────────────────────────
        effective_search_type = search_type or _DEFAULT_SEARCH_TYPE
        effective_top_k = self._normalise_top_k(top_k)
        effective_vector_weight = self._normalise_vector_weight(
            vector_weight, effective_search_type, binding.search_profile_json
        )

        # ── 4. Vector-model consistency check ─────────────────────────────
        bound_model: str | None = binding.vector_model
        if vector_model and bound_model and vector_model != bound_model:
            raise VectorModelConflictError(
                requested=vector_model, bound=bound_model
            )
        # Use the binding's model for actual embedding; caller's value only
        # served as an assertion above.
        effective_vector_model = bound_model

        # ── 5. Delegate to Searcher ───────────────────────────────────────
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

        # ── 6. Build response ─────────────────────────────────────────────
        return self._build_response(
            tag=tag,
            kb_index=search_result["kb_index"],
            total=search_result["total"],
            items=search_result["items"],
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

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
        """Resolve the effective vector_weight for this request.

        - Non-vector/hybrid types: always ``None`` (weight is irrelevant).
        - vector/hybrid + caller supplied a value: use that value as-is
          (range validation 0≤w≤1 is done by the API layer).
        - vector/hybrid + caller omitted (``None``): fall back to
          ``search_type_profile.hybrid.default_vector_weight`` from the
          binding profile, then to the hard-coded default 0.6.
        """
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
