"""QueryProfileCompiler — translates a search_profile dict + runtime params into OpenSearch DSL.

Supported search_type values: keyword | title | text | vector | hybrid
"""

from __future__ import annotations

from typing import Any

SEARCH_TYPES = frozenset({"keyword", "title", "text", "vector", "hybrid"})

TOP_LEVEL_KEYS = frozenset({"tag", "search_type_profile", "response_fields"})
FIELD_ENTRY_KEYS = frozenset({"field", "weight"})
TYPE_PROFILE_KEYS: dict[str, frozenset[str]] = {
    "keyword": frozenset({"enabled", "term_fields"}),
    "title": frozenset({"enabled", "match_fields"}),
    "text": frozenset({"enabled", "fields", "multi_match_type"}),
    "vector": frozenset(
        {"enabled", "vector_field", "num_candidates"}
    ),
    "hybrid": frozenset(
        {
            "enabled",
            "default_vector_weight",
            "vector_field",
            "num_candidates",
            "fields",
            "match_fields",
            "multi_match_type",
        }
    ),
}


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

        source_fields = self._extract_response_fields(search_profile)
        if source_fields:
            dsl["_source"] = source_fields

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
        _query: str,
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
        knn_body: dict[str, Any] = {
            "vector": query_vector,
            "k": top_k,
        }
        num_candidates = profile.get("num_candidates")
        if num_candidates is not None:
            knn_body["num_candidates"] = num_candidates
        return {
            "size": top_k,
            "query": {
                "knn": {
                    vector_field: knn_body,
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
        knn_body: dict[str, Any] = {
            "vector": query_vector,
            "k": top_k,
        }
        num_candidates = profile.get("num_candidates")
        if num_candidates is not None:
            knn_body["num_candidates"] = num_candidates
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
                                        vector_field: knn_body,
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
        if search_type not in SEARCH_TYPES:
            raise SearchProfileInvalidError(
                f"Unsupported search_type: '{search_type}'.  "
                "Allowed: keyword, title, text, vector, hybrid."
            )

        wrapper = search_profile.get("search_type_profile")
        if wrapper is not None:
            self._validate_top_level_profile(search_profile)
            self._validate_profile_wrapper(wrapper)
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
            self._validate_type_profile(search_type, type_entry)
            return type_entry  # type: ignore[return-value]

        if search_type in search_profile:
            self._validate_grouped_flat_profile(search_profile)
            type_entry = search_profile[search_type]
            if not isinstance(type_entry, dict):
                raise SearchProfileInvalidError(
                    f"{search_type} profile must be a dict."
                )
            if not type_entry.get("enabled", True):
                raise SearchProfileInvalidError(
                    f"search_type '{search_type}' is disabled in this profile."
                )
            self._validate_type_profile(search_type, type_entry)
            return type_entry

        # Legacy flat form: the top-level profile IS the type-specific dict.
        self._validate_type_profile(
            search_type,
            search_profile,
            extra_allowed_keys=frozenset({"tag", "response_fields"}),
        )
        return search_profile

    @staticmethod
    def _extract_response_fields(search_profile: dict[str, Any]) -> list[str]:
        """Return fields for OpenSearch ``_source`` filtering, excluding score."""
        response_fields = search_profile.get("response_fields", [])
        if not isinstance(response_fields, list):
            raise SearchProfileInvalidError("response_fields must be a list.")

        source_fields: list[str] = []
        for field in response_fields:
            if not isinstance(field, str):
                raise SearchProfileInvalidError("response_fields entries must be strings.")
            if field != "score":
                source_fields.append(field)
        return source_fields

    @staticmethod
    def _validate_top_level_profile(search_profile: dict[str, Any]) -> None:
        unknown = set(search_profile) - TOP_LEVEL_KEYS
        if unknown:
            raise SearchProfileInvalidError(
                "search_profile contains unknown top-level keys: "
                + ", ".join(sorted(unknown))
            )

    @staticmethod
    def _validate_profile_wrapper(wrapper: Any) -> None:
        if not isinstance(wrapper, dict):
            raise SearchProfileInvalidError("search_type_profile must be a dict.")
        unknown = set(wrapper) - SEARCH_TYPES
        if unknown:
            raise SearchProfileInvalidError(
                "search_type_profile contains unknown search types: "
                + ", ".join(sorted(unknown))
            )

    @staticmethod
    def _validate_grouped_flat_profile(search_profile: dict[str, Any]) -> None:
        allowed = SEARCH_TYPES | frozenset({"tag", "response_fields"})
        unknown = set(search_profile) - allowed
        if unknown:
            raise SearchProfileInvalidError(
                "search_profile contains unknown top-level keys: "
                + ", ".join(sorted(unknown))
            )

    def _validate_type_profile(
        self,
        search_type: str,
        profile: Any,
        extra_allowed_keys: frozenset[str] = frozenset(),
    ) -> None:
        if not isinstance(profile, dict):
            raise SearchProfileInvalidError(f"{search_type} profile must be a dict.")

        allowed_keys = TYPE_PROFILE_KEYS[search_type] | extra_allowed_keys
        unknown = set(profile) - allowed_keys
        if unknown:
            raise SearchProfileInvalidError(
                f"{search_type} profile contains unknown keys: "
                + ", ".join(sorted(unknown))
            )

        field_list_names = {
            "keyword": ("term_fields",),
            "title": ("match_fields",),
            "text": ("fields",),
            "vector": (),
            "hybrid": ("fields", "match_fields"),
        }[search_type]
        for list_name in field_list_names:
            if list_name in profile:
                self._validate_field_entries(search_type, list_name, profile[list_name])

        if "num_candidates" in profile:
            num_candidates = profile["num_candidates"]
            if type(num_candidates) is not int or num_candidates <= 0:
                raise SearchProfileInvalidError(
                    f"{search_type}.num_candidates must be a positive integer."
                )

    @staticmethod
    def _validate_field_entries(
        search_type: str, list_name: str, entries: Any
    ) -> None:
        if not isinstance(entries, list):
            raise SearchProfileInvalidError(
                f"{search_type}.{list_name} must be a list."
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise SearchProfileInvalidError(
                    f"{search_type}.{list_name} entries must be dicts."
                )
            unknown = set(entry) - FIELD_ENTRY_KEYS
            if unknown:
                raise SearchProfileInvalidError(
                    f"{search_type}.{list_name} contains unknown keys: "
                    + ", ".join(sorted(unknown))
                )
