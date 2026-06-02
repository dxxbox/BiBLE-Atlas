"""Unit tests for SkillSearcher (Task A).

All infrastructure dependencies are replaced with lightweight fakes so
these tests run without a real database or embedding model.

Fakes
-----
FakeDBWriter   — records search_content_docs() call args; returns configurable hits.
FakeVectorTool — records ensure_model_ready() / embed_query() calls.
FakeCompiler   — returns a fixed (dsl, response_fields) pair; can be made to raise.
"""

from __future__ import annotations

from typing import Any

import pytest

from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.features.search.skill_search.searcher.search_skill import (
    SkillSearcher,
    _resolve_dot_path,
    _MISSING,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures / fakes
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_skill_main"
DUMMY_VECTOR = [0.1] * 8

SKILL_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "keyword": {
            "enabled": True,
            "term_fields": [{"field": "name.keyword", "weight": 1.0}],
        },
        "title": {
            "enabled": True,
            "match_fields": [{"field": "name", "weight": 2.0}],
        },
        "text": {
            "enabled": True,
            "multi_match_type": "most_fields",
            "fields": [
                {"field": "name", "weight": 4.0},
                {"field": "description", "weight": 2.0},
                {"field": "body", "weight": 1.5},
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
            "default_vector_weight": 0.5,
            "vector_field": "content_vector",
            "num_candidates_min": 100,
            "num_candidates_multiplier": 3,
            "fields": [{"field": "name", "weight": 4.0}],
        },
    },
    "response_fields": [
        "doc_id", "name", "description", "body", "content",
        "metadata.related_storage_paths", "score",
    ],
}

TWO_HITS: dict[str, Any] = {
    "total": 2,
    "hits": [
        {
            "_score": 0.92,
            "_source": {
                "doc_id": "s1",
                "name": "k8s-log-cleaner",
                "description": "Remove stale logs",
                "body": "#!/bin/bash\nrm -f /var/log/*.old",
                "content": "k8s log maintenance",
                "chunk_id": "s1::0",       # must be excluded
                "took_ms": 5,              # must be excluded
                "metadata": {
                    "related_storage_paths": ["/mnt/skill/2026/demo.sh"]
                },
            },
        },
        {
            "_score": 0.71,
            "_source": {
                "doc_id": "s2",
                "name": "db-backup",
                "description": "Postgres backup helper",
                "body": "pg_dump ...",
                "content": "database backup",
                "metadata": {},            # no related_storage_paths
            },
        },
    ],
}

ZERO_HITS: dict[str, Any] = {"total": 0, "hits": []}


class FakeDBWriter:
    def __init__(
        self,
        hits: dict[str, Any] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self._hits = hits if hits is not None else TWO_HITS
        self._side_effect = side_effect
        self.search_calls: list[dict[str, Any]] = []

    def search_content_docs(self, index: str, dsl: dict[str, Any]) -> dict[str, Any]:
        self.search_calls.append({"index": index, "dsl": dsl})
        if self._side_effect is not None:
            raise self._side_effect
        return self._hits

    # ── protocol no-ops ──────────────────────────────────────────────────
    def get_binding_by_domain_tag(self, *a: Any, **kw: Any) -> None:
        return None


class FakeVectorTool:
    def __init__(
        self,
        vector: list[float] | None = None,
        embed_side_effect: Exception | None = None,
    ) -> None:
        self._vector = vector if vector is not None else DUMMY_VECTOR
        self._embed_side_effect = embed_side_effect
        self.ensure_calls: list[str] = []
        self.embed_calls: list[tuple[str, str]] = []

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        self.ensure_calls.append(model_name)
        return {"status": "ready"}

    def embed_query(self, query: str, model_name: str) -> list[float]:
        self.embed_calls.append((query, model_name))
        if self._embed_side_effect is not None:
            raise self._embed_side_effect
        return self._vector


class FakeCompiler:
    """Compiler stub: returns a fixed DSL / response_fields pair."""

    def __init__(
        self,
        dsl: dict[str, Any] | None = None,
        response_fields: list[str] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self._dsl = dsl or {"query": {"match_all": {}}, "size": 10}
        self._response_fields = response_fields if response_fields is not None else [
            "doc_id", "name", "description", "body", "content",
            "metadata.related_storage_paths", "score",
        ]
        self._side_effect = side_effect
        self.compile_calls: list[dict[str, Any]] = []

    def compile(self, **kwargs: Any) -> tuple[dict[str, Any], list[str]]:
        self.compile_calls.append(kwargs)
        if self._side_effect is not None:
            raise self._side_effect
        return self._dsl, self._response_fields


def make_searcher(
    db_writer: FakeDBWriter | None = None,
    vector_tool: FakeVectorTool | None = None,
    compiler: FakeCompiler | None = None,
) -> tuple[SkillSearcher, FakeDBWriter, FakeVectorTool, FakeCompiler]:
    db = db_writer or FakeDBWriter()
    vec = vector_tool or FakeVectorTool()
    cmp = compiler or FakeCompiler()
    srch = SkillSearcher(db_writer=db, vector_tool=vec, compiler=cmp)  # type: ignore[arg-type]
    return srch, db, vec, cmp


def _search(searcher: SkillSearcher, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(
        kb_index=KB_INDEX,
        query="clean logs",
        search_type="text",
        top_k=10,
        search_profile=SKILL_PROFILE,
        vector_model=None,
        vector_weight=None,
    )
    defaults.update(overrides)
    return searcher.search(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Vector-tool interaction
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorToolInteraction:
    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_non_vector_types_do_not_call_vector_tool(self, search_type: str) -> None:
        srch, _, vec, _ = make_searcher()
        _search(srch, search_type=search_type)
        assert vec.ensure_calls == []
        assert vec.embed_calls == []

    def test_vector_search_calls_ensure_model_ready(self) -> None:
        srch, _, vec, _ = make_searcher()
        _search(srch, search_type="vector", vector_model=VECTOR_MODEL)
        assert vec.ensure_calls == [VECTOR_MODEL]

    def test_vector_search_calls_embed_query(self) -> None:
        srch, _, vec, _ = make_searcher()
        _search(srch, search_type="vector", vector_model=VECTOR_MODEL, query="deploy k8s")
        assert vec.embed_calls == [("deploy k8s", VECTOR_MODEL)]

    def test_hybrid_search_calls_vector_tool(self) -> None:
        srch, _, vec, _ = make_searcher()
        _search(srch, search_type="hybrid", vector_model=VECTOR_MODEL)
        assert len(vec.ensure_calls) == 1
        assert len(vec.embed_calls) == 1

    def test_query_vector_passed_to_compiler_for_vector_type(self) -> None:
        srch, _, vec, cmp = make_searcher()
        vec._vector = [0.5] * 4
        _search(srch, search_type="vector", vector_model=VECTOR_MODEL)
        assert cmp.compile_calls[0]["query_vector"] == [0.5] * 4

    def test_query_vector_none_for_non_vector_types(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_type="text")
        assert cmp.compile_calls[0]["query_vector"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 2. Compiler interaction
# ──────────────────────────────────────────────────────────────────────────────


class TestCompilerInteraction:
    def test_compiler_compile_called_once(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_type="text")
        assert len(cmp.compile_calls) == 1

    def test_compiler_receives_search_type(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_type="keyword")
        assert cmp.compile_calls[0]["search_type"] == "keyword"

    def test_compiler_receives_query(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, query="backup database")
        assert cmp.compile_calls[0]["query"] == "backup database"

    def test_compiler_receives_top_k(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, top_k=7)
        assert cmp.compile_calls[0]["top_k"] == 7

    def test_compiler_receives_search_profile(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_profile=SKILL_PROFILE)
        assert cmp.compile_calls[0]["search_profile"] == SKILL_PROFILE

    def test_compiler_receives_vector_weight(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, vector_weight=0.7)
        assert cmp.compile_calls[0]["vector_weight"] == 0.7


# ──────────────────────────────────────────────────────────────────────────────
# 3. DB writer interaction
# ──────────────────────────────────────────────────────────────────────────────


class TestDBWriterInteraction:
    def test_search_content_docs_called_once(self) -> None:
        srch, db, _, _ = make_searcher()
        _search(srch)
        assert len(db.search_calls) == 1

    def test_search_content_docs_receives_correct_index(self) -> None:
        srch, db, _, _ = make_searcher()
        _search(srch, kb_index="kb_skill_main")
        assert db.search_calls[0]["index"] == "kb_skill_main"

    def test_search_content_docs_receives_dsl_from_compiler(self) -> None:
        fixed_dsl = {"query": {"term": {"name.keyword": {"value": "cleaner"}}}, "size": 5}
        cmp = FakeCompiler(dsl=fixed_dsl)
        srch, db, _, _ = make_searcher(compiler=cmp)
        _search(srch)
        assert db.search_calls[0]["dsl"] == fixed_dsl


# ──────────────────────────────────────────────────────────────────────────────
# 4. Return value structure
# ──────────────────────────────────────────────────────────────────────────────


class TestReturnStructure:
    def test_result_has_kb_index(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch, kb_index="kb_skill_main")
        assert r["kb_index"] == "kb_skill_main"

    def test_result_has_total(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["total"] == 2

    def test_total_from_raw_hits(self) -> None:
        db = FakeDBWriter(hits={"total": 99, "hits": []})
        srch, _, _, _ = make_searcher(db_writer=db)
        r = _search(srch)
        assert r["total"] == 99

    def test_result_has_items_list(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert isinstance(r["items"], list)

    def test_items_count_matches_hits(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert len(r["items"]) == 2

    def test_zero_hits_returns_empty_items(self) -> None:
        db = FakeDBWriter(hits=ZERO_HITS)
        srch, _, _, _ = make_searcher(db_writer=db)
        r = _search(srch)
        assert r["total"] == 0
        assert r["items"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 5. _map_hits — field extraction rules
# ──────────────────────────────────────────────────────────────────────────────


class TestMapHits:
    def test_score_from_underscore_score(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["score"] == pytest.approx(0.92)
        assert r["items"][1]["score"] == pytest.approx(0.71)

    def test_chunk_id_never_in_response(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        for item in r["items"]:
            assert "chunk_id" not in item

    def test_took_ms_never_in_response(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        for item in r["items"]:
            assert "took_ms" not in item

    def test_response_fields_filter_applied(self) -> None:
        cmp = FakeCompiler(response_fields=["doc_id", "name", "score"])
        srch, _, _, _ = make_searcher(compiler=cmp)
        r = _search(srch)
        assert set(r["items"][0].keys()) == {"doc_id", "name", "score"}

    def test_empty_response_fields_returns_all_source_fields(self) -> None:
        cmp = FakeCompiler(response_fields=[])
        srch, _, _, _ = make_searcher(compiler=cmp)
        r = _search(srch)
        item = r["items"][0]
        # all _source fields except chunk_id/took_ms must appear
        assert "doc_id" in item
        assert "name" in item
        assert "chunk_id" not in item
        assert "took_ms" not in item
        assert "score" in item

    def test_related_storage_paths_flattened_to_top_level(self) -> None:
        """metadata.related_storage_paths → top-level key 'related_storage_paths'."""
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        item0 = r["items"][0]
        assert "related_storage_paths" in item0
        assert item0["related_storage_paths"] == ["/mnt/skill/2026/demo.sh"]

    def test_missing_related_storage_paths_does_not_raise(self) -> None:
        """Hit without metadata.related_storage_paths must still be returned."""
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        item1 = r["items"][1]
        assert "related_storage_paths" not in item1

    def test_dot_path_absent_field_silently_skipped(self) -> None:
        cmp = FakeCompiler(response_fields=["doc_id", "metadata.nonexistent", "score"])
        srch, _, _, _ = make_searcher(compiler=cmp)
        r = _search(srch)
        assert "nonexistent" not in r["items"][0]

    def test_metadata_not_dict_does_not_raise(self) -> None:
        """Graceful handling when _source.metadata is not a dict."""
        hits = {
            "total": 1,
            "hits": [
                {"_score": 0.5, "_source": {"doc_id": "x1", "metadata": "broken"}}
            ],
        }
        db = FakeDBWriter(hits=hits)
        cmp = FakeCompiler(response_fields=["doc_id", "metadata.related_storage_paths", "score"])
        srch, _, _, _ = make_searcher(db_writer=db, compiler=cmp)
        r = _search(srch)
        assert r["items"][0]["doc_id"] == "x1"
        assert "related_storage_paths" not in r["items"][0]

    def test_related_storage_paths_empty_list_included(self) -> None:
        """Empty list [] is a valid value and should NOT be dropped."""
        hits = {
            "total": 1,
            "hits": [
                {
                    "_score": 0.8,
                    "_source": {
                        "doc_id": "x2",
                        "metadata": {"related_storage_paths": []},
                    },
                }
            ],
        }
        db = FakeDBWriter(hits=hits)
        srch, _, _, _ = make_searcher(db_writer=db)
        r = _search(srch)
        assert "related_storage_paths" in r["items"][0]
        assert r["items"][0]["related_storage_paths"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 6. Error handling
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_vector_without_model_raises_search_profile_invalid(self) -> None:
        srch, _, _, _ = make_searcher()
        with pytest.raises(SearchProfileInvalidError):
            _search(srch, search_type="vector", vector_model=None)

    def test_hybrid_without_model_raises_search_profile_invalid(self) -> None:
        srch, _, _, _ = make_searcher()
        with pytest.raises(SearchProfileInvalidError):
            _search(srch, search_type="hybrid", vector_model=None)

    def test_embed_query_failure_raises_search_internal_error(self) -> None:
        vec = FakeVectorTool(embed_side_effect=RuntimeError("GPU out of memory"))
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)

    def test_ensure_model_ready_failure_raises_search_internal_error(self) -> None:
        class BoomTool(FakeVectorTool):
            def ensure_model_ready(self, model_name: str) -> dict[str, Any]:  # type: ignore[override]
                raise OSError("model download failed")

        vec = BoomTool()
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)

    def test_db_failure_raises_search_internal_error(self) -> None:
        db = FakeDBWriter(side_effect=ConnectionError("ES unreachable"))
        srch, _, _, _ = make_searcher(db_writer=db)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="text")

    def test_compiler_failure_propagates_search_profile_invalid(self) -> None:
        cmp = FakeCompiler(side_effect=SearchProfileInvalidError("term_fields empty"))
        srch, _, _, _ = make_searcher(compiler=cmp)
        with pytest.raises(SearchProfileInvalidError, match="term_fields empty"):
            _search(srch, search_type="keyword")

    def test_embed_error_message_not_exposed_in_wrapper(self) -> None:
        """SearchInternalError wraps the raw exception; its message should include
        context but the original exception is the ``__cause__``."""
        vec = FakeVectorTool(embed_side_effect=RuntimeError("secret internal detail"))
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError) as exc_info:
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)
        assert exc_info.value.__cause__ is not None


# ──────────────────────────────────────────────────────────────────────────────
# 7. Unit tests for _resolve_dot_path helper
# ──────────────────────────────────────────────────────────────────────────────


class TestResolveDotPath:
    def test_simple_key_present(self) -> None:
        leaf, val = _resolve_dot_path({"a": 1}, "a")
        assert leaf == "a"
        assert val == 1

    def test_nested_key_present(self) -> None:
        leaf, val = _resolve_dot_path({"meta": {"paths": ["/x"]}}, "meta.paths")
        assert leaf == "paths"
        assert val == ["/x"]

    def test_deeply_nested_key(self) -> None:
        src = {"a": {"b": {"c": 42}}}
        leaf, val = _resolve_dot_path(src, "a.b.c")
        assert leaf == "c"
        assert val == 42

    def test_key_absent_returns_missing(self) -> None:
        _, val = _resolve_dot_path({}, "metadata.paths")
        assert val is _MISSING

    def test_intermediate_key_absent_returns_missing(self) -> None:
        _, val = _resolve_dot_path({"x": 1}, "x.y.z")
        assert val is _MISSING

    def test_intermediate_not_dict_returns_missing(self) -> None:
        _, val = _resolve_dot_path({"metadata": "broken"}, "metadata.paths")
        assert val is _MISSING

    def test_empty_list_value_not_missing(self) -> None:
        _, val = _resolve_dot_path({"meta": {"paths": []}}, "meta.paths")
        assert val is not _MISSING
        assert val == []

    def test_false_value_not_missing(self) -> None:
        _, val = _resolve_dot_path({"meta": {"active": False}}, "meta.active")
        assert val is not _MISSING
        assert val is False
