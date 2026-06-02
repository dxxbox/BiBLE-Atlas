"""Centralised error-code contract for the v4 Search API layer.

Sources
-------
- ``02_API接口文档.md`` §7 错误码表
- ``knowledge_base_search_implementation.md`` §11 错误码建议（检索侧）
- ``knowledge_base_search_flow.puml`` 各 alt 分支

Usage (in an API route)
-----------------------
::

    from bible.features.search.errors import raise_search_http_exception

    try:
        result = svc.search(...)
    except Exception as exc:
        raise_search_http_exception(exc)   # re-raises as HTTPException

    # Or look up a status code directly:
    from bible.features.search.errors import http_status_for_search_code
    status = http_status_for_search_code("INDEX_NOT_BOUND")   # → 404
"""

from __future__ import annotations

from fastapi import HTTPException

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

# ── Error-code → HTTP status mapping ──────────────────────────────────────────
# Derived from §7 of 02_API接口文档.md and §11 of knowledge_base_search_implementation.md

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


# ── Exception → HTTPException mapper ──────────────────────────────────────────

# Each entry: (exception_type, error_code, expose_message, log_as_error)
#   expose_message=True  → include the exception message in the response body
#   expose_message=False → return a generic message (avoid leaking internals)
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
    """Convert a known search exception into an ``HTTPException`` and raise it.

    If *exc* matches a known type it is converted; otherwise it is re-raised
    as-is so the caller / FastAPI global handler can deal with it.

    Parameters
    ----------
    exc:
        The exception caught in the API route handler.

    Raises
    ------
    HTTPException
        Always raised when *exc* is a known search exception.
    """
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
