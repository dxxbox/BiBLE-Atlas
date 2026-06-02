"""QueryProfileCompiler — translates a search_profile dict + runtime params into OpenSearch DSL.

Supported search_type values: keyword | title | text | vector | hybrid
"""

from __future__ import annotations

from typing import Any


class SearchProfileInvalidError(ValueError):
    """Raised when a search_profile cannot be compiled into a valid DSL.

    Maps to the SEARCH_PROFILE_INVALID error code in the API layer.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QueryProfileCompiler:
    """Stateless compiler: call :meth:`compile` for each request."""

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def compile(
        self,
        *,
        search_type: str,
        query: str,
        top_k: int,
        search_profile: dict[str, Any],
        vector_weight: float | None = None,
        query_vector: list[float] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Compile *search_profile* + runtime params into ``(dsl, response_fields)``.

        Parameters
        ----------
        search_type:
            One of ``keyword``, ``title``, ``text``, ``vector``, ``hybrid``.
        query:
            Raw user query string.
        top_k:
            Maximum number of hits to return.
        search_profile:
            Binding-level profile dict.  The top-level key
            ``search_type_profile`` is the canonical wrapper; a flat profile
            (keys directly present at the top level) is also accepted for
            backwards compatibility.
        vector_weight:
            BM25 vs. kNN balance for ``hybrid`` (0 < w ≤ 1; higher means more
            kNN).  Falls back to ``default_vector_weight`` from the profile.
        query_vector:
            Pre-computed dense vector for ``vector`` / ``hybrid`` searches.
            Must be provided when ``search_type`` is ``vector`` or ``hybrid``.

        Returns
        -------
        tuple[dict[str, Any], list[str]]
            ``(opensearch_dsl, response_fields)``

        Raises
        ------
        SearchProfileInvalidError
            When the profile cannot be compiled (e.g. missing fields, missing
            ``query_vector`` for vector/hybrid, disabled search type).
        """
        stp = self._extract_type_profile(search_type, search_profile)
        response_fields: list[str] = search_profile.get("response_fields", [])

        if search_type == "keyword":
            dsl = self._compile_keyword(query, top_k, stp)
        elif search_type == "title":
            dsl = self._compile_title(query, top_k, stp)
        elif search_type == "text":
            dsl = self._compile_text(query, top_k, stp)
        elif search_type == "vector":
            dsl = self._compile_vector(query, top_k, stp, query_vector)
        elif search_type == "hybrid":
            dsl = self._compile_hybrid(query, top_k, stp, query_vector, vector_weight)
        else:
            raise SearchProfileInvalidError(
                f"Unsupported search_type: '{search_type}'.  "
                "Allowed: keyword, title, text, vector, hybrid."
            )

        return dsl, response_fields

    # ------------------------------------------------------------------ #
    # Per-type compilers                                                   #
    # ------------------------------------------------------------------ #

    def _compile_keyword(
        self, query: str, top_k: int, profile: dict[str, Any]
    ) -> dict[str, Any]:
        term_fields: list[dict[str, Any]] = profile.get("term_fields", [])
        if not term_fields:
            raise SearchProfileInvalidError(
                "keyword profile must contain at least one entry in 'term_fields'."
            )
        clauses = [
            {
                "term": {
                    tf["field"]: {
                        "value": query,
                        "boost": tf.get("weight", 1.0),
                    }
                }
            }
            for tf in term_fields
        ]
        query_clause = (
            {"bool": {"should": clauses}} if len(clauses) > 1 else clauses[0]
        )
        return {"size": top_k, "query": query_clause}

    def _compile_title(
        self, query: str, top_k: int, profile: dict[str, Any]
    ) -> dict[str, Any]:
        match_fields: list[dict[str, Any]] = profile.get("match_fields", [])
        if not match_fields:
            raise SearchProfileInvalidError(
                "title profile must contain at least one entry in 'match_fields'."
            )
        clauses = [
            {
                "match": {
                    mf["field"]: {
                        "query": query,
                        "boost": mf.get("weight", 1.0),
                    }
                }
            }
            for mf in match_fields
        ]
        query_clause = (
            {"bool": {"should": clauses}} if len(clauses) > 1 else clauses[0]
        )
        return {"size": top_k, "query": query_clause}

    def _compile_text(
        self, query: str, top_k: int, profile: dict[str, Any]
    ) -> dict[str, Any]:
        fields_cfg: list[dict[str, Any]] = profile.get("fields", [])
        if not fields_cfg:
            raise SearchProfileInvalidError(
                "text profile must contain at least one entry in 'fields'."
            )
        # Build OpenSearch "field^boost" notation
        fields = [
            f"{f['field']}^{f.get('weight', 1.0)}" for f in fields_cfg
        ]
        multi_match_type: str = profile.get("multi_match_type", "most_fields")
        return {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": fields,
                    "type": multi_match_type,
                }
            },
        }

    def _compile_vector(
        self,
        query: str,
        top_k: int,
        profile: dict[str, Any],
        query_vector: list[float] | None,
    ) -> dict[str, Any]:
        if query_vector is None:
            raise SearchProfileInvalidError(
                "query_vector must be provided for search_type='vector'."
            )
        vector_field: str | None = profile.get("vector_field")
        if not vector_field:
            raise SearchProfileInvalidError(
                "vector profile must specify 'vector_field'."
            )
        num_candidates = max(
            profile.get("num_candidates_min", 100),
            top_k * profile.get("num_candidates_multiplier", 3),
        )
        return {
            "size": top_k,
            "query": {
                "knn": {
                    vector_field: {
                        "vector": query_vector,
                        "k": top_k,
                        "num_candidates": num_candidates,
                    }
                }
            },
        }

    def _compile_hybrid(
        self,
        query: str,
        top_k: int,
        profile: dict[str, Any],
        query_vector: list[float] | None,
        vector_weight: float | None,
    ) -> dict[str, Any]:
        if query_vector is None:
            raise SearchProfileInvalidError(
                "query_vector must be provided for search_type='hybrid'."
            )
        vw = (
            vector_weight
            if vector_weight is not None
            else profile.get("default_vector_weight", 0.6)
        )
        text_weight = round(1.0 - vw, 6)

        # Resolve the sub-profiles used for text and vector arms.
        # For hybrid we fall back to reasonable defaults when the explicit
        # keyword/text/vector profiles are absent.
        vector_field: str | None = profile.get("vector_field")
        if not vector_field:
            raise SearchProfileInvalidError(
                "hybrid profile must specify 'vector_field'."
            )
        num_candidates = max(
            profile.get("num_candidates_min", 100),
            top_k * profile.get("num_candidates_multiplier", 3),
        )

        bm25_query: dict[str, Any]
        match_fields: list[dict[str, Any]] = profile.get("match_fields", [])
        fields_cfg: list[dict[str, Any]] = profile.get("fields", [])
        if fields_cfg:
            fields = [f"{f['field']}^{f.get('weight', 1.0)}" for f in fields_cfg]
            bm25_query = {
                "multi_match": {
                    "query": query,
                    "fields": fields,
                    "type": profile.get("multi_match_type", "most_fields"),
                }
            }
        elif match_fields:
            clauses = [
                {"match": {mf["field"]: {"query": query, "boost": mf.get("weight", 1.0)}}}
                for mf in match_fields
            ]
            bm25_query = {"bool": {"should": clauses}} if len(clauses) > 1 else clauses[0]
        else:
            # Minimal fallback: match_all for the text arm
            bm25_query = {"match_all": {}}

        return {
            "size": top_k,
            "query": {
                "bool": {
                    "should": [
                        {
                            "function_score": {
                                "query": bm25_query,
                                "weight": text_weight,
                            }
                        },
                        {
                            "function_score": {
                                "query": {
                                    "knn": {
                                        vector_field: {
                                            "vector": query_vector,
                                            "k": top_k,
                                            "num_candidates": num_candidates,
                                        }
                                    }
                                },
                                "weight": vw,
                            }
                        },
                    ]
                }
            },
        }

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _extract_type_profile(
        self, search_type: str, search_profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the sub-profile dict for *search_type*.

        Supports both the canonical ``search_type_profile`` wrapper and the
        flat (legacy) form where type keys live at the top level.
        """
        wrapper = search_profile.get("search_type_profile")
        if wrapper is not None:
            # Canonical wrapped form
            type_entry: Any = wrapper.get(search_type)
            if type_entry is None:
                raise SearchProfileInvalidError(
                    f"search_profile.search_type_profile has no entry for '{search_type}'."
                )
            if not type_entry.get("enabled", True):
                raise SearchProfileInvalidError(
                    f"search_type '{search_type}' is disabled in this profile."
                )
            return type_entry  # type: ignore[return-value]

        # Flat form: the top-level profile IS the type-specific dict
        return search_profile
