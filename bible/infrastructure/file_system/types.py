from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bible.common.errors import DomainError, ErrorCode

@dataclass(slots=True)
class FileStoreResult:
    storage_path: str
    file_hash: str
    size_bytes: int
    filename: str
    domain: str
    kb_index: str


class FileSystemError(DomainError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(code, message, details=details, retryable=retryable)
