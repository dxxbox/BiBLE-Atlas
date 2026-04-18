"""Async HTTP client implementation for bible-cli."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from bible_cli.client.base import BaseClient
from bible_cli.exceptions import NotFoundError, map_server_error
from bible_cli.utils.async_bridge import run_async


class AsyncHTTPClient(BaseClient):
    """Async HTTP implementation with unified response handling."""

    def _initialize(self) -> None:
        base_url = self.config.get("base_url", "http://127.0.0.1:5555")
        timeout_seconds = float(self.config.get("timeout_seconds", 30))
        api_key = self.config.get("api_key")
        default_headers = dict(self.config.get("default_headers", {}))
        transport = self.config.get("transport")
        trust_env = bool(self.config.get("trust_env", False))

        if api_key and "X-API-Key" not in default_headers:
            default_headers["X-API-Key"] = str(api_key)

        self._client = httpx.AsyncClient(
            base_url=str(base_url),
            timeout=timeout_seconds,
            headers=default_headers,
            transport=transport,
            trust_env=trust_env,
        )

    def close(self) -> None:
        run_async(self.aclose())

    async def aclose(self) -> None:
        await self._client.aclose()

    async def status(self) -> dict[str, Any]:
        """Check server status from system endpoint."""
        try:
            payload = await self._request_json(
                "GET",
                "/api/v1/system/status",
                expect_envelope=True,
                allow_plain_status_ok=True,
            )
        except NotFoundError:
            payload = await self._request_json(
                "GET",
                "/health",
                expect_envelope=False,
            )
        if not isinstance(payload, dict):
            return {"status": "ok", "result": payload}
        return payload

    async def health(self) -> dict[str, Any]:
        """Backward-compatible alias for top-level heartbeat command."""
        return await self.status()

    async def info(self) -> dict[str, Any]:
        """Fetch system info from API endpoint."""
        try:
            payload = await self._request_json(
                "GET",
                "/api/v1/system/info",
                expect_envelope=True,
            )
        except NotFoundError:
            payload = await self._request_json(
                "GET",
                "/info",
                expect_envelope=False,
            )
        if not isinstance(payload, dict):
            return {"info": payload}
        return payload

    async def knowledge_list(self) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            "/api/v1/knowledge/list",
            expect_envelope=True,
        )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    async def knowledge_search(self, query: str | None = None) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            "/api/v1/knowledge/search",
            params={"query": query} if query else None,
            expect_envelope=True,
        )
        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        expect_envelope: bool = True,
        allow_plain_status_ok: bool = False,
    ) -> Any:
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise map_server_error(
                code="DEADLINE_EXCEEDED",
                message="Request timed out.",
                details={"path": path, "method": method},
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise map_server_error(
                code="UNAVAILABLE",
                message="HTTP transport error.",
                details={"path": path, "method": method, "cause": str(exc)},
                retryable=True,
            ) from exc

        payload = self._safe_parse_json(response)

        if response.status_code >= 400:
            self._raise_http_error(response.status_code, payload, response.text)

        if not isinstance(payload, dict):
            raise map_server_error(
                code="INTERNAL",
                message="Expected a JSON object response.",
                details={"path": path, "status_code": response.status_code},
                status_code=response.status_code,
            )

        if expect_envelope:
            if self._is_envelope(payload):
                return self._handle_response(payload, status_code=response.status_code)
            if allow_plain_status_ok and payload.get("status") == "ok":
                return payload
            raise map_server_error(
                code="INTERNAL",
                message="Malformed response envelope.",
                details={"payload": payload},
                status_code=response.status_code,
            )

        return payload

    def _handle_response(self, payload: dict[str, Any], *, status_code: int | None = None) -> Any:
        """Unwrap standard response envelope and raise typed exceptions for errors."""
        status = payload.get("status")
        if status == "ok":
            # Keep compatibility with lightweight probe responses: {"status": "ok"}.
            if "result" not in payload and "error" not in payload:
                return payload
            return payload.get("result")
        if status == "error":
            self._raise_exception(payload.get("error"), status_code=status_code)

        self._raise_exception(
            {
                "code": "INTERNAL",
                "message": "Malformed response envelope.",
                "details": {"payload": payload},
                "retryable": False,
            },
            status_code=status_code,
        )
        return None

    def _raise_exception(
        self,
        error_payload: dict[str, Any] | None,
        *,
        status_code: int | None = None,
    ) -> None:
        """Raise local strong-typed exception from server error payload."""
        payload = error_payload or {}
        raise map_server_error(
            code=payload.get("code"),
            message=payload.get("message", "Unknown server error"),
            details=payload.get("details"),
            retryable=bool(payload.get("retryable", False)),
            status_code=status_code,
        )

    def _raise_http_error(
        self,
        status_code: int,
        payload: dict[str, Any] | None,
        raw_text: str,
    ) -> None:
        if payload and payload.get("status") == "error":
            self._raise_exception(payload.get("error"), status_code=status_code)

        detail_value = payload.get("detail") if isinstance(payload, dict) else raw_text
        message = str(detail_value) if detail_value else f"HTTP request failed with {status_code}."
        code = self._error_code_from_http_status(status_code)
        raise map_server_error(
            code=code,
            message=message,
            details={"detail": detail_value},
            retryable=code in {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED"},
            status_code=status_code,
        )

    @staticmethod
    def _safe_parse_json(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _is_envelope(payload: dict[str, Any]) -> bool:
        return payload.get("status") in {"ok", "error"}

    @staticmethod
    def _error_code_from_http_status(status_code: int) -> str:
        if status_code == 400:
            return "INVALID_ARGUMENT"
        if status_code == 401:
            return "UNAUTHENTICATED"
        if status_code == 403:
            return "PERMISSION_DENIED"
        if status_code == 404:
            return "NOT_FOUND"
        if status_code == 409:
            return "CONFLICT"
        if status_code == 412:
            return "FAILED_PRECONDITION"
        if status_code == 429:
            return "RESOURCE_EXHAUSTED"
        if status_code == 501:
            return "NOT_IMPLEMENTED"
        if status_code == 503:
            return "UNAVAILABLE"
        if status_code == 504:
            return "DEADLINE_EXCEEDED"
        return "INTERNAL"
