from __future__ import annotations

from fastapi import HTTPException

from bible.common.errors import DomainError


def raise_search_http_exception(exc: Exception) -> None:
    if isinstance(exc, DomainError):
        raise HTTPException(
            status_code=exc.http_status_code,
            detail={
                "code": exc.code.value,
                "message": exc.message,
                "details": exc.details,
                "retryable": exc.retryable,
            },
        ) from exc
    raise exc
