from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class MemoryImportPayload:
    kb_index: str
    tag: Literal["memory"]
    vector_model: str | None
    parser_context: dict[str, Any] | None
    parser_script_path: str | None = None
    parser_script_filename: str | None = None
    session_upload_dir: str | None = None


@dataclass
class FileStoreResult:
    filename: str
    storage_path: str
    file_hash: str
    size_bytes: int


@dataclass
class ParseResult:
    chunks: list[dict[str, Any]]
    search_profile: dict[str, Any]
    local_file_storage_plan: dict[str, Any] | None
