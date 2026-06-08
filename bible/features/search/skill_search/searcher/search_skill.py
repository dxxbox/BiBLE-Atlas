"""SkillSearcher — executes a single SKILL domain search request.

Orchestration order (per PUML skill_search_flow, steps 100-141):
  1. (vector / hybrid only) ensure_model_ready → embed_query   (VectorTool)
  2. compile DSL                                                (QueryProfileCompiler)
  3. search_content_docs                                        (IDatabaseWriter)
  4. map_hits → return result dict

SKILL-specific field conventions
---------------------------------
* ``keyword`` search targets ``name.keyword`` (field^boost notation, design §4).
* ``title`` search is equivalent to matching on ``name`` (design §4).
* ``text`` search spans: ``name``, ``description``, ``body``, ``content``.
* ``vector`` / ``hybrid`` embed the query and use ``content_vector``.

* Hit mapping (dot-path resolution, exclusions, score sourcing) is handled
  by :func:`bible.features.search.common.hit_mapper.map_hits`.

Profile format
--------------
The binding stores the profile in the flat SKILL-canonical format (design §5)::

    {
      "keyword":  {"fields": ["name.keyword^5"]},
      "title":    {"fields": ["name^3"]},
      "text":     {"fields": ["name^4", "description^2", "body^1.5", "content^1"]},
      "vector":   {"vector_field": "content_vector",
                   "source_template": "...", "num_candidates": 100},
      "hybrid":   {"default_vector_weight": 0.5},
      "response_fields": [...]
    }

:func:`_adapt_skill_profile` converts this to :class:`QueryProfileCompiler`
format before calling ``compiler.compile()``.  Profiles already in the
``search_type_profile`` wrapper format (e.g. unit-test fixtures) are passed
through unchanged.
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
# Reuse the definition from the KB searcher module (see task-doc §3).
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.vector.vector_tool import VectorTool

logger = get_logger(__name__)

_VECTOR_TYPES = frozenset({"vector", "hybrid"})


def _parse_field_boost(spec: str) -> dict[str, Any]:
    """Parse ``"field^boost"`` notation into ``{"field": ..., "weight": ...}``.

    Examples::
        "name.keyword^5"  →  {"field": "name.keyword", "weight": 5.0}
        "name"            →  {"field": "name", "weight": 1.0}
    """
    if "^" in spec:
        field, _, boost_str = spec.partition("^")
        try:
            weight = float(boost_str)
        except ValueError:
            weight = 1.0
        return {"field": field, "weight": weight}
    return {"field": spec, "weight": 1.0}


def _adapt_skill_profile(raw_profile: dict[str, Any]) -> dict[str, Any]:
    """Convert the SKILL-canonical profile format to QueryProfileCompiler format.

    The skill upload service (design-doc §5) writes a flat profile where:
    - ``keyword.fields`` / ``title.fields`` / ``text.fields`` are ``"field^boost"``
      string lists
    - ``vector`` has ``vector_field``, ``source_template``, ``num_candidates``
    - ``hybrid.default_vector_weight`` is the kNN balance scalar (older builders
      may write ``vector_weight`` instead)

    QueryProfileCompiler expects:
    - ``keyword.term_fields``  – list of ``{"field": ..., "weight": ...}`` dicts
    - ``title.match_fields``   – list of ``{"field": ..., "weight": ...}`` dicts
    - ``text.fields``          – list of ``{"field": ..., "weight": ...}`` dicts
    - ``vector``               – only ``vector_field`` and (optional) ``num_candidates``
    - ``hybrid.default_vector_weight`` + ``vector_field`` – scalar and field name

    This function performs the conversion so the existing compiler is reused
    unchanged.

    If the profile already contains a ``search_type_profile`` wrapper key it is
    already in the format the compiler expects; return it unchanged so that
    unit-test fixtures and manually-constructed profiles are not corrupted.
    """
    if "search_type_profile" in raw_profile:
        return raw_profile

    adapted: dict[str, Any] = {}

    # ── keyword ───────────────────────────────────────────────────────────
    kw = raw_profile.get("keyword")
    if isinstance(kw, dict):
        fields_raw: list[str] = kw.get("fields", [])
        if fields_raw and all(isinstance(f, str) for f in fields_raw):
            adapted["keyword"] = {"term_fields": [_parse_field_boost(f) for f in fields_raw]}
        else:
            # Already in compiler format or empty — pass through
            adapted["keyword"] = {k: v for k, v in kw.items() if k != "fields"}
            if kw.get("term_fields"):
                adapted["keyword"]["term_fields"] = kw["term_fields"]

    # ── title ─────────────────────────────────────────────────────────────
    # Design §4: title search is equivalent to name matching.
    ti = raw_profile.get("title")
    if isinstance(ti, dict):
        ti_fields_raw: list = ti.get("fields", [])
        if ti_fields_raw and all(isinstance(f, str) for f in ti_fields_raw):
            adapted["title"] = {"match_fields": [_parse_field_boost(f) for f in ti_fields_raw]}
        elif ti.get("match_fields"):
            adapted["title"] = {"match_fields": ti["match_fields"]}
    if "title" not in adapted:
        # Backward-compat: older bindings without a title section default to
        # matching the name field with neutral weight.
        adapted["title"] = {"match_fields": [{"field": "name", "weight": 1.0}]}

    # ── text ──────────────────────────────────────────────────────────────
    tx = raw_profile.get("text")
    if isinstance(tx, dict):
        tx_fields_raw: list = tx.get("fields", [])
        if tx_fields_raw and all(isinstance(f, str) for f in tx_fields_raw):
            converted = [_parse_field_boost(f) for f in tx_fields_raw]
        else:
            converted = tx_fields_raw  # already dicts or empty
        tx_adapted: dict[str, Any] = {"fields": converted}
        if "multi_match_type" in tx:
            tx_adapted["multi_match_type"] = tx["multi_match_type"]
        adapted["text"] = tx_adapted

    # ── vector ────────────────────────────────────────────────────────────
    vec = raw_profile.get("vector")
    if isinstance(vec, dict):
        vec_adapted: dict[str, Any] = {}
        # The compiler requires vector_field; default to "content_vector" per
        # design-doc §5 when the binding omits it (older bindings written by
        # the upload service may only have source_template).
        vec_adapted["vector_field"] = vec.get("vector_field", "content_vector")
        if "num_candidates" in vec:
            vec_adapted["num_candidates"] = vec["num_candidates"]
        adapted["vector"] = vec_adapted

    # ── hybrid ────────────────────────────────────────────────────────────
    hy = raw_profile.get("hybrid")
    if isinstance(hy, dict):
        hy_adapted: dict[str, Any] = {}
        # Accept both "vector_weight" and "default_vector_weight"
        dvw = hy.get("default_vector_weight") or hy.get("vector_weight")
        if dvw is not None:
            hy_adapted["default_vector_weight"] = float(dvw)
        # The compiler requires vector_field for hybrid; fall back to
        # the vector sub-profile's value (or default "content_vector").
        vec_sub = raw_profile.get("vector") or {}
        hy_adapted["vector_field"] = hy.get("vector_field") or vec_sub.get("vector_field", "content_vector")
        for key in ("num_candidates", "fields", "match_fields", "multi_match_type"):
            if key in hy:
                hy_adapted[key] = hy[key]
        adapted["hybrid"] = hy_adapted

    # ── response_fields (pass through untouched) ─────────────────────────
    if "response_fields" in raw_profile:
        adapted["response_fields"] = raw_profile["response_fields"]

    return adapted


class SkillSearcher:
    """Searcher for the SKILL domain.

    All infrastructure dependencies are injected at construction time so the
    class is fully testable without a real database or embedding model.

    Parameters
    ----------
    db_writer:
        Concrete :class:`IDatabaseWriter` instance for the SKILL domain.
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
        """Execute a SKILL search and return a normalised result dict.

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
            "SKILL searcher started index=%s search_type=%s top_k=%d vector_model=%s query_len=%d",
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
                    "SKILL binding has no vector_model set." % search_type
                )
            try:
                logger.info(
                    "SKILL searcher preparing query vector index=%s model=%s",
                    kb_index,
                    vector_model,
                )
                self._vector_tool.ensure_model_ready(vector_model)
                query_vector = self._vector_tool.embed_query(query, vector_model)
                logger.info(
                    "SKILL searcher query vector ready index=%s model=%s dims=%d",
                    kb_index,
                    vector_model,
                    len(query_vector),
                )
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
        # Adapt the SKILL-canonical profile format to QueryProfileCompiler's
        # expected format before compilation.  SearchProfileInvalidError
        # propagates to the API layer → HTTP 422.
        adapted_profile = _adapt_skill_profile(search_profile)
        logger.info(
            "SKILL searcher compiling DSL index=%s search_type=%s",
            kb_index,
            search_type,
        )
        dsl, response_fields = self._compiler.compile(
            search_type=search_type,
            query=query,
            top_k=top_k,
            search_profile=adapted_profile,
            vector_weight=vector_weight,
            query_vector=query_vector,
        )
        logger.info(
            "SKILL searcher DSL compiled index=%s search_type=%s response_fields=%d",
            kb_index,
            search_type,
            len(response_fields),
        )

        # ── Step 3: execute search ────────────────────────────────────────
        try:
            logger.info("SKILL searcher querying database index=%s", kb_index)
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
        logger.info(
            "SKILL searcher mapped results index=%s total=%s raw_hits=%d items=%d",
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
