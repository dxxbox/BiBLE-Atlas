"""Unit tests for SkillSearchService (Task B — skill_search).

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
from bible.features.search.skill_search.skill_search_service import (
    IndexNotBoundError,
    SkillSearchService,
    VectorModelConflictError,
)
from bible.infrastructure.database.types import DomainType, IndexBinding

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────

VECTOR_MODEL = "BAAI/bge-base-zh-v1.5"
KB_INDEX = "kb_skill_main"

SKILL_PROFILE: dict[str, Any] = {
    "search_type_profile": {
        "hybrid": {"enabled": True, "default_vector_weight": 0.5},
        "text": {
            "enabled": True,
            "fields": [{"field": "name", "weight": 4.0}],
        },
    }
}

BINDING_WITH_MODEL = IndexBinding(
    domain_type="SKILL",
    kb_index=KB_INDEX,
    tag="skill",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=VECTOR_MODEL,
    search_profile_json=SKILL_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

BINDING_NO_MODEL = IndexBinding(
    domain_type="SKILL",
    kb_index=KB_INDEX,
    tag="skill",
    parser_script_source="",
    parser_script_sha256="",
    vector_model=None,
    search_profile_json=SKILL_PROFILE,
    search_profile_sha256="",
    is_active=True,
)

FAKE_ITEMS = [
    {"doc_id": "skill_001", "name": "k8s-log-cleaner", "score": 0.91},
    {"doc_id": "skill_002", "name": "oom-killer-guard", "score": 0.71},
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
        self.binding_index_calls: list[tuple[str, str]] = []

    def get_binding_by_domain_tag(
        self, domain: DomainType, tag: str
    ) -> IndexBinding | None:
        self.binding_calls.append((domain, tag))
        return self._binding

    def get_binding_by_domain_index(
        self, domain: DomainType, kb_index: str
    ) -> IndexBinding | None:
        self.binding_index_calls.append((domain, kb_index))
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
) -> tuple[SkillSearchService, FakeDBWriter, FakeDBFactory, FakeSearcher]:
    db_writer = FakeDBWriter(binding=binding)
    db_factory = FakeDBFactory(writer=db_writer)
    vec = FakeVectorTool()
    cfg = search_cfg or SearchConfig(default_top_k=10, max_top_k=50)
    searcher = fake_searcher or FakeSearcher()
    svc = SkillSearchService(
        db_factory=db_factory,  # type: ignore[arg-type]
        vector_tool=vec,         # type: ignore[arg-type]
        search_cfg=cfg,
        searcher=searcher,       # type: ignore[arg-type]
    )
    return svc, db_writer, db_factory, searcher


def _search(svc: SkillSearchService, **overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(
        query="k8s log cleaner script",
        tag="skill",
        search_type=None,
        top_k=None,
        vector_model=None,
        vector_weight=None,
    )
    defaults.update(overrides)
    return svc.search(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Binding lookup
# ──────────────────────────────────────────────────────────────────────────────


class TestBindingLookup:
    def test_binding_not_found_raises_index_not_bound(self) -> None:
        svc, _, _, _ = make_service(binding=None)
        with pytest.raises(IndexNotBoundError):
            _search(svc)

    def test_index_not_bound_error_contains_tag(self) -> None:
        svc, _, _, _ = make_service(binding=None)
        with pytest.raises(IndexNotBoundError) as exc_info:
            _search(svc, tag="skill")
        assert "skill" in str(exc_info.value)

    def test_db_factory_called_with_skill_domain(self) -> None:
        svc, _, db_factory, _ = make_service()
        _search(svc)
        assert db_factory.domain_calls == ["SKILL"]

    def test_binding_lookup_by_tag_when_kb_index_absent(self) -> None:
        svc, db_writer, _, _ = make_service()
        _search(svc, tag="skill")
        assert db_writer.binding_calls == [("SKILL", "skill")]
        assert db_writer.binding_index_calls == []

    def test_binding_lookup_by_domain_index_when_kb_index_provided(self) -> None:
        svc, db_writer, _, _ = make_service()
        _search(svc, kb_index=KB_INDEX)
        assert db_writer.binding_index_calls == [("SKILL", KB_INDEX)]
        assert db_writer.binding_calls == []


# ──────────────────────────────────────────────────────────────────────────────
# 2. Parameter normalisation
# ──────────────────────────────────────────────────────────────────────────────


class TestParameterNormalisation:
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

    def test_top_k_within_limit_passes_through(self) -> None:
        cfg = SearchConfig(default_top_k=10, max_top_k=50)
        svc, _, _, searcher = make_service(search_cfg=cfg)
        _search(svc, top_k=15)
        assert searcher.calls[0]["top_k"] == 15

    @pytest.mark.parametrize("search_type", ["keyword", "title", "text"])
    def test_vector_weight_is_none_for_non_vector_types(self, search_type: str) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type=search_type, vector_weight=0.7)
        assert searcher.calls[0]["vector_weight"] is None

    def test_vector_weight_from_profile_when_omitted_for_hybrid(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="hybrid", vector_weight=None)
        # SKILL_PROFILE hybrid default_vector_weight = 0.5
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.5)

    def test_explicit_vector_weight_passed_through_for_hybrid(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, search_type="hybrid", vector_weight=0.8)
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.8)

    def test_vector_weight_fallback_default_when_profile_has_no_hybrid(self) -> None:
        """When the profile has no hybrid section, fallback is 0.5 (SKILL default)."""
        binding = IndexBinding(
            domain_type="SKILL",
            kb_index=KB_INDEX,
            tag="skill",
            parser_script_source="",
            parser_script_sha256="",
            vector_model=VECTOR_MODEL,
            search_profile_json={},  # no search_type_profile
            search_profile_sha256="",
            is_active=True,
        )
        svc, _, _, searcher = make_service(binding=binding)
        _search(svc, search_type="hybrid", vector_weight=None)
        assert searcher.calls[0]["vector_weight"] == pytest.approx(0.5)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Vector-model consistency check
# ──────────────────────────────────────────────────────────────────────────────


class TestVectorModelConsistency:
    def test_vector_model_conflict_raises_error(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_WITH_MODEL)
        with pytest.raises(VectorModelConflictError):
            _search(svc, vector_model="other-model/v1")

    def test_vector_model_conflict_error_contains_requested_and_bound(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_WITH_MODEL)
        with pytest.raises(VectorModelConflictError) as exc_info:
            _search(svc, vector_model="bad-model")
        msg = str(exc_info.value)
        assert "bad-model" in msg
        assert VECTOR_MODEL in msg

    def test_caller_model_matches_binding_does_not_raise(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_WITH_MODEL)
        # Should not raise — same model
        _search(svc, vector_model=VECTOR_MODEL)

    def test_binding_without_vector_model_no_conflict(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_NO_MODEL)
        # binding.vector_model is None → no conflict check
        _search(svc, vector_model="any-model")

    def test_caller_omits_model_no_conflict(self) -> None:
        svc, _, _, _ = make_service(binding=BINDING_WITH_MODEL)
        # vector_model=None → no check
        _search(svc, vector_model=None)

    def test_effective_vector_model_from_binding_passed_to_searcher(self) -> None:
        svc, _, _, searcher = make_service(binding=BINDING_WITH_MODEL)
        _search(svc, vector_model=None)
        assert searcher.calls[0]["vector_model"] == VECTOR_MODEL

    def test_effective_vector_model_none_when_binding_has_no_model(self) -> None:
        svc, _, _, searcher = make_service(binding=BINDING_NO_MODEL)
        _search(svc, vector_model=None)
        assert searcher.calls[0]["vector_model"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 4. Searcher delegation
# ──────────────────────────────────────────────────────────────────────────────


class TestSearcherDelegation:
    def test_searcher_called_once(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert len(searcher.calls) == 1

    def test_searcher_receives_correct_kb_index_from_binding(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert searcher.calls[0]["kb_index"] == KB_INDEX

    def test_searcher_receives_query(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc, query="oom killer guard")
        assert searcher.calls[0]["query"] == "oom killer guard"

    def test_searcher_receives_search_profile_from_binding(self) -> None:
        svc, _, _, searcher = make_service()
        _search(svc)
        assert searcher.calls[0]["search_profile"] == SKILL_PROFILE

    def test_custom_searcher_injection_is_used(self) -> None:
        custom = FakeSearcher(result={"kb_index": KB_INDEX, "total": 0, "items": []})
        svc, _, _, _ = make_service(fake_searcher=custom)
        _search(svc)
        assert len(custom.calls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 5. Response structure
# ──────────────────────────────────────────────────────────────────────────────


class TestResponseStructure:
    def test_success_returns_structured_response(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc, tag="skill")
        assert result["success"] is True
        assert result["domain"] == "SKILL"
        assert result["kb_index"] == KB_INDEX
        assert result["tag"] == "skill"
        assert "total" in result
        assert "results" in result

    def test_response_domain_is_skill(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["domain"] == "SKILL"

    def test_response_results_key_is_skill(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert "skill" in result["results"]

    def test_total_from_searcher_result(self) -> None:
        searcher = FakeSearcher(result={"kb_index": KB_INDEX, "total": 42, "items": []})
        svc, _, _, _ = make_service(fake_searcher=searcher)
        result = _search(svc)
        assert result["total"] == 42

    def test_items_from_searcher_result(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["results"]["skill"] == FAKE_ITEMS

    def test_kb_index_in_response_from_binding(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc)
        assert result["kb_index"] == KB_INDEX

    def test_tag_preserved_in_response(self) -> None:
        svc, _, _, _ = make_service()
        result = _search(svc, tag="skill")
        assert result["tag"] == "skill"


# ──────────────────────────────────────────────────────────────────────────────
# 6. kb_index optional parameter routing
# ──────────────────────────────────────────────────────────────────────────────


class TestKbIndexRouting:
    def test_no_kb_index_uses_tag_lookup(self) -> None:
        svc, db_writer, _, _ = make_service()
        _search(svc, tag="skill")
        assert ("SKILL", "skill") in db_writer.binding_calls

    def test_explicit_kb_index_uses_index_lookup(self) -> None:
        svc, db_writer, _, _ = make_service()
        _search(svc, kb_index="kb_skill_alt")
        assert ("SKILL", "kb_skill_alt") in db_writer.binding_index_calls
        assert db_writer.binding_calls == []

    def test_explicit_kb_index_not_found_raises_index_not_bound(self) -> None:
        svc, _, _, _ = make_service(binding=None)
        with pytest.raises(IndexNotBoundError) as exc_info:
            _search(svc, kb_index="kb_nonexistent")
        assert "kb_nonexistent" in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────────────
# 7. _normalise_vector_weight edge cases (static method)
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseVectorWeight:
    def _norm(self, vw: float | None, st: str, profile: dict[str, Any]) -> float | None:
        return SkillSearchService._normalise_vector_weight(vw, st, profile)

    def test_keyword_always_returns_none(self) -> None:
        assert self._norm(0.8, "keyword", SKILL_PROFILE) is None

    def test_title_always_returns_none(self) -> None:
        assert self._norm(0.8, "title", SKILL_PROFILE) is None

    def test_text_always_returns_none(self) -> None:
        assert self._norm(0.8, "text", SKILL_PROFILE) is None

    def test_vector_explicit_value_returned(self) -> None:
        assert self._norm(0.9, "vector", SKILL_PROFILE) == pytest.approx(0.9)

    def test_hybrid_explicit_value_returned(self) -> None:
        assert self._norm(0.3, "hybrid", SKILL_PROFILE) == pytest.approx(0.3)

    def test_hybrid_none_falls_back_to_profile_default(self) -> None:
        profile = {"search_type_profile": {"hybrid": {"default_vector_weight": 0.5}}}
        assert self._norm(None, "hybrid", profile) == pytest.approx(0.5)

    def test_hybrid_none_falls_back_to_hard_default_when_no_profile(self) -> None:
        assert self._norm(None, "hybrid", {}) == pytest.approx(0.5)

    def test_vector_none_falls_back_to_profile_default(self) -> None:
        profile = {"search_type_profile": {"hybrid": {"default_vector_weight": 0.4}}}
        assert self._norm(None, "vector", profile) == pytest.approx(0.4)
