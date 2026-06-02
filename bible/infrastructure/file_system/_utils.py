from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

UTC = timezone.utc
_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_segment(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    cleaned = _SEGMENT_RE.sub("_", text)
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def sanitize_filename(filename: str) -> str:
    basename = Path(filename or "").name.strip()
    if not basename:
        return "unnamed.bin"
    cleaned = _SEGMENT_RE.sub("_", basename)
    cleaned = cleaned.strip()
    if cleaned in {".", "..", ""}:
        return "unnamed.bin"
    return cleaned


def build_storage_path(
    domain: str,
    kb_index: str,
    filename: str,
    task_id: str | None = None,
) -> str:
    """Build the relative storage path: domain/kb_index/YYYYMMDD/task_id/filename.

    This path is backend-agnostic and never includes the bucket name or prefix.
    """
    safe_domain = sanitize_segment(domain, fallback="UNKNOWN")
    safe_kb_index = sanitize_segment(kb_index, fallback="default")
    safe_task_id = sanitize_segment(task_id or "default", fallback="default")
    safe_filename = sanitize_filename(filename)
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    return f"{safe_domain}/{safe_kb_index}/{date_part}/{safe_task_id}/{safe_filename}"


def to_object_key(storage_path: str, prefix: str) -> str:
    """Prepend prefix (if any) to form the actual object key in the bucket.

    The prefix is a deployment-level concern and must NOT be stored in storage_path.
    """
    prefix = prefix.strip("/")
    if prefix:
        return f"{prefix}/{storage_path}"
    return storage_path


def read_and_hash(
    file_stream: BinaryIO,
    chunk_size: int = 1024 * 1024,
    hash_algo: str = "sha256",
) -> tuple[io.BytesIO, str, int]:
    """Read *file_stream* into a BytesIO buffer while computing a content hash.

    Returns:
        buf        – seeked-to-start BytesIO ready for upload
        hex_digest – hash of the full content
        size_bytes – total bytes read
    """
    if hasattr(file_stream, "seek"):
        try:
            file_stream.seek(0)
        except Exception:
            pass

    hasher = hashlib.new(hash_algo)
    buf = io.BytesIO()
    size_bytes = 0

    while True:
        chunk = file_stream.read(chunk_size)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        buf.write(chunk)
        hasher.update(chunk)
        size_bytes += len(chunk)

    buf.seek(0)
    return buf, hasher.hexdigest(), size_bytes
