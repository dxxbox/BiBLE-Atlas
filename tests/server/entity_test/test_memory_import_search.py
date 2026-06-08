from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import uuid

import httpx
import pytest

from _helpers import (
    BackendLogAssertions,
    assert_memory_id_absent_from_database,
    assert_memory_not_written_to_database,
    assert_memory_written_to_database,
    assert_validation_error,
    detail_code,
    import_files,
    memory_meta,
    response_json,
    unique_id,
    wait_for_import_task,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKEND_LOG_PATHS = [
    PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "server.log",
    PROJECT_ROOT / "scripts" / "server_deploy" / "runs" / "worker.log",
    PROJECT_ROOT / "workspace" / "log" / "bible-atlas.log",
]
BACKEND_LOG_PATHS = [
    Path(path)
    for path in os.environ.get(
        "BIBLE_BACKEND_LOGS",
        os.pathsep.join(str(path) for path in DEFAULT_BACKEND_LOG_PATHS),
    ).split(os.pathsep)
    if path
]
LOG_LEVEL_RE = re.compile(r"\]\s+(WARNING|ERROR)\s+")


def _assert_memory_search_finds_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    memory_id: str,
) -> None:
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/memory",
            json={
                "query": memory_id,
                "tag": "memory",
                "kb_index": kb_index,
                "search_type": "keyword",
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "MEMORY"
        assert payload["kb_index"] == kb_index
        assert payload["tag"] == "memory"
        if any(item["memory_id"] == memory_id for item in payload["results"]["memory"]):
            backend_log.expect(f"MEMORY search started tag=memory kb_index={kb_index}")
            backend_log.expect(
                f"OpenSearch binding lookup by index hit domain=MEMORY kb_index={kb_index}"
            )
            backend_log.expect(
                f"MEMORY search completed kb_index={kb_index} content_index=memory_{kb_index}"
            )
            backend_log.expect("HTTP request completed method=POST path=/api/search/memory")
            return
        time.sleep(1)

    raise AssertionError(
        f"memory_id {memory_id!r} was not searchable in kb_index {kb_index!r} "
        f"within {timeout}s; last_payload={last_payload!r}"
    )


def _assert_memory_search_not_bound(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    memory_id: str,
) -> None:
    response = client.post(
        "/api/search/memory",
        json={
            "query": memory_id,
            "tag": "memory",
            "kb_index": kb_index,
            "search_type": "keyword",
            "top_k": 5,
        },
    )

    assert response.status_code == 404
    assert detail_code(response) == "INDEX_NOT_BOUND"
    backend_log.expect(f"MEMORY search started tag=memory kb_index={kb_index}")
    backend_log.allow_warning(
        f"MEMORY search binding not found selector=kb_index value={kb_index}"
    )
    backend_log.expect("HTTP request completed method=POST path=/api/search/memory")


def _assert_completed_import_wrote_database_and_is_searchable(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    response: httpx.Response,
    *,
    kb_index: str,
    memory_id: str,
) -> None:
    task_id = response_json(response)["task_id"]
    task = wait_for_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1
    assert_memory_written_to_database(kb_index, memory_id)
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect(f"Starting memory import: kb_index={kb_index}")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_finds_import(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_accepts_valid_meta_file_and_returns_task(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search")
    memory_id = unique_id("mem_import_search")

    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory"},
        files=import_files(memory_id),
    )

    assert response.status_code == 202
    payload = response_json(response)
    assert payload["domain"] == "MEMORY"
    assert payload["kb_index"] == kb_index
    assert payload["tag"] == "memory"
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert isinstance(payload["task_id"], str)
    assert payload["task_id"]
    _assert_completed_import_wrote_database_and_is_searchable(
        client,
        backend_log,
        response,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_accepts_attachment_and_parser_context(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_attachment")
    memory_id = unique_id("mem_import_search_attachment")

    response = client.post(
        "/api/import/memory",
        data={
            "kb_index": kb_index,
            "tag": "memory",
            "parser_context": json.dumps({"source": "server_entity"}),
        },
        files=import_files(memory_id, attachment=True),
    )

    assert response.status_code == 202
    payload = response_json(response)
    assert payload["domain"] == "MEMORY"
    assert payload["tag"] == "memory"
    assert isinstance(payload["task_id"], str)
    _assert_completed_import_wrote_database_and_is_searchable(
        client,
        backend_log,
        response,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_task_query_returns_task_status(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_task")
    memory_id = unique_id("mem_import_search_task")
    submit = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory"},
        files=import_files(memory_id),
    )
    assert submit.status_code == 202

    task_id = response_json(submit)["task_id"]
    response = client.get(f"/api/import/memory/task/{task_id}")

    assert response.status_code == 200
    payload = response_json(response)
    assert payload["task_id"] == task_id
    assert payload["task_type"] == "import.memory"
    assert payload["status"] in {"queued", "running", "completed", "failed", "cancelled"}
    assert "created_at" in payload
    assert "updated_at" in payload
    backend_log.expect("HTTP request completed method=GET path=/api/import/memory/task/")
    _assert_completed_import_wrote_database_and_is_searchable(
        client,
        backend_log,
        submit,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_completed_task_writes_database(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_db")
    memory_id = unique_id("mem_import_search_db")

    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory"},
        files=import_files(memory_id),
    )
    assert response.status_code == 202

    task_id = response_json(response)["task_id"]
    task = wait_for_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1
    assert_memory_written_to_database(kb_index, memory_id)
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect(f"Starting memory import: kb_index={kb_index}")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_finds_import(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_task_query_unknown_task_returns_404(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_unknown_task")
    memory_id = unique_id("mem_import_search_unknown_task")
    response = client.get(f"/api/import/memory/task/missing-{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert detail_code(response) == "NOT_FOUND"
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect("HTTP request completed method=GET path=/api/import/memory/task/")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


@pytest.mark.parametrize("tag", ["skill", "Memory"])
def test_import_memory_rejects_invalid_tag(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    tag: str,
) -> None:
    kb_index = unique_id("kb_import_search_bad_tag")
    memory_id = unique_id("mem_import_search_bad_tag")
    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": tag},
        files=import_files(memory_id),
    )

    assert response.status_code == 400
    assert detail_code(response) == "TAG_INVALID"
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag={tag}")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_rejects_empty_tag_as_validation_error(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_empty_tag")
    memory_id = unique_id("mem_import_search_empty_tag")
    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": ""},
        files=import_files(memory_id),
    )

    assert_validation_error(response, "tag")
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_rejects_blank_kb_index(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    memory_id = unique_id("mem_import_search_blank_kb")
    search_kb_index = unique_id("kb_import_search_blank_kb")
    response = client.post(
        "/api/import/memory",
        data={"kb_index": "   ", "tag": "memory"},
        files=import_files(memory_id),
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    assert_memory_id_absent_from_database(memory_id)
    backend_log.expect("POST /api/import/memory received: kb_index=    tag=memory")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=search_kb_index,
        memory_id=memory_id,
    )


def test_import_memory_rejects_missing_files(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_missing_files")
    memory_id = unique_id("mem_import_search_missing_files")
    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory"},
    )

    assert_validation_error(response, "files")
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_rejects_invalid_parser_context(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_bad_context")
    memory_id = unique_id("mem_import_search_bad_context")
    response = client.post(
        "/api/import/memory",
        data={
            "kb_index": kb_index,
            "tag": "memory",
            "parser_context": "{invalid-json",
        },
        files=import_files(memory_id),
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )


def test_import_memory_rejects_unsupported_file_extension(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_bad_extension")
    memory_id = unique_id("mem_import_search_bad_extension")
    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory"},
        files=[("files", ("meta.txt", memory_meta(memory_id), "text/plain"))],
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    assert_memory_not_written_to_database(kb_index, memory_id)
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect("Session upload dir removed (task not submitted):")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_not_bound(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )
