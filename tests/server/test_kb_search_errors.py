"""Unit tests for bible.features.search.errors (Task P).

Cross-checks the error-code → HTTP-status mapping table against
02_API接口文档.md §7 and knowledge_base_search_implementation.md §11.

Also verifies raise_search_http_exception() converts every known exception
type to the correct HTTPException and leaves unknown exceptions untouched.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
from bible.features.search.errors import (
    SEARCH_ERROR_HTTP_STATUS,
    http_status_for_search_code,
    raise_search_http_exception,
)
from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
    IndexNotBoundError,
    VectorModelConflictError,
)
from bible.features.search.knowledge_base_search.searcher.search_knowledge_base import (
    SearchInternalError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Table-driven: error code → HTTP status (§7 of API doc + §11 of impl doc)
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchErrorHttpStatusTable:
    """Assert every documented error code maps to its expected HTTP status."""

    @pytest.mark.parametrize("code, expected_status", [
        # 400 — client / argument errors
        ("INVALID_ARGUMENT",    400),
        ("TAG_REQUIRED",        400),
        ("TAG_INVALID",         400),
        ("SEARCH_TYPE_INVALID", 400),
        # 404 — not found
        ("INDEX_NOT_BOUND",     404),
        # 409 — conflict
        ("VECTOR_MODEL_CONFLICT", 409),
        # 422 — unprocessable entity
        ("SEARCH_PROFILE_INVALID", 422),
        # 500 — internal
        ("INTERNAL_ERROR",      500),
    ])
    def test_http_status_for_search_code(self, code: str, expected_status: int) -> None:
        assert http_status_for_search_code(code) == expected_status

    def test_unknown_code_falls_back_to_500(self) -> None:
        assert http_status_for_search_code("NO_SUCH_CODE") == 500

    def test_all_documented_codes_present_in_mapping(self) -> None:
        """Ensure the mapping dict contains all documented codes."""
        required = {
            "INVALID_ARGUMENT", "TAG_REQUIRED", "TAG_INVALID",
            "SEARCH_TYPE_INVALID", "INDEX_NOT_BOUND",
            "VECTOR_MODEL_CONFLICT", "SEARCH_PROFILE_INVALID", "INTERNAL_ERROR",
        }
        assert required <= SEARCH_ERROR_HTTP_STATUS.keys()


# ──────────────────────────────────────────────────────────────────────────────
# raise_search_http_exception — known exception types
# ──────────────────────────────────────────────────────────────────────────────


class TestRaiseSearchHttpException:

    def test_index_not_bound_raises_404(self) -> None:
        exc = IndexNotBoundError("unknown_tag")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert info.value.status_code == 404
        assert info.value.detail["code"] == "INDEX_NOT_BOUND"

    def test_index_not_bound_message_exposed(self) -> None:
        exc = IndexNotBoundError("myTag")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert "myTag" in info.value.detail["message"]

    def test_vector_model_conflict_raises_409(self) -> None:
        exc = VectorModelConflictError("req/model", "bound/model")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert info.value.status_code == 409
        assert info.value.detail["code"] == "VECTOR_MODEL_CONFLICT"

    def test_vector_model_conflict_message_exposed(self) -> None:
        exc = VectorModelConflictError("a", "b")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        msg = info.value.detail["message"]
        assert "a" in msg and "b" in msg

    def test_search_profile_invalid_raises_422(self) -> None:
        exc = SearchProfileInvalidError("bad profile")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert info.value.status_code == 422
        assert info.value.detail["code"] == "SEARCH_PROFILE_INVALID"

    def test_search_profile_invalid_reason_exposed(self) -> None:
        exc = SearchProfileInvalidError("missing vector_field")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert "missing vector_field" in info.value.detail["message"]

    def test_search_internal_error_raises_500(self) -> None:
        exc = SearchInternalError("db down")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        assert info.value.status_code == 500
        assert info.value.detail["code"] == "INTERNAL_ERROR"

    def test_search_internal_error_message_not_exposed(self) -> None:
        """Internal errors must not leak implementation details to the client."""
        exc = SearchInternalError("connection pool exhausted at 10.0.0.5:9200")
        with pytest.raises(HTTPException) as info:
            raise_search_http_exception(exc)
        # Original message must NOT appear in the response
        assert "connection pool" not in info.value.detail["message"]
        assert "10.0.0.5" not in info.value.detail["message"]

    def test_unknown_exception_is_reraised(self) -> None:
        """Exceptions not in the known set must propagate unchanged."""
        exc = RuntimeError("something unexpected")
        with pytest.raises(RuntimeError, match="something unexpected"):
            raise_search_http_exception(exc)

    def test_value_error_is_reraised(self) -> None:
        exc = ValueError("plain value error")
        with pytest.raises(ValueError):
            raise_search_http_exception(exc)
