from __future__ import annotations

from enum import Enum
from typing import Any

from bible.common.schemas import ErrorInfo


class ErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    INVALID_TAG = "INVALID_TAG"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    FAILED_PRECONDITION = "FAILED_PRECONDITION"
    CONFLICT = "CONFLICT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNAVAILABLE = "UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    AUTH_INVALID_API_KEY = "AUTH_INVALID_API_KEY"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"


ERROR_HTTP_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.INVALID_ARGUMENT: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.FAILED_PRECONDITION: 412,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RESOURCE_EXHAUSTED: 429,
    ErrorCode.CANCELLED: 499,
    ErrorCode.INTERNAL: 500,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.UNAVAILABLE: 503,
    ErrorCode.DEADLINE_EXCEEDED: 504,
    ErrorCode.AUTH_INVALID_API_KEY: 401,
    ErrorCode.TENANT_NOT_FOUND: 404,
}

RETRYABLE_ERROR_CODES: set[ErrorCode] = {
    ErrorCode.RESOURCE_EXHAUSTED,
    ErrorCode.UNAVAILABLE,
    ErrorCode.DEADLINE_EXCEEDED,
}


def error_code_from_value(value: ErrorCode | str) -> ErrorCode:
    if isinstance(value, ErrorCode):
        return value

    try:
        return ErrorCode(value)
    except ValueError:
        return ErrorCode.INTERNAL


def http_status_for_error(code: ErrorCode | str) -> int:
    normalized = error_code_from_value(code)
    return ERROR_HTTP_STATUS_MAP.get(normalized, 500)


def is_retryable_error(code: ErrorCode | str) -> bool:
    normalized = error_code_from_value(code)
    return normalized in RETRYABLE_ERROR_CODES


class DomainError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.retryable = is_retryable_error(code) if retryable is None else retryable

    @property
    def http_status_code(self) -> int:
        return http_status_for_error(self.code)

    def to_error_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code.value,
            message=self.message,
            details=self.details,
            retryable=self.retryable,
        )


class InvalidArgumentError(DomainError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.INVALID_ARGUMENT, message, details=details, retryable=False)


class AuthError(DomainError):
    def __init__(
        self,
        message: str = "Authentication required",
        *,
        code: ErrorCode = ErrorCode.UNAUTHENTICATED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details=details, retryable=False)


class PermissionDeniedError(DomainError):
    def __init__(self, message: str = "Permission denied", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.PERMISSION_DENIED, message, details=details, retryable=False)


class NotFoundError(DomainError):
    def __init__(self, message: str = "Resource not found", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.NOT_FOUND, message, details=details, retryable=False)


class ConflictError(DomainError):
    def __init__(self, message: str = "Resource conflict", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(ErrorCode.CONFLICT, message, details=details, retryable=False)
