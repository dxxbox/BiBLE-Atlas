"""Unit tests for MemorySearchService (Task B — memory_search).

All infrastructure is replaced with fakes so these tests run without a real
database, embedding model, or config file.

Fakes
-----
FakeDBWriter    — configurable binding lookup; no-op search_content_docs.
FakeDBFactory   — wraps FakeDBWriter; records the domain passed to get_writer.
FakeSearcher    — records search() call args; returns configurable result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from bible.config.configure import SearchConfig
from bible.features.search.memory_search.memory_search_service import (
    IndexNotBoundError,
    MemorySearchService,
    VectorModelConflictError,
)
from bible.infrastructure.database.types import DomainType, IndexBinding

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_memory_main"

MEMORY_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "hybrid": {"enabled": True, "default_vector_weight": 0.65},
        "text": {
            "enabled": True,
            "fields": [{"field": "title", "weight": 3.0}],
        },
    }
}

BINDING_WITH_MODEL = IndexBinding(
    domain_type="MEMORY",
    kb_index=KB_INDEX,
    tag="memory",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=VECTOR_MODEL,
    search_profile_json=MEMORY_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

BINDING_NO_MODEL = IndexBinding(
    domain_type="MEMORY",
    kb_index=KB_INDEX,
    tag="memory",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=None,
    search_profile_json=MEMORY_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

FAKE_ITEMS = [
    {"doc_id": "mem_001", "memory_id": "mem_001", "title": "CNI race", "score": 0.9},
    {"doc_id": "mem_002", "memory_id": "mem_002", "title": "OOM kernel", "score": 0.7},
]

FAKE_SEARCH_RESULT: dict[str, Any] = {
    "kb_index": KB_INDEX,
    "total": 2,
    "items": FAKE_ITEMS,
}


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeDBWriter:
    def __init__(self, binding: IndexBinding | None = BINDING_WITH_MODEL) -> None:
        self._binding = binding
        self.binding_calls: list[tuple[str, str]] = []

    def get_binding_by_domain_tag(
        self, domain: DomainType, tag: str
    ) -> IndexBinding | None:
        self.binding_calls.append((domain, tag))
        return self._binding

    def search_content_docs(self, *a: Any, **kw: Any) -> dict[str, Any]:
        return {"total": 0, "hits": []}


class FakeDBFactory:
    def __init__(self, writer: FakeDBWriter) -> None:
        self._writer = writer
        self.domain_calls: list[str] = []

    def get_writer(self, domain: str) -> FakeDBWriter:
        self.domain_calls.append(domain)
        return self._writer


class FakeVectorTool:
    pass


class FakeSearcher:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self._result = result or FAKE_SEARCH_RESULT
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self._result


def make_service(
    binding: IndexBinding | None = BINDING_WITH_MODEL,
    search_cfg: SearchConfig | None = None,
    fake_searcher: FakeSearcher | None = None,
) -> tuple[MemorySearchService, FakeDBWriter, FakeDBFactory, FakeSearcher]:
    db_writer = FakeDBWriter(binding=binding)
    db_factory = FakeDBFactory(writer=db_writer)
    vec = FakeVectorTool()
    cfg = search_cfg or SearchConfig(default_top_k=10, max_top_k=50)
    searcher = fake_searcher or FakeSearcher()
    svc = MemorySearchService(
        db_factory=db_factory,  # type: ignore[arg-type]
        vector_tool=vec,         # type: ignore[arg-type]
        search_cfg=cfg,
        searcher=searcher,       # type: ignore[arg-type]
    )
    return svc, db_writer, db_factory, searcher


def _search(svc: MemorySearchService, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(
        query="CNI race condition",
        tag="memory",
        search_type=None,
        top_k=None,
        vector_model=None,
        vector_weight=None,
    )
    defaults.update(overrides)
    return svc.search(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Binding lookup errors
# ──────────────────────────────────────────────────────────────────────────────


class TestBindingLookup:
    def test_binding_not_found_raises_index_not_bound(self) -> None:
        svc, _, _, _ = make_service(binding=None)
        with pytest.raises(IndexNotBoundError):
            _search(svc)

    def test_index_not_bound_error_contains_tag(self) -> None:
        svc, _, _, _ = make_service(binding=None)
        with pytest.raises(IndexNotBoundError) as exc_info:
            _search(svc, tag="memory")
        assert "memory" in str(exc_info.value)

    def test_db_factory_called_with_memory_domain(self) -> None:
        svc, _, db_factory, _ = make_service()
        _search(svc)
        assert db_factory.domain_calls == ["MEMORY"]

    def test_binding_lookup_uses_correct_domain_and_tag(self) -> None:
        svc, db_writer, _, _ = make_service()
        _search(svc, tag="memory")
        assert db_writer.binding_calls == [("MEMORY", "memory")]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Parameter normalisation
# ──────────────────────────────────────────────────────────────────────────────


class TestParamNormalisation:
    def test_search_type_defaults_to_text(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type=None)
        assert searcher.calls[0]["search_type"] == "text"

    def test_explicit_search_type_passed_through(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="keyword")
        assert searcher.calls[0]["search_type"] == "keyword"

    def test_top_k_defaults_to_config_default(self) -> None:
        cfg = SearchConfig(default_top_k=7, max_top_k=50)
        svc, _, _, searcher = make_service(search_cfg=cfg)
        _search(svc, top_k=None)
        assert searcher.calls[0]["top_k"] == 7

    def test_top_k_clamped_to_max(self) -> None:
        cfg = SearchConfig(default_top_k=10, max_top_k=20)
        svc, _, _, searcher = make_service(search_cfg=cfg)
        _search(svc, top_k=999)
        assert searcher.calls[0]["top_k"] == 20

    def test_top_k_passed_through_when_below_max(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, top_k=5)
        assert searcher.calls[0]["top_k"] == 5

    def test_vector_weight_from_profile_when_omitted_for_hybrid(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="hybrid", vector_weight=None)
        # Profile hybrid.default_vector_weight = 0.65
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.65)

    def test_explicit_vector_weight_used_as_is(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="hybrid", vector_weight=0.4)
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.4)

    def test_vector_weight_none_for_keyword(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="keyword", vector_weight=0.9)
        assert searcher.calls[0]["vector_weight"] is None

    def test_vector_weight_none_for_title(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="title")
        assert searcher.calls[0]["vector_weight"] is None

    def test_vector_weight_none_for_text(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="text")
        assert searcher.calls[0]["vector_weight"] is None

    def test_vector_weight_from_profile_for_vector_type(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="vector", vector_weight=None)
        # Same default from hybrid section (0.65) is used as fallback
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.65)

    def test_vector_weight_fallback_060_when_no_profile_default(self) -> None:
        profile_no_hybrid = {"search_type_profile": {}}
        binding = IndexBinding(
            domain_type="MEMORY", kb_index=KB_INDEX, tag="memory",
            parser_script_source="", parser_script_sha256="",
            vector_model=None, search_profile_json=profile_no_hybrid,
            search_profile_sha256="",
        )
        svc, _, _, searcher = make_service(binding=binding)
        _search(svc, search_type="hybrid", vector_weight=None)
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.6)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Vector-model consistency
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorModelConsistency:
    def test_vector_model_conflict_raises_error(self) -> None:
        svc, _, _, _ = make_service()
        with pytest.raises(VectorModelConflictError):
            _search(svc, vector_model="other/model")

    def test_vector_model_conflict_message_contains_both_models(self) -> None:
        svc, _, _, _ = make_service()
        with pytest.raises(VectorModelConflictError) as exc_info:
            _search(svc, vector_model="other/model")
        msg = str(exc_info.value)
        assert "other/model" in msg
        assert VECTOR_MODEL in msg

    def test_caller_model_matches_binding_no_conflict(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc, vector_model=VECTOR_MODEL)
        assert result["success"] is True

    def test_binding_no_vector_model_no_conflict(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_NO_MODEL)
        result = _search(svc, vector_model="any/model")
        assert result["success"] is True

    def test_effective_vector_model_comes_from_binding(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert searcher.calls[0]["vector_model"] == VECTOR_MODEL

    def test_effective_vector_model_none_when_binding_has_no_model(self) -> None:
        svc, _, _, searcher = make_service(binding=BINDING_NO_MODEL)
        _search(svc)
        assert searcher.calls[0]["vector_model"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 4. Searcher delegation
# ──────────────────────────────────────────────────────────────────────────────


class TestSearcherDelegation:
    def test_searcher_called_once(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert len(searcher.calls) == 1

    def test_searcher_receives_correct_kb_index(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert searcher.calls[0]["kb_index"] == KB_INDEX

    def test_searcher_receives_query(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, query="OOM kernel pressure")
        assert searcher.calls[0]["query"] == "OOM kernel pressure"

    def test_searcher_receives_search_profile_from_binding(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert searcher.calls[0]["search_profile"] == MEMORY_PROFILE

    def test_custom_searcher_injection(self) -> None:
        """When a searcher is injected, no new instance should be created."""
        fake = FakeSearcher()
        svc, _, _, _ = make_service(fake_searcher=fake)
        _search(svc)
        assert len(fake.calls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 5. Response structure
# ──────────────────────────────────────────────────────────────────────────────


class TestResponseStructure:
    def test_success_returns_complete_response(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["success"] is True
        assert result["domain"] == "MEMORY"
        assert result["kb_index"] == KB_INDEX
        assert result["tag"] == "memory"
        assert "total" in result
        assert "results" in result

    def test_response_domain_is_memory(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["domain"] == "MEMORY"

    def test_response_results_key_is_memory(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert "memory" in result["results"]

    def test_total_from_searcher_result(self) -> None:
        searcher = FakeSearcher(result={**FAKE_SEARCH_RESULT, "total": 42})
        svc, _, _, _ = make_service(fake_searcher=searcher)
        result = _search(svc)
        assert result["total"] == 42

    def test_items_from_searcher_result(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["results"]["memory"] == FAKE_ITEMS

    def test_kb_index_from_searcher_result(self) -> None:
        searcher = FakeSearcher(result={**FAKE_SEARCH_RESULT, "kb_index": "kb_memory_alt"})
        svc, _, _, _ = make_service(fake_searcher=searcher)
        result = _search(svc)
        assert result["kb_index"] == "kb_memory_alt"

    def test_tag_in_response_reflects_input(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc, tag="memory")
        assert result["tag"] == "memory"
