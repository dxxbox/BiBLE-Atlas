"""Entity tests for the skill import + search pipeline.

Coverage:
  1. Happy path — valid .skill file accepted, task queued, completes, binding written to DB,
     and the imported skill is keyword-searchable via POST /api/search/skill.
  2. Task status endpoint — GET /api/import/skill/task/{task_id} returns task fields.
  3. Unknown task — 404 NOT_FOUND; subsequent search on the unbound kb_index returns
     404 INDEX_NOT_BOUND.
  4. Import validation rejection — invalid tag, blank kb_index, missing files,
     unsupported file extension, malformed parser_context.
  5. Search rejection — invalid tag returns 400 TAG_INVALID (case-sensitive).
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

from _helpers import (
    BackendLogAssertions,
    assert_skill_binding_written,
    assert_validation_error,
    detail_code,
    response_json,
    skill_zip_bytes,
    unique_id,
    wait_for_skill_import_task,
)

DEFAULT_VECTOR_MODEL = os.environ.get(
    "BIBLE_ENTITY_TEST_VECTOR_MODEL",
    "BAAI/bge-base-zh-v1.5",
)


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------

def _skill_files(skill_name: str = "test-skill") -> list[tuple[str, tuple[str, bytes, str]]]:
    """Return multipart file tuples for a minimal .skill archive.

    The SKILL.md title line is set to *skill_name* so keyword search on the
    ``name.keyword`` field can uniquely identify the imported document.
    """
    skills_md = (
        f"# {skill_name}\n\n"
        "A skill for automated server entity tests.\n\n"
        "## Usage\n\n"
        "This skill validates the end-to-end skill import and search pipeline.\n"
    )
    return [
        (
            "files",
            (
                f"{skill_name}.skill",
                skill_zip_bytes(skill_name, skills_md),
                "application/octet-stream",
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Search assertion helpers
# ---------------------------------------------------------------------------

def _assert_skill_search_finds_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    skill_name: str,
) -> None:
    """Poll POST /api/search/skill until the imported skill is visible.

    Uses keyword search (``name.keyword`` term query) so only an exact match
    on the unique *skill_name* is counted as a hit.
    """
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/skill",
            json={
                "query": skill_name,
                "tag": "skill",
                "kb_index": kb_index,
                "search_type": "keyword",
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "SKILL"
        assert payload["kb_index"] == kb_index
        assert payload["tag"] == "skill"
        assert isinstance(payload["total"], int)
        assert "skill" in payload["results"]

        matched = [
            item for item in payload["results"]["skill"]
            if item.get("name") == skill_name
        ]
        if matched:
            hit = matched[0]
            assert "doc_id" in hit, f"doc_id missing from hit: {hit}"
            assert isinstance(hit.get("score"), (int, float)), (
                f"score is not a number: {hit.get('score')!r}"
            )
            assert "chunk_id" not in hit, f"chunk_id must not be in response: {hit}"
            assert "took_ms" not in hit, f"took_ms must not be in response: {hit}"
            backend_log.expect(f"SKILL search started tag=skill kb_index={kb_index}")
            backend_log.expect(
                f"SKILL search binding selected selector=kb_index value={kb_index}"
            )
            backend_log.expect(f"SKILL search completed kb_index={kb_index}")
            backend_log.expect("HTTP request completed method=POST path=/api/search/skill")
            return
        time.sleep(1)

    raise AssertionError(
        f"skill_name {skill_name!r} was not keyword-searchable in kb_index {kb_index!r} "
        f"within {timeout}s; last_payload={last_payload!r}"
    )


def _assert_skill_search_not_bound(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
) -> None:
    """Assert that POST /api/search/skill returns 404 INDEX_NOT_BOUND for an unbound kb_index."""
    response = client.post(
        "/api/search/skill",
        json={
            "query": "test",
            "tag": "skill",
            "kb_index": kb_index,
            "search_type": "keyword",
            "top_k": 5,
        },
    )

    assert response.status_code == 404
    assert detail_code(response) == "INDEX_NOT_BOUND"
    backend_log.expect(f"SKILL search started tag=skill kb_index={kb_index}")
    backend_log.allow_warning(
        f"SKILL search binding not found selector=kb_index value={kb_index}"
    )
    backend_log.expect("HTTP request completed method=POST path=/api/search/skill")


# ---------------------------------------------------------------------------
# Import + search assertion helper
# ---------------------------------------------------------------------------

def _assert_completed_import_wrote_binding_and_is_searchable(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    response: httpx.Response,
    *,
    kb_index: str,
    skill_name: str,
) -> None:
    """Wait for the import task to complete, verify DB binding, then verify search visibility."""
    task_id = response_json(response)["task_id"]
    task = wait_for_skill_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1
    assert_skill_binding_written(kb_index)
    backend_log.expect(f"POST /api/import/skill received: kb_index={kb_index} tag=skill")
    backend_log.expect(f"Starting skill import: kb_index={kb_index}")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")
    _assert_skill_search_finds_import(
        client,
        backend_log,
        kb_index=kb_index,
        skill_name=skill_name,
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_import_skill_accepts_valid_skill_file_and_returns_task(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_skill_import")
    skill_name = unique_id("skill_import")

    response = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill"},
        files=_skill_files(skill_name),
    )

    assert response.status_code == 202
    payload = response_json(response)
    assert payload["domain"] == "SKILL"
    assert payload["kb_index"] == kb_index
    assert payload["tag"] == "skill"
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert isinstance(payload["task_id"], str) and payload["task_id"]
    _assert_completed_import_wrote_binding_and_is_searchable(
        client, backend_log, response, kb_index=kb_index, skill_name=skill_name
    )


def test_import_skill_task_query_returns_task_status(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_skill_task_status")
    skill_name = unique_id("skill_task_status")

    submit = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill"},
        files=_skill_files(skill_name),
    )
    assert submit.status_code == 202
    task_id = response_json(submit)["task_id"]

    response = client.get(f"/api/import/skill/task/{task_id}")

    assert response.status_code == 200
    payload = response_json(response)
    assert payload["task_id"] == task_id
    assert payload["task_type"] == "import.skill"
    assert payload["status"] in {"queued", "running", "completed", "failed", "cancelled"}
    assert "created_at" in payload
    assert "updated_at" in payload
    backend_log.expect("HTTP request completed method=GET path=/api/import/skill/task/")
    _assert_completed_import_wrote_binding_and_is_searchable(
        client, backend_log, submit, kb_index=kb_index, skill_name=skill_name
    )


# ---------------------------------------------------------------------------
# Import rejection tests
# ---------------------------------------------------------------------------

def test_import_skill_task_query_unknown_task_returns_404(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    unbound_kb_index = unique_id("kb_skill_unknown_task")

    response = client.get(f"/api/import/skill/task/missing-{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert detail_code(response) == "NOT_FOUND"
    backend_log.expect("HTTP request completed method=GET path=/api/import/skill/task/")
    _assert_skill_search_not_bound(
        client,
        backend_log,
        kb_index=unbound_kb_index,
    )


def test_search_skill_by_tag_without_kb_index_finds_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    """Search binding lookup falls back to domain+tag when kb_index is omitted.

    Design doc §2.2: if kb_index absent → get_binding_by_domain_tag(SKILL, tag="skill").
    """
    # In repeated test runs multiple SKILL bindings may exist for the same tag.
    # The writer logs a WARNING in that case; allow it here since the writer
    # correctly selects the most-recently-created binding (sorted by created_at desc).
    backend_log.allowed_warning_fragments.append("Duplicated active bindings")

    kb_index = unique_id("kb_skill_tag_lookup")
    skill_name = unique_id("skill_tag_lookup")

    submit = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill"},
        files=_skill_files(skill_name),
    )
    assert submit.status_code == 202
    _assert_completed_import_wrote_binding_and_is_searchable(
        client, backend_log, submit, kb_index=kb_index, skill_name=skill_name
    )

    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/skill",
            json={
                "query": skill_name,
                "tag": "skill",
                # kb_index intentionally omitted — service must fall back to tag lookup
                "search_type": "keyword",
                "top_k": 5,
            },
        )
        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "SKILL"
        assert payload["tag"] == "skill"
        assert isinstance(payload["total"], int)

        if any(item.get("name") == skill_name for item in payload["results"]["skill"]):
            backend_log.expect("SKILL search started tag=skill kb_index=<by-tag>")
            backend_log.expect(
                "SKILL search binding selected selector=tag value=skill"
            )
            backend_log.expect("HTTP request completed method=POST path=/api/search/skill")
            return
        time.sleep(1)

    raise AssertionError(
        f"tag-only search did not find skill_name {skill_name!r} within {timeout}s; "
        f"last_payload={last_payload!r}"
    )


@pytest.mark.parametrize("tag", ["memory", "Skill"])
def test_import_skill_rejects_invalid_tag(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    tag: str,
) -> None:
    kb_index = unique_id("kb_skill_bad_tag")

    response = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": tag},
        files=_skill_files(),
    )

    assert response.status_code == 400
    assert detail_code(response) == "TAG_INVALID"
    backend_log.expect(f"POST /api/import/skill received: kb_index={kb_index} tag={tag}")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


def test_import_skill_rejects_blank_kb_index(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    response = client.post(
        "/api/import/skill",
        data={"kb_index": "   ", "tag": "skill"},
        files=_skill_files(),
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    backend_log.expect("POST /api/import/skill received: kb_index=    tag=skill")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


def test_import_skill_rejects_missing_files(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    response = client.post(
        "/api/import/skill",
        data={"kb_index": unique_id("kb_skill_no_files"), "tag": "skill"},
    )

    assert_validation_error(response, "files")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


def test_import_skill_rejects_unsupported_extension(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_skill_bad_ext")

    response = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill"},
        files=[("files", ("skill_pkg.zip", b"fake zip content", "application/zip"))],
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    backend_log.expect(f"POST /api/import/skill received: kb_index={kb_index} tag=skill")
    backend_log.expect("Session upload dir removed (task not submitted):")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


def test_import_skill_rejects_invalid_parser_context(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_skill_bad_ctx")

    response = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill", "parser_context": "{not-json"},
        files=_skill_files(),
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    backend_log.expect(f"POST /api/import/skill received: kb_index={kb_index} tag=skill")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


# ---------------------------------------------------------------------------
# Search rejection tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag", ["memory", "Skill", "SKILL"])
def test_search_skill_rejects_invalid_tag(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    tag: str,
) -> None:
    """POST /api/search/skill must reject any tag that is not exactly 'skill'."""
    response = client.post(
        "/api/search/skill",
        json={
            "query": "test query",
            "tag": tag,
            "search_type": "keyword",
            "top_k": 5,
        },
    )

    assert response.status_code == 400
    assert detail_code(response) == "TAG_INVALID"
    backend_log.expect("HTTP request completed method=POST path=/api/search/skill")


def test_search_skill_rejects_unknown_search_type(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    """POST /api/search/skill with an unrecognised search_type must return 400 SEARCH_TYPE_INVALID."""
    response = client.post(
        "/api/search/skill",
        json={
            "query": "test query",
            "tag": "skill",
            "search_type": "bm25_fuzz",
            "top_k": 5,
        },
    )

    assert response.status_code == 400
    assert detail_code(response) == "SEARCH_TYPE_INVALID"
    backend_log.expect("HTTP request completed method=POST path=/api/search/skill")


def test_search_skill_rejects_top_k_exceeding_maximum(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    """POST /api/search/skill with top_k beyond the server's max must return 400 INVALID_ARGUMENT."""
    response = client.post(
        "/api/search/skill",
        json={
            "query": "test query",
            "tag": "skill",
            "top_k": 99999,
        },
    )

    assert response.status_code == 400
    assert detail_code(response) == "INVALID_ARGUMENT"
    backend_log.expect("HTTP request completed method=POST path=/api/search/skill")
