"""Unit tests for KnowledgeBaseSearchAPI (Task K).

Strategy
--------
- Create a minimal FastAPI app that includes only the KB search router.
- Use ``app.dependency_overrides`` to inject:
    * a ``FakeService`` instead of the real KnowledgeBaseSearchService
    * a ``FakeSearchConfig`` to control max_top_k / allowed_search_types
- Use ``httpx.Client`` with ``transport=ASGITransport`` (TestClient equivalent
  for the installed httpx/starlette versions) to send requests.

Coverage
--------
- 200: success path, response shape.
- 400 INVALID_ARGUMENT: empty query, top_k out of range.
- 400 SEARCH_TYPE_INVALID: unknown search_type.
- 404 INDEX_NOT_BOUND: service raises IndexNotBoundError.
- 409 VECTOR_MODEL_CONFLICT: service raises VectorModelConflictError.
- 422 SEARCH_PROFILE_INVALID: service raises SearchProfileInvalidError.
- 500 INTERNAL_ERROR: service raises SearchInternalError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bible.api.deps import get_kb_search_service, get_search_cfg
from bible.api.search import search_router
from bible.config.configure import SearchConfig
from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
    IndexNotBoundError,
    KnowledgeBaseSearchService,
    VectorModelConflictError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared test data
# ──────────────────────────────────────────────────────────────────────────────

SUCCESS_RESPONSE: dict[str, Any] = {
    "success": True,
    "domain": "KNOWLEDGE_BASE",
    "kb_index": "kb_design_main",
    "tag": "design",
    "total": 1,
    "results": {
        "knowledge_base": [
            {"doc_id": "abc#1", "title": "Scheduler", "score": 0.87}
        ]
    },
}

VALID_BODY: dict[str, Any] = {
    "query": "scheduler",
    "tag": "design",
}

# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeService:
    """Configurable stub for KnowledgeBaseSearchService."""

    response: dict[str, Any] = field(default_factory=lambda: SUCCESS_RESPONSE)
    side_effect: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.side_effect is not None:
            raise self.side_effect
        return self.response


# ──────────────────────────────────────────────────────────────────────────────
# App fixture factory
# ──────────────────────────────────────────────────────────────────────────────


def make_client(
    fake_svc: FakeService | None = None,
    search_cfg: SearchConfig | None = None,
) -> TestClient:
    """Return a TestClient with dependency overrides applied."""
    app = FastAPI()
    app.include_router(search_router)

    cfg = search_cfg or SearchConfig(
        default_top_k=10,
        max_top_k=50,
        allowed_search_types=["keyword", "title", "text", "vector", "hybrid"],
    )
    svc = fake_svc or FakeService()

    app.dependency_overrides[get_search_cfg] = lambda: cfg
    app.dependency_overrides[get_kb_search_service] = lambda: svc

    return TestClient(app, raise_server_exceptions=False)


# ──────────────────────────────────────────────────────────────────────────────
# Success path
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessPath:
    def test_200_status(self) -> None:
        client = make_client()
        resp = client.post("/api/search/knowledge-base", json=VALID_BODY)
        assert resp.status_code == 200

    def test_response_shape(self) -> None:
        client = make_client()
        resp = client.post("/api/search/knowledge-base", json=VALID_BODY)
        body = resp.json()
        assert body["success"] is True
        assert body["domain"] == "KNOWLEDGE_BASE"
        assert body["kb_index"] == "kb_design_main"
        assert body["tag"] == "design"
        assert body["total"] == 1
        assert "knowledge_base" in body["results"]

    def test_optional_fields_accepted(self) -> None:
        client = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={
                **VALID_BODY,
                "search_type": "text",
                "top_k": 5,
                "vector_model": "BAAI/bge",
                "vector_weight": 0.6,
            },
        )
        assert resp.status_code == 200

    def test_service_receives_kb_index(self) -> None:
        svc = FakeService()
        client = make_client(fake_svc=svc)
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "kb_index": "kb_design_main"},
        )
        assert resp.status_code == 200
        assert svc.calls[0]["kb_index"] == "kb_design_main"


# ──────────────────────────────────────────────────────────────────────────────
# 400 INVALID_ARGUMENT — bad query / top_k
# ──────────────────────────────────────────────────────────────────────────────


class TestInvalidArgument:
    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query_400(self, query: str) -> None:
        client = make_client()
        resp = client.post(
            "/api/search/knowledge-base", json={"query": query, "tag": "design"}
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_top_k_exceeds_max_400(self) -> None:
        client = make_client(search_cfg=SearchConfig(max_top_k=50))
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "top_k": 999},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_ARGUMENT"

    def test_top_k_zero_rejected_by_pydantic(self) -> None:
        client = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "top_k": 0},
        )
        assert resp.status_code == 422  # ge=1 constraint

    def test_vector_weight_out_of_range_rejected_by_pydantic(self) -> None:
        client = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "vector_weight": 1.5},
        )
        assert resp.status_code == 422  # le=1.0 constraint


# ──────────────────────────────────────────────────────────────────────────────
# 400 SEARCH_TYPE_INVALID
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchTypeInvalid:
    def test_unknown_search_type_400(self) -> None:
        client = make_client()
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "search_type": "fuzzy"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "SEARCH_TYPE_INVALID"

    def test_known_search_type_passes(self) -> None:
        client = make_client()
        for stype in ["keyword", "title", "text", "vector", "hybrid"]:
            resp = client.post(
                "/api/search/knowledge-base",
                json={**VALID_BODY, "search_type": stype},
            )
            assert resp.status_code == 200, f"Unexpected error for search_type={stype}"


# ──────────────────────────────────────────────────────────────────────────────
# 404 INDEX_NOT_BOUND
# ──────────────────────────────────────────────────────────────────────────────


class TestIndexNotBound:
    def test_404_when_no_binding(self) -> None:
        svc = FakeService(side_effect=IndexNotBoundError("unknown"))
        client = make_client(fake_svc=svc)
        resp = client.post("/api/search/knowledge-base", json=VALID_BODY)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "INDEX_NOT_BOUND"


# ──────────────────────────────────────────────────────────────────────────────
# 409 VECTOR_MODEL_CONFLICT
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorModelConflict:
    def test_409_on_model_conflict(self) -> None:
        svc = FakeService(
            side_effect=VectorModelConflictError("other/model", "BAAI/bge")
        )
        client = make_client(fake_svc=svc)
        resp = client.post(
            "/api/search/knowledge-base",
            json={**VALID_BODY, "vector_model": "other/model"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "VECTOR_MODEL_CONFLICT"


# ──────────────────────────────────────────────────────────────────────────────
# 422 SEARCH_PROFILE_INVALID
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchProfileInvalid:
    def test_422_on_bad_profile(self) -> None:
        svc = FakeService(side_effect=SearchProfileInvalidError("bad profile"))
        client = make_client(fake_svc=svc)
        resp = client.post("/api/search/knowledge-base", json=VALID_BODY)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"


# ──────────────────────────────────────────────────────────────────────────────
# 500 INTERNAL_ERROR
# ──────────────────────────────────────────────────────────────────────────────


class TestInternalError:
    def test_500_on_internal_error(self) -> None:
        svc = FakeService(side_effect=SearchInternalError("db down"))
        client = make_client(fake_svc=svc)
        resp = client.post("/api/search/knowledge-base", json=VALID_BODY)
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"
