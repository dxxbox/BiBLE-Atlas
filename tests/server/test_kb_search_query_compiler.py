"""Unit tests for QueryProfileCompiler (Task H).

Coverage:
  - All five search_type values (keyword / title / text / vector / hybrid)
  - Table-driven positive cases with canonical (wrapped) and flat profiles
  - Error cases: missing query_vector, disabled type, missing required fields
  - response_fields pass-through
  - hybrid vector_weight override and default fallback
"""

from __future__ import annotations

import pytest

from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & shared data
# ──────────────────────────────────────────────────────────────────────────────

DUMMY_VECTOR = [0.1, 0.2, 0.3]

FULL_WRAPPED_PROFILE: dict = {
    "tag": "design",
    "search_type_profile": {
        "keyword": {
            "enabled": True,
            "term_fields": [{"field": "title.keyword", "weight": 1.0}],
        },
        "title": {
            "enabled": True,
            "match_fields": [{"field": "title", "weight": 2.0}],
        },
        "text": {
            "enabled": True,
            "multi_match_type": "most_fields",
            "fields": [
                {"field": "content", "weight": 3.0},
                {"field": "content.english", "weight": 2.0},
                {"field": "title", "weight": 2.0},
            ],
        },
        "vector": {
            "enabled": True,
            "vector_field": "content_vector",
            "num_candidates_min": 100,
            "num_candidates_multiplier": 3,
        },
        "hybrid": {
            "enabled": True,
            "default_vector_weight": 0.6,
            "vector_field": "content_vector",
            "num_candidates_min": 100,
            "num_candidates_multiplier": 3,
            "fields": [
                {"field": "content", "weight": 3.0},
                {"field": "title", "weight": 2.0},
            ],
        },
    },
    "response_fields": ["doc_id", "title", "content", "score"],
}


@pytest.fixture
def compiler() -> QueryProfileCompiler:
    return QueryProfileCompiler()


# ──────────────────────────────────────────────────────────────────────────────
# keyword
# ──────────────────────────────────────────────────────────────────────────────


class TestKeyword:
    def test_single_term_field(self, compiler: QueryProfileCompiler) -> None:
        dsl, fields = compiler.compile(
            search_type="keyword",
            query="scheduler",
            top_k=5,
            search_profile=FULL_WRAPPED_PROFILE,
        )
        assert dsl["size"] == 5
        term_clause = dsl["query"]["term"]
        assert "title.keyword" in term_clause
        assert term_clause["title.keyword"]["value"] == "scheduler"
        assert fields == ["doc_id", "title", "content", "score"]

    def test_multiple_term_fields_become_should(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {
            "search_type_profile": {
                "keyword": {
                    "enabled": True,
                    "term_fields": [
                        {"field": "title.keyword", "weight": 1.0},
                        {"field": "tag.keyword", "weight": 0.5},
                    ],
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="keyword", query="foo", top_k=3, search_profile=profile
        )
        assert "bool" in dsl["query"]
        assert len(dsl["query"]["bool"]["should"]) == 2

    def test_missing_term_fields_raises(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {"keyword": {"enabled": True, "term_fields": []}}
        }
        with pytest.raises(SearchProfileInvalidError, match="term_fields"):
            compiler.compile(
                search_type="keyword", query="x", top_k=5, search_profile=profile
            )

    def test_flat_profile_keyword(self, compiler: QueryProfileCompiler) -> None:
        flat = {"term_fields": [{"field": "title.keyword", "weight": 1.0}]}
        dsl, _ = compiler.compile(
            search_type="keyword", query="test", top_k=10, search_profile=flat
        )
        assert "term" in dsl["query"]


# ──────────────────────────────────────────────────────────────────────────────
# title
# ──────────────────────────────────────────────────────────────────────────────


class TestTitle:
    def test_single_match_field(self, compiler: QueryProfileCompiler) -> None:
        dsl, _ = compiler.compile(
            search_type="title",
            query="allocation",
            top_k=10,
            search_profile=FULL_WRAPPED_PROFILE,
        )
        assert dsl["size"] == 10
        assert "match" in dsl["query"]
        assert dsl["query"]["match"]["title"]["query"] == "allocation"
        assert dsl["query"]["match"]["title"]["boost"] == 2.0

    def test_multiple_match_fields_become_should(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {
            "search_type_profile": {
                "title": {
                    "enabled": True,
                    "match_fields": [
                        {"field": "title", "weight": 2.0},
                        {"field": "subtitle", "weight": 1.0},
                    ],
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="title", query="q", top_k=5, search_profile=profile
        )
        assert "bool" in dsl["query"]
        assert len(dsl["query"]["bool"]["should"]) == 2

    def test_missing_match_fields_raises(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {"title": {"enabled": True, "match_fields": []}}
        }
        with pytest.raises(SearchProfileInvalidError, match="match_fields"):
            compiler.compile(
                search_type="title", query="x", top_k=5, search_profile=profile
            )


# ──────────────────────────────────────────────────────────────────────────────
# text
# ──────────────────────────────────────────────────────────────────────────────


class TestText:
    def test_multi_match_structure(self, compiler: QueryProfileCompiler) -> None:
        dsl, _ = compiler.compile(
            search_type="text",
            query="memory management",
            top_k=20,
            search_profile=FULL_WRAPPED_PROFILE,
        )
        mm = dsl["query"]["multi_match"]
        assert mm["query"] == "memory management"
        assert mm["type"] == "most_fields"
        # Check boost notation
        assert "content^3.0" in mm["fields"]
        assert "title^2.0" in mm["fields"]

    def test_default_multi_match_type(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {
                "text": {
                    "enabled": True,
                    "fields": [{"field": "content", "weight": 1.0}],
                    # multi_match_type omitted → should default to most_fields
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="text", query="x", top_k=5, search_profile=profile
        )
        assert dsl["query"]["multi_match"]["type"] == "most_fields"

    def test_missing_fields_raises(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {"text": {"enabled": True, "fields": []}}
        }
        with pytest.raises(SearchProfileInvalidError, match="fields"):
            compiler.compile(
                search_type="text", query="x", top_k=5, search_profile=profile
            )


# ──────────────────────────────────────────────────────────────────────────────
# vector
# ──────────────────────────────────────────────────────────────────────────────


class TestVector:
    def test_knn_structure(self, compiler: QueryProfileCompiler) -> None:
        dsl, _ = compiler.compile(
            search_type="vector",
            query="unused",
            top_k=5,
            search_profile=FULL_WRAPPED_PROFILE,
            query_vector=DUMMY_VECTOR,
        )
        knn = dsl["query"]["knn"]["content_vector"]
        assert knn["vector"] == DUMMY_VECTOR
        assert knn["k"] == 5
        assert knn["num_candidates"] >= 5

    def test_num_candidates_min_floor(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {
                "vector": {
                    "enabled": True,
                    "vector_field": "vec",
                    "num_candidates_min": 200,
                    "num_candidates_multiplier": 3,
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="vector",
            query="x",
            top_k=5,
            search_profile=profile,
            query_vector=DUMMY_VECTOR,
        )
        # 5*3=15 < 200, so min floor 200 should win
        assert dsl["query"]["knn"]["vec"]["num_candidates"] == 200

    def test_missing_query_vector_raises(self, compiler: QueryProfileCompiler) -> None:
        with pytest.raises(SearchProfileInvalidError, match="query_vector"):
            compiler.compile(
                search_type="vector",
                query="x",
                top_k=5,
                search_profile=FULL_WRAPPED_PROFILE,
            )

    def test_missing_vector_field_raises(self, compiler: QueryProfileCompiler) -> None:
        profile = {
            "search_type_profile": {
                "vector": {"enabled": True}  # no vector_field
            }
        }
        with pytest.raises(SearchProfileInvalidError, match="vector_field"):
            compiler.compile(
                search_type="vector",
                query="x",
                top_k=5,
                search_profile=profile,
                query_vector=DUMMY_VECTOR,
            )


# ──────────────────────────────────────────────────────────────────────────────
# hybrid
# ──────────────────────────────────────────────────────────────────────────────


class TestHybrid:
    def test_hybrid_structure(self, compiler: QueryProfileCompiler) -> None:
        dsl, _ = compiler.compile(
            search_type="hybrid",
            query="scheduler",
            top_k=10,
            search_profile=FULL_WRAPPED_PROFILE,
            query_vector=DUMMY_VECTOR,
        )
        should = dsl["query"]["bool"]["should"]
        assert len(should) == 2
        weights = {s["function_score"]["weight"] for s in should}
        # Default vector_weight=0.6, text_weight=0.4
        assert 0.6 in weights
        assert round(0.4, 6) in weights

    def test_hybrid_vector_weight_override(
        self, compiler: QueryProfileCompiler
    ) -> None:
        dsl, _ = compiler.compile(
            search_type="hybrid",
            query="q",
            top_k=5,
            search_profile=FULL_WRAPPED_PROFILE,
            query_vector=DUMMY_VECTOR,
            vector_weight=0.8,
        )
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.8 in weights
        assert round(0.2, 6) in weights

    def test_hybrid_default_vector_weight_from_profile(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {
            "search_type_profile": {
                "hybrid": {
                    "enabled": True,
                    "default_vector_weight": 0.7,
                    "vector_field": "vec",
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="hybrid",
            query="q",
            top_k=5,
            search_profile=profile,
            query_vector=DUMMY_VECTOR,
        )
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.7 in weights

    def test_hybrid_missing_query_vector_raises(
        self, compiler: QueryProfileCompiler
    ) -> None:
        with pytest.raises(SearchProfileInvalidError, match="query_vector"):
            compiler.compile(
                search_type="hybrid",
                query="q",
                top_k=5,
                search_profile=FULL_WRAPPED_PROFILE,
            )

    def test_hybrid_missing_vector_field_raises(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {
            "search_type_profile": {
                "hybrid": {"enabled": True, "default_vector_weight": 0.5}
                # no vector_field
            }
        }
        with pytest.raises(SearchProfileInvalidError, match="vector_field"):
            compiler.compile(
                search_type="hybrid",
                query="q",
                top_k=5,
                search_profile=profile,
                query_vector=DUMMY_VECTOR,
            )

    def test_hybrid_fallback_to_match_all_when_no_text_fields(
        self, compiler: QueryProfileCompiler
    ) -> None:
        """When neither fields nor match_fields are in the hybrid profile,
        a match_all clause is used for the BM25 arm."""
        profile = {
            "search_type_profile": {
                "hybrid": {
                    "enabled": True,
                    "vector_field": "vec",
                    "default_vector_weight": 0.5,
                }
            }
        }
        dsl, _ = compiler.compile(
            search_type="hybrid",
            query="q",
            top_k=5,
            search_profile=profile,
            query_vector=DUMMY_VECTOR,
        )
        should = dsl["query"]["bool"]["should"]
        bm25_arm = next(
            s for s in should
            if "knn" not in str(s["function_score"]["query"])
        )
        assert "match_all" in bm25_arm["function_score"]["query"]


# ──────────────────────────────────────────────────────────────────────────────
# Disabled search type
# ──────────────────────────────────────────────────────────────────────────────


class TestDisabledSearchType:
    @pytest.mark.parametrize("stype", ["keyword", "title", "text", "vector", "hybrid"])
    def test_disabled_type_raises(
        self, compiler: QueryProfileCompiler, stype: str
    ) -> None:
        profile = {
            "search_type_profile": {stype: {"enabled": False}}
        }
        kwargs: dict = dict(
            search_type=stype, query="q", top_k=5, search_profile=profile
        )
        if stype in ("vector", "hybrid"):
            kwargs["query_vector"] = DUMMY_VECTOR
        with pytest.raises(SearchProfileInvalidError, match="disabled"):
            compiler.compile(**kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Unsupported search_type
# ──────────────────────────────────────────────────────────────────────────────


class TestUnsupportedSearchType:
    def test_unknown_type_raises(self, compiler: QueryProfileCompiler) -> None:
        with pytest.raises(SearchProfileInvalidError, match="Unsupported search_type"):
            compiler.compile(
                search_type="fuzzy",
                query="q",
                top_k=5,
                search_profile={},
            )


# ──────────────────────────────────────────────────────────────────────────────
# response_fields pass-through
# ──────────────────────────────────────────────────────────────────────────────


class TestResponseFields:
    def test_response_fields_returned(self, compiler: QueryProfileCompiler) -> None:
        _, fields = compiler.compile(
            search_type="keyword",
            query="q",
            top_k=5,
            search_profile=FULL_WRAPPED_PROFILE,
        )
        assert fields == ["doc_id", "title", "content", "score"]

    def test_empty_response_fields_when_absent(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {
            "search_type_profile": {
                "keyword": {
                    "enabled": True,
                    "term_fields": [{"field": "f.keyword"}],
                }
            }
            # no response_fields key
        }
        _, fields = compiler.compile(
            search_type="keyword", query="q", top_k=5, search_profile=profile
        )
        assert fields == []


# ──────────────────────────────────────────────────────────────────────────────
# Missing type entry in search_type_profile
# ──────────────────────────────────────────────────────────────────────────────


class TestMissingTypeEntry:
    def test_missing_entry_in_wrapper_raises(
        self, compiler: QueryProfileCompiler
    ) -> None:
        profile = {"search_type_profile": {}}  # empty — no entries at all
        with pytest.raises(SearchProfileInvalidError, match="no entry for"):
            compiler.compile(
                search_type="keyword", query="q", top_k=5, search_profile=profile
            )
