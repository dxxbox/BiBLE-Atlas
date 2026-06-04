from __future__ import annotations

import importlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile

from bible.common.errors import DomainError
from bible.common.logger import get_logger
from bible.test_mode.resolver import FixtureConflictError, FixtureResolver
from bible.test_mode.constants import SERVICE_NAME
from bible.test_mode.responses import binary_response, error_response, json_response
from bible.test_mode.schemas import RequestContext, ResponseFixture, TaskFixture
from bible.test_mode.task_store import InMemoryTaskStore
from bible.test_mode.validators import (
    ValidationFailure,
    validate_download,
    validate_import_fields,
    validate_search,
)

router = APIRouter()
logger = get_logger(__name__)
_preflight_module = importlib.import_module("bible.features.import.preflight")
ImportFileRef = _preflight_module.ImportFileRef
run_import_preflight = _preflight_module.run_import_preflight


@router.get("/health")
async def health(request: Request):
    _log_client_input(_context(request))
    logger.info("Test Mode health check")
    return json_response({"status": "ok", "service": SERVICE_NAME, "mode": "server"})


@router.post("/api/search/knowledge-base")
async def search_knowledge_base(request: Request):
    return await _search(request, "KNOWLEDGE_BASE")


@router.post("/api/search/skill")
async def search_skill(request: Request):
    return await _search(request, "SKILL")


@router.post("/api/search/memory")
async def search_memory(request: Request):
    return await _search(request, "MEMORY")


async def _search(request: Request, domain: str):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValidationFailure("INVALID_ARGUMENT", "request body must be a JSON object")
        context = _context(request, domain=domain, body=body)
        _log_client_input(context)
        validate_search(domain, body)
        fixture = _resolver(request).resolve(context)
        if fixture is None:
            logger.warning("Test Mode search fixture miss domain=%s path=%s", domain, request.url.path)
            return json_response(_empty_search_payload(domain, body))
        logger.info(
            "Test Mode search fixture hit domain=%s path=%s fixture_id=%s",
            domain,
            request.url.path,
            fixture.id or "<anonymous>",
        )
        return _fixture_response(fixture.response)
    except ValidationFailure as exc:
        logger.warning("Test Mode search validation failed domain=%s code=%s message=%s", domain, exc.code, exc.message)
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    except FixtureConflictError as exc:
        logger.error("Test Mode search fixture conflict domain=%s error=%s", domain, exc)
        return error_response("FIXTURE_CONFLICT", str(exc), 500)
    except Exception as exc:
        logger.warning("Test Mode search invalid JSON domain=%s error=%s", domain, exc)
        return error_response("INVALID_ARGUMENT", f"invalid JSON body: {exc}", 400)


@router.post("/api/import/knowledge-base")
async def import_knowledge_base(request: Request):
    return await _import_domain(request, "KNOWLEDGE_BASE")


@router.post("/api/import/skill")
async def import_skill(request: Request):
    return await _import_domain(request, "SKILL")


@router.post("/api/import/memory")
async def import_memory(request: Request):
    return await _import_domain(request, "MEMORY")


async def _import_domain(
    request: Request,
    domain: str,
):
    tmp_dir = Path(tempfile.mkdtemp(prefix="bible_test_mode_import_"))
    try:
        files, parser_script, fields = await _parse_import_form(request)
        _log_client_input(
            _context(
                request,
                domain=domain,
                multipart=_raw_import_multipart(fields, files, parser_script),
            )
        )
        kb_index = fields.get("kb_index") or ""
        tag = fields.get("tag") or ""
        vector_model = fields.get("vector_model")
        parser_context = fields.get("parser_context")
        parsed_context = validate_import_fields(
            domain=domain,
            files=files,
            kb_index=kb_index,
            tag=tag,
            parser_context=parser_context,
        )
        refs, parser_script_path = await _persist_uploads(tmp_dir, files, parser_script)
        preflight = run_import_preflight(
            domain=domain,
            files=refs,
            parser_script_path=parser_script_path,
            parser_context=parsed_context,
        )
        logger.info(
            "Test Mode import preflight passed domain=%s path=%s files=%d kb_index=%s tag=%s",
            domain,
            request.url.path,
            len(refs),
            kb_index,
            tag,
        )
        fields = {
            "kb_index": kb_index,
            "tag": tag,
            "vector_model": vector_model,
            "parser_context": parsed_context,
        }
        context = _context(
            request,
            domain=domain,
            multipart={
                "fields": fields,
                "files": [_file_ref_input(ref) for ref in refs],
                "file_names": [ref.filename for ref in refs],
                "parser_script": _parser_script_input(parser_script, parser_script_path),
            },
        )
        fixture = _resolver(request).resolve(context)
        if fixture is not None:
            payload = fixture.response.json_body or {}
            _ensure_task(request, payload, operation="import", domain=domain, tag=tag)
            logger.info(
                "Test Mode import fixture hit domain=%s fixture_id=%s status=%s",
                domain,
                fixture.id or "<anonymous>",
                payload.get("status"),
            )
            return _fixture_response(fixture.response)
        task_id = f"import_{domain.lower()}_builtin"
        payload = {
            "success": True,
            "task_id": task_id,
            "domain": domain,
            "kb_index": kb_index,
            "tag": tag,
            "status": "completed",
            "result": {"imported": 1, "skipped": 0, "failed": 0, "preflight": preflight},
        }
        _task_store(request).create(
            operation="import",
            domain=domain,  # type: ignore[arg-type]
            tag=tag,
            task_id=task_id,
            status="completed",
            result=payload["result"],
        )
        logger.info("Test Mode import builtin completed domain=%s task_id=%s", domain, task_id)
        return json_response(payload, 202)
    except ValidationFailure as exc:
        logger.warning("Test Mode import validation failed domain=%s code=%s message=%s", domain, exc.code, exc.message)
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    except DomainError as exc:
        logger.warning("Test Mode import preflight failed domain=%s code=%s message=%s", domain, exc.code.value, exc.message)
        return error_response(exc.code.value, exc.message, exc.http_status_code, exc.details)
    except ValueError as exc:
        logger.warning("Test Mode import failed domain=%s error=%s", domain, exc)
        return error_response("INVALID_ARGUMENT", str(exc), 400)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/api/download/skill/file")
async def download_skill_file(request: Request):
    return await _download(request, "SKILL", batch=False)


@router.post("/api/download/skill/batch")
async def download_skill_batch(request: Request):
    return await _download(request, "SKILL", batch=True)


@router.post("/api/download/memory/file")
async def download_memory_file(request: Request):
    return await _download(request, "MEMORY", batch=False)


@router.post("/api/download/memory/batch")
async def download_memory_batch(request: Request):
    return await _download(request, "MEMORY", batch=True)


async def _download(request: Request, domain: str, *, batch: bool):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValidationFailure("INVALID_ARGUMENT", "request body must be a JSON object")
        context = _context(request, domain=domain, body=body)
        _log_client_input(context)
        validate_download(domain, body, batch=batch)
        fixture = _resolver(request).resolve(context)
        if fixture is None:
            logger.warning("Test Mode download fixture miss domain=%s path=%s", domain, request.url.path)
            if domain == "SKILL" and not batch:
                storage_path = body.get("storage_path")
                return error_response(
                    "SKILL_NOT_FOUND",
                    f"Skill {storage_path!r} not found in Test Mode fixtures.",
                    404,
                )
            return error_response("NOT_FOUND", "fixture route not found", 404)
        payload = fixture.response.json_body or {}
        _ensure_task(request, payload, operation="download", domain=domain, tag=body.get("tag"))
        logger.info(
            "Test Mode download fixture hit domain=%s path=%s fixture_id=%s task_id=%s status=%s",
            domain,
            request.url.path,
            fixture.id or "<anonymous>",
            payload.get("task_id"),
            payload.get("status"),
        )
        return _fixture_response(fixture.response)
    except ValidationFailure as exc:
        logger.warning("Test Mode download validation failed domain=%s code=%s message=%s", domain, exc.code, exc.message)
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    except FixtureConflictError as exc:
        logger.error("Test Mode download fixture conflict domain=%s error=%s", domain, exc)
        return error_response("FIXTURE_CONFLICT", str(exc), 500)
    except Exception as exc:
        logger.warning("Test Mode download invalid JSON domain=%s error=%s", domain, exc)
        return error_response("INVALID_ARGUMENT", f"invalid JSON body: {exc}", 400)


@router.get("/api/download/skill/artifact/{artifact_id}")
async def get_skill_artifact(artifact_id: str, request: Request):
    return _get_artifact("SKILL", artifact_id, request)


@router.get("/api/download/memory/artifact/{artifact_id}")
async def get_memory_artifact(artifact_id: str, request: Request):
    return _get_artifact("MEMORY", artifact_id, request)


def _get_artifact(domain: str, artifact_id: str, request: Request):
    _log_client_input(_context(request, domain=domain))
    artifacts = request.app.state.artifact_store
    if artifacts.is_expired(artifact_id):
        logger.warning("Test Mode artifact expired domain=%s artifact_id=%s", domain, artifact_id)
        return error_response("DOWNLOAD_ARTIFACT_EXPIRED", f"Artifact {artifact_id!r} is expired", 410)
    found = artifacts.get(artifact_id, domain)
    if found is None:
        logger.warning("Test Mode artifact not found domain=%s artifact_id=%s", domain, artifact_id)
        return error_response("DOWNLOAD_ARTIFACT_NOT_FOUND", f"Artifact {artifact_id!r} not found", 404)
    artifact, body = found
    logger.info(
        "Test Mode artifact downloaded domain=%s artifact_id=%s file_name=%s bytes=%d",
        domain,
        artifact_id,
        artifact.file_name,
        len(body),
    )
    return binary_response(body, content_type=artifact.content_type, file_name=artifact.file_name)


@router.get("/api/control/admin/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    _log_client_input(_context(request))
    task = _task_store(request).get(task_id)
    if task is None:
        return error_response("TASK_NOT_FOUND", f"Task {task_id!r} not found", 404)
    logger.info("Test Mode task queried task_id=%s status=%s", task_id, task.status)
    return json_response(_task_payload(task))


@router.delete("/api/control/admin/tasks/{task_id}")
async def cancel_task(task_id: str, request: Request):
    _log_client_input(_context(request))
    task, code = _task_store(request).cancel(task_id)
    if task is None:
        return error_response("TASK_NOT_FOUND", f"Task {task_id!r} not found", 404)
    if code == "TASK_ALREADY_COMPLETED":
        return error_response(code, f"Task {task_id!r} is already completed", 409)
    if code == "TASK_ALREADY_FINISHED":
        return error_response(code, f"Task {task_id!r} is already finished", 409)
    return json_response(_task_payload(task))


@router.api_route("/api/control/docs/{rest:path}", methods=["GET", "PUT", "DELETE"])
@router.api_route("/api/control/statistics/{rest:path}", methods=["GET"])
@router.api_route("/api/control/admin/{rest:path}", methods=["GET", "POST"])
async def control_fixture(rest: str, request: Request):
    body: dict[str, Any] = {}
    if request.method in {"POST", "PUT"}:
        try:
            maybe_body = await request.json()
            body = maybe_body if isinstance(maybe_body, dict) else {}
        except Exception:
            body = {}
    context = _context(request, body=body)
    _log_client_input(context)
    fixture = _resolver(request).resolve(context)
    if fixture is None:
        logger.warning("Test Mode control fixture miss method=%s path=%s", request.method, request.url.path)
        return error_response("NOT_FOUND", "control fixture route not found", 404)
    logger.info(
        "Test Mode control fixture hit method=%s path=%s fixture_id=%s",
        request.method,
        request.url.path,
        fixture.id or "<anonymous>",
    )
    return _fixture_response(fixture.response)


# Catch-all for completely unmatched paths (FastAPI default 404 does not
# carry our custom header or error shape).
@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def catch_all_not_found(rest: str, request: Request):
    _log_client_input(_context(request, domain=None))
    logger.warning(
        "code=NOT_FOUND status_code=404 method=%s path=%s",
        request.method,
        request.url.path,
    )
    return error_response("NOT_FOUND", "Route not found", 404, {"path": request.url.path})


def _resolver(request: Request) -> FixtureResolver:
    return request.app.state.fixture_resolver


def _task_store(request: Request) -> InMemoryTaskStore:
    return request.app.state.task_store


def _context(
    request: Request,
    *,
    domain: str | None = None,
    body: dict[str, Any] | None = None,
    multipart: dict[str, Any] | None = None,
) -> RequestContext:
    return RequestContext(
        method=request.method,
        path=request.url.path,
        domain=domain,  # type: ignore[arg-type]
        body=body or {},
        params=dict(request.query_params),
        path_params=dict(request.path_params),
        multipart=multipart or {},
    )


def _log_client_input(context: RequestContext) -> None:
    payload = {
        "method": context.method,
        "path": context.path,
        "domain": context.domain,
        "params": context.params,
        "path_params": context.path_params,
        "body": context.body,
        "multipart": context.multipart,
    }
    logger.info(
        "Test Mode client input %s",
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
    )


def _raw_import_multipart(
    fields: dict[str, str | None],
    files: list[UploadFile],
    parser_script: UploadFile | None,
) -> dict[str, Any]:
    return {
        "fields": fields,
        "files": [_upload_input(upload) for upload in files],
        "file_names": [upload.filename or f"upload_{index}" for index, upload in enumerate(files, start=1)],
        "parser_script": _upload_input(parser_script) if parser_script is not None else None,
    }


def _upload_input(upload: UploadFile) -> dict[str, Any]:
    return {
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": getattr(upload, "size", None),
    }


def _file_ref_input(ref: Any) -> dict[str, Any]:
    return {
        "filename": ref.filename,
        "content_type": ref.content_type,
        "size": ref.size,
    }


def _parser_script_input(
    parser_script: UploadFile | None,
    parser_script_path: str | None,
) -> dict[str, Any] | None:
    if parser_script is None:
        return None
    path = Path(parser_script_path) if parser_script_path else None
    return {
        "filename": parser_script.filename,
        "content_type": parser_script.content_type,
        "size": path.stat().st_size if path and path.exists() else None,
    }


def _fixture_response(response: ResponseFixture):
    return json_response(response.json_body or {}, status_code=response.status, headers=response.headers)


def _empty_search_payload(domain: str, body: dict[str, Any]) -> dict[str, Any]:
    tag = body.get("tag")
    result_key = {
        "KNOWLEDGE_BASE": "knowledge_base",
        "SKILL": "skill",
        "MEMORY": "memory",
    }[domain]
    default_kb_index = {
        "KNOWLEDGE_BASE": "kb_design_test",
        "SKILL": "kb_skill_test",
        "MEMORY": "kb_memory_main",
    }[domain]
    kb_index = body.get("kb_index")
    return {
        "success": True,
        "domain": domain,
        "kb_index": kb_index if isinstance(kb_index, str) and kb_index else default_kb_index,
        "tag": tag if isinstance(tag, str) else None,
        "total": 0,
        "results": {result_key: []},
    }


def _ensure_task(
    request: Request,
    payload: dict[str, Any],
    *,
    operation: str,
    domain: str,
    tag: str | None,
) -> None:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return
    if _task_store(request).get(task_id, advance=False) is not None:
        return
    _task_store(request).create(
        operation=operation,
        domain=domain,  # type: ignore[arg-type]
        tag=tag,
        task_id=task_id,
        status=payload.get("status", "queued"),
        final_status="completed",
        result=payload.get("result"),
        error=payload.get("error"),
    )


def _task_payload(task: TaskFixture) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "domain": task.domain,
        "tag": task.tag,
        "status": task.status,
        "result": task.result,
        "error": task.error,
    }


async def _parse_import_form(
    request: Request,
) -> tuple[list[UploadFile], UploadFile | None, dict[str, str | None]]:
    try:
        form = await request.form()
    except RuntimeError as exc:
        if "python-multipart" in str(exc):
            logger.error("Test Mode import form parsing failed missing_dependency=python-multipart")
            raise ValidationFailure(
                "INVALID_ARGUMENT",
                "multipart form parsing requires python-multipart to be installed",
                details={"dependency": "python-multipart"},
            ) from exc
        raise
    files = [item for item in form.getlist("files") if isinstance(item, UploadFile)]
    parser_script_value = form.get("parser_script")
    parser_script = parser_script_value if isinstance(parser_script_value, UploadFile) else None
    fields = {
        "kb_index": _form_text(form.get("kb_index")),
        "tag": _form_text(form.get("tag")),
        "vector_model": _form_text(form.get("vector_model")),
        "parser_context": _form_text(form.get("parser_context")),
    }
    logger.info(
        "Test Mode import form parsed path=%s files=%d has_parser_script=%s kb_index=%s tag=%s",
        request.url.path,
        len(files),
        parser_script is not None,
        fields.get("kb_index"),
        fields.get("tag"),
    )
    return files, parser_script, fields


def _form_text(value: Any) -> str | None:
    if value is None or isinstance(value, UploadFile):
        return None
    return str(value)


async def _persist_uploads(
    tmp_dir: Path,
    files: list[UploadFile],
    parser_script: UploadFile | None,
) -> tuple[list[ImportFileRef], str | None]:
    refs: list[ImportFileRef] = []
    for index, upload in enumerate(files, start=1):
        filename = upload.filename or f"upload_{index}"
        path = tmp_dir / filename
        with path.open("wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        refs.append(
            ImportFileRef(
                filename=filename,
                path=str(path),
                content_type=upload.content_type,
                size=path.stat().st_size,
            )
        )
    parser_script_path: str | None = None
    if parser_script is not None:
        filename = parser_script.filename or "parser.py"
        path = tmp_dir / filename
        with path.open("wb") as fh:
            shutil.copyfileobj(parser_script.file, fh)
        parser_script_path = str(path)
    return refs, parser_script_path

