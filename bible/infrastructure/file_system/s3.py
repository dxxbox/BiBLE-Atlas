from __future__ import annotations

import time
from typing import BinaryIO

from bible.common.logger import get_logger

from ._utils import build_storage_path, read_and_hash, sanitize_filename, sanitize_segment, to_object_key
from .types import FileStoreResult, FileSystemError

logger = get_logger(__name__)


class S3FileSystemGateway:
    """AWS S3-backed file system gateway using the ``boto3`` S3 client.

    Constructor args:
        client    – ``boto3.client("s3")`` instance (injected by factory)
        bucket    – target bucket name
        prefix    – optional object key prefix, e.g. ``"bible-files"`` (no slashes)
        hash_algo – digest algorithm for content hashing (default: sha256)
        chunk_size – read buffer size in bytes (default: 1 MB)

    storage_path convention:
        Always a logical relative path: ``MEMORY/kb1/20260522/task-id/file.md``.
        The bucket name and prefix are never stored inside storage_path so the
        path stays portable across backends and deployments.

    Note on hashing:
        S3 ETag is an MD5 of uploaded parts, not SHA-256. We compute SHA-256
        separately in-flight before upload so the hash remains backend-agnostic.
    """

    def __init__(
        self,
        client: object,
        bucket: str,
        prefix: str = "",
        hash_algo: str = "sha256",
        chunk_size: int = 1024 * 1024,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._hash_algo = hash_algo
        self._chunk_size = chunk_size

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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
        safe_filename = sanitize_filename(filename)
        storage_path = build_storage_path(domain, kb_index, filename, task_id)
        key = to_object_key(storage_path, self._prefix)

        try:
            buf, file_hash, size_bytes = read_and_hash(
                file_stream, chunk_size=self._chunk_size, hash_algo=self._hash_algo
            )
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=buf,
                ContentLength=size_bytes,
            )

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "Stored file to S3: domain=%s kb_index=%s path=%s size=%d bytes elapsed=%dms",
                safe_domain, safe_kb_index, storage_path, size_bytes, elapsed_ms,
            )
            return FileStoreResult(
                storage_path=storage_path,
                file_hash=file_hash,
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
                message=f"Failed to store object to S3 bucket '{self._bucket}': {exc}",
                details={"bucket": self._bucket, "key": key},
            ) from exc

    def open_read(self, storage_path: str) -> BinaryIO:
        """Return an open stream for the object. Caller must close it (use ``with``)."""
        key = to_object_key(storage_path, self._prefix)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"]  # botocore StreamingBody
        except Exception as exc:
            if _is_s3_not_found(exc):
                raise FileSystemError(
                    code="FILE_NOT_FOUND",
                    message=f"Object not found in S3: {storage_path}",
                ) from exc
            raise FileSystemError(
                code="FILE_NOT_FOUND",
                message=f"Failed to read object from S3: {exc}",
                details={"bucket": self._bucket, "key": key},
            ) from exc

    def exists(self, storage_path: str) -> bool:
        key = to_object_key(storage_path, self._prefix)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as exc:
            if _is_s3_not_found(exc):
                return False
            logger.warning("S3 exists check failed for %s: %s", storage_path, exc)
            return False

    def delete(self, storage_path: str) -> bool:
        key = to_object_key(storage_path, self._prefix)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.debug("Deleted S3 object: %s", storage_path)
            return True
        except Exception as exc:
            logger.warning("Failed to delete S3 object %s: %s", storage_path, exc)
            return False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_s3_not_found(exc: Exception) -> bool:
    """Return True if the botocore ClientError signals a missing object (404 / NoSuchKey)."""
    response = getattr(exc, "response", None)
    if response:
        error = response.get("Error", {})
        code = str(error.get("Code", ""))
        status = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        return code in ("404", "NoSuchKey") or status == 404
    return "404" in str(exc) or "NoSuchKey" in str(exc)
