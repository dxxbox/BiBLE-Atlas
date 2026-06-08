"""Unit tests for KnowledgeBaseSearcher (Task I).

Strategy
--------
- ``FakeDBWriter``  — in-memory fake that implements IDatabaseWriter.search_content_docs.
- ``FakeVectorTool`` — records calls to ensure_model_ready / embed_query.
- ``FakeCompiler``  — thin wrapper that records compile() call args.
- Tests assert BOTH the correct call order AND the shape of returned data.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from bible.features.search.common.query_profile_compiler import (
    QueryProfileCompiler,
    SearchProfileInvalidError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    KnowledgeBaseSearcher,
    SearchInternalError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures & fakes
# ──────────────────────────────────────────────────────────────────────────────

DUMMY_VECTOR = [0.1, 0.2, 0.3]
KB_INDEX = "kb_design_main"
VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"

SAMPLE_PROFILE = {
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
            "fields": [
                {"field": "content", "weight": 3.0},
                {"field": "title", "weight": 2.0},
            ],
        },
        "vector": {
            "enabled": True,
            "vector_field": "content_vector",
            "num_candidates": 100,
        },
        "hybrid": {
            "enabled": True,
            "default_vector_weight": 0.6,
            "vector_field": "content_vector",
            "num_candidates": 100,
            "fields": [{"field": "content", "weight": 3.0}],
        },
    },
    "response_fields": ["doc_id", "title", "content", "score"],
}

SAMPLE_HITS = {
    "total": 2,
    "hits": [
        {
            "_score": 0.87,
            "_source": {
                "doc_id": "abc#1",
                "title": "Scheduler",
                "content": "Periodic task management",
                "chunk_id": "abc#1::0",   # must be excluded
                "took_ms": 5,              # must be excluded
            },
        },
        {
            "_score": 0.72,
            "_source": {
                "doc_id": "abc#2",
                "title": "Memory layout",
                "content": "Stack and heap",
                "chunk_id": "abc#2::0",
            },
        },
    ],
}


class FakeVectorTool:
    """Records calls; embed_query returns a fixed DUMMY_VECTOR."""

    def __init__(self) -> None:
        self.ensure_calls: list[str] = []
        self.embed_calls: list[tuple[str, str]] = []

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        self.ensure_calls.append(model_name)
        return {"model_name": model_name, "status": "ready", "source": "cache"}

    def embed_query(self, query: str, model_name: str) -> list[float]:
        self.embed_calls.append((query, model_name))
        return DUMMY_VECTOR


class FakeDBWriter:
    """Returns SAMPLE_HITS from search_content_docs."""

    def __init__(self, hits: dict[str, Any] | None = None) -> None:
        self._hits = hits if hits is not None else SAMPLE_HITS
        self.search_calls: list[dict[str, Any]] = []

    def search_content_docs(
        self, index: str, dsl: dict[str, Any]
    ) -> dict[str, Any]:
        self.search_calls.append({"index": index, "dsl": dsl})
        return self._hits

    # satisfy Protocol stubs (no-op)
    def get_binding_by_domain_index(self, *a: Any, **kw: Any) -> None:  # type: ignore[override]
        return None

    def get_binding_by_domain_tag(self, *a: Any, **kw: Any) -> None:  # type: ignore[override]
        return None

    def create_index_binding(self, *a: Any, **kw: Any) -> dict[str, Any]:
        return {}

    def deactivate_binding(self, *a: Any, **kw: Any) -> dict[str, Any]:
        return {}

    def bulk_upsert_content_docs(self, *a: Any, **kw: Any) -> Any:
        return None

    def bulk_upsert_file_registry(self, *a: Any, **kw: Any) -> Any:
        return None

    def create_async_task(self, *a: Any, **kw: Any) -> None:
        pass

    def get_async_task(self, *a: Any, **kw: Any) -> None:
        return None

    def find_async_task_by_idempotency(self, *a: Any, **kw: Any) -> None:
        return None

    def update_async_task(self, *a: Any, **kw: Any) -> bool:
        return True


@pytest.fixture
def fake_vector() -> FakeVectorTool:
    return FakeVectorTool()


@pytest.fixture
def fake_db() -> FakeDBWriter:
    return FakeDBWriter()


@pytest.fixture
def searcher(fake_db: FakeDBWriter, fake_vector: FakeVectorTool) -> KnowledgeBaseSearcher:
    return KnowledgeBaseSearcher(db_writer=fake_db, vector_tool=fake_vector)


# ──────────────────────────────────────────────────────────────────────────────
# Non-vector search types (keyword / title / text)
# ──────────────────────────────────────────────────────────────────────────────


class TestNonVectorSearch:
    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_no_vector_calls(
        self,
        searcher: KnowledgeBaseSearcher,
        fake_vector: FakeVectorTool,
        search_type: str,
    ) -> None:
        searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type=search_type,
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        assert fake_vector.ensure_calls == []
        assert fake_vector.embed_calls == []

    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_db_search_called_with_correct_index(
        self,
        searcher: KnowledgeBaseSearcher,
        fake_db: FakeDBWriter,
        search_type: str,
    ) -> None:
        searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type=search_type,
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        assert len(fake_db.search_calls) == 1
        assert fake_db.search_calls[0]["index"] == KB_INDEX

    def test_returns_correct_total(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        result = searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="text",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        assert result["total"] == 2
        assert result["kb_index"] == KB_INDEX
        assert len(result["items"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Vector search
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorSearch:
    def test_ensure_then_embed_called(
        self,
        searcher: KnowledgeBaseSearcher,
        fake_vector: FakeVectorTool,
    ) -> None:
        searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="vector",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=VECTOR_MODEL,
            vector_weight=None,
        )
        assert fake_vector.ensure_calls == [VECTOR_MODEL]
        assert fake_vector.embed_calls == [("scheduler", VECTOR_MODEL)]

    def test_query_vector_reaches_compiler(
        self, fake_db: FakeDBWriter, fake_vector: FakeVectorTool
    ) -> None:
        """The query_vector produced by embed_query must end up in the DSL."""
        recording_compiler = QueryProfileCompiler()
        compile_args: dict[str, Any] = {}
        original_compile = recording_compiler.compile

        def spy_compile(**kwargs: Any) -> Any:
            compile_args.update(kwargs)
            return original_compile(**kwargs)

        recording_compiler.compile = spy_compile  # type: ignore[method-assign]
        srch = KnowledgeBaseSearcher(
            db_writer=fake_db, vector_tool=fake_vector, compiler=recording_compiler
        )
        srch.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="vector",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=VECTOR_MODEL,
            vector_weight=None,
        )
        assert compile_args.get("query_vector") == DUMMY_VECTOR

    def test_missing_vector_model_raises_profile_invalid(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        with pytest.raises(SearchProfileInvalidError, match="vector_model is required"):
            searcher.search(
                kb_index=KB_INDEX,
                query="q",
                search_type="vector",
                top_k=5,
                search_profile=SAMPLE_PROFILE,
                vector_model=None,   # missing!
                vector_weight=None,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Hybrid search
# ──────────────────────────────────────────────────────────────────────────────


class TestHybridSearch:
    def test_ensure_and_embed_called_for_hybrid(
        self,
        searcher: KnowledgeBaseSearcher,
        fake_vector: FakeVectorTool,
    ) -> None:
        searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="hybrid",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=VECTOR_MODEL,
            vector_weight=0.7,
        )
        assert fake_vector.ensure_calls == [VECTOR_MODEL]
        assert fake_vector.embed_calls == [("scheduler", VECTOR_MODEL)]

    def test_vector_weight_forwarded(
        self, fake_db: FakeDBWriter, fake_vector: FakeVectorTool
    ) -> None:
        compile_args: dict[str, Any] = {}
        original = QueryProfileCompiler().compile

        compiler = QueryProfileCompiler()

        def spy(**kwargs: Any) -> Any:
            compile_args.update(kwargs)
            return original(**kwargs)

        compiler.compile = spy  # type: ignore[method-assign]
        srch = KnowledgeBaseSearcher(
            db_writer=fake_db, vector_tool=fake_vector, compiler=compiler
        )
        srch.search(
            kb_index=KB_INDEX,
            query="q",
            search_type="hybrid",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=VECTOR_MODEL,
            vector_weight=0.8,
        )
        assert compile_args.get("vector_weight") == 0.8


# ──────────────────────────────────────────────────────────────────────────────
# map_hits: field filtering & excluded fields
# ──────────────────────────────────────────────────────────────────────────────


class TestMapHits:
    def test_response_fields_filter(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        result = searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="text",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        for item in result["items"]:
            # response_fields = ["doc_id", "title", "content", "score"]
            assert "doc_id" in item
            assert "title" in item
            assert "content" in item
            assert "score" in item

    def test_chunk_id_excluded(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        result = searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="text",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        for item in result["items"]:
            assert "chunk_id" not in item

    def test_took_ms_excluded(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        result = searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="text",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        for item in result["items"]:
            assert "took_ms" not in item

    def test_score_from_underscore_score(
        self, searcher: KnowledgeBaseSearcher
    ) -> None:
        result = searcher.search(
            kb_index=KB_INDEX,
            query="scheduler",
            search_type="text",
            top_k=5,
            search_profile=SAMPLE_PROFILE,
            vector_model=None,
            vector_weight=None,
        )
        assert result["items"][0]["score"] == pytest.approx(0.87)
        assert result["items"][1]["score"] == pytest.approx(0.72)

    def test_empty_response_fields_returns_all_source_fields(
        self, fake_vector: FakeVectorTool
    ) -> None:
        """When response_fields is absent, every _source key is kept."""
        profile_no_rf = {
            "search_type_profile": {
                "text": {
                    "enabled": True,
                    "fields": [{"field": "content", "weight": 1.0}],
                }
            }
            # no "response_fields" key
        }
        db = FakeDBWriter(
            hits={
                "total": 1,
                "hits": [
                    {
                        "_score": 0.5,
                        "_source": {"doc_id": "x", "title": "T", "chunk_id": "c"},
                    }
                ],
            }
        )
        srch = KnowledgeBaseSearcher(db_writer=db, vector_tool=fake_vector)
        result = srch.search(
            kb_index=KB_INDEX,
            query="q",
            search_type="text",
            top_k=5,
            search_profile=profile_no_rf,
            vector_model=None,
            vector_weight=None,
        )
        item = result["items"][0]
        assert "doc_id" in item
        assert "title" in item
        assert "chunk_id" not in item  # always excluded
        assert item["score"] == pytest.approx(0.5)


# ──────────────────────────────────────────────────────────────────────────────
# Error propagation
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorPropagation:
    def test_compiler_error_propagates(
        self, fake_db: FakeDBWriter, fake_vector: FakeVectorTool
    ) -> None:
        """SearchProfileInvalidError from the compiler must not be swallowed."""
        bad_profile = {
            "search_type_profile": {
                "keyword": {"enabled": True, "term_fields": []}  # empty → error
            }
        }
        srch = KnowledgeBaseSearcher(db_writer=fake_db, vector_tool=fake_vector)
        with pytest.raises(SearchProfileInvalidError):
            srch.search(
                kb_index=KB_INDEX,
                query="q",
                search_type="keyword",
                top_k=5,
                search_profile=bad_profile,
                vector_model=None,
                vector_weight=None,
            )

    def test_db_error_raises_internal_error(
        self, fake_vector: FakeVectorTool
    ) -> None:
        """Exceptions from search_content_docs are wrapped in SearchInternalError."""

        class BrokenDB(FakeDBWriter):
            def search_content_docs(self, index: str, dsl: dict[str, Any]) -> dict[str, Any]:
                raise RuntimeError("connection refused")

        srch = KnowledgeBaseSearcher(db_writer=BrokenDB(), vector_tool=fake_vector)
        with pytest.raises(SearchInternalError, match="Database search failed"):
            srch.search(
                kb_index=KB_INDEX,
                query="q",
                search_type="text",
                top_k=5,
                search_profile=SAMPLE_PROFILE,
                vector_model=None,
                vector_weight=None,
            )

    def test_embed_error_raises_internal_error(
        self, fake_db: FakeDBWriter
    ) -> None:
        """Exceptions from embed_query are wrapped in SearchInternalError."""

        class BrokenVector(FakeVectorTool):
            def embed_query(self, query: str, model_name: str) -> list[float]:
                raise RuntimeError("GPU OOM")

        srch = KnowledgeBaseSearcher(db_writer=fake_db, vector_tool=BrokenVector())
        with pytest.raises(SearchInternalError, match="Vector embedding failed"):
            srch.search(
                kb_index=KB_INDEX,
                query="q",
                search_type="vector",
                top_k=5,
                search_profile=SAMPLE_PROFILE,
                vector_model=VECTOR_MODEL,
                vector_weight=None,
            )
