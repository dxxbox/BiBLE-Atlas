from __future__ import annotations

import httpx
import pytest

from bible_cli.client.async_http import AsyncHTTPClient
from bible_cli.exceptions import (
    InvalidArgumentError,
    NotFoundError,
    ProcessingError,
    UnauthenticatedError,
    map_server_error,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_map_server_error_for_known_code() -> None:
    error = map_server_error(
        code="INVALID_ARGUMENT",
        message="invalid page",
        details={"field": "page"},
        retryable=False,
    )

    assert isinstance(error, InvalidArgumentError)
    assert error.code == "INVALID_ARGUMENT"
    assert error.details == {"field": "page"}
    assert error.retryable is False


def test_map_server_error_for_domain_code() -> None:
    error = map_server_error(
        code="AUTH_INVALID_API_KEY",
        message="api key is invalid",
        details={"header": "X-API-Key"},
        retryable=False,
    )

    assert isinstance(error, UnauthenticatedError)
    assert error.code == "AUTH_INVALID_API_KEY"
    assert error.details == {"header": "X-API-Key"}


def test_map_server_error_unknown_code_fallback() -> None:
    error = map_server_error(
        code="SOME_UNKNOWN_ERROR",
        message="unknown",
        details={"source": "server"},
        retryable=True,
        status_code=520,
    )

    assert isinstance(error, ProcessingError)
    assert error.code == "SOME_UNKNOWN_ERROR"
    assert error.retryable is True
    assert error.status_code == 520


def test_handle_response_success_unwraps_result() -> None:
    client = AsyncHTTPClient()
    payload = {"status": "ok", "result": {"healthy": True}, "meta": {"request_id": "r1"}}

    assert client._handle_response(payload) == {"healthy": True}


def test_handle_response_error_raises_typed_exception() -> None:
    client = AsyncHTTPClient()
    payload = {
        "status": "error",
        "error": {
            "code": "NOT_FOUND",
            "message": "resource missing",
            "details": {"id": "abc"},
            "retryable": False,
        },
    }

    with pytest.raises(NotFoundError) as raised:
        client._handle_response(payload, status_code=404)

    error = raised.value
    assert str(error) == "resource missing"
    assert getattr(error, "code", None) == "NOT_FOUND"
    assert getattr(error, "status_code", None) == 404


def test_handle_response_malformed_payload_raises_processing_error() -> None:
    client = AsyncHTTPClient()

    with pytest.raises(ProcessingError) as raised:
        client._handle_response({"result": {"healthy": True}})

    assert raised.value.code == "INTERNAL"
    assert "Malformed response envelope" in raised.value.message


@pytest.mark.anyio
async def test_request_json_calls_handle_response_on_success_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/system/status"
        return httpx.Response(200, json={"status": "ok", "result": {"healthy": True}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        payload = await client._request_json("GET", "/api/v1/system/status")
        assert payload == {"healthy": True}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_request_json_maps_error_envelope_to_typed_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "status": "error",
                "error": {
                    "code": "AUTH_INVALID_API_KEY",
                    "message": "bad key",
                    "details": {"header": "X-API-Key"},
                    "retryable": False,
                },
            },
        )

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        with pytest.raises(UnauthenticatedError) as raised:
            await client._request_json("GET", "/api/v1/system/status")
        assert raised.value.code == "AUTH_INVALID_API_KEY"
        assert raised.value.status_code == 401
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_health_falls_back_to_probe_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system/status":
            return httpx.Response(
                404,
                json={"status": "error", "error": {"code": "NOT_FOUND", "message": "missing"}},
            )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(500, json={"status": "error", "error": {"code": "INTERNAL"}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        payload = await client.health()
        assert payload == {"status": "ok"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_info_calls_system_info_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system/info":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "version": "0.0.1",
                        "description": "BiBLE-Atlas: Agent-native context DB",
                    },
                },
            )
        return httpx.Response(500, json={"status": "error", "error": {"code": "INTERNAL"}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        payload = await client.info()
        assert payload["version"] == "0.0.1"
        assert payload["description"] == "BiBLE-Atlas: Agent-native context DB"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_info_falls_back_to_legacy_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system/info":
            return httpx.Response(
                404,
                json={"status": "error", "error": {"code": "NOT_FOUND", "message": "missing"}},
            )
        if request.url.path == "/info":
            return httpx.Response(
                200,
                json={"version": "0.0.2", "description": "BiBLE-Atlas: Agent-native context DB"},
            )
        return httpx.Response(500, json={"status": "error", "error": {"code": "INTERNAL"}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        payload = await client.info()
        assert payload["version"] == "0.0.2"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_knowledge_list_not_implemented_returns_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/knowledge/list":
            return httpx.Response(
                501,
                json={
                    "status": "error",
                    "error": {
                        "code": "NOT_IMPLEMENTED",
                        "message": "not implemented",
                        "details": {"operation": "list"},
                        "retryable": False,
                    },
                },
            )
        return httpx.Response(500, json={"status": "error", "error": {"code": "INTERNAL"}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        with pytest.raises(ProcessingError) as raised:
            await client.knowledge_list()
        assert raised.value.code == "NOT_IMPLEMENTED"
        assert raised.value.status_code == 501
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_knowledge_search_not_implemented_returns_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/knowledge/search":
            assert request.url.params.get("query") == "grace"
            return httpx.Response(
                501,
                json={
                    "status": "error",
                    "error": {
                        "code": "NOT_IMPLEMENTED",
                        "message": "not implemented",
                        "details": {"operation": "search"},
                        "retryable": False,
                    },
                },
            )
        return httpx.Response(500, json={"status": "error", "error": {"code": "INTERNAL"}})

    client = AsyncHTTPClient(
        config={
            "base_url": "http://testserver",
            "transport": httpx.MockTransport(handler),
        }
    )
    try:
        with pytest.raises(ProcessingError) as raised:
            await client.knowledge_search(query="grace")
        assert raised.value.code == "NOT_IMPLEMENTED"
        assert raised.value.status_code == 501
    finally:
        await client.aclose()
