"""Unit tests for MemorySearcher (Task A — memory_search).

All infrastructure dependencies are replaced with lightweight fakes so
these tests run without a real database or embedding model.

Fakes
-----
FakeDBWriter    — records search_content_docs() call args; returns configurable hits.
FakeVectorTool  — records ensure_model_ready() / embed_query() calls.
FakeCompiler    — returns a fixed (dsl, response_fields) pair; can be made to raise.
"""

from __future__ import annotations

from typing import Any

import pytest

from bible.features.search.common.query_profile_compiler import (
    SearchProfileInvalidError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.features.search.memory_search.searcher.search_memory import MemorySearcher

# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_memory_main"
DUMMY_VECTOR = [0.2] * 8

# Minimal profile covering all 5 search types with complete hybrid section
MEMORY_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "keyword": {
            "enabled": True,
            "term_fields": [
                {"field": "memory_id.keyword",     "weight": 5.0},
                {"field": "task_ids.keyword",       "weight": 2.0},
                {"field": "feature_tags.keyword",   "weight": 1.5},
                {"field": "domain_tags.keyword",    "weight": 1.2},
                {"field": "component_tags.keyword", "weight": 1.2},
            ],
        },
        "title": {
            "enabled": True,
            "match_fields": [{"field": "title", "weight": 3.0}],
        },
        "text": {
            "enabled": True,
            "multi_match_type": "most_fields",
            "fields": [
                {"field": "title",    "weight": 3.0},
                {"field": "abstract", "weight": 3.0},
                {"field": "overview", "weight": 2.5},
                {"field": "content",  "weight": 2.0},
            ],
        },
        "vector": {
            "enabled": True,
            "vector_field": "content_vector",
            "num_candidates": 100,
        },
        "hybrid": {
            "enabled": True,
            "default_vector_weight": 0.65,
            "vector_field": "content_vector",
            "num_candidates": 100,
            "fields": [
                {"field": "title",    "weight": 3.0},
                {"field": "abstract", "weight": 3.0},
                {"field": "overview", "weight": 2.5},
                {"field": "content",  "weight": 2.0},
            ],
        },
    },
    "response_fields": [
        "doc_id", "memory_id", "title", "abstract", "overview",
        "task_ids", "feature_tags", "domain_tags", "component_tags",
        "metadata.related_storage_paths", "score",
    ],
}

TWO_HITS: dict[str, Any] = {
    "total": 2,
    "hits": [
        {
            "_score": 0.89,
            "_source": {
                "doc_id": "mem_001",
                "memory_id": "mem_001",
                "title": "CNI allocator concurrency issue",
                "abstract": "Root cause of the race condition.",
                "overview": "Thread-safety fix applied.",
                "task_ids": ["TASK-101"],
                "feature_tags": ["networking"],
                "domain_tags": ["k8s"],
                "component_tags": ["cni"],
                "content": "Full analysis...",
                "chunk_id": "mem_001::0",       # must be excluded
                "took_ms": 8,                   # must be excluded
                "metadata": {
                    "related_storage_paths": ["/mnt/memory/2026/05/mem_001.json"]
                },
            },
        },
        {
            "_score": 0.63,
            "_source": {
                "doc_id": "mem_002",
                "memory_id": "mem_002",
                "title": "Memory allocator pressure",
                "abstract": "OOM investigation.",
                "overview": "",
                "task_ids": ["TASK-202", "TASK-203"],
                "feature_tags": ["memory"],
                "domain_tags": ["linux"],
                "component_tags": ["kernel"],
                "content": "Details here...",
                "metadata": {},                  # no related_storage_paths
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

    def get_binding_by_domain_tag(self, *a: Any, **kw: Any) -> None:
        return None


class FakeVectorTool:
    def __init__(
        self,
        vector: list[float] | None = None,
        embed_side_effect: Exception | None = None,
        ensure_side_effect: Exception | None = None,
    ) -> None:
        self._vector = vector if vector is not None else DUMMY_VECTOR
        self._embed_side_effect = embed_side_effect
        self._ensure_side_effect = ensure_side_effect
        self.ensure_calls: list[str] = []
        self.embed_calls: list[tuple[str, str]] = []

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        self.ensure_calls.append(model_name)
        if self._ensure_side_effect is not None:
            raise self._ensure_side_effect
        return {"status": "ready"}

    def embed_query(self, query: str, model_name: str) -> list[float]:
        self.embed_calls.append((query, model_name))
        if self._embed_side_effect is not None:
            raise self._embed_side_effect
        return self._vector


class FakeCompiler:
    def __init__(
        self,
        dsl: dict[str, Any] | None = None,
        response_fields: list[str] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self._dsl = dsl or {"query": {"match_all": {}}, "size": 10}
        self._response_fields = response_fields if response_fields is not None else [
            "doc_id", "memory_id", "title", "abstract", "overview",
            "task_ids", "feature_tags", "domain_tags", "component_tags",
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
) -> tuple[MemorySearcher, FakeDBWriter, FakeVectorTool, FakeCompiler]:
    db = db_writer or FakeDBWriter()
    vec = vector_tool or FakeVectorTool()
    cmp = compiler or FakeCompiler()
    srch = MemorySearcher(db_writer=db, vector_tool=vec, compiler=cmp)  # type: ignore[arg-type]
    return srch, db, vec, cmp


def _search(searcher: MemorySearcher, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(
        kb_index=KB_INDEX,
        query="CNI concurrency race condition",
        search_type="text",
        top_k=10,
        search_profile=MEMORY_PROFILE,
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
        _search(srch, search_type="vector", vector_model=VECTOR_MODEL, query="OOM kernel")
        assert vec.embed_calls == [("OOM kernel", VECTOR_MODEL)]

    def test_hybrid_search_calls_vector_tool(self) -> None:
        srch, _, vec, _ = make_searcher()
        _search(srch, search_type="hybrid", vector_model=VECTOR_MODEL)
        assert len(vec.ensure_calls) == 1
        assert len(vec.embed_calls) == 1

    def test_query_vector_passed_to_compiler_for_vector_type(self) -> None:
        srch, _, vec, cmp = make_searcher()
        vec._vector = [0.9] * 4
        _search(srch, search_type="vector", vector_model=VECTOR_MODEL)
        assert cmp.compile_calls[0]["query_vector"] == [0.9] * 4

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
        _search(srch)
        assert len(cmp.compile_calls) == 1

    def test_compiler_receives_search_type(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_type="keyword")
        assert cmp.compile_calls[0]["search_type"] == "keyword"

    def test_compiler_receives_query(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, query="memory pressure OOM")
        assert cmp.compile_calls[0]["query"] == "memory pressure OOM"

    def test_compiler_receives_top_k(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, top_k=5)
        assert cmp.compile_calls[0]["top_k"] == 5

    def test_compiler_receives_search_profile(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, search_profile=MEMORY_PROFILE)
        assert cmp.compile_calls[0]["search_profile"] == MEMORY_PROFILE

    def test_compiler_receives_vector_weight(self) -> None:
        srch, _, _, cmp = make_searcher()
        _search(srch, vector_weight=0.65)
        assert cmp.compile_calls[0]["vector_weight"] == 0.65


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
        _search(srch, kb_index="kb_memory_main")
        assert db.search_calls[0]["index"] == "kb_memory_main"

    def test_search_content_docs_receives_dsl_from_compiler(self) -> None:
        fixed_dsl = {"query": {"bool": {"should": [{"term": {"memory_id.keyword": "mem_001"}}]}}, "size": 3}
        cmp = FakeCompiler(dsl=fixed_dsl)
        srch, db, _, _ = make_searcher(compiler=cmp)
        _search(srch)
        assert db.search_calls[0]["dsl"] == fixed_dsl


# ──────────────────────────────────────────────────────────────────────────────
# 4. Return value structure
# ──────────────────────────────────────────────────────────────────────────────


class TestReturnStructure:
    def test_result_has_kb_index_total_items(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert "kb_index" in r and "total" in r and "items" in r

    def test_kb_index_matches_input(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch, kb_index="kb_memory_main")
        assert r["kb_index"] == "kb_memory_main"

    def test_total_from_raw_hits(self) -> None:
        db = FakeDBWriter(hits={"total": 42, "hits": []})
        srch, _, _, _ = make_searcher(db_writer=db)
        r = _search(srch)
        assert r["total"] == 42

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
# 5. _map_hits — field extraction (via hit_mapper)
# ──────────────────────────────────────────────────────────────────────────────


class TestMapHits:
    def test_score_from_underscore_score(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["score"] == pytest.approx(0.89)
        assert r["items"][1]["score"] == pytest.approx(0.63)

    def test_chunk_id_excluded(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        for item in r["items"]:
            assert "chunk_id" not in item

    def test_took_ms_excluded(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        for item in r["items"]:
            assert "took_ms" not in item

    def test_memory_id_in_result(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["memory_id"] == "mem_001"

    def test_task_ids_in_result(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["task_ids"] == ["TASK-101"]

    def test_feature_tags_in_result(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["feature_tags"] == ["networking"]

    def test_domain_tags_in_result(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["domain_tags"] == ["k8s"]

    def test_component_tags_in_result(self) -> None:
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        assert r["items"][0]["component_tags"] == ["cni"]

    def test_related_storage_paths_flattened(self) -> None:
        """metadata.related_storage_paths → top-level key 'related_storage_paths'."""
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        item0 = r["items"][0]
        assert "related_storage_paths" in item0
        assert item0["related_storage_paths"] == ["/mnt/memory/2026/05/mem_001.json"]

    def test_missing_related_storage_paths_skipped(self) -> None:
        """Hit with empty metadata dict must not raise."""
        srch, _, _, _ = make_searcher()
        r = _search(srch)
        item1 = r["items"][1]
        assert "related_storage_paths" not in item1

    def test_related_storage_paths_empty_list_included(self) -> None:
        hits = {
            "total": 1,
            "hits": [
                {"_score": 0.5, "_source": {"doc_id": "x", "memory_id": "x", "metadata": {"related_storage_paths": []}}}
            ],
        }
        db = FakeDBWriter(hits=hits)
        srch, _, _, _ = make_searcher(db_writer=db)
        r = _search(srch)
        assert "related_storage_paths" in r["items"][0]
        assert r["items"][0]["related_storage_paths"] == []

    def test_response_fields_filter_applied(self) -> None:
        cmp = FakeCompiler(response_fields=["doc_id", "memory_id", "title", "score"])
        srch, _, _, _ = make_searcher(compiler=cmp)
        r = _search(srch)
        assert set(r["items"][0].keys()) == {"doc_id", "memory_id", "title", "score"}

    def test_empty_response_fields_returns_all_source_fields(self) -> None:
        cmp = FakeCompiler(response_fields=[])
        srch, _, _, _ = make_searcher(compiler=cmp)
        r = _search(srch)
        item = r["items"][0]
        assert "memory_id" in item
        assert "task_ids" in item
        assert "chunk_id" not in item
        assert "took_ms" not in item
        assert "score" in item

    def test_metadata_not_dict_does_not_raise(self) -> None:
        hits = {
            "total": 1,
            "hits": [{"_score": 0.5, "_source": {"doc_id": "y", "metadata": "corrupt"}}],
        }
        db = FakeDBWriter(hits=hits)
        cmp = FakeCompiler(response_fields=["doc_id", "metadata.related_storage_paths", "score"])
        srch, _, _, _ = make_searcher(db_writer=db, compiler=cmp)
        r = _search(srch)
        assert r["items"][0]["doc_id"] == "y"
        assert "related_storage_paths" not in r["items"][0]


# ──────────────────────────────────────────────────────────────────────────────
# 6. Error handling
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_vector_without_model_raises_profile_invalid(self) -> None:
        srch, _, _, _ = make_searcher()
        with pytest.raises(SearchProfileInvalidError):
            _search(srch, search_type="vector", vector_model=None)

    def test_hybrid_without_model_raises_profile_invalid(self) -> None:
        srch, _, _, _ = make_searcher()
        with pytest.raises(SearchProfileInvalidError):
            _search(srch, search_type="hybrid", vector_model=None)

    def test_embed_query_failure_raises_search_internal_error(self) -> None:
        vec = FakeVectorTool(embed_side_effect=RuntimeError("CUDA OOM"))
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)

    def test_ensure_model_ready_failure_raises_search_internal_error(self) -> None:
        vec = FakeVectorTool(ensure_side_effect=OSError("download failed"))
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)

    def test_db_failure_raises_search_internal_error(self) -> None:
        db = FakeDBWriter(side_effect=ConnectionError("OpenSearch unreachable"))
        srch, _, _, _ = make_searcher(db_writer=db)
        with pytest.raises(SearchInternalError):
            _search(srch, search_type="text")

    def test_compiler_failure_propagates_profile_invalid(self) -> None:
        cmp = FakeCompiler(side_effect=SearchProfileInvalidError("term_fields missing"))
        srch, _, _, _ = make_searcher(compiler=cmp)
        with pytest.raises(SearchProfileInvalidError, match="term_fields missing"):
            _search(srch, search_type="keyword")

    def test_internal_error_wraps_original_cause(self) -> None:
        original = RuntimeError("GPU fault")
        vec = FakeVectorTool(embed_side_effect=original)
        srch, _, _, _ = make_searcher(vector_tool=vec)
        with pytest.raises(SearchInternalError) as exc_info:
            _search(srch, search_type="vector", vector_model=VECTOR_MODEL)
        assert exc_info.value.__cause__ is original

    def test_db_internal_error_wraps_original_cause(self) -> None:
        original = TimeoutError("query timed out")
        db = FakeDBWriter(side_effect=original)
        srch, _, _, _ = make_searcher(db_writer=db)
        with pytest.raises(SearchInternalError) as exc_info:
            _search(srch, search_type="text")
        assert exc_info.value.__cause__ is original


# ──────────────────────────────────────────────────────────────────────────────
# 7. MEMORY-specific: keyword multi-term via real compiler
# ──────────────────────────────────────────────────────────────────────────────


class TestKeywordMultiTermWithRealCompiler:
    """Verify that the MEMORY keyword profile produces bool.should + term DSL."""

    def setup_method(self) -> None:
        from bible.features.search.common.query_profile_compiler import QueryProfileCompiler
        self.db = FakeDBWriter()
        self.vec = FakeVectorTool()
        self.srch = MemorySearcher(
            db_writer=self.db,  # type: ignore[arg-type]
            vector_tool=self.vec,  # type: ignore[arg-type]
            compiler=QueryProfileCompiler(),
        )

    def test_keyword_dsl_contains_bool_should(self) -> None:
        _search(self.srch, search_type="keyword", query="TASK-101")
        dsl = self.db.search_calls[0]["dsl"]
        assert "bool" in dsl["query"]
        assert "should" in dsl["query"]["bool"]

    def test_keyword_dsl_has_memory_id_keyword_clause(self) -> None:
        _search(self.srch, search_type="keyword", query="mem_001")
        dsl = self.db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        fields = [list(clause["term"].keys())[0] for clause in should]
        assert "memory_id.keyword" in fields

    def test_keyword_dsl_has_task_ids_keyword_clause(self) -> None:
        _search(self.srch, search_type="keyword", query="TASK-202")
        dsl = self.db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        fields = [list(clause["term"].keys())[0] for clause in should]
        assert "task_ids.keyword" in fields

    def test_keyword_dsl_has_five_term_clauses(self) -> None:
        _search(self.srch, search_type="keyword", query="k8s")
        dsl = self.db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        assert len(should) == 5

    def test_text_dsl_uses_four_fields(self) -> None:
        _search(self.srch, search_type="text", query="memory pressure")
        dsl = self.db.search_calls[0]["dsl"]
        fields = dsl["query"]["multi_match"]["fields"]
        field_names = [f.split("^")[0] for f in fields]
        assert set(field_names) == {"title", "abstract", "overview", "content"}
