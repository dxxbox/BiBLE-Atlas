"""Unit / API-layer tests for POST /api/search/memory.

Strategy
--------
The FastAPI app is created with ``app.dependency_overrides`` that replace
``get_memory_search_service`` and ``get_search_cfg`` with lightweight fakes,
so these tests exercise the API route (validation, error mapping, response
shape) without touching real infrastructure.

Coverage matches the task-B test plan:
  success path, response shape, Pydantic 422 errors, tag validation,
  top_k / search_type / vector_weight validation, service-exception mapping.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bible.api.deps import get_memory_search_service, get_search_cfg
from bible.api.search import search_router
from bible.config.configure import SearchConfig
from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.features.search.memory_search.memory_search_service import (
    IndexNotBoundError,
    MemorySearchService,
    VectorModelConflictError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fakes & fixtures
# ──────────────────────────────────────────────────────────────────────────────

KB_INDEX = "kb_memory_main"

FAKE_RESPONSE: dict[str, Any] = {
    "success": True,
    "domain": "MEMORY",
    "kb_index": KB_INDEX,
    "tag": "memory",
    "total": 1,
    "results": {"memory": [{"doc_id": "mem_001", "score": 0.9}]},
}


class FakeMemorySearchService:
    """Controllable service stub.

    Set ``side_effect`` to an exception instance to make ``search()`` raise it.
    """

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response or FAKE_RESPONSE
        self.side_effect: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.side_effect is not None:
            raise self.side_effect
        return self._response


_DEFAULT_CFG = SearchConfig(
    default_top_k=10,
    max_top_k=50,
    allowed_search_types=["keyword", "title", "text", "vector", "hybrid"],
)


def _make_app(
    fake_svc: FakeMemorySearchService | None = None,
    cfg: SearchConfig | None = None,
) -> tuple[FastAPI, FakeMemorySearchService]:
    svc = fake_svc or FakeMemorySearchService()
    effective_cfg = cfg or _DEFAULT_CFG
    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_memory_search_service] = lambda: svc
    app.dependency_overrides[get_search_cfg] = lambda: effective_cfg
    return app, svc


def _client(
    fake_svc: FakeMemorySearchService | None = None,
    cfg: SearchConfig | None = None,
) -> tuple[TestClient, FakeMemorySearchService]:
    app, svc = _make_app(fake_svc, cfg)
    return TestClient(app, raise_server_exceptions=False), svc


def _post(client: TestClient, **overrides: Any) -> Any:
    body: dict[str, Any] = {"query": "CNI race condition", "tag": "memory"}
    body.update(overrides)
    return client.post("/api/search/memory", json=body)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Success path
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessPath:
    def test_success_200(self) -> None:
        client, _ = _client()
        resp = _post(client)
        assert resp.status_code == 200

    def test_response_shape(self) -> None:
        client, _ = _client()
        resp = _post(client)
        data = resp.json()
        assert data["success"] is True
        assert data["domain"] == "MEMORY"
        assert data["kb_index"] == KB_INDEX
        assert data["tag"] == "memory"
        assert "total" in data
        assert "memory" in data["results"]

    def test_optional_fields_omitted(self) -> None:
        """All optional fields absent → 200."""
        client, _ = _client()
        resp = client.post("/api/search/memory", json={"query": "q", "tag": "memory"})
        assert resp.status_code == 200

    def test_all_optional_fields_sent(self) -> None:
        client, _ = _client()
        resp = _post(
            client,
            search_type="hybrid",
            top_k=5,
            vector_model="BAAI/bge-base",
            vector_weight=0.7,
        )
        assert resp.status_code == 200

    def test_service_receives_correct_params(self) -> None:
        client, svc = _client()
        _post(client, search_type="text", top_k=3, kb_index=KB_INDEX)
        assert svc.calls[0]["query"] == "CNI race condition"
        assert svc.calls[0]["tag"] == "memory"
        assert svc.calls[0]["kb_index"] == KB_INDEX
        assert svc.calls[0]["search_type"] == "text"
        assert svc.calls[0]["top_k"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# 2. Pydantic 422 validation
# ──────────────────────────────────────────────────────────────────────────────


class TestPydantic422:
    def test_empty_query_422(self) -> None:
        client, _ = _client()
        resp = _post(client, query="")
        assert resp.status_code == 422

    def test_whitespace_query_422(self) -> None:
        client, _ = _client()
        resp = _post(client, query="   ")
        assert resp.status_code == 422

    def test_empty_tag_422(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="")
        assert resp.status_code == 422

    def test_top_k_zero_422(self) -> None:
        client, _ = _client()
        resp = _post(client, top_k=0)
        assert resp.status_code == 422

    def test_invalid_vector_weight_too_high_422(self) -> None:
        client, _ = _client()
        resp = _post(client, vector_weight=1.5)
        assert resp.status_code == 422

    def test_invalid_vector_weight_negative_422(self) -> None:
        client, _ = _client()
        resp = _post(client, vector_weight=-0.1)
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tag validation (400 TAG_INVALID)
# ──────────────────────────────────────────────────────────────────────────────


class TestTagValidation:
    def test_wrong_tag_400_tag_invalid(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="skill")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_wrong_tag_case_sensitive(self) -> None:
        """'Memory' (capital M) is not the same as 'memory'."""
        client, _ = _client()
        resp = _post(client, tag="Memory")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_wrong_tag_uppercase(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="MEMORY")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_correct_tag_passes(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="memory")
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 4. search_type and top_k business validation (400)
# ──────────────────────────────────────────────────────────────────────────────


class TestBusinessValidation:
    def test_unknown_search_type_400(self) -> None:
        client, _ = _client()
        resp = _post(client, search_type="fuzzy_bm25")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "SEARCH_TYPE_INVALID"

    def test_top_k_exceeds_max_400(self) -> None:
        cfg = SearchConfig(default_top_k=10, max_top_k=20)
        client, _ = _client(cfg=cfg)
        resp = _post(client, top_k=999)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_ARGUMENT"

    def test_top_k_at_max_passes(self) -> None:
        cfg = SearchConfig(default_top_k=10, max_top_k=20)
        client, _ = _client(cfg=cfg)
        resp = _post(client, top_k=20)
        assert resp.status_code == 200

    def test_valid_search_types_pass(self) -> None:
        for st in ("keyword", "title", "text", "vector", "hybrid"):
            client, _ = _client()
            resp = _post(client, search_type=st)
            assert resp.status_code == 200, f"Expected 200 for search_type={st!r}"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Service exception → HTTP status mapping
# ──────────────────────────────────────────────────────────────────────────────


class TestServiceExceptionMapping:
    def test_index_not_bound_404(self) -> None:
        svc = FakeMemorySearchService()
        svc.side_effect = IndexNotBoundError("memory")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "INDEX_NOT_BOUND"

    def test_vector_model_conflict_409(self) -> None:
        svc = FakeMemorySearchService()
        svc.side_effect = VectorModelConflictError("req/model", "bound/model")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "VECTOR_MODEL_CONFLICT"

    def test_search_profile_invalid_422(self) -> None:
        svc = FakeMemorySearchService()
        svc.side_effect = SearchProfileInvalidError("bad profile")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_internal_error_500(self) -> None:
        svc = FakeMemorySearchService()
        svc.side_effect = SearchInternalError("db down")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"

    def test_internal_error_message_not_exposed(self) -> None:
        """Internal detail must NOT leak into the response body."""
        svc = FakeMemorySearchService()
        svc.side_effect = SearchInternalError("secret db host: db.internal:9200")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert "db.internal" not in resp.text
        assert "secret" not in resp.text

    def test_index_not_bound_message_contains_tag(self) -> None:
        svc = FakeMemorySearchService()
        svc.side_effect = IndexNotBoundError("memory")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert "memory" in resp.json()["detail"]["message"]
