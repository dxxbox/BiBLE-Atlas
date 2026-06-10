from __future__ import annotations

import io
import json
import os
import re
import time
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest


JsonDict = dict[str, Any]
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_BACKEND_LOG_PATHS = [
    _PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "test" / "server.log",
    _PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "test" / "worker.log",
    _PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "server.log",
    _PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "worker.log",
    _PROJECT_ROOT / "workspace" / "log" / "bible-atlas.log",
]
BACKEND_LOG_PATHS: list[Path] = [
    Path(p)
    for p in os.environ.get(
        "BIBLE_BACKEND_LOGS",
        os.pathsep.join(str(p) for p in _DEFAULT_BACKEND_LOG_PATHS),
    ).split(os.pathsep)
    if p
]
_LOG_LEVEL_RE = re.compile(r"\]\s+(WARNING|ERROR)\s+")


class BackendLogAssertions:
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        self.start_offsets = {
            path: path.stat().st_size if path.exists() else 0
            for path in paths
        }
        self.expected: list[str] = []
        self.allowed_warning_fragments: list[str] = []

    def expect(self, fragment: str) -> None:
        self.expected.append(fragment)

    def allow_warning(self, fragment: str) -> None:
        self.allowed_warning_fragments.append(fragment)
        self.expect(fragment)

    def read_new_logs(self) -> str:
        chunks: list[str] = []
        for path in self.paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                log_file.seek(self.start_offsets.get(path, 0))
                data = log_file.read()
            if data:
                chunks.append(f"\n--- {path} ---\n{data}")
        return "".join(chunks)

    def assert_expected(self) -> None:
        logs = self.read_new_logs()
        missing = [f for f in self.expected if f not in logs]
        assert not missing, f"missing expected backend log fragments: {missing}\nlogs:\n{logs}"

        unexpected: list[str] = []
        for line in logs.splitlines():
            match = _LOG_LEVEL_RE.search(line)
            if match is None:
                continue
            level = match.group(1)
            if level == "WARNING" and any(
                frag in line for frag in self.allowed_warning_fragments
            ):
                continue
            unexpected.append(line)

        assert not unexpected, "unexpected backend WARNING/ERROR logs:\n" + "\n".join(unexpected)


@dataclass(frozen=True)
class MemoryDatabaseState:
    binding: JsonDict
    document: JsonDict


@dataclass(frozen=True)
class MemoryDatabasePresence:
    binding_exists: bool
    document_exists: bool


def response_json(response: httpx.Response) -> JsonDict:
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def detail_code(response: httpx.Response) -> str | None:
    payload = response_json(response)
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        return code if isinstance(code, str) else None
    return None


def assert_validation_error(response: httpx.Response, field: str) -> None:
    assert response.status_code == 422
    detail = response_json(response)["detail"]
    assert isinstance(detail, list)
    assert any(field in item.get("loc", []) for item in detail if isinstance(item, dict))


def memory_meta(memory_id: str) -> bytes:
    return json.dumps(
        {
            "memory_id": memory_id,
            "title": f"Server Entity Test {memory_id}",
            "abstract": "Live API import smoke data.",
            "overview": "Used by tests/server_entity to verify the running backend.",
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
            "language": "en",
        }
    ).encode("utf-8")


def import_files(memory_id: str, *, attachment: bool = False) -> list[tuple[str, tuple[str, bytes, str]]]:
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("files", ("meta.json", memory_meta(memory_id), "application/json")),
    ]
    if attachment:
        files.append(("files", ("note.md", b"# Server Entity Test\n", "text/markdown")))
    return files


def unique_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def wait_for_import_task(
    client: httpx.Client,
    task_id: str,
    *,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float = 1.0,
) -> JsonDict:
    timeout = timeout_seconds or float(os.environ.get("BIBLE_IMPORT_TASK_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout
    last_payload: JsonDict | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/import/memory/task/{task_id}")
        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        if payload["status"] in TERMINAL_TASK_STATUSES:
            return payload
        time.sleep(poll_interval_seconds)

    pytest.fail(f"task {task_id!r} did not finish within {timeout}s; last={last_payload!r}")


def get_memory_database_state(kb_index: str, memory_id: str) -> MemoryDatabaseState:
    with _opensearch_client() as client:
        cfg = _load_test_config()
        os_cfg = cfg.database.opensearch
        binding_id = f"MEMORY::{kb_index}"
        content_index = f"memory_{kb_index}"

        try:
            binding = client.get(index=os_cfg.binding_index, id=binding_id)["_source"]
            document = client.get(index=content_index, id=memory_id)["_source"]
        except _not_found_error_type() as exc:
            raise AssertionError(
                "import task completed but database record was not found: "
                f"binding_id={binding_id!r} content_index={content_index!r} memory_id={memory_id!r}"
            ) from exc
        except _transport_error_type() as exc:
            raise AssertionError(f"failed to query OpenSearch for imported memory: {exc}") from exc

        assert isinstance(binding, dict)
        assert isinstance(document, dict)
        return MemoryDatabaseState(binding=binding, document=document)


def get_memory_database_presence(kb_index: str, memory_id: str) -> MemoryDatabasePresence:
    with _opensearch_client() as client:
        cfg = _load_test_config()
        os_cfg = cfg.database.opensearch
        binding_id = f"MEMORY::{kb_index}"
        content_index = f"memory_{kb_index}"

        binding_exists = _document_exists(client, os_cfg.binding_index, binding_id)
        document_exists = _document_exists(client, content_index, memory_id)
        return MemoryDatabasePresence(
            binding_exists=binding_exists,
            document_exists=document_exists,
        )


def assert_memory_written_to_database(kb_index: str, memory_id: str) -> None:
    db_state = get_memory_database_state(kb_index, memory_id)
    assert db_state.binding["domain_type"] == "MEMORY"
    assert db_state.binding["kb_index"] == kb_index
    assert db_state.binding["tag"] == "memory"
    assert db_state.binding["is_active"] is True
    assert db_state.document["memory_id"] == memory_id
    assert db_state.document["title"] == f"Server Entity Test {memory_id}"
    assert db_state.document["abstract"] == "Live API import smoke data."


def assert_memory_not_written_to_database(kb_index: str, memory_id: str) -> None:
    presence = get_memory_database_presence(kb_index, memory_id)
    assert presence.binding_exists is False
    assert presence.document_exists is False


def assert_memory_id_absent_from_database(memory_id: str) -> None:
    with _opensearch_client() as client:
        try:
            response = client.search(
                index="memory_*",
                body={
                    "size": 0,
                    "query": {"ids": {"values": [memory_id]}},
                },
            )
        except _not_found_error_type():
            return
        except _transport_error_type() as exc:
            raise AssertionError(
                f"failed to search OpenSearch for memory_id absence: memory_id={memory_id!r}: {exc}"
            ) from exc

    total = (response.get("hits") or {}).get("total", 0)
    if isinstance(total, dict):
        total_value = int(total.get("value", 0))
    else:
        total_value = int(total)
    assert total_value == 0


@contextmanager
def _opensearch_client() -> Iterator[Any]:
    cfg = _load_test_config()
    backend = cfg.database.backend.lower()
    if backend != "opensearch":
        pytest.xfail(f"server_entity database verification only supports opensearch, got {backend!r}")

    from opensearchpy import OpenSearch

    os_cfg = cfg.database.opensearch
    kwargs: dict[str, Any] = {
        "hosts": os_cfg.hosts,
        "timeout": os_cfg.timeout_seconds,
        "use_ssl": os_cfg.use_ssl,
        "verify_certs": os_cfg.verify_certs,
    }
    if os_cfg.username and os_cfg.password:
        kwargs["http_auth"] = (os_cfg.username, os_cfg.password)

    client = OpenSearch(**kwargs)
    try:
        if not client.ping():
            pytest.xfail(f"OpenSearch is not reachable at {os_cfg.hosts!r}")
        yield client
    finally:
        transport = getattr(client, "transport", None)
        if transport is not None and hasattr(transport, "close"):
            transport.close()


def _document_exists(client: Any, index: str, doc_id: str) -> bool:
    try:
        return bool(client.exists(index=index, id=doc_id))
    except _not_found_error_type():
        return False
    except _transport_error_type() as exc:
        raise AssertionError(
            f"failed to check OpenSearch document existence: index={index!r} id={doc_id!r}: {exc}"
        ) from exc


def _not_found_error_type() -> type[Exception]:
    from opensearchpy.exceptions import NotFoundError

    return NotFoundError


def _transport_error_type() -> type[Exception]:
    from opensearchpy.exceptions import TransportError

    return TransportError


def _load_test_config() -> Any:
    try:
        from bible.config.configure import (
            _clear_bible_atlas_config_cache,
            get_bible_atlas_config,
        )

        _clear_bible_atlas_config_cache()
        return get_bible_atlas_config()
    except Exception as exc:
        pytest.xfail(f"failed to load bible atlas config for database verification: {exc}")


def assert_search_contract(response: httpx.Response, domain: str, result_key: str) -> None:
    payload = response_json(response)
    assert payload["success"] is True
    assert payload["domain"] == domain
    assert isinstance(payload["total"], int)
    assert isinstance(payload["results"], dict)
    assert result_key in payload["results"]


# ---------------------------------------------------------------------------
# Skill import helpers
# ---------------------------------------------------------------------------

def skill_zip_bytes(skill_name: str, skills_md_content: str) -> bytes:
    """Return the bytes of a minimal valid .skill ZIP file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{skill_name}/SKILL.md", skills_md_content)
    return buf.getvalue()


def wait_for_skill_import_task(
    client: httpx.Client,
    task_id: str,
    *,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float = 1.0,
) -> JsonDict:
    timeout = timeout_seconds or float(os.environ.get("BIBLE_IMPORT_TASK_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout
    last_payload: JsonDict | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/import/skill/task/{task_id}")
        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        if payload["status"] in TERMINAL_TASK_STATUSES:
            return payload
        time.sleep(poll_interval_seconds)

    pytest.fail(f"skill task {task_id!r} did not finish within {timeout}s; last={last_payload!r}")


def get_skill_binding(kb_index: str) -> JsonDict:
    """Read the SKILL binding from OpenSearch and return the _source dict."""
    with _opensearch_client() as client:
        cfg = _load_test_config()
        os_cfg = cfg.database.opensearch
        binding_id = f"SKILL::{kb_index}"
        try:
            return client.get(index=os_cfg.binding_index, id=binding_id)["_source"]
        except _not_found_error_type() as exc:
            raise AssertionError(
                f"SKILL binding not found in OpenSearch: binding_id={binding_id!r}"
            ) from exc
        except _transport_error_type() as exc:
            raise AssertionError(f"failed to query OpenSearch for skill binding: {exc}") from exc


def assert_skill_binding_written(kb_index: str) -> None:
    binding = get_skill_binding(kb_index)
    assert binding["domain_type"] == "SKILL"
    assert binding["kb_index"] == kb_index
    assert binding["tag"] == "skill"
    assert binding["is_active"] is True
    assert binding.get("search_profile_json") not in (None, {}, ""), (
        f"SKILL binding for {kb_index!r} must have a non-empty search_profile_json; "
        f"got: {binding.get('search_profile_json')!r}"
    )


def skill_chunk_count(kb_index: str) -> int:
    """Return the number of content documents in the skill's content index."""
    with _opensearch_client() as os_client:
        try:
            resp = os_client.count(index=kb_index, body={"query": {"match_all": {}}})
            return int(resp.get("count", 0))
        except _not_found_error_type():
            return 0
        except _transport_error_type() as exc:
            raise AssertionError(
                f"failed to count skill content docs in index {kb_index!r}: {exc}"
            ) from exc


def get_skill_content_vectors(kb_index: str) -> list[list[Any]]:
    """Return the ``content_vector`` values from every document in the skill content index.

    The skill content index is named *kb_index* directly (no ``skill_`` prefix).
    Documents that have no ``content_vector`` field produce an empty-list entry.

    Forces an index refresh before querying to avoid stale reads when the
    import pipeline uses ``refresh=false`` (the default write policy).
    """
    with _opensearch_client() as os_client:
        # Force refresh so documents written with refresh=false are visible.
        try:
            os_client.indices.refresh(index=kb_index)
        except _not_found_error_type():
            return []
        except _transport_error_type():
            pass  # best-effort refresh; search will return what's visible

        try:
            resp = os_client.search(
                index=kb_index,
                body={
                    "size": 50,
                    "query": {"match_all": {}},
                    "_source": ["content_vector", "name"],
                },
            )
        except _not_found_error_type():
            return []
        except _transport_error_type() as exc:
            raise AssertionError(
                f"failed to query skill content index {kb_index!r}: {exc}"
            ) from exc

        hits = (resp.get("hits") or {}).get("hits", [])
        return [hit.get("_source", {}).get("content_vector", []) for hit in hits]


