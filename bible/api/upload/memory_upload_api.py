from __future__ import annotations

import json
import shutil
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bible.common.errors import DomainError
from bible.common.logger import get_logger
from bible.features import get_task_repository, get_task_service
from ._utils import (
    build_task_response,
    get_import_config,
    save_upload_to_session,
    validate_upload_constraints,
)

logger = get_logger(__name__)

router = APIRouter()

_SUPPORTED_TAG = "memory"
_get_config = get_import_config  # kept for backward compatibility with test patches


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

    config = _get_config()

    from bible.config.configure import ImportMemoryConfig, UploadConstraintsConfig
    import_memory_cfg: ImportMemoryConfig = (
        config.import_memory
        if config is not None and hasattr(config, "import_memory")
        else ImportMemoryConfig()
    )

    session_dir, file_refs, parser_script_path = await save_upload_to_session(
        files, parser_script, import_memory_cfg.import_work_dir
    )

    task_submitted = False
    try:
        upload: UploadConstraintsConfig = (
            config.upload
            if config is not None and isinstance(config.upload, UploadConstraintsConfig)
            else UploadConstraintsConfig()
        )
        validate_upload_constraints(
            file_refs,
            allowed_extensions=upload.allowed_extensions,
            max_count=upload.max_file_count,
            max_file_size=upload.max_file_size,
            max_total_size=upload.max_total_size,
        )

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
            shutil.rmtree(session_dir, ignore_errors=True)
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
    return build_task_response(task_id, get_task_repository())
