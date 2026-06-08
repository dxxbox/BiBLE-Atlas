"""Unit tests for errors.py — Skill exception mappings (Task F).

Verifies that:
  1. Skill-specific exceptions map to the correct HTTP status codes.
  2. KB and Memory exception mappings are not broken (regression).
  3. Shared exceptions (SearchProfileInvalidError, SearchInternalError)
     continue to map correctly.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.errors import raise_search_http_exception
from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
    IndexNotBoundError as KBIndexNotBoundError,
    VectorModelConflictError as KBVectorModelConflictError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)
from bible.features.search.memory_search.memory_search_service import (
    IndexNotBoundError as MemoryIndexNotBoundError,
    VectorModelConflictError as MemoryVectorModelConflictError,
)
from bible.features.search.skill_search.skill_search_service import (
    IndexNotBoundError as SkillIndexNotBoundError,
    VectorModelConflictError as SkillVectorModelConflictError,
)


def _raise_and_catch(exc: Exception) -> HTTPException:
    """Call raise_search_http_exception and capture the resulting HTTPException."""
    with pytest.raises(HTTPException) as exc_info:
        raise_search_http_exception(exc)
    return exc_info.value


# ──────────────────────────────────────────────────────────────────────────────
# 1. SKILL-specific exception mapping
# ──────────────────────────────────────────────────────────────────────────────


class TestSkillExceptionMapping:
    def test_skill_index_not_bound_maps_to_404(self) -> None:
        http_exc = _raise_and_catch(SkillIndexNotBoundError("skill"))
        assert http_exc.status_code == 404

    def test_skill_index_not_bound_error_code(self) -> None:
        http_exc = _raise_and_catch(SkillIndexNotBoundError("skill"))
        assert http_exc.detail["code"] == "INDEX_NOT_BOUND"

    def test_skill_index_not_bound_message_exposed(self) -> None:
        http_exc = _raise_and_catch(SkillIndexNotBoundError("kb_skill_main", selector="kb_index"))
        assert "kb_skill_main" in http_exc.detail["message"]

    def test_skill_vector_model_conflict_maps_to_409(self) -> None:
        http_exc = _raise_and_catch(SkillVectorModelConflictError("req/model", "bound/model"))
        assert http_exc.status_code == 409

    def test_skill_vector_model_conflict_error_code(self) -> None:
        http_exc = _raise_and_catch(SkillVectorModelConflictError("req/model", "bound/model"))
        assert http_exc.detail["code"] == "VECTOR_MODEL_CONFLICT"

    def test_skill_vector_model_conflict_message_exposed(self) -> None:
        http_exc = _raise_and_catch(SkillVectorModelConflictError("req-model", "bound-model"))
        msg = http_exc.detail["message"]
        assert "req-model" in msg
        assert "bound-model" in msg


# ──────────────────────────────────────────────────────────────────────────────
# 2. KB exception regression
# ──────────────────────────────────────────────────────────────────────────────


class TestKBExceptionRegression:
    def test_kb_index_not_bound_still_maps_to_404(self) -> None:
        http_exc = _raise_and_catch(KBIndexNotBoundError("design"))
        assert http_exc.status_code == 404
        assert http_exc.detail["code"] == "INDEX_NOT_BOUND"

    def test_kb_vector_model_conflict_still_maps_to_409(self) -> None:
        http_exc = _raise_and_catch(KBVectorModelConflictError("r", "b"))
        assert http_exc.status_code == 409
        assert http_exc.detail["code"] == "VECTOR_MODEL_CONFLICT"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Memory exception regression
# ──────────────────────────────────────────────────────────────────────────────


class TestMemoryExceptionRegression:
    def test_memory_index_not_bound_still_maps_to_404(self) -> None:
        http_exc = _raise_and_catch(MemoryIndexNotBoundError("memory"))
        assert http_exc.status_code == 404
        assert http_exc.detail["code"] == "INDEX_NOT_BOUND"

    def test_memory_vector_model_conflict_still_maps_to_409(self) -> None:
        http_exc = _raise_and_catch(MemoryVectorModelConflictError("r", "b"))
        assert http_exc.status_code == 409
        assert http_exc.detail["code"] == "VECTOR_MODEL_CONFLICT"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Shared exception regression
# ──────────────────────────────────────────────────────────────────────────────


class TestSharedExceptionRegression:
    def test_search_profile_invalid_maps_to_422(self) -> None:
        http_exc = _raise_and_catch(SearchProfileInvalidError("term_fields missing"))
        assert http_exc.status_code == 422
        assert http_exc.detail["code"] == "SEARCH_PROFILE_INVALID"

    def test_search_profile_invalid_message_exposed(self) -> None:
        http_exc = _raise_and_catch(SearchProfileInvalidError("bad profile config"))
        assert "bad profile config" in http_exc.detail["message"]

    def test_internal_error_maps_to_500(self) -> None:
        http_exc = _raise_and_catch(SearchInternalError("db connection failed"))
        assert http_exc.status_code == 500
        assert http_exc.detail["code"] == "INTERNAL_ERROR"

    def test_internal_error_message_not_exposed(self) -> None:
        """Internal errors must return a generic message, not the original detail."""
        http_exc = _raise_and_catch(SearchInternalError("secret host: db.internal:9200"))
        assert "secret" not in http_exc.detail["message"]
        assert "db.internal" not in http_exc.detail["message"]

    def test_unknown_exception_propagates(self) -> None:
        """Exceptions not in the map must be re-raised as-is."""
        class _UnknownError(Exception):
            pass

        with pytest.raises(_UnknownError):
            raise_search_http_exception(_UnknownError("unexpected"))
