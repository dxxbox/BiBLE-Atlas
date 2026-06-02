from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bible.common.errors import DomainError, ErrorCode
from bible.common.logger import get_logger
from bible.features import get_task_repository, get_task_service

logger = get_logger(__name__)

router = APIRouter()

_SUPPORTED_TAG = "memory"


@router.post("/api/import/memory", tags=["Import"], status_code=202)
async def import_memory(
    files: list[UploadFile] = File(...),
    kb_index: str = Form(...),
    tag: str = Form(...),
    parser_script: UploadFile | None = File(None),
    vector_model: str | None = Form(None),
    parser_context: str | None = Form(None),
) -> JSONResponse:
    logger.info(
        "POST /api/import/memory received: kb_index=%s tag=%s files=%d has_parser_script=%s",
        kb_index, tag, len(files), parser_script is not None,
    )
    if tag != _SUPPORTED_TAG:
        raise HTTPException(
            status_code=400,
            detail={"code": "TAG_INVALID", "message": f"tag must be 'memory', got '{tag}'"},
        )

    if not kb_index or not kb_index.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_ARGUMENT", "message": "kb_index is required"},
        )

    parser_script_filename: str | None = parser_script.filename if parser_script is not None else None

    parsed_context: dict[str, Any] | None = None
    if parser_context:
        try:
            parsed_context = json.loads(parser_context)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_ARGUMENT", "message": "parser_context must be valid JSON"},
            )

    import shutil as _shutil

    config = _get_config()

    # Stream every uploaded file directly to a per-request session directory
    # under import_work_dir (configured in bible-atlas.yaml).  No file content
    # is held in memory — _save_upload_to_session uses shutil.copyfileobj to
    # copy in chunks and returns file paths instead of bytes.
    # The session dir path is passed to the async task so the service can clean
    # it up after the task finishes (success or keep_failed_workspace failure).
    session_dir, file_refs, parser_script_path = await _save_upload_to_session(
        files, parser_script, config
    )

    # If anything fails before the task is successfully submitted the session
    # dir is removed here; once submit() succeeds the service owns cleanup.
    task_submitted = False
    try:
        _validate_upload_constraints(file_refs, config)

        # Pass file paths (not content) to the task payload.  The service reads
        # files directly from disk via the paths in _files and parser_script_path.
        payload: dict[str, Any] = {
            "kb_index": kb_index,
            "tag": tag,
            "vector_model": vector_model,
            "parser_context": parsed_context,
            "parser_script_path": parser_script_path,
            "parser_script_filename": parser_script_filename,
            "_session_upload_dir": session_dir,
            "_files": file_refs,
        }

        try:
            task_service = get_task_service()
            result = task_service.submit(task_type="import.memory", payload=payload)
            task_submitted = True
        except DomainError as exc:
            logger.error("Task submission failed: [%s] %s", exc.code.value, exc.message)
            raise HTTPException(
                status_code=exc.http_status_code,
                detail={"code": exc.code.value, "message": exc.message},
            )
        except Exception as exc:
            logger.exception("Unexpected error during task submission")
            raise HTTPException(
                status_code=500,
                detail={"code": "INTERNAL_ERROR", "message": str(exc)},
            )
    finally:
        if not task_submitted:
            _shutil.rmtree(session_dir, ignore_errors=True)
            logger.info("Session upload dir removed (task not submitted): %s", session_dir)

    return JSONResponse(
        status_code=202,
        content={
            "task_id": result["task_id"],
            "domain": "MEMORY",
            "kb_index": kb_index,
            "tag": tag,
            "status": result["status"],
        },
    )


@router.get("/api/import/memory/task/{task_id}", tags=["Import"])
async def get_import_task(task_id: str) -> JSONResponse:
    repository = get_task_repository()
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Task {task_id!r} not found"})
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_config() -> Any:
    try:
        from bible.config.configure import get_bible_atlas_config
        return get_bible_atlas_config()
    except Exception:
        return None


def _generate_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{timestamp}_{unique_id}"


async def _save_upload_to_session(
    files: list[UploadFile],
    parser_script: UploadFile | None,
    config: Any,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Stream each uploaded file directly to a per-request session directory.

    Uses ``shutil.copyfileobj`` to copy in chunks without accumulating file
    content in memory.

    Returns ``(session_dir, file_refs, parser_script_path)`` where:
    - *session_dir* is the absolute path to the created directory.
    - *file_refs* carries ``{filename, path, content_type, size}`` — no content bytes.
    - *parser_script_path* is the saved path for the parser script (or ``None``).
    """
    import shutil as _shutil
    from bible.config.configure import ImportMemoryConfig

    import_memory_cfg: ImportMemoryConfig = (
        config.import_memory
        if config is not None and hasattr(config, "import_memory")
        else ImportMemoryConfig()
    )

    session_dir = Path(import_memory_cfg.import_work_dir) / _generate_session_id()
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Session upload dir created: %s", session_dir)

    file_refs: list[dict[str, Any]] = []
    for uf in files:
        filename = uf.filename or "upload"
        file_path = session_dir / filename
        with open(file_path, "wb") as dest:
            _shutil.copyfileobj(uf.file, dest)
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
            _shutil.copyfileobj(parser_script.file, dest)
        parser_script_path = str(script_path)

    return str(session_dir), file_refs, parser_script_path


def _validate_upload_constraints(file_objects: list[dict[str, Any]], config: Any) -> None:
    """Validate count, extension, per-file size and total size against config limits."""
    from bible.config.configure import UploadConstraintsConfig
    upload: UploadConstraintsConfig = (
        config.upload if config is not None and isinstance(config.upload, UploadConstraintsConfig)
        else UploadConstraintsConfig()
    )

    max_count = upload.max_file_count
    max_file_size = upload.max_file_size
    max_total_size = upload.max_total_size
    allowed_ext = upload.allowed_extensions

    # 1. File count
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

        # 2. Extension whitelist
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if allowed_ext and ext not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_ARGUMENT",
                    "message": (
                        f"File '{filename}' has unsupported extension '{ext}'. "
                        f"Allowed: {', '.join(allowed_ext)}"
                    ),
                },
            )

        # 3. Per-file size
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

    # 4. Total size
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
