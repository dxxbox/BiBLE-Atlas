from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from bible.common.errors import ErrorCode
from bible.common.logger import get_logger
from bible.infrastructure.file_system.base import IFileSystemGateway
from bible.infrastructure.file_system.types import FileStoreResult, FileSystemError


class LocalFileSystemGateway(IFileSystemGateway):
    _SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")

    def __init__(
        self,
        root_dir: str,
        hash_algo: str = "sha256",
        chunk_size: int = 1024 * 1024,
        use_atomic_rename: bool = True,
    ) -> None:
        self._root_dir = Path(root_dir).resolve()
        self._hash_algo = hash_algo
        self._chunk_size = max(1, chunk_size)
        self._use_atomic_rename = use_atomic_rename
        self._logger = get_logger(__name__)
        self._root_dir.mkdir(parents=True, exist_ok=True)

        try:
            hashlib.new(hash_algo)
        except ValueError as exc:
            raise FileSystemError(
                ErrorCode.INVALID_STORAGE_PATH,
                f"Unsupported file hash algorithm: {hash_algo}.",
            ) from exc

    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult:
        started_at = time.monotonic()
        safe_domain = self._sanitize_segment(domain, fallback="UNKNOWN")
        safe_kb_index = self._sanitize_segment(kb_index, fallback="default")
        safe_task_id = self._sanitize_segment(task_id or "default", fallback="default")
        safe_filename = self._sanitize_filename(filename)
        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")

        relative_dir = Path(safe_domain) / safe_kb_index / date_part / safe_task_id
        relative_path = relative_dir / f"{uuid4().hex}_{safe_filename}"
        final_path = self._resolve_storage_path(relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.new(self._hash_algo)
        size_bytes = 0
        temp_path: Path | None = None

        try:
            seek = getattr(file_stream, "seek", None)
            if callable(seek):
                try:
                    seek(0)
                except Exception:
                    pass

            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=str(final_path.parent),
                prefix=".upload-",
                suffix=".tmp",
            ) as temp_file:
                temp_path = Path(temp_file.name)
                while True:
                    chunk = file_stream.read(self._chunk_size)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    temp_file.write(chunk)
                    hasher.update(chunk)
                    size_bytes += len(chunk)

            if self._use_atomic_rename:
                os.replace(temp_path, final_path)
            else:
                shutil.move(str(temp_path), str(final_path))

            storage_path = relative_path.as_posix()
            self._logger.info(
                "Stored file successfully",
                extra={
                    "domain": safe_domain,
                    "kb_index": safe_kb_index,
                    "stored_filename": safe_filename,
                    "storage_path": storage_path,
                    "size_bytes": size_bytes,
                    "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            return FileStoreResult(
                storage_path=storage_path,
                file_hash=hasher.hexdigest(),
                size_bytes=size_bytes,
                filename=safe_filename,
                domain=safe_domain,
                kb_index=safe_kb_index,
            )
        except FileSystemError:
            raise
        except Exception as exc:
            raise FileSystemError(
                ErrorCode.FILE_STORE_FAILED,
                "Failed to store file stream to local filesystem.",
                details={"domain": safe_domain, "kb_index": safe_kb_index, "filename": safe_filename},
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def open_read(self, storage_path: str) -> BinaryIO:
        abs_path = self._resolve_storage_path(storage_path)
        if not abs_path.exists() or not abs_path.is_file():
            raise FileSystemError(
                ErrorCode.FILE_NOT_FOUND,
                f"File not found for storage path: {storage_path}.",
                details={"storage_path": storage_path},
            )
        return abs_path.open("rb")

    def exists(self, storage_path: str) -> bool:
        try:
            abs_path = self._resolve_storage_path(storage_path)
        except FileSystemError:
            return False
        return abs_path.exists() and abs_path.is_file()

    def delete(self, storage_path: str) -> bool:
        try:
            abs_path = self._resolve_storage_path(storage_path)
            if not abs_path.exists():
                return False
            abs_path.unlink()
            return True
        except FileSystemError:
            return False
        except Exception as exc:
            self._logger.warning(
                "Delete file failed",
                extra={"storage_path": storage_path, "error": repr(exc)},
            )
            return False

    def _resolve_storage_path(self, storage_path: str | Path) -> Path:
        relative = Path(storage_path)
        if relative.is_absolute():
            raise FileSystemError(
                ErrorCode.INVALID_STORAGE_PATH,
                f"Absolute storage path is not allowed: {storage_path}.",
            )

        abs_path = (self._root_dir / relative).resolve(strict=False)
        if os.path.commonpath([str(self._root_dir), str(abs_path)]) != str(self._root_dir):
            raise FileSystemError(
                ErrorCode.INVALID_STORAGE_PATH,
                f"Storage path escapes root_dir: {storage_path}.",
            )
        return abs_path

    def _sanitize_segment(self, value: str, fallback: str) -> str:
        text = (value or "").strip()
        if not text:
            return fallback
        cleaned = self._SEGMENT_RE.sub("_", text).strip("._-")
        return cleaned or fallback

    def _sanitize_filename(self, filename: str) -> str:
        basename = Path(filename or "").name.strip()
        if not basename:
            return "unnamed.bin"
        cleaned = self._SEGMENT_RE.sub("_", basename).strip()
        if cleaned in {"", ".", ".."}:
            return "unnamed.bin"
        return cleaned
