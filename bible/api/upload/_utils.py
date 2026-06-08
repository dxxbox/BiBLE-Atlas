"""Shared upload utilities for import API handlers."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bible.common.logger import get_logger

logger = get_logger(__name__)


def get_import_config() -> Any:
    try:
        from bible.config.configure import get_bible_atlas_config
        return get_bible_atlas_config()
    except Exception:
        return None


def generate_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{timestamp}_{unique_id}"


async def save_upload_to_session(
    files: list[UploadFile],
    parser_script: UploadFile | None,
    import_work_dir: str,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Stream each uploaded file to a per-request session directory.

    Uses ``shutil.copyfileobj`` to avoid accumulating file content in memory.

    Returns ``(session_dir, file_refs, parser_script_path)`` where:
    - *session_dir*: absolute path of the created session directory.
    - *file_refs*: list of ``{filename, path, content_type, size}`` dicts.
    - *parser_script_path*: saved path for the optional parser script, or ``None``.
    """
    session_dir = Path(import_work_dir) / generate_session_id()
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Session upload dir created: %s", session_dir)

    file_refs: list[dict[str, Any]] = []
    for uf in files:
        filename = uf.filename or "upload"
        file_path = session_dir / filename
        with open(file_path, "wb") as dest:
            shutil.copyfileobj(uf.file, dest)
        file_refs.append(
            {
                "filename": filename,
                "path": str(file_path),
                "content_type": uf.content_type or "application/octet-stream",
                "size": file_path.stat().st_size,
            }
        )

    parser_script_path: str | None = None
    if parser_script is not None:
        script_filename = parser_script.filename or "parse_upload.py"
        script_path = session_dir / script_filename
        with open(script_path, "wb") as dest:
            shutil.copyfileobj(parser_script.file, dest)
        parser_script_path = str(script_path)

    return str(session_dir), file_refs, parser_script_path


def validate_upload_constraints(
    file_objects: list[dict[str, Any]],
    allowed_extensions: list[str],
    max_count: int,
    max_file_size: int,
    max_total_size: int,
) -> None:
    """Validate file count, extensions, per-file size and total size.

    Raises ``HTTPException(400)`` on the first violation.

    Parameters
    ----------
    file_objects:
        List of ``{filename, size, ...}`` dicts as returned by
        ``save_upload_to_session``.
    allowed_extensions:
        Whitelist of lowercase dot-prefixed extensions (e.g. ``[".md", ".skill"]``).
        Pass an empty list to skip extension checking.
    max_count:
        Maximum number of files allowed per upload.
    max_file_size:
        Maximum size in bytes for a single file.
    max_total_size:
        Maximum combined size in bytes across all files.
    """
    if len(file_objects) > max_count:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ARGUMENT",
                "message": f"Too many files: {len(file_objects)}, max allowed is {max_count}",
            },
        )

    total_size = 0
    for fo in file_objects:
        filename: str = fo["filename"]
        size: int = fo["size"]

        if allowed_extensions:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in allowed_extensions:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "INVALID_ARGUMENT",
                        "message": (
                            f"File '{filename}' has unsupported extension '{ext}'. "
                            f"Allowed: {', '.join(allowed_extensions)}"
                        ),
                    },
                )

        if size > max_file_size:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_ARGUMENT",
                    "message": (
                        f"File '{filename}' is {size} bytes, "
                        f"exceeds max {max_file_size} bytes per file"
                    ),
                },
            )

        total_size += size

    if total_size > max_total_size:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ARGUMENT",
                "message": (
                    f"Total upload size {total_size} bytes "
                    f"exceeds max {max_total_size} bytes"
                ),
            },
        )


def build_task_response(task_id: str, repository: Any) -> JSONResponse:
    """Build a standard task-status JSON response from the given repository."""
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Task {task_id!r} not found"},
        )
    return JSONResponse(
        content={
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }
    )
