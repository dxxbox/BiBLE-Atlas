"""MemorySearchService — business-logic layer for MEMORY search.

Implements the flow described in memory_search_implementation.md §6
and memory_search_flow.puml steps 69-139:

  1. Get IDatabaseWriter from DatabaseFactory (domain=MEMORY).
  2. Look up binding by (MEMORY, tag).
  3. Normalise search_type / top_k / vector_weight.
  4. Check vector_model consistency.
  5. Delegate to MemorySearcher.
  6. Build and return the unified response structure.
"""

from __future__ import annotations

from typing import Any

from bible.common.logger import get_logger
from bible.config.configure import SearchConfig
from bible.features.search.memory_search.searcher.search_memory import MemorySearcher
from bible.infrastructure.database.factory import DatabaseFactory
from bible.infrastructure.vector.vector_tool import VectorTool

logger = get_logger(__name__)

# ── Domain constant ────────────────────────────────────────────────────────────
_DOMAIN = "MEMORY"
_DEFAULT_SEARCH_TYPE = "text"

# ── Service-level error classes ────────────────────────────────────────────────


class IndexNotBoundError(LookupError):
    """Raised when no active MEMORY binding is found for the given tag.

    Maps to INDEX_NOT_BOUND / HTTP 404 at the API layer.
    """

    def __init__(self, value: str, *, selector: str = "tag") -> None:
        super().__init__(
            f"No active MEMORY binding found for {selector}='{value}'."
        )
        self.tag = value
        self.selector = selector
        self.value = value


class VectorModelConflictError(ValueError):
    """Raised when the caller's vector_model differs from the binding's model.

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


class MemorySearchService:
    """Orchestrates the full MEMORY search flow.

    Parameters
    ----------
    db_factory:
        Factory that yields :class:`IDatabaseWriter` instances.
    vector_tool:
        Shared embedding tool; passed through to :class:`MemorySearcher`.
    search_cfg:
        Search-related config (default_top_k, max_top_k, allowed_search_types).
        Defaults to library defaults when omitted.
    searcher:
        Optional pre-built :class:`MemorySearcher` instance.  When *None*
        (the production default) the service constructs one per request.
        Inject a fake here in unit tests.
    """

    def __init__(
        self,
        db_factory: DatabaseFactory,
        vector_tool: VectorTool,
        search_cfg: SearchConfig | None = None,
        searcher: MemorySearcher | None = None,
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
        kb_index: str | None = None,
    ) -> dict[str, Any]:
        """Execute a MEMORY search and return a structured response.

        Parameters
        ----------
        query:
            User query string (required, non-empty; validated by the API layer).
        tag:
            MEMORY tag used to look up the binding.  Per design the fixed
            value is ``"memory"``; the API layer enforces this constraint.
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
                "domain": "MEMORY",
                "kb_index": "...",
                "tag": "memory",
                "total": N,
                "results": {"memory": [...]},
            }

        Raises
        ------
        IndexNotBoundError
            No active binding exists for the given *tag*.
        VectorModelConflictError
            *vector_model* was supplied and differs from the binding's model.
        SearchProfileInvalidError
            The binding's profile cannot be compiled (propagated from Searcher).
        SearchInternalError
            Database or embedding failure (propagated from Searcher).
        """
        logger.info(
            "MEMORY search started tag=%s kb_index=%s query_len=%d requested_search_type=%s requested_top_k=%s vector_model=%s",
            tag,
            kb_index or "<by-tag>",
            len(query),
            search_type or "<default>",
            top_k if top_k is not None else "<default>",
            vector_model or "<binding>",
        )

        # ── 1. Obtain DB writer ───────────────────────────────────────────
        db_writer = self._db_factory.get_writer(domain=_DOMAIN)  # type: ignore[arg-type]
        logger.debug("MEMORY search DB writer acquired backend_domain=%s", _DOMAIN)

        # ── 2. Look up binding ────────────────────────────────────────────
        if kb_index:
            binding = db_writer.get_binding_by_domain_index(_DOMAIN, kb_index)  # type: ignore[arg-type]
            binding_selector = "kb_index"
            binding_selector_value = kb_index
        else:
            binding = db_writer.get_binding_by_domain_tag(_DOMAIN, tag)  # type: ignore[arg-type]
            binding_selector = "tag"
            binding_selector_value = tag
        if binding is None:
            logger.warning(
                "MEMORY search binding not found selector=%s value=%s",
                binding_selector,
                binding_selector_value,
            )
            raise IndexNotBoundError(binding_selector_value, selector=binding_selector)
        logger.info(
            "MEMORY search binding selected selector=%s value=%s tag=%s kb_index=%s active=%s vector_model=%s",
            binding_selector,
            binding_selector_value,
            binding.tag,
            binding.kb_index,
            binding.is_active,
            binding.vector_model or "<none>",
        )

        # ── 3. Normalise parameters ───────────────────────────────────────
        effective_search_type = search_type or _DEFAULT_SEARCH_TYPE
        effective_top_k = self._normalise_top_k(top_k)
        effective_vector_weight = self._normalise_vector_weight(
            vector_weight, effective_search_type, binding.search_profile_json
        )
        logger.info(
            "MEMORY search parameters normalised kb_index=%s search_type=%s top_k=%d vector_weight=%s",
            binding.kb_index,
            effective_search_type,
            effective_top_k,
            effective_vector_weight if effective_vector_weight is not None else "<none>",
        )

        # ── 4. Vector-model consistency check ─────────────────────────────
        bound_model: str | None = binding.vector_model
        if vector_model and bound_model and vector_model != bound_model:
            logger.warning(
                "MEMORY search vector model conflict requested=%s bound=%s kb_index=%s",
                vector_model,
                bound_model,
                binding.kb_index,
            )
            raise VectorModelConflictError(
                requested=vector_model, bound=bound_model
            )
        # Use the binding's model for actual embedding; caller's value only
        # served as a consistency assertion above.
        effective_vector_model = bound_model

        # ── 5. Delegate to Searcher ───────────────────────────────────────
        searcher = self._get_searcher(db_writer)
        content_index = f"memory_{binding.kb_index}"
        logger.info(
            "MEMORY search dispatching to searcher kb_index=%s content_index=%s",
            binding.kb_index,
            content_index,
        )
        search_result = searcher.search(
            kb_index=content_index,
            query=query,
            search_type=effective_search_type,
            top_k=effective_top_k,
            search_profile=binding.search_profile_json,
            vector_model=effective_vector_model,
            vector_weight=effective_vector_weight,
        )
        logger.info(
            "MEMORY search completed kb_index=%s content_index=%s total=%s items=%d",
            binding.kb_index,
            content_index,
            search_result.get("total"),
            len(search_result.get("items", [])),
        )

        # ── 6. Build response ─────────────────────────────────────────────
        return self._build_response(
            tag=tag,
            kb_index=binding.kb_index,
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

        - Non-vector/hybrid types: always ``None``.
        - vector/hybrid + caller supplied: use as-is (range validated by API).
        - vector/hybrid + caller omitted: fall back to
          ``search_type_profile.hybrid.default_vector_weight``,
          then to the hard-coded default 0.6.
        """
        if search_type not in ("vector", "hybrid"):
            return None
        if vector_weight is not None:
            return vector_weight
        stp = search_profile.get("search_type_profile", {})
        hybrid_cfg = stp.get("hybrid", search_profile)
        return hybrid_cfg.get("default_vector_weight", 0.6)

    def _get_searcher(self, db_writer: Any) -> MemorySearcher:
        """Return the injected searcher or create one from the current writer."""
        if self._searcher is not None:
            return self._searcher
        return MemorySearcher(
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
            "results": {"memory": items},
        }
