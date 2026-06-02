from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse, Response


def json_response(payload: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    response_headers = {"X-Bible-Test-Mode": "true"}
    if headers:
        response_headers.update(headers)
    return JSONResponse(status_code=status_code, content=payload, headers=response_headers)


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return json_response(payload, status_code=status_code)


def binary_response(
    body: bytes,
    *,
    content_type: str,
    file_name: str,
    headers: dict[str, str] | None = None,
) -> Response:
    response_headers = {
        "X-Bible-Test-Mode": "true",
        "Content-Disposition": f'attachment; filename="{file_name}"',
    }
    if headers:
        response_headers.update(headers)
    return Response(content=body, media_type=content_type, headers=response_headers)
