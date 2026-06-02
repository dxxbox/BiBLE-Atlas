"""Integration tests for the full MEMORY search path.

Chain under test (real code, no mocks except at the infrastructure boundary)
-----------------------------------------------------------------------------
HTTP POST /api/search/memory
  → FastAPI route    (MemorySearchRequest validation + _validate_tag)
  → MemorySearchService  (param normalisation, binding lookup, model check)
  → MemorySearcher       (vector embedding gate, DSL compilation, hit mapping)
  → QueryProfileCompiler  (real DSL generation)
  → [FakeDBWriter]        ← only mock boundary
  → [FakeVectorTool]      ← only mock boundary

What these tests catch that unit tests cannot
---------------------------------------------
- End-to-end param normalisation (top_k / search_type / vector_weight defaults
  flow all the way through to the DSL actually sent to the DB).
- Real QueryProfileCompiler rules applied to MEMORY-specific profiles
  (multi-field keyword → bool.should+term, multi-field text → multi_match).
- Hit-mapping (chunk_id / took_ms excluded, score wired from _score,
  dot-path resolution for metadata.related_storage_paths).
- Error propagation without any exception-swallowing along the chain.
- Tag validation: tag != "memory" → 400 TAG_INVALID before reaching the service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bible.api.deps import get_memory_search_service, get_search_cfg
from bible.api.search import search_router
from bible.config.configure import SearchConfig
from bible.features.search.memory_search.memory_search_service import MemorySearchService
from bible.infrastructure.database.types import DomainType, IndexBinding

# ──────────────────────────────────────────────────────────────────────────────
# Shared profiles and bindings
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_memory_main"
DUMMY_VECTOR = [0.1] * 8

# Complete MEMORY profile (hybrid must include vector_field / num_candidates / fields)
FULL_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "keyword": {
            "enabled": True,
            "term_fields": [
                {"field": "memory_id.keyword", "weight": 1.0},
                {"field": "task_ids.keyword", "weight": 1.0},
                {"field": "feature_tags.keyword", "weight": 1.0},
                {"field": "domain_tags.keyword", "weight": 1.0},
                {"field": "component_tags.keyword", "weight": 1.0},
            ],
        },
        "title": {
            "enabled": True,
            "match_fields": [{"field": "title", "weight": 2.0}],
        },
        "text": {
            "enabled": True,
            "multi_match_type": "most_fields",
            "fields": [
                {"field": "title", "weight": 3.0},
                {"field": "abstract", "weight": 2.0},
                {"field": "overview", "weight": 2.0},
                {"field": "content", "weight": 1.0},
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
            "default_vector_weight": 0.65,
            "vector_field": "content_vector",
            "num_candidates_min": 100,
            "num_candidates_multiplier": 3,
            "fields": [
                {"field": "title", "weight": 3.0},
                {"field": "content", "weight": 1.0},
            ],
        },
    },
    "response_fields": [
        "doc_id", "memory_id", "title", "abstract", "score",
        "metadata.related_storage_paths",
    ],
}

BINDING_WITH_VECTOR = IndexBinding(
    domain_type="MEMORY",
    kb_index=KB_INDEX,
    tag="memory",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=VECTOR_MODEL,
    search_profile_json=FULL_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

BINDING_NO_VECTOR = IndexBinding(
    domain_type="MEMORY",
    kb_index=KB_INDEX,
    tag="memory",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=None,
    search_profile_json=FULL_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

TWO_HITS: dict[str, Any] = {
    "total": 2,
    "hits": [
        {
            "_score": 0.93,
            "_source": {
                "doc_id": "mem_001",
                "memory_id": "mem_001",
                "title": "CNI race condition fix",
                "abstract": "Fix race in CNI plugin",
                "chunk_id": "mem_001::0",        # must be stripped
                "took_ms": 5,                    # must be stripped
                "metadata": {
                    "related_storage_paths": ["s3://bucket/cni.md", "s3://bucket/fix.md"]
                },
            },
        },
        {
            "_score": 0.77,
            "_source": {
                "doc_id": "mem_002",
                "memory_id": "mem_002",
                "title": "OOM kernel pressure",
                "abstract": "Kernel OOM killer analysis",
                "metadata": {"related_storage_paths": []},
            },
        },
    ],
}

ZERO_HITS: dict[str, Any] = {"total": 0, "hits": []}


# ──────────────────────────────────────────────────────────────────────────────
# Infrastructure fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeDBWriter:
    """Configurable fake IDatabaseWriter.  search_calls records every DSL sent."""

    def __init__(
        self,
        binding: IndexBinding | None = BINDING_WITH_VECTOR,
        hits: dict[str, Any] | None = None,
        search_side_effect: Exception | None = None,
    ) -> None:
        self._binding = binding
        self._hits = hits if hits is not None else TWO_HITS
        self._search_side_effect = search_side_effect
        self.search_calls: list[dict[str, Any]] = []

    def get_binding_by_domain_tag(
        self, domain: DomainType, tag: str
    ) -> IndexBinding | None:
        return self._binding

    def search_content_docs(
        self, index: str, dsl: dict[str, Any]
    ) -> dict[str, Any]:
        self.search_calls.append({"index": index, "dsl": dsl})
        if self._search_side_effect is not None:
            raise self._search_side_effect
        return self._hits

    # Protocol no-ops
    def get_binding_by_domain_index(self, *a: Any, **kw: Any) -> None:
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


class FakeVectorTool:
    """Configurable fake VectorTool."""

    def __init__(
        self,
        embed_side_effect: Exception | None = None,
        vector: list[float] | None = None,
    ) -> None:
        self._embed_side_effect = embed_side_effect
        self._vector = vector if vector is not None else DUMMY_VECTOR
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


class FakeDBFactory:
    def __init__(self, writer: FakeDBWriter) -> None:
        self._writer = writer

    def get_writer(self, domain: str) -> FakeDBWriter:
        return self._writer


# ──────────────────────────────────────────────────────────────────────────────
# Client factory
# ──────────────────────────────────────────────────────────────────────────────


def make_client(
    db_writer: FakeDBWriter | None = None,
    vector_tool: FakeVectorTool | None = None,
    search_cfg: SearchConfig | None = None,
) -> tuple[TestClient, FakeDBWriter, FakeVectorTool]:
    """Return (TestClient, fake_db, fake_vector) wired with the real service chain."""
    fake_db = db_writer or FakeDBWriter()
    fake_vec = vector_tool or FakeVectorTool()
    cfg = search_cfg or SearchConfig(default_top_k=10, max_top_k=50)

    svc = MemorySearchService(
        db_factory=FakeDBFactory(fake_db),  # type: ignore[arg-type]
        vector_tool=fake_vec,               # type: ignore[arg-type]
        search_cfg=cfg,
    )

    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_search_cfg] = lambda: cfg
    app.dependency_overrides[get_memory_search_service] = lambda: svc

    return TestClient(app, raise_server_exceptions=False), fake_db, fake_vec


BASE_BODY: dict[str, Any] = {"query": "CNI race", "tag": "memory"}


# ──────────────────────────────────────────────────────────────────────────────
# 1. Success path — response shape
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessResponseShape:
    def test_200_status(self) -> None:
        client, _, _ = make_client()
        assert client.post("/api/search/memory", json=BASE_BODY).status_code == 200

    def test_response_top_level_fields(self) -> None:
        client, _, _ = make_client()
        body = client.post("/api/search/memory", json=BASE_BODY).json()
        assert body["success"] is True
        assert body["domain"] == "MEMORY"
        assert body["kb_index"] == KB_INDEX
        assert body["tag"] == "memory"
        assert body["total"] == 2
        assert "memory" in body["results"]

    def test_result_items_count(self) -> None:
        client, _, _ = make_client()
        body = client.post("/api/search/memory", json=BASE_BODY).json()
        assert len(body["results"]["memory"]) == 2

    def test_score_wired_from_underscore_score(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"]
        assert items[0]["score"] == pytest.approx(0.93)
        assert items[1]["score"] == pytest.approx(0.77)

    def test_chunk_id_never_in_response(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"]
        for item in items:
            assert "chunk_id" not in item

    def test_took_ms_never_in_response(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"]
        for item in items:
            assert "took_ms" not in item

    def test_response_fields_filter_applied(self) -> None:
        """Only fields listed in profile.response_fields appear in results."""
        client, _, _ = make_client()
        item = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"][0]
        # response_fields = ["doc_id", "memory_id", "title", "abstract", "score",
        #                    "metadata.related_storage_paths"]
        # dot-path field is stored under leaf key "related_storage_paths"
        assert "doc_id" in item
        assert "memory_id" in item
        assert "title" in item
        assert "abstract" in item
        assert "score" in item
        assert "related_storage_paths" in item

    def test_dot_path_metadata_related_storage_paths_flattened(self) -> None:
        """metadata.related_storage_paths must be stored under leaf key."""
        client, _, _ = make_client()
        item = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"][0]
        assert item["related_storage_paths"] == ["s3://bucket/cni.md", "s3://bucket/fix.md"]

    def test_metadata_dict_not_in_response(self) -> None:
        """The nested 'metadata' dict itself must not appear — only flattened leaf."""
        client, _, _ = make_client()
        item = client.post("/api/search/memory", json=BASE_BODY).json()["results"]["memory"][0]
        assert "metadata" not in item

    def test_zero_hits(self) -> None:
        client, _, _ = make_client(db_writer=FakeDBWriter(hits=ZERO_HITS))
        body = client.post("/api/search/memory", json=BASE_BODY).json()
        assert body["total"] == 0
        assert body["results"]["memory"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 2. All five search_type values
# ──────────────────────────────────────────────────────────────────────────────


class TestAllSearchTypes:
    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_non_vector_types_do_not_call_vector_tool(self, search_type: str) -> None:
        client, _, fake_vec = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": search_type})
        assert resp.status_code == 200
        assert fake_vec.ensure_calls == []
        assert fake_vec.embed_calls == []

    def test_keyword_dsl_uses_bool_should_for_multi_field(self) -> None:
        """MEMORY keyword search spans 5 term_fields → bool.should."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "keyword"})
        dsl = fake_db.search_calls[0]["dsl"]
        assert "bool" in dsl["query"]
        assert "should" in dsl["query"]["bool"]

    def test_keyword_dsl_has_five_should_clauses(self) -> None:
        """5 term_fields → 5 should clauses."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "keyword"})
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        assert len(should) == 5

    def test_keyword_dsl_includes_memory_id_field(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "keyword"})
        dsl_str = str(fake_db.search_calls[0]["dsl"])
        assert "memory_id.keyword" in dsl_str

    def test_title_dsl_uses_match_clause(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "title"})
        dsl = fake_db.search_calls[0]["dsl"]
        assert "match" in dsl["query"]

    def test_text_dsl_uses_multi_match(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "text"})
        dsl = fake_db.search_calls[0]["dsl"]
        assert "multi_match" in dsl["query"]

    def test_text_dsl_includes_memory_specific_fields(self) -> None:
        """text search must target title / abstract / overview / content."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "text"})
        fields_str = str(fake_db.search_calls[0]["dsl"]["query"]["multi_match"]["fields"])
        assert "abstract" in fields_str
        assert "overview" in fields_str

    def test_vector_calls_ensure_and_embed(self) -> None:
        client, _, fake_vec = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector"})
        assert resp.status_code == 200
        assert fake_vec.ensure_calls == [VECTOR_MODEL]
        assert fake_vec.embed_calls == [("CNI race", VECTOR_MODEL)]

    def test_vector_dsl_uses_knn(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector"})
        dsl = fake_db.search_calls[0]["dsl"]
        assert "knn" in dsl["query"]

    def test_hybrid_calls_vector_tool(self) -> None:
        client, _, fake_vec = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "hybrid"})
        assert resp.status_code == 200
        assert fake_vec.embed_calls == [("CNI race", VECTOR_MODEL)]

    def test_hybrid_dsl_has_two_function_score_arms(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "hybrid"})
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        assert len(should) == 2

    def test_default_search_type_is_text(self) -> None:
        """When search_type is omitted, the service normalises to 'text'."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json=BASE_BODY)
        dsl = fake_db.search_calls[0]["dsl"]
        assert "multi_match" in dsl["query"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Parameter normalisation end-to-end
# ──────────────────────────────────────────────────────────────────────────────


class TestParamNormalisation:
    def test_top_k_none_uses_config_default(self) -> None:
        cfg = SearchConfig(default_top_k=7, max_top_k=50)
        client, fake_db, _ = make_client(search_cfg=cfg)
        client.post("/api/search/memory", json=BASE_BODY)
        assert fake_db.search_calls[0]["dsl"]["size"] == 7

    def test_top_k_passed_through(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "top_k": 3})
        assert fake_db.search_calls[0]["dsl"]["size"] == 3

    def test_top_k_clamped_to_max_at_service(self) -> None:
        cfg = SearchConfig(default_top_k=10, max_top_k=20)
        client, fake_db, _ = make_client(search_cfg=cfg)
        client.post("/api/search/memory", json={**BASE_BODY, "top_k": 20})
        assert fake_db.search_calls[0]["dsl"]["size"] == 20

    def test_vector_weight_from_profile_default_when_omitted(self) -> None:
        """profile hybrid.default_vector_weight = 0.65 must reach the DSL."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "hybrid"})
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.65 in weights

    def test_explicit_vector_weight_overrides_profile_default(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/memory",
            json={**BASE_BODY, "search_type": "hybrid", "vector_weight": 0.8},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.8 in weights

    def test_vector_weight_discarded_for_text_search(self) -> None:
        client, fake_db, _ = make_client()
        resp = client.post(
            "/api/search/memory",
            json={**BASE_BODY, "search_type": "text", "vector_weight": 0.9},
        )
        assert resp.status_code == 200
        dsl = fake_db.search_calls[0]["dsl"]
        assert "function_score" not in str(dsl)

    def test_effective_vector_model_from_binding(self) -> None:
        """The binding's vector_model must be used even when caller omits it."""
        client, _, fake_vec = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector"})
        _, model_used = fake_vec.embed_calls[0]
        assert model_used == VECTOR_MODEL

    def test_index_used_is_from_binding(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json=BASE_BODY)
        assert fake_db.search_calls[0]["index"] == KB_INDEX


# ──────────────────────────────────────────────────────────────────────────────
# 4. HTTP input validation (API layer)
# ──────────────────────────────────────────────────────────────────────────────


class TestInputValidation:
    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query_422(self, query: str) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={"query": query, "tag": "memory"})
        assert resp.status_code == 422

    @pytest.mark.parametrize("tag", ["", "   "])
    def test_empty_tag_422(self, tag: str) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={"query": "q", "tag": tag})
        assert resp.status_code == 422

    @pytest.mark.parametrize("tag", ["skill", "knowledge_base", "Memory", "MEMORY"])
    def test_wrong_tag_400_tag_invalid(self, tag: str) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={"query": "q", "tag": tag})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_top_k_zero_422(self) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "top_k": 0})
        assert resp.status_code == 422

    def test_top_k_exceeds_max_400(self) -> None:
        cfg = SearchConfig(max_top_k=20)
        client, _, _ = make_client(search_cfg=cfg)
        resp = client.post("/api/search/memory", json={**BASE_BODY, "top_k": 999})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_ARGUMENT"

    def test_vector_weight_out_of_range_422(self) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "vector_weight": 1.5})
        assert resp.status_code == 422

    def test_unknown_search_type_400(self) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "bm25_fuzzy"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "SEARCH_TYPE_INVALID"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Business errors from the service / searcher layers
# ──────────────────────────────────────────────────────────────────────────────


class TestBusinessErrors:
    def test_binding_not_found_404(self) -> None:
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=None))
        resp = client.post("/api/search/memory", json=BASE_BODY)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "INDEX_NOT_BOUND"

    def test_vector_model_conflict_409(self) -> None:
        client, _, _ = make_client()
        resp = client.post("/api/search/memory", json={**BASE_BODY, "vector_model": "other/model"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "VECTOR_MODEL_CONFLICT"
        detail = resp.json()["detail"]["message"]
        assert "other/model" in detail
        assert VECTOR_MODEL in detail

    def test_bad_profile_keyword_empty_term_fields_422(self) -> None:
        """Binding with empty term_fields for keyword → 422 SEARCH_PROFILE_INVALID."""
        bad_profile: dict[str, Any] = {
            "search_type_profile": {
                "keyword": {"enabled": True, "term_fields": []}  # empty → compiler error
            }
        }
        bad_binding = IndexBinding(
            domain_type="MEMORY", kb_index=KB_INDEX, tag="memory",
            parser_script_source="", parser_script_sha256="",
            vector_model=None, search_profile_json=bad_profile, search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=bad_binding))
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "keyword"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_missing_search_type_in_profile_422(self) -> None:
        """Profile without 'text' entry → 422 when text is requested."""
        partial_profile: dict[str, Any] = {
            "search_type_profile": {
                "keyword": {
                    "enabled": True,
                    "term_fields": [{"field": "memory_id.keyword", "weight": 1.0}],
                }
                # "text" intentionally absent
            }
        }
        binding = IndexBinding(
            domain_type="MEMORY", kb_index=KB_INDEX, tag="memory",
            parser_script_source="", parser_script_sha256="",
            vector_model=None, search_profile_json=partial_profile, search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=binding))
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "text"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_disabled_search_type_422(self) -> None:
        profile: dict[str, Any] = {
            "search_type_profile": {
                "text": {
                    "enabled": False,
                    "fields": [{"field": "content", "weight": 1.0}],
                }
            }
        }
        binding = IndexBinding(
            domain_type="MEMORY", kb_index=KB_INDEX, tag="memory",
            parser_script_source="", parser_script_sha256="",
            vector_model=None, search_profile_json=profile, search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=binding))
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "text"})
        assert resp.status_code == 422

    def test_db_exception_500(self) -> None:
        db = FakeDBWriter(search_side_effect=RuntimeError("connection refused"))
        client, _, _ = make_client(db_writer=db)
        resp = client.post("/api/search/memory", json=BASE_BODY)
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"
        assert "connection refused" not in resp.json()["detail"]["message"]

    def test_vector_embed_exception_500(self) -> None:
        vec = FakeVectorTool(embed_side_effect=RuntimeError("GPU OOM"))
        client, _, _ = make_client(vector_tool=vec)
        resp = client.post(
            "/api/search/memory", json={**BASE_BODY, "search_type": "vector"}
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"

    def test_vector_search_without_binding_model_422(self) -> None:
        """vector search with a binding that has no vector_model → 422."""
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=BINDING_NO_VECTOR))
        resp = client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_internal_error_details_not_exposed(self) -> None:
        db = FakeDBWriter(search_side_effect=RuntimeError("secret host: db.internal:9200"))
        client, _, _ = make_client(db_writer=db)
        resp = client.post("/api/search/memory", json=BASE_BODY)
        assert "db.internal" not in resp.text
        assert "secret" not in resp.text


# ──────────────────────────────────────────────────────────────────────────────
# 6. DSL correctness spot-checks (real compiler rules applied)
# ──────────────────────────────────────────────────────────────────────────────


class TestDslCorrectness:
    def test_keyword_term_value_equals_query(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/memory",
            json={**BASE_BODY, "query": "TASK-101", "search_type": "keyword"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        # Each term clause in should must contain the exact query value
        should = dsl["query"]["bool"]["should"]
        all_values = [
            list(clause["term"].values())[0]["value"]
            for clause in should
            if "term" in clause
        ]
        assert all(v == "TASK-101" for v in all_values)

    def test_text_multi_match_contains_query(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "query": "kernel OOM", "search_type": "text"})
        dsl = fake_db.search_calls[0]["dsl"]
        assert dsl["query"]["multi_match"]["query"] == "kernel OOM"

    def test_text_fields_have_boost(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "text"})
        fields = fake_db.search_calls[0]["dsl"]["query"]["multi_match"]["fields"]
        assert any("^" in f for f in fields)

    def test_vector_dsl_contains_query_vector(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector"})
        dsl = fake_db.search_calls[0]["dsl"]
        knn_vec = dsl["query"]["knn"]["content_vector"]["vector"]
        assert knn_vec == DUMMY_VECTOR

    def test_hybrid_dsl_knn_arm_uses_profile_vector_field(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "hybrid"})
        dsl_str = str(fake_db.search_calls[0]["dsl"])
        assert "content_vector" in dsl_str

    def test_num_candidates_not_below_min(self) -> None:
        """top_k=2, min=100 → num_candidates must be ≥ 100."""
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json={**BASE_BODY, "search_type": "vector", "top_k": 2})
        dsl = fake_db.search_calls[0]["dsl"]
        knn = dsl["query"]["knn"]["content_vector"]
        assert knn["num_candidates"] >= 100

    def test_size_field_present_in_dsl(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/memory", json=BASE_BODY)
        assert "size" in fake_db.search_calls[0]["dsl"]
