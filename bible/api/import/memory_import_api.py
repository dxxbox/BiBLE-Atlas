from __future__ import annotations
from datetime import datetime
from typing import Any
from pathlib import Path

import json
import uuid
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bible.common.logger import get_logger
from bible.common.errors import ErrorCode, DomainError

from bible.features import get_task_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/import", tags=["Import"])

_SUPPORTED_TAG = "memory"


@router.post("/memory", tags=["Import"], status_code=202)
async def import_memory(
    files: list[UploadFile] = File(...),
    kb_index: str = Form(...),
    tag: str = Form(...),
    parser_script: UploadFile | None = File(None),
    vector_model: str | None = Form(None),
    parser_context: str | None = Form(None),
) -> JSONResponse:
    parser_script_filename = parser_script.filename if parser_script else None
    filenames = [file.filename for file in files]

    logger.info(
        "Received import request with %s files, kb_index=%s, tag=%s, parser_script=%s, "
        "vector_model=%s, parser_context=%s",
        len(files),
        kb_index,
        tag,
        parser_script_filename,
        vector_model,
        parser_context,
    )

    if tag != _SUPPORTED_TAG:
        raise HTTPException(
            status_code=400,
            detail= {"code": ErrorCode.INVALID_TAG, "message": f"Unsupported tag '{tag}'. Supported tag is '{_SUPPORTED_TAG}'."},
        )

    if not kb_index or not kb_index.strip():
        raise HTTPException(
            status_code=400, 
            detail= {"code": ErrorCode.INVALID_ARGUMENT, "message": "kb_index is required and cannot be empty"}
        )
    
    parsed_context: dict[str, Any] | None = None
    if parser_context:
        try:
            parsed_context = json.loads(parser_context)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail={"code": ErrorCode.INVALID_ARGUMENT, "message": f"parser_context is not valid JSON: {str(e)}"},
            )
        
    import shutil as _shutil

    config = _get_config()

    session_dir, file_refs, parser_script_path = await _save_upload_to_session(
        files=files,
        parser_script=parser_script,
        config=config,
    )

    task_submitted = False
    try:
        _validate_upload_constraints(file_refs, config)

        # Here you would typically enqueue a background task to process the files
        # For example:
        # from bible.tasks import process_imported_files
        # process_imported_files.delay(session_dir, kb_index, tag, parser_script_path, vector_model, parsed_context)

        payload: dict[str, Any] = {
            "kb_index": kb_index,
            "tag": tag,
            "_files": file_refs,
            "parser_script": parser_script_path,
            "vector_model": vector_model,
            "parser_context": parsed_context,
            "parser_script_path": parser_script_path,
            "parsser_script_filename": parser_script_filename, 
            "_session_upload_dir": session_dir,  # For debugging, not returned in response
        }

        try:
            task_service = get_task_service()
            result = task_service.submit_task(
                task_name="import_memory",
                payload=payload)
            task_submitted = True
        except DomainError as exc:
            logger.error("Failed to submit import task: %s", str(exc))
            raise HTTPException(
                status_code=exc.http_status_code or 500,
                detail={"code": exc.code.value, "message": f"Failed to submit import task: {str(exc)}"},
            )
        except Exception as exc:
            logger.error("Unexpected error during task submission: %s", str(exc))
            raise HTTPException(
                status_code=500,
                detail={"code": "TASK_SUBMISSION_ERROR", "message": f"Unexpected error during task submission: {str(exc)}"},
            )
    finally:
        if not task_submitted:
            _shutil.rmtree(session_dir, ignore_errors=True)
            logger.warning("Import task was not submitted, cleaning up session dir: %s", session_dir)

    return JSONResponse(
        status_code=202,
        content={
            "task_id": result.task_id,
            "domain": "MEMORY",
            "kb_index": kb_index,
            "tag": tag,
            "status": result.status,
        },
    )

@router.get("/memory/task/{task_id}", tags=["Import"])
async def get_import_task_status(task_id: str) -> JSONResponse:

    repository = get_task_service().repository
    task = repository.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TASK_NOT_FOUND", "message": f"No task found with id '{task_id}'"},
        )

    return JSONResponse(
        content = {
            "task_id": task_id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }
    )
    pass

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

# --------------------------------------------------------------
#  Helper functions for handling uploads and sessions
# --------------------------------------------------------------

def _get_config() -> Any:
    try:
        from bible.config.configure import get_bible_atlas_config
        return get_bible_atlas_config()
    except ImportError:
        logger.warning("Could not import get_bible_atlas_config, returning empty config")
        return None
    
def _generate_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return f"{timestamp}_{unique_id}"

async def _save_upload_to_session (
        files: list[UploadFile],
        parser_script: UploadFile | None,
        config: Any,
) -> tuple [str, list[dict[str, Any]], str | None]:
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
