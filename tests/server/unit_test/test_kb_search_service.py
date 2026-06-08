"""Unit tests for KnowledgeBaseSearchService (Task J).

Strategy
--------
- ``FakeDBFactory``   — returns a ``FakeDBWriter`` from ``get_writer()``.
- ``FakeDBWriter``    — implements IDatabaseWriter; ``get_binding_by_domain_tag``
                       is configurable per test.
- ``FakeSearcher``    — replaces KnowledgeBaseSearcher; records call args.
- ``FakeVectorTool``  — stub (never called by the Service directly).

Coverage
--------
- Success path: full response shape, field values.
- Binding absent → IndexNotBoundError.
- vector_model conflict → VectorModelConflictError.
- Empty query / tag → InvalidArgumentError.
- top_k normalisation (None → default, over max → clamp).
- search_type normalisation (None → "text").
- effective_vector_model comes from binding, not from caller.
- SearchProfileInvalidError / SearchInternalError propagated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from bible.config.configure import SearchConfig
from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
    IndexNotBoundError,
    KnowledgeBaseSearchService,
    VectorModelConflictError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    KnowledgeBaseSearcher,
    SearchInternalError,
)
from bible.infrastructure.database.types import DomainType, IndexBinding

# ──────────────────────────────────────────────────────────────────────────────
# Shared test data
# ──────────────────────────────────────────────────────────────────────────────

KB_INDEX = "kb_design_main"
TAG = "design"
VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"

SAMPLE_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "text": {
            "enabled": True,
            "fields": [{"field": "content", "weight": 1.0}],
        }
    },
    "response_fields": ["doc_id", "title", "content", "score"],
}

SAMPLE_BINDING = IndexBinding(
    domain_type="KNOWLEDGE_BASE",
    kb_index=KB_INDEX,
    tag=TAG,
    parser_script_source="",
    parser_script_sha256="",
    vector_model=VECTOR_MODEL,
    search_profile_json=SAMPLE_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

SAMPLE_SEARCH_RESULT: dict[str, Any] = {
    "kb_index": KB_INDEX,
    "total": 2,
    "items": [
        {"doc_id": "abc#1", "title": "Scheduler", "content": "...", "score": 0.87},
        {"doc_id": "abc#2", "title": "Memory",    "content": "...", "score": 0.72},
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeDBWriter:
    """Configurable stub for IDatabaseWriter."""

    def __init__(self, binding: IndexBinding | None = SAMPLE_BINDING) -> None:
        self._binding = binding
        self.binding_lookup_calls: list[tuple[str, str]] = []
        self.binding_index_lookup_calls: list[tuple[str, str]] = []

    def get_binding_by_domain_tag(
        self, domain: DomainType, tag: str
    ) -> IndexBinding | None:
        self.binding_lookup_calls.append((domain, tag))
        return self._binding

    # ── Protocol stubs (no-op) ─────────────────────────────────────────
    def get_binding_by_domain_index(
        self, domain: DomainType, kb_index: str
    ) -> IndexBinding | None:
        self.binding_index_lookup_calls.append((domain, kb_index))
        return self._binding

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

    def search_content_docs(self, *a: Any, **kw: Any) -> dict[str, Any]:
        return {"total": 0, "hits": []}


class FakeDBFactory:
    """Stub for DatabaseFactory."""

    def __init__(self, writer: FakeDBWriter) -> None:
        self._writer = writer
        self.get_writer_calls: list[str] = []

    def get_writer(self, domain: str) -> FakeDBWriter:
        self.get_writer_calls.append(domain)
        return self._writer


class FakeVectorTool:
    """Stub — Service never calls VectorTool directly."""


@dataclass
class FakeSearcher:
    """Configurable stub for KnowledgeBaseSearcher."""

    result: dict[str, Any] = field(default_factory=lambda: SAMPLE_SEARCH_RESULT)
    side_effect: Exception | None = None
    call_args: dict[str, Any] = field(default_factory=dict)

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.call_args = kwargs
        if self.side_effect is not None:
            raise self.side_effect
        return self.result


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_writer() -> FakeDBWriter:
    return FakeDBWriter()


@pytest.fixture
def fake_factory(fake_writer: FakeDBWriter) -> FakeDBFactory:
    return FakeDBFactory(fake_writer)


@pytest.fixture
def fake_searcher() -> FakeSearcher:
    return FakeSearcher()


@pytest.fixture
def search_cfg() -> SearchConfig:
    return SearchConfig(default_top_k=10, max_top_k=50)


@pytest.fixture
def svc(
    fake_factory: FakeDBFactory,
    fake_searcher: FakeSearcher,
    search_cfg: SearchConfig,
) -> KnowledgeBaseSearchService:
    return KnowledgeBaseSearchService(
        db_factory=fake_factory,  # type: ignore[arg-type]
        vector_tool=FakeVectorTool(),  # type: ignore[arg-type]
        search_cfg=search_cfg,
        searcher=fake_searcher,  # type: ignore[arg-type]
    )


# ──────────────────────────────────────────────────────────────────────────────
# Success path
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessPath:
    def test_response_shape(self, svc: KnowledgeBaseSearchService) -> None:
        resp = svc.search(
            query="scheduler",
            tag=TAG,
            search_type="text",
            top_k=5,
            vector_model=None,
            vector_weight=None,
        )
        assert resp["success"] is True
        assert resp["domain"] == "KNOWLEDGE_BASE"
        assert resp["kb_index"] == KB_INDEX
        assert resp["tag"] == TAG
        assert resp["total"] == 2
        assert "knowledge_base" in resp["results"]
        assert len(resp["results"]["knowledge_base"]) == 2

    def test_get_writer_called_with_knowledge_base_domain(
        self,
        svc: KnowledgeBaseSearchService,
        fake_factory: FakeDBFactory,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert fake_factory.get_writer_calls == ["KNOWLEDGE_BASE"]

    def test_binding_lookup_uses_correct_tag(
        self,
        svc: KnowledgeBaseSearchService,
        fake_writer: FakeDBWriter,
    ) -> None:
        svc.search(query="q", tag="flow", search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert ("KNOWLEDGE_BASE", "flow") in fake_writer.binding_lookup_calls

    def test_binding_lookup_can_use_explicit_kb_index(
        self,
        svc: KnowledgeBaseSearchService,
        fake_writer: FakeDBWriter,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None, kb_index=KB_INDEX)
        assert fake_writer.binding_index_lookup_calls == [("KNOWLEDGE_BASE", KB_INDEX)]
        assert fake_writer.binding_lookup_calls == []

    def test_items_in_results(
        self, svc: KnowledgeBaseSearchService
    ) -> None:
        resp = svc.search(query="q", tag=TAG, search_type="text", top_k=5,
                          vector_model=None, vector_weight=None)
        first = resp["results"]["knowledge_base"][0]
        assert first["doc_id"] == "abc#1"
        assert first["score"] == pytest.approx(0.87)


# ──────────────────────────────────────────────────────────────────────────────
# Parameter normalisation
# ──────────────────────────────────────────────────────────────────────────────


class TestNormalisation:
    def test_search_type_defaults_to_text(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["search_type"] == "text"

    def test_top_k_defaults_when_none(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
        search_cfg: SearchConfig,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["top_k"] == search_cfg.default_top_k

    def test_top_k_clamped_to_max(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
        search_cfg: SearchConfig,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=9999,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["top_k"] == search_cfg.max_top_k

    def test_top_k_within_max_passes_through(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=7,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["top_k"] == 7

    def test_effective_vector_model_comes_from_binding(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        """Even when caller passes no vector_model, the binding's model is used."""
        svc.search(query="q", tag=TAG, search_type="vector", top_k=5,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["vector_model"] == VECTOR_MODEL

    def test_vector_weight_passed_through_for_hybrid(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type="hybrid", top_k=5,
                   vector_model=None, vector_weight=0.7)
        assert fake_searcher.call_args["vector_weight"] == pytest.approx(0.7)

    def test_vector_weight_defaults_from_profile_when_none_and_hybrid(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        """When vector_weight is omitted for hybrid, the profile default is used."""
        svc.search(query="q", tag=TAG, search_type="hybrid", top_k=5,
                   vector_model=None, vector_weight=None)
        # SAMPLE_PROFILE has no hybrid.default_vector_weight → falls back to 0.6
        assert fake_searcher.call_args["vector_weight"] == pytest.approx(0.6)

    def test_vector_weight_none_for_non_vector_types(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        """For keyword/title/text the normalised weight should always be None."""
        for stype in ("keyword", "title", "text"):
            svc.search(query="q", tag=TAG, search_type=stype, top_k=5,
                       vector_model=None, vector_weight=0.9)
            assert fake_searcher.call_args["vector_weight"] is None, (
                f"Expected None for search_type={stype}"
            )

    def test_search_profile_from_binding(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["search_profile"] == SAMPLE_PROFILE

    def test_kb_index_from_binding(
        self,
        svc: KnowledgeBaseSearchService,
        fake_searcher: FakeSearcher,
    ) -> None:
        svc.search(query="q", tag=TAG, search_type=None, top_k=None,
                   vector_model=None, vector_weight=None)
        assert fake_searcher.call_args["kb_index"] == KB_INDEX


# ──────────────────────────────────────────────────────────────────────────────
# Error: missing binding
# ──────────────────────────────────────────────────────────────────────────────


class TestIndexNotBound:
    def test_raises_index_not_bound_when_no_binding(
        self, fake_factory: FakeDBFactory, search_cfg: SearchConfig
    ) -> None:
        writer = FakeDBWriter(binding=None)
        factory = FakeDBFactory(writer)
        svc = KnowledgeBaseSearchService(
            db_factory=factory,  # type: ignore[arg-type]
            vector_tool=FakeVectorTool(),  # type: ignore[arg-type]
            search_cfg=search_cfg,
        )
        with pytest.raises(IndexNotBoundError) as exc_info:
            svc.search(query="q", tag="unknown_tag", search_type=None,
                       top_k=None, vector_model=None, vector_weight=None)
        assert exc_info.value.tag == "unknown_tag"


# ──────────────────────────────────────────────────────────────────────────────
# Error: vector model conflict
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorModelConflict:
    def test_raises_when_models_differ(
        self, svc: KnowledgeBaseSearchService
    ) -> None:
        with pytest.raises(VectorModelConflictError) as exc_info:
            svc.search(
                query="q",
                tag=TAG,
                search_type="vector",
                top_k=5,
                vector_model="other/model",   # differs from binding's VECTOR_MODEL
                vector_weight=None,
            )
        assert exc_info.value.requested == "other/model"
        assert exc_info.value.bound == VECTOR_MODEL

    def test_no_conflict_when_model_matches_binding(
        self, svc: KnowledgeBaseSearchService
    ) -> None:
        # Should not raise
        svc.search(
            query="q",
            tag=TAG,
            search_type="vector",
            top_k=5,
            vector_model=VECTOR_MODEL,   # same as binding
            vector_weight=None,
        )

    def test_no_conflict_when_caller_omits_model(
        self, svc: KnowledgeBaseSearchService
    ) -> None:
        # caller passes None → no assertion, binding's model is used silently
        svc.search(query="q", tag=TAG, search_type="vector", top_k=5,
                   vector_model=None, vector_weight=None)

    def test_no_conflict_when_binding_has_no_model(
        self, search_cfg: SearchConfig, fake_searcher: FakeSearcher
    ) -> None:
        """If binding has no vector_model, any caller value is accepted."""
        binding_no_model = IndexBinding(
            domain_type="KNOWLEDGE_BASE",
            kb_index=KB_INDEX,
            tag=TAG,
            parser_script_source="",
            parser_script_sha256="",
            vector_model=None,   # no model
            search_profile_json=SAMPLE_PROFILE,
            search_profile_sha256="",
            is_active=True,
        )
        writer = FakeDBWriter(binding=binding_no_model)
        factory = FakeDBFactory(writer)
        svc = KnowledgeBaseSearchService(
            db_factory=factory,  # type: ignore[arg-type]
            vector_tool=FakeVectorTool(),  # type: ignore[arg-type]
            search_cfg=search_cfg,
            searcher=fake_searcher,  # type: ignore[arg-type]
        )
        # Should not raise even though caller supplies a model name
        svc.search(query="q", tag=TAG, search_type="text", top_k=5,
                   vector_model="some/model", vector_weight=None)


# ──────────────────────────────────────────────────────────────────────────────
# Error propagation from Searcher
# ──────────────────────────────────────────────────────────────────────────────


class TestErrorPropagation:
    def test_search_profile_invalid_propagates(
        self,
        fake_factory: FakeDBFactory,
        search_cfg: SearchConfig,
    ) -> None:
        bad_searcher = FakeSearcher(
            side_effect=SearchProfileInvalidError("bad profile")
        )
        svc = KnowledgeBaseSearchService(
            db_factory=fake_factory,  # type: ignore[arg-type]
            vector_tool=FakeVectorTool(),  # type: ignore[arg-type]
            search_cfg=search_cfg,
            searcher=bad_searcher,  # type: ignore[arg-type]
        )
        with pytest.raises(SearchProfileInvalidError):
            svc.search(query="q", tag=TAG, search_type=None,
                       top_k=None, vector_model=None, vector_weight=None)

    def test_internal_error_propagates(
        self,
        fake_factory: FakeDBFactory,
        search_cfg: SearchConfig,
    ) -> None:
        bad_searcher = FakeSearcher(
            side_effect=SearchInternalError("db down")
        )
        svc = KnowledgeBaseSearchService(
            db_factory=fake_factory,  # type: ignore[arg-type]
            vector_tool=FakeVectorTool(),  # type: ignore[arg-type]
            search_cfg=search_cfg,
            searcher=bad_searcher,  # type: ignore[arg-type]
        )
        with pytest.raises(SearchInternalError):
            svc.search(query="q", tag=TAG, search_type=None,
                       top_k=None, vector_model=None, vector_weight=None)
