"""Exception model for bible-cli."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COMMAND_NOT_IMPLEMENTED_EXIT_CODE = 3


@dataclass(slots=True)
class BibleCLIError(Exception):
    """Base error with stable code/details fields for CLI output."""

    message: str
    code: str = "CLI_ERROR"
    exit_code: int = 1
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclass(slots=True)
class BibleAPIError(BibleCLIError):
    """Typed API/domain error restored from server error payload."""

    code: str = "INTERNAL"
    retryable: bool = False
    status_code: int | None = None

# ----------------------- CLI Error -----------------------
class CommandNotImplementedError(BibleCLIError):
    """Raised when a command path is declared but not implemented yet."""

    def __init__(self, command_path: str) -> None:
        super().__init__(
            message=f"Command '{command_path}' is not implemented yet.",
            code="CLI_NOT_IMPLEMENTED",
            exit_code=COMMAND_NOT_IMPLEMENTED_EXIT_CODE,
            details={"command_path": command_path},
        )

# ----------------------- API Error -----------------------
class InvalidArgumentError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="INVALID_ARGUMENT", details=details, retryable=False)


class UnauthenticatedError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="UNAUTHENTICATED", details=details, retryable=False)


class PermissionDeniedError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="PERMISSION_DENIED", details=details, retryable=False)


class NotFoundError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="NOT_FOUND", details=details, retryable=False)


class ConflictError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="CONFLICT", details=details, retryable=False)


class ResourceExhaustedError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="RESOURCE_EXHAUSTED", details=details, retryable=True)


class UnavailableError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="UNAVAILABLE", details=details, retryable=True)


class DeadlineExceededError(BibleAPIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, code="DEADLINE_EXCEEDED", details=details, retryable=True)

# ----------------------- Mapping Server Error to Local Error -----------------------
class ProcessingError(BibleAPIError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "INTERNAL",
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            details=details,
            retryable=retryable,
            status_code=status_code,
        )


ERROR_CODE_EXCEPTION_MAP: dict[str, type[BibleAPIError]] = {
    "INVALID_ARGUMENT": InvalidArgumentError,
    "UNAUTHENTICATED": UnauthenticatedError,
    "AUTH_INVALID_API_KEY": UnauthenticatedError,
    "PERMISSION_DENIED": PermissionDeniedError,
    "NOT_FOUND": NotFoundError,
    "TENANT_NOT_FOUND": NotFoundError,
    "TASK_NOT_FOUND": NotFoundError,
    "CONFLICT": ConflictError,
    "ALREADY_EXISTS": ConflictError,
    "KB_INDEX_BINDING_CONFLICT": ConflictError,
    "RESOURCE_EXHAUSTED": ResourceExhaustedError,
    "UNAVAILABLE": UnavailableError,
    "VECTOR_MODEL_NOT_READY": UnavailableError,
    "DEADLINE_EXCEEDED": DeadlineExceededError,
    # v4 MEMORY-specific parse/import errors
    "META_JSON_REQUIRED": InvalidArgumentError,
    "META_JSON_SCHEMA_INVALID": InvalidArgumentError,
    "PARSE_RESULT_SCHEMA_INVALID": InvalidArgumentError,
    "IMPORT_TASK_REJECTED": InvalidArgumentError,
    "MEMORY_ID_REQUIRED": InvalidArgumentError,
}


def map_server_error(
    *,
    code: str | None,
    message: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    status_code: int | None = None,
) -> BibleAPIError:
    """Map a server error payload to a local typed exception."""
    normalized_code = code or "INTERNAL"
    error_type = ERROR_CODE_EXCEPTION_MAP.get(normalized_code)

    if error_type is None:
        return ProcessingError(
            message=message,
            code=normalized_code,
            details=details,
            retryable=retryable,
            status_code=status_code,
        )

    error = error_type(message=message, details=details)
    error.retryable = retryable
    error.status_code = status_code
    # Preserve domain-specific codes while using canonical local classes.
    error.code = normalized_code
    return error
