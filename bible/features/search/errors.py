from __future__ import annotations

from fastapi import HTTPException

from bible.common.errors import DomainError

from bible.features.search.common.query_profile_compiler import SearchProfileInvalidError
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

SEARCH_ERROR_HTTP_STATUS: dict[str, int] = {
    # 400 — client errors
    "INVALID_ARGUMENT": 400,
    "TAG_REQUIRED": 400,
    "TAG_INVALID": 400,
    "SEARCH_TYPE_INVALID": 400,
    # 404 — not found
    "INDEX_NOT_BOUND": 404,
    # 409 — conflict
    "VECTOR_MODEL_CONFLICT": 409,
    # 422 — unprocessable (profile cannot be compiled)
    "SEARCH_PROFILE_INVALID": 422,
    # 500 — internal
    "INTERNAL_ERROR": 500,
}

def http_status_for_search_code(code: str) -> int:
    """Return the HTTP status code for a search error-code string.

    Falls back to 500 for unknown codes.
    """
    return SEARCH_ERROR_HTTP_STATUS.get(code, 500)

_EXCEPTION_MAP: list[tuple[type[Exception], str, bool]] = [
    # KNOWLEDGE_BASE
    (KBIndexNotBoundError,          "INDEX_NOT_BOUND",       True),
    (KBVectorModelConflictError,    "VECTOR_MODEL_CONFLICT", True),
    # MEMORY
    (MemoryIndexNotBoundError,      "INDEX_NOT_BOUND",       True),
    (MemoryVectorModelConflictError,"VECTOR_MODEL_CONFLICT", True),
    # Shared
    (SearchProfileInvalidError,     "SEARCH_PROFILE_INVALID",True),
    (SearchInternalError,           "INTERNAL_ERROR",        False),
]



def raise_search_http_exception(exc: Exception) -> None:

    for exc_type, code, expose in _EXCEPTION_MAP:
        if isinstance(exc, exc_type):
            status = http_status_for_search_code(code)
            if expose:
                # Use the exception's own message or .reason attribute
                message = getattr(exc, "reason", None) or str(exc)
            else:
                message = "An internal error occurred."
            raise HTTPException(
                status_code=status,
                detail={"code": code, "message": message},
            ) from exc

    # Not a known search exception — let it propagate
    raise exc
