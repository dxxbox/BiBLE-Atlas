"""Integration tests for the full KNOWLEDGE_BASE search path.

Chain under test (real code, no mocks except at the infrastructure boundary)
-----------------------------------------------------------------------------
HTTP POST
  → FastAPI route (KBSearchRequest validation)
  → KnowledgeBaseSearchService  (param normalisation, binding lookup, model check)
  → KnowledgeBaseSearcher       (vector embedding gate, DSL compilation, hit mapping)
  → QueryProfileCompiler         (real DSL generation)
  → [FakeDBWriter]               ← only mock boundary
  → [FakeVectorTool]             ← only mock boundary

What these tests catch that unit tests cannot
---------------------------------------------
- End-to-end param normalisation (top_k/search_type/vector_weight defaults flow
  all the way through to the DSL actually sent to the DB).
- Real QueryProfileCompiler rules applied to real binding profiles.
- Hit-mapping (chunk_id / took_ms excluded, score wired from _score).
- Error propagation without any exception-swallowing along the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bible.api.deps import get_kb_search_service, get_search_cfg
from bible.api.search import search_router
from bible.config.configure import SearchConfig
from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
    KnowledgeBaseSearchService,
)
from bible.infrastructure.database.types import DomainType, IndexBinding

# ──────────────────────────────────────────────────────────────────────────────
# Shared profiles and bindings
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_design_main"
DUMMY_VECTOR = [0.1] * 8   # short for tests

FULL_PROFILE: dict[str, Any] = {
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
            "fields": [{"field": "content", "weight": 3.0}],
        },
    },
    "response_fields": ["doc_id", "title", "content", "score"],
}

BINDING_WITH_VECTOR = IndexBinding(
    domain_type="KNOWLEDGE_BASE",
    kb_index=KB_INDEX,
    tag="design",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=VECTOR_MODEL,
    search_profile_json=FULL_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

BINDING_NO_VECTOR = IndexBinding(
    domain_type="KNOWLEDGE_BASE",
    kb_index=KB_INDEX,
    tag="design",
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
            "_score": 0.91,
            "_source": {
                "doc_id": "abc#1",
                "title": "Scheduler",
                "content": "Periodic task manager",
                "chunk_id": "abc#1::0",    # must be stripped
                "took_ms": 12,             # must be stripped
            },
        },
        {
            "_score": 0.75,
            "_source": {
                "doc_id": "abc#2",
                "title": "Memory layout",
                "content": "Stack and heap",
                "chunk_id": "abc#2::0",
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
    """Return (TestClient, fake_db, fake_vector) wired with real service chain."""
    fake_db = db_writer or FakeDBWriter()
    fake_vec = vector_tool or FakeVectorTool()
    cfg = search_cfg or SearchConfig(default_top_k=10, max_top_k=50)

    svc = KnowledgeBaseSearchService(
        db_factory=FakeDBFactory(fake_db),  # type: ignore[arg-type]
        vector_tool=fake_vec,               # type: ignore[arg-type]
        search_cfg=cfg,
    )

    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_search_cfg] = lambda: cfg
    app.dependency_overrides[get_kb_search_service] = lambda: svc

    return TestClient(app, raise_server_exceptions=False), fake_db, fake_vec


BASE_BODY: dict[str, Any] = {"query": "scheduler", "tag": "design"}


# ──────────────────────────────────────────────────────────────────────────────
# 1. Success path — response shape
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessResponseShape:
    def test_200_status(self) -> None:
        client, _, _ = make_client()
        assert client.post("/api/search/knowledge-base", json=BASE_BODY).status_code == 200

    def test_response_top_level_fields(self) -> None:
        client, _, _ = make_client()
        body = client.post("/api/search/knowledge-base", json=BASE_BODY).json()
        assert body["success"] is True
        assert body["domain"] == "KNOWLEDGE_BASE"
        assert body["kb_index"] == KB_INDEX
        assert body["tag"] == "design"
        assert body["total"] == 2
        assert "knowledge_base" in body["results"]

    def test_result_items_count(self) -> None:
        client, _, _ = make_client()
        body = client.post("/api/search/knowledge-base", json=BASE_BODY).json()
        assert len(body["results"]["knowledge_base"]) == 2

    def test_score_wired_from_underscore_score(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/knowledge-base", json=BASE_BODY).json()[
            "results"
        ]["knowledge_base"]
        assert items[0]["score"] == pytest.approx(0.91)
        assert items[1]["score"] == pytest.approx(0.75)

    def test_chunk_id_never_in_response(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/knowledge-base", json=BASE_BODY).json()[
            "results"
        ]["knowledge_base"]
        for item in items:
            assert "chunk_id" not in item

    def test_took_ms_never_in_response(self) -> None:
        client, _, _ = make_client()
        items = client.post("/api/search/knowledge-base", json=BASE_BODY).json()[
            "results"
        ]["knowledge_base"]
        for item in items:
            assert "took_ms" not in item

    def test_response_fields_filter_applied(self) -> None:
        """Only fields listed in profile.response_fields appear in results."""
        client, _, _ = make_client()
        item = client.post("/api/search/knowledge-base", json=BASE_BODY).json()[
            "results"
        ]["knowledge_base"][0]
        # response_fields = ["doc_id", "title", "content", "score"]
        assert set(item.keys()) == {"doc_id", "title", "content", "score"}

    def test_zero_hits(self) -> None:
        client, _, _ = make_client(db_writer=FakeDBWriter(hits=ZERO_HITS))
        body = client.post("/api/search/knowledge-base", json=BASE_BODY).json()
        assert body["total"] == 0
        assert body["results"]["knowledge_base"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 2. Success path — all five search_type values
# ──────────────────────────────────────────────────────────────────────────────


class TestAllSearchTypes:
    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_non_vector_types_do_not_call_vector_tool(
        self, search_type: str
    ) -> None:
        client, _, fake_vec = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": search_type},
        )
        assert resp.status_code == 200
        assert fake_vec.ensure_calls == []
        assert fake_vec.embed_calls == []

    def test_keyword_dsl_uses_term_clause(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "keyword"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        assert "term" in dsl["query"]

    def test_title_dsl_uses_match_clause(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "title"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        assert "match" in dsl["query"]

    def test_text_dsl_uses_multi_match(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "text"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        assert "multi_match" in dsl["query"]

    def test_vector_calls_ensure_and_embed(self) -> None:
        client, _, fake_vec = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        assert resp.status_code == 200
        assert fake_vec.ensure_calls == [VECTOR_MODEL]
        assert fake_vec.embed_calls == [("scheduler", VECTOR_MODEL)]

    def test_vector_dsl_uses_knn(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        assert "knn" in dsl["query"]

    def test_hybrid_calls_vector_tool(self) -> None:
        client, _, fake_vec = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "hybrid"},
        )
        assert resp.status_code == 200
        assert fake_vec.embed_calls == [("scheduler", VECTOR_MODEL)]

    def test_hybrid_dsl_has_two_function_score_arms(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "hybrid"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        assert len(should) == 2

    def test_default_search_type_is_text(self) -> None:
        """When search_type is omitted, the service normalises to 'text'."""
        client, fake_db, _ = make_client()
        client.post("/api/search/knowledge-base", json=BASE_BODY)
        dsl = fake_db.search_calls[0]["dsl"]
        assert "multi_match" in dsl["query"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Parameter normalisation end-to-end
# ──────────────────────────────────────────────────────────────────────────────


class TestParamNormalisation:
    def test_top_k_none_uses_default(self) -> None:
        cfg = SearchConfig(default_top_k=7, max_top_k=50)
        client, fake_db, _ = make_client(search_cfg=cfg)
        client.post("/api/search/knowledge-base", json=BASE_BODY)
        assert fake_db.search_calls[0]["dsl"]["size"] == 7

    def test_top_k_clamped_to_max_at_service(self) -> None:
        """top_k=999 should be clamped to max_top_k=50 before reaching the DB."""
        cfg = SearchConfig(default_top_k=10, max_top_k=50)
        client, fake_db, _ = make_client(search_cfg=cfg)
        client.post(
            "/api/search/knowledge-base", json={**BASE_BODY, "top_k": 50}
        )
        assert fake_db.search_calls[0]["dsl"]["size"] == 50

    def test_top_k_passed_through(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base", json={**BASE_BODY, "top_k": 3}
        )
        assert fake_db.search_calls[0]["dsl"]["size"] == 3

    def test_vector_weight_from_profile_default_when_omitted(self) -> None:
        """When vector_weight is not sent, the profile's default_vector_weight (0.6)
        should end up in the DSL."""
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "hybrid"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.6 in weights

    def test_explicit_vector_weight_overrides_profile_default(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "hybrid", "vector_weight": 0.8},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        should = dsl["query"]["bool"]["should"]
        weights = {s["function_score"]["weight"] for s in should}
        assert 0.8 in weights

    def test_vector_weight_set_to_none_for_non_vector_types(self) -> None:
        """For text search, vector_weight should be discarded (not reach compiler)."""
        client, fake_db, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "text", "vector_weight": 0.9},
        )
        assert resp.status_code == 200
        dsl = fake_db.search_calls[0]["dsl"]
        # text DSL must NOT contain function_score (weight would appear there)
        assert "function_score" not in str(dsl)

    def test_effective_vector_model_from_binding(self) -> None:
        """The binding's vector_model must be used even when caller omits it."""
        client, _, fake_vec = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        _, model_used = fake_vec.embed_calls[0]
        assert model_used == VECTOR_MODEL

    def test_index_used_is_from_binding(self) -> None:
        client, fake_db, _ = make_client()
        client.post("/api/search/knowledge-base", json=BASE_BODY)
        assert fake_db.search_calls[0]["index"] == KB_INDEX


# ──────────────────────────────────────────────────────────────────────────────
# 4. HTTP input validation (API layer)
# ──────────────────────────────────────────────────────────────────────────────


class TestInputValidation:
    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query_422(self, query: str) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base", json={"query": query, "tag": "design"}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("tag", ["", "   "])
    def test_empty_tag_422(self, tag: str) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base", json={"query": "q", "tag": tag}
        )
        assert resp.status_code == 422

    def test_top_k_zero_422(self) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base", json={**BASE_BODY, "top_k": 0}
        )
        assert resp.status_code == 422

    def test_top_k_exceeds_max_400(self) -> None:
        cfg = SearchConfig(max_top_k=20)
        client, _, _ = make_client(search_cfg=cfg)
        resp = client.post(
            "/api/search/knowledge-base", json={**BASE_BODY, "top_k": 999}
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_ARGUMENT"

    def test_vector_weight_out_of_range_422(self) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "vector_weight": 1.5},
        )
        assert resp.status_code == 422

    def test_unknown_search_type_400(self) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "bm25_fuzzy"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "SEARCH_TYPE_INVALID"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Business errors from the service / searcher layers
# ──────────────────────────────────────────────────────────────────────────────


class TestBusinessErrors:
    def test_binding_not_found_404(self) -> None:
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=None))
        resp = client.post("/api/search/knowledge-base", json=BASE_BODY)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "INDEX_NOT_BOUND"

    def test_vector_model_conflict_409(self) -> None:
        client, _, _ = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "vector_model": "other/model"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "VECTOR_MODEL_CONFLICT"
        detail = resp.json()["detail"]["message"]
        assert "other/model" in detail
        assert VECTOR_MODEL in detail

    def test_bad_profile_422(self) -> None:
        """A binding with an invalid (empty term_fields) profile must yield 422."""
        bad_profile: dict[str, Any] = {
            "search_type_profile": {
                "keyword": {"enabled": True, "term_fields": []}  # empty → error
            }
        }
        bad_binding = IndexBinding(
            domain_type="KNOWLEDGE_BASE",
            kb_index=KB_INDEX,
            tag="design",
            parser_script_source="",
            parser_script_sha256="",
            vector_model=None,
            search_profile_json=bad_profile,
            search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=bad_binding))
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "keyword"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_missing_search_type_in_profile_422(self) -> None:
        """If the profile has no entry for the requested search_type, 422."""
        partial_profile: dict[str, Any] = {
            "search_type_profile": {
                "text": {
                    "enabled": True,
                    "fields": [{"field": "content", "weight": 1.0}],
                }
                # "keyword" intentionally absent
            }
        }
        binding = IndexBinding(
            domain_type="KNOWLEDGE_BASE",
            kb_index=KB_INDEX,
            tag="design",
            parser_script_source="",
            parser_script_sha256="",
            vector_model=None,
            search_profile_json=partial_profile,
            search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=binding))
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "keyword"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_disabled_search_type_in_profile_422(self) -> None:
        profile: dict[str, Any] = {
            "search_type_profile": {
                "text": {"enabled": False, "fields": [{"field": "content", "weight": 1.0}]}
            }
        }
        binding = IndexBinding(
            domain_type="KNOWLEDGE_BASE",
            kb_index=KB_INDEX,
            tag="design",
            parser_script_source="",
            parser_script_sha256="",
            vector_model=None,
            search_profile_json=profile,
            search_profile_sha256="",
        )
        client, _, _ = make_client(db_writer=FakeDBWriter(binding=binding))
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "text"},
        )
        assert resp.status_code == 422

    def test_db_exception_500(self) -> None:
        db = FakeDBWriter(search_side_effect=RuntimeError("connection refused"))
        client, _, _ = make_client(db_writer=db)
        resp = client.post("/api/search/knowledge-base", json=BASE_BODY)
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"
        # Internal details must NOT be exposed
        assert "connection refused" not in resp.json()["detail"]["message"]

    def test_vector_embed_exception_500(self) -> None:
        vec = FakeVectorTool(embed_side_effect=RuntimeError("GPU OOM"))
        client, _, _ = make_client(vector_tool=vec)
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"

    def test_vector_search_without_binding_model_422(self) -> None:
        """vector search with a binding that has no vector_model → 422."""
        client, _, _ = make_client(
            db_writer=FakeDBWriter(binding=BINDING_NO_VECTOR)
        )
        resp = client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"


# ──────────────────────────────────────────────────────────────────────────────
# 6. DSL correctness spot-checks (real compiler rules applied)
# ──────────────────────────────────────────────────────────────────────────────


class TestDslCorrectness:
    def test_keyword_term_value_equals_query(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "query": "SrVariablePeriodicityMgt", "search_type": "keyword"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        term_clause = dsl["query"]["term"]
        assert term_clause["title.keyword"]["value"] == "SrVariablePeriodicityMgt"

    def test_text_multi_match_contains_query(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "query": "memory management", "search_type": "text"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        assert dsl["query"]["multi_match"]["query"] == "memory management"

    def test_text_fields_have_boost(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "text"},
        )
        fields = fake_db.search_calls[0]["dsl"]["query"]["multi_match"]["fields"]
        assert any("^" in f for f in fields)

    def test_vector_dsl_contains_query_vector(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector"},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        knn_vec = dsl["query"]["knn"]["content_vector"]["vector"]
        assert knn_vec == DUMMY_VECTOR

    def test_hybrid_dsl_knn_arm_uses_profile_vector_field(self) -> None:
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "hybrid"},
        )
        dsl_str = str(fake_db.search_calls[0]["dsl"])
        assert "content_vector" in dsl_str

    def test_num_candidates_not_below_min(self) -> None:
        """top_k=2, min=100 → num_candidates must be ≥ 100."""
        client, fake_db, _ = make_client()
        client.post(
            "/api/search/knowledge-base",
            json={**BASE_BODY, "search_type": "vector", "top_k": 2},
        )
        dsl = fake_db.search_calls[0]["dsl"]
        knn = dsl["query"]["knn"]["content_vector"]
        assert knn["num_candidates"] >= 100
