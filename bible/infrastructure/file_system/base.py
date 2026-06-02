from __future__ import annotations

from typing import BinaryIO, Protocol

from .types import FileStoreResult


class IFileSystemGateway(Protocol):
    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult:
        ...

    def open_read(self, storage_path: str) -> BinaryIO:
        ...

    def exists(self, storage_path: str) -> bool:
        ...

    def delete(self, storage_path: str) -> bool:
        ...
