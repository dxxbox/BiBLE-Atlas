from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FileSystemErrorCode = Literal[
    "FILE_STORE_FAILED",
    "FILE_NOT_FOUND",
    "FILE_DELETE_FAILED",
    "INVALID_STORAGE_PATH",
    "FILE_SYSTEM_BACKEND_UNSUPPORTED",
]


@dataclass(slots=True)
class FileStoreResult:
    storage_path: str
    file_hash: str
    size_bytes: int
    filename: str
    domain: str
    kb_index: str


@dataclass(slots=True)
class FileSystemError(RuntimeError):
    code: FileSystemErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
