"""Unit / API-layer tests for POST /api/search/skill.

Strategy
--------
The FastAPI app is created with ``app.dependency_overrides`` that replace
``get_skill_search_service`` and ``get_search_cfg`` with lightweight fakes,
so these tests exercise the API route (validation, error mapping, response
shape) without touching real infrastructure.

Coverage matches the task-C test plan:
  success path, response shape, Pydantic 422 errors, tag validation,
  top_k / search_type / vector_weight validation, service-exception mapping.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bible.api.deps import get_skill_search_service, get_search_cfg
from bible.api.search import search_router
from bible.config.configure import SearchConfig
from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.features.search.skill_search.skill_search_service import (
    IndexNotBoundError,
    SkillSearchService,
    VectorModelConflictError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fakes & fixtures
# ──────────────────────────────────────────────────────────────────────────────

KB_INDEX = "kb_skill_main"

FAKE_RESPONSE: dict[str, Any] = {
    "success": True,
    "domain": "SKILL",
    "kb_index": KB_INDEX,
    "tag": "skill",
    "total": 2,
    "results": {
        "skill": [
            {"doc_id": "skill_001", "name": "k8s-log-cleaner", "score": 0.91},
            {"doc_id": "skill_002", "name": "oom-killer-guard", "score": 0.71},
        ]
    },
}


class FakeSkillSearchService:
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
    fake_svc: FakeSkillSearchService | None = None,
    cfg: SearchConfig | None = None,
) -> tuple[FastAPI, FakeSkillSearchService]:
    svc = fake_svc or FakeSkillSearchService()
    effective_cfg = cfg or _DEFAULT_CFG
    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_skill_search_service] = lambda: svc
    app.dependency_overrides[get_search_cfg] = lambda: effective_cfg
    return app, svc


def _client(
    fake_svc: FakeSkillSearchService | None = None,
    cfg: SearchConfig | None = None,
) -> tuple[TestClient, FakeSkillSearchService]:
    app, svc = _make_app(fake_svc, cfg)
    return TestClient(app, raise_server_exceptions=False), svc


def _post(client: TestClient, **overrides: Any) -> Any:
    body: dict[str, Any] = {"query": "k8s log cleaner script", "tag": "skill"}
    body.update(overrides)
    return client.post("/api/search/skill", json=body)


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
        assert data["domain"] == "SKILL"
        assert data["kb_index"] == KB_INDEX
        assert data["tag"] == "skill"
        assert "total" in data
        assert "skill" in data["results"]

    def test_optional_fields_omitted(self) -> None:
        """All optional fields absent → 200."""
        client, _ = _client()
        resp = client.post("/api/search/skill", json={"query": "q", "tag": "skill"})
        assert resp.status_code == 200

    def test_all_optional_fields_sent(self) -> None:
        client, _ = _client()
        resp = _post(
            client,
            search_type="hybrid",
            top_k=5,
            vector_model="BAAI/bge-base-zh-v1.5",
            vector_weight=0.5,
        )
        assert resp.status_code == 200

    def test_service_receives_correct_params(self) -> None:
        client, svc = _client()
        _post(client, search_type="text", top_k=3, kb_index=KB_INDEX)
        call = svc.calls[0]
        assert call["query"] == "k8s log cleaner script"
        assert call["tag"] == "skill"
        assert call["kb_index"] == KB_INDEX
        assert call["search_type"] == "text"
        assert call["top_k"] == 3

    def test_kb_index_forwarded_to_service(self) -> None:
        client, svc = _client()
        _post(client, kb_index="kb_skill_alt")
        assert svc.calls[0]["kb_index"] == "kb_skill_alt"

    def test_kb_index_none_when_omitted(self) -> None:
        client, svc = _client()
        _post(client)
        assert svc.calls[0]["kb_index"] is None

    def test_results_contain_skill_key(self) -> None:
        client, _ = _client()
        data = _post(client).json()
        assert "skill" in data["results"]
        assert isinstance(data["results"]["skill"], list)


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

    def test_missing_query_422(self) -> None:
        client, _ = _client()
        resp = client.post("/api/search/skill", json={"tag": "skill"})
        assert resp.status_code == 422

    def test_missing_tag_422(self) -> None:
        client, _ = _client()
        resp = client.post("/api/search/skill", json={"query": "something"})
        assert resp.status_code == 422

    def test_empty_kb_index_422(self) -> None:
        """kb_index provided as empty string must be rejected by Pydantic validator."""
        client, _ = _client()
        resp = _post(client, kb_index="")
        assert resp.status_code == 422

    def test_whitespace_kb_index_422(self) -> None:
        """kb_index provided as whitespace string must be rejected."""
        client, _ = _client()
        resp = _post(client, kb_index="   ")
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tag validation (400 TAG_INVALID)
# ──────────────────────────────────────────────────────────────────────────────


class TestTagValidation:
    def test_wrong_tag_400_tag_invalid(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="knowledge")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_tag_memory_rejected(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="memory")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_tag_case_sensitive_capital_s(self) -> None:
        """'Skill' (capital S) must be rejected."""
        client, _ = _client()
        resp = _post(client, tag="Skill")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_tag_all_uppercase_rejected(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="SKILL")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "TAG_INVALID"

    def test_correct_tag_passes(self) -> None:
        client, _ = _client()
        resp = _post(client, tag="skill")
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 4. search_type and top_k business validation (400)
# ──────────────────────────────────────────────────────────────────────────────


class TestBusinessValidation:
    def test_unknown_search_type_400(self) -> None:
        client, _ = _client()
        resp = _post(client, search_type="bm25_fuzz")
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

    def test_search_type_none_passes(self) -> None:
        """Omitting search_type is valid; service defaults to 'text'."""
        client, _ = _client()
        resp = _post(client)
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 5. Service exception → HTTP status mapping
# ──────────────────────────────────────────────────────────────────────────────


class TestServiceExceptionMapping:
    def test_index_not_bound_404(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = IndexNotBoundError("skill")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "INDEX_NOT_BOUND"

    def test_vector_model_conflict_409(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = VectorModelConflictError("req/model", "bound/model")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "VECTOR_MODEL_CONFLICT"

    def test_search_profile_invalid_422(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = SearchProfileInvalidError("missing term_fields")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "SEARCH_PROFILE_INVALID"

    def test_internal_error_500(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = SearchInternalError("db down")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "INTERNAL_ERROR"

    def test_internal_error_message_not_exposed(self) -> None:
        """Internal detail must NOT leak into the response body."""
        svc = FakeSkillSearchService()
        svc.side_effect = SearchInternalError("secret db host: db.internal:9200")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert "db.internal" not in resp.text
        assert "secret" not in resp.text

    def test_index_not_bound_message_contains_tag(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = IndexNotBoundError("skill")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert "skill" in resp.json()["detail"]["message"]

    def test_vector_model_conflict_message_contains_models(self) -> None:
        svc = FakeSkillSearchService()
        svc.side_effect = VectorModelConflictError("requested-model", "bound-model")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        msg = resp.json()["detail"]["message"]
        assert "requested-model" in msg
        assert "bound-model" in msg

    def test_service_raises_http_exception_passed_through(self) -> None:
        """If service somehow raises an HTTPException it must not be double-wrapped."""
        from fastapi import HTTPException as _HTTPException
        svc = FakeSkillSearchService()
        svc.side_effect = _HTTPException(status_code=418, detail="teapot")
        client, _ = _client(fake_svc=svc)
        resp = _post(client)
        assert resp.status_code == 418
