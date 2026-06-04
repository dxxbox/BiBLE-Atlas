"""BiBLE Atlas HTTP client.

Mirrors the TypeScript BibleAtlasClient (src/http/client.ts) using httpx.
Supports JSON-envelope unwrapping, bearer auth, timeouts, multipart memory
import, and task polling.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import httpx

from .logging_utils import action_logger, log

logger = logging.getLogger(__name__)


# ── endpoints ────────────────────────────────────────────────────────────────

class Endpoints:
    health = "/health"
    system_status = "/api/v1/system/status"
    memory_search = "/api/search/memory"
    skill_search = "/api/search/skill"
    knowledge_search = "/api/search/knowledge-base"
    knowledge_list = "/api/control/docs/list"
    knowledge_list_fallback = "/api/v1/knowledge/list"
    memory_import = "/api/import/memory"
    memory_get = "/api/memory/get"
    skill_get = "/api/skill/get"

    @staticmethod
    def task(task_id: str) -> str:
        return f"/api/control/admin/tasks/{task_id}"


# ── errors ───────────────────────────────────────────────────────────────────

class BibleAtlasError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        server_error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.server_error_code = server_error_code

    def __repr__(self) -> str:
        return f"BibleAtlasError(code={self.code!r}, status={self.status_code}, msg={self!s})"


def _map_status_to_code(status_code: int) -> str:
    mapping = {
        400: "BIBLE_INVALID_ARGS",
        401: "BIBLE_AUTH_FAILED",
        403: "BIBLE_AUTH_FAILED",
        404: "BIBLE_NOT_FOUND",
        422: "BIBLE_CONTRACT_MISMATCH",
        501: "BIBLE_NOT_IMPLEMENTED",
        503: "BIBLE_SERVICE_UNAVAILABLE",
        504: "BIBLE_SERVICE_UNAVAILABLE",
    }
    if status_code in mapping:
        return mapping[status_code]
    return "BIBLE_SERVICE_UNAVAILABLE" if status_code >= 500 else "BIBLE_INTERNAL"


def _to_bible_error(exc: Exception) -> BibleAtlasError:
    if isinstance(exc, BibleAtlasError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return BibleAtlasError("BIBLE_TIMEOUT", "BiBLE Atlas request timed out.")
    if isinstance(exc, httpx.RequestError):
        return BibleAtlasError("BIBLE_SERVICE_UNAVAILABLE", str(exc))
    return BibleAtlasError("BIBLE_INTERNAL", str(exc))


# ── request / response helpers ───────────────────────────────────────────────

def _unwrap_envelope(payload: dict, status_code: int) -> dict:
    """Unwrap the standard {status, result} envelope from BiBLE Atlas."""
    if payload.get("status") == "ok":
        result = payload.get("result")
        if result is None:
            return payload
        if isinstance(result, dict):
            return result
        return {"result": result}
    if payload.get("status") == "error":
        raise _error_from_payload(status_code, payload)
    return payload


def _error_from_payload(status_code: int, payload: dict) -> BibleAtlasError:
    error = payload.get("error", {})
    if not isinstance(error, dict):
        error = payload
    server_code = error.get("code") if isinstance(error.get("code"), str) else None
    message = (
        error.get("message")
        or payload.get("detail")
        or f"HTTP request failed with {status_code}."
    )
    return BibleAtlasError(_map_status_to_code(status_code), str(message), status_code, server_code)


# ── client ───────────────────────────────────────────────────────────────────

class BibleAtlasClient:
    """Synchronous HTTP client for the BiBLE Atlas service."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_ms: int = 30_000,
        default_kb_index: str = "kb_memory_main",
        source_client: str = "hermes",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_ms / 1000.0
        self._default_kb_index = default_kb_index
        self._source_client = source_client

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _get(self, path: str, *, envelope: bool = False) -> dict:
        url = self._base_url + path
        log("debug", "http.get request", {"method": "GET", "url": url})
        try:
            response = httpx.get(
                url,
                headers=self._headers(),
                timeout=self._timeout,
            )
            payload = _parse_json(response)
            log("debug", "http.get response", {
                "method": "GET",
                "url": url,
                "status": response.status_code,
                "body_len": len(response.text),
                "body_preview": _truncate_body_for_log(payload),
            })
            if not response.is_success:
                raise _error_from_payload(response.status_code, payload)
            return _unwrap_envelope(payload, response.status_code) if envelope else payload
        except BibleAtlasError:
            raise
        except Exception as exc:
            raise _to_bible_error(exc) from exc

    def _post(self, path: str, body: dict, *, envelope: bool = True) -> dict:
        url = self._base_url + path
        body_str = json.dumps(_prune_none(body))
        log("debug", "http.post request", {
            "method": "POST",
            "url": url,
            "body_len": len(body_str),
            "body_preview": _truncate_str_for_log(body_str),
        })
        try:
            response = httpx.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                content=body_str,
                timeout=self._timeout,
            )
            payload = _parse_json(response)
            log("debug", "http.post response", {
                "method": "POST",
                "url": url,
                "status": response.status_code,
                "body_len": len(response.text),
                "body_preview": _truncate_body_for_log(payload),
            })
            if not response.is_success:
                raise _error_from_payload(response.status_code, payload)
            return _unwrap_envelope(payload, response.status_code) if envelope else payload
        except BibleAtlasError:
            raise
        except Exception as exc:
            raise _to_bible_error(exc) from exc

    def _post_multipart(self, path: str, files: list[tuple], data: dict) -> dict:
        url = self._base_url + path
        log("debug", "http.post_multipart request", {
            "method": "POST",
            "url": url,
            "file_count": len(files),
            "data_keys": list(data.keys()),
        })
        try:
            response = httpx.post(
                url,
                headers=self._headers(),
                files=files,
                data=data,
                timeout=self._timeout,
            )
            payload = _parse_json(response)
            log("debug", "http.post_multipart response", {
                "method": "POST",
                "url": url,
                "status": response.status_code,
                "body_len": len(response.text),
                "body_preview": _truncate_body_for_log(payload),
            })
            if not response.is_success:
                raise _error_from_payload(response.status_code, payload)
            return payload
        except BibleAtlasError:
            raise
        except Exception as exc:
            raise _to_bible_error(exc) from exc

    # ── public API ────────────────────────────────────────────────────────────

    def health(self) -> dict:
        al = action_logger("client.health")
        al.start()
        try:
            result = self._get(Endpoints.health)
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def system_status(self) -> dict:
        al = action_logger("client.system_status")
        al.start()
        try:
            try:
                result = self._get(Endpoints.system_status, envelope=True)
            except BibleAtlasError as exc:
                if exc.status_code == 404 or exc.code == "BIBLE_NOT_FOUND":
                    result = self._get(Endpoints.health)
                else:
                    raise
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def search_memory(
        self,
        query: str,
        top_k: int = 8,
        min_score: float | None = None,
        search_type: str = "hybrid",
    ) -> dict:
        al = action_logger("client.search_memory", {"query_len": len(query), "top_k": top_k, "search_type": search_type})
        al.start()
        try:
            result = self._post(Endpoints.memory_search, _search_body(query, "memory", top_k, min_score, search_type))
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def search_skill(
        self,
        query: str,
        top_k: int = 8,
        min_score: float | None = None,
        search_type: str = "hybrid",
    ) -> dict:
        al = action_logger("client.search_skill", {"query_len": len(query), "top_k": top_k})
        al.start()
        try:
            result = self._post(Endpoints.skill_search, _search_body(query, "skill", top_k, min_score, search_type))
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def search_knowledge(
        self,
        query: str,
        tag: str,
        top_k: int = 8,
        min_score: float | None = None,
        search_type: str = "hybrid",
    ) -> dict:
        al = action_logger("client.search_knowledge", {"query_len": len(query), "tag": tag, "top_k": top_k})
        al.start()
        try:
            result = self._post(Endpoints.knowledge_search, _search_body(query, tag, top_k, min_score, search_type))
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def list_knowledge(self) -> dict:
        al = action_logger("client.list_knowledge")
        al.start()
        try:
            try:
                result = self._get(Endpoints.knowledge_list, envelope=True)
            except BibleAtlasError as exc:
                if exc.status_code == 404 or exc.code == "BIBLE_NOT_FOUND":
                    result = self._get(Endpoints.knowledge_list_fallback, envelope=True)
                else:
                    raise
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def save_memory(
        self,
        messages: list[dict],
        title: str | None = None,
        abstract: str | None = None,
        overview: str | None = None,
        kb_index: str | None = None,
        task_ids: list[str] | None = None,
        feature_tags: list[str] | None = None,
        domain_tags: list[str] | None = None,
        component_tags: list[str] | None = None,
        metadata: dict | None = None,
        wait: bool = False,
    ) -> dict:
        al = action_logger("client.save_memory", {"msg_count": len(messages), "wait": wait})
        al.start()
        try:
            kb_index = kb_index or self._default_kb_index
            now = _iso_now()
            memory_id = f"mem_{int(time.time() * 1000)}_{random.randint(0, 0xFFFF):04x}"
            derived_abstract = (abstract or _derive_abstract(messages))[:500]
            derived_overview = (overview or _derive_overview(messages))[:2000]
            meta = _prune_none({
                "memory_id": memory_id,
                "title": title or derived_abstract[:200] or "Conversation memory",
                "abstract": derived_abstract,
                "overview": derived_overview,
                "created_at": now,
                "updated_at": now,
                "task_ids": task_ids or [],
                "feature_tags": feature_tags or [],
                "domain_tags": domain_tags or [],
                "component_tags": component_tags or [],
                "source_client": self._source_client,
                **(metadata or {}),
            })
            files: list[tuple] = [
                ("files", ("meta.json", json.dumps(meta), "application/json")),
            ]
            if messages:
                files.append(("files", ("message.json", json.dumps({"messages": messages}), "application/json")))
            data = {"kb_index": kb_index, "tag": "memory"}
            raw = self._post_multipart(Endpoints.memory_import, files, data)
            if wait:
                task_id = raw.get("task_id") if isinstance(raw.get("task_id"), str) else None
                if task_id:
                    raw = self.poll_task(task_id)
            al.done({"memory_id": memory_id, "task_id": raw.get("task_id")})
            return raw
        except Exception as exc:
            al.fail(exc)
            raise

    def get_memory(self, memory_id: str) -> dict:
        al = action_logger("client.get_memory", {"memory_id": memory_id})
        al.start()
        try:
            result = self._post(Endpoints.memory_get, {"memory_id": memory_id})
            al.done()
            return result
        except BibleAtlasError as exc:
            if exc.status_code == 404:
                raise BibleAtlasError(
                    "BIBLE_NOT_IMPLEMENTED",
                    "get_memory is not yet available on this BiBLE Atlas server.",
                ) from exc
            al.fail(exc)
            raise
        except Exception as exc:
            al.fail(exc)
            raise

    def get_skill(self, skill_id: str | None = None, name: str | None = None) -> dict:
        al = action_logger("client.get_skill", {"skill_id": skill_id, "name": name})
        al.start()
        try:
            result = self._post(Endpoints.skill_get, _prune_none({"skill_id": skill_id, "name": name}))
            al.done()
            return result
        except BibleAtlasError as exc:
            if exc.status_code == 404:
                raise BibleAtlasError(
                    "BIBLE_NOT_IMPLEMENTED",
                    "get_skill is not yet available on this BiBLE Atlas server.",
                ) from exc
            al.fail(exc)
            raise
        except Exception as exc:
            al.fail(exc)
            raise

    def get_task(self, task_id: str) -> dict:
        al = action_logger("client.get_task", {"task_id": task_id})
        al.start()
        try:
            result = self._get(Endpoints.task(task_id))
            al.done()
            return result
        except Exception as exc:
            al.fail(exc)
            raise

    def poll_task(
        self,
        task_id: str,
        interval_ms: int = 500,
        timeout_ms: int | None = None,
    ) -> dict:
        deadline = time.monotonic() + (timeout_ms or self._timeout * 1000) / 1000.0
        while True:
            payload = self.get_task(task_id)
            status = str(payload.get("status") or payload.get("state") or "")
            if status in ("completed", "failed", "cancelled"):
                return payload
            if time.monotonic() >= deadline:
                raise BibleAtlasError("BIBLE_TASK_TIMEOUT", f"Task {task_id} did not complete in time.")
            time.sleep(interval_ms / 1000.0)


# ── internal helpers ──────────────────────────────────────────────────────────

def _search_body(
    query: str,
    tag: str,
    top_k: int,
    min_score: float | None,
    search_type: str,
) -> dict:
    return _prune_none({
        "query": query,
        "top_k": top_k,
        "threshold": min_score,
        "search_type": search_type or "hybrid",
        "tag": tag,
    })


def _parse_json(response: httpx.Response) -> dict:
    text = response.text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


def _prune_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _derive_abstract(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"])
    return messages[0].get("content", "") if messages else ""


def _derive_overview(messages: list[dict]) -> str:
    return "\n".join(f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in messages)


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _truncate_str_for_log(s: str, max_len: int = 500) -> str:
    """Truncate a string for safe debug logging."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...[truncated, total={len(s)}]"


def _truncate_body_for_log(body: Any, max_len: int = 500) -> str:
    """JSON-serialize and truncate a response body for debug logging, redacting secrets."""
    if body is None:
        return "null"
    try:
        s = json.dumps(body, default=str)
    except (TypeError, ValueError):
        s = str(body)
    return _truncate_str_for_log(s, max_len)


# ── error details helper (used by tools) ──────────────────────────────────────

def error_details(exc: Exception) -> dict[str, Any]:
    """Convert any exception into a structured error dict for tool results."""
    mapped = exc if isinstance(exc, BibleAtlasError) else _to_bible_error(exc)
    return {
        "code": mapped.code,
        "message": str(mapped),
        "status_code": mapped.status_code,
        "server_error_code": mapped.server_error_code,
    }
