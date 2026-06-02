from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from bible.common.logger import get_logger

from ._utils import sanitize_filename, sanitize_segment
from .types import FileStoreResult, FileSystemError

UTC = timezone.utc


class LocalFileSystemGateway:

    def __init__(
        self,
        root_dir: str,
        hash_algo: str = "sha256",
        chunk_size: int = 1024 * 1024,
        use_atomic_rename: bool = True,
    ) -> None:
        self._root_dir = Path(root_dir).resolve()
        self._hash_algo = hash_algo
        self._chunk_size = chunk_size
        self._use_atomic_rename = use_atomic_rename
        self._logger = get_logger(__name__)
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult:
        started_at = time.monotonic()
        safe_domain = sanitize_segment(domain, fallback="UNKNOWN")
        safe_kb_index = sanitize_segment(kb_index, fallback="default")
        safe_task_id = sanitize_segment(task_id or "default", fallback="default")
        safe_filename = sanitize_filename(filename)
        date_part = datetime.now(UTC).strftime("%Y%m%d")

        relative_path = Path(safe_domain) / safe_kb_index / date_part / safe_task_id / safe_filename
        final_path = self._resolve_storage_path(relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # Stream directly to a temp file while hashing — single pass, no extra memory.
        hasher = hashlib.new(self._hash_algo)
        size_bytes = 0
        temp_path: Path | None = None

        try:
            if hasattr(file_stream, "seek"):
                try:
                    file_stream.seek(0)
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
            temp_path = None  # ownership transferred

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self._logger.info(
                "Stored file successfully: domain=%s kb_index=%s path=%s size=%d bytes elapsed=%dms",
                safe_domain,
                safe_kb_index,
                relative_path.as_posix(),
                size_bytes,
                elapsed_ms,
            )

            return FileStoreResult(
                storage_path=relative_path.as_posix(),
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
                code="FILE_STORE_FAILED",
                message="Failed to store file stream to local filesystem.",
                details={
                    "domain": safe_domain,
                    "kb_index": safe_kb_index,
                    "filename": safe_filename,
                },
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def open_read(self, storage_path: str) -> BinaryIO:
        abs_path = self._resolve_storage_path(storage_path)
        if not abs_path.exists() or not abs_path.is_file():
            raise FileSystemError(
                code="FILE_NOT_FOUND",
                message=f"File not found for storage path: {storage_path}",
            )
        return abs_path.open("rb")  # type: ignore[return-value]

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
            self._logger.warning("Delete file failed: storage_path=%s error=%s", storage_path, repr(exc))
            return False

    def _resolve_storage_path(self, storage_path: str | Path) -> Path:
        relative = Path(storage_path)
        if relative.is_absolute():
            raise FileSystemError(
                code="INVALID_STORAGE_PATH",
                message=f"Absolute path is not allowed: {storage_path}",
            )
        abs_path = (self._root_dir / relative).resolve(strict=False)
        root = str(self._root_dir)
        candidate = str(abs_path)
        if os.path.commonpath([root, candidate]) != root:
            raise FileSystemError(
                code="INVALID_STORAGE_PATH",
                message=f"Storage path escapes root_dir: {storage_path}",
            )
        return abs_path
