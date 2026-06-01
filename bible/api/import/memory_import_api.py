from __future__ import annotations
from datetime import datetime
from typing import Any

import json
import uuid
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bible.common.logger import get_logger
from bible.common.errors import ErrorCode

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



    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "result": {
                "kb_index": kb_index,
                "tag": tag,
                "files": filenames,
                "parser_script": parser_script_filename,
                "vector_model": vector_model,
                "parser_context": parser_context,
            },
        },
    )


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
    from bible.config.configure import get_bible_atlas_config

    import_memory_cfg: ImportMemoryConfig