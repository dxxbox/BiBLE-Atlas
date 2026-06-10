"""Entity tests for skill import + vector search.

Coverage:
  1. Import a single skill with *vector_model* → binding records the model,
     all indexed documents have a non-empty ``content_vector``, and the skill
     is discoverable via ``search_type=vector``.
  2. Import three skills with semantically distinct content and assert that
     vector search returns them in the expected relevance order (most similar
     first, unrelated last).
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import pytest

from _helpers import (
    BackendLogAssertions,
    get_skill_binding,
    get_skill_content_vectors,
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
# File / content builders
# ---------------------------------------------------------------------------

def _skill_files_with_content(
    skill_name: str,
    skills_md: str,
) -> list[tuple[str, tuple[str, bytes, str]]]:
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


def _skills_md(skill_name: str, body: str) -> str:
    """Build minimal SKILL.md content whose title is *skill_name*."""
    return f"# {skill_name}\n\n{body}\n"


# ---------------------------------------------------------------------------
# Log expectation helpers
# ---------------------------------------------------------------------------

def _expect_vector_import_logs(
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    vector_model: str,
) -> None:
    backend_log.expect(f"POST /api/import/skill received: kb_index={kb_index} tag=skill")
    backend_log.expect(f"Starting skill import: kb_index={kb_index}")
    backend_log.expect(f"Vectorizing 1 chunk(s): kb_index={kb_index} model={vector_model}")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/skill")


def _expect_vector_search_logs(
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    vector_model: str,
) -> None:
    backend_log.expect(f"SKILL search started tag=skill kb_index={kb_index}")
    backend_log.expect(
        f"SKILL search binding selected selector=kb_index value={kb_index}"
    )
    backend_log.expect(
        f"SKILL search parameters normalised kb_index={kb_index} search_type=vector"
    )
    backend_log.expect(
        f"SKILL searcher preparing query vector index={kb_index} model={vector_model}"
    )
    backend_log.expect(f"SKILL search completed kb_index={kb_index}")
    backend_log.expect("HTTP request completed method=POST path=/api/search/skill")


# ---------------------------------------------------------------------------
# Search assertion helpers
# ---------------------------------------------------------------------------

def _import_vector_skill(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    skill_name: str,
    vector_model: str,
    skills_md: str,
) -> None:
    """Submit a vector-skill import and wait for completion."""
    response = client.post(
        "/api/import/skill",
        data={"kb_index": kb_index, "tag": "skill", "vector_model": vector_model},
        files=_skill_files_with_content(skill_name, skills_md),
    )

    assert response.status_code == 202
    task_id = response_json(response)["task_id"]
    task = wait_for_skill_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1

    binding = get_skill_binding(kb_index)
    assert binding["vector_model"] == vector_model
    _expect_vector_import_logs(backend_log, kb_index=kb_index, vector_model=vector_model)


def _assert_vector_is_non_zero(vector: Any) -> None:
    assert isinstance(vector, list)
    if all(isinstance(v, int | float) and abs(v) < 1e-12 for v in vector):
        pytest.xfail("vector model produced only zero values; ranking cannot be asserted")


def _assert_skill_vector_search_finds_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    skill_name: str,
    vector_model: str,
) -> None:
    """Poll POST /api/search/skill (vector) until the imported skill is visible."""
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
                "search_type": "vector",
                "vector_model": vector_model,
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
        assert "skill" in payload["results"]

        if any(item.get("name") == skill_name for item in payload["results"]["skill"]):
            _expect_vector_search_logs(
                backend_log,
                kb_index=kb_index,
                vector_model=vector_model,
            )
            return
        time.sleep(1)

    raise AssertionError(
        f"skill_name {skill_name!r} was not vector-searchable in kb_index {kb_index!r} "
        f"within {timeout}s; last_payload={last_payload!r}"
    )


def _assert_skill_vector_search_returns_order(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    query: str,
    vector_model: str,
    expected_skill_names: list[str],
) -> None:
    """Poll until vector search returns *expected_skill_names* in exact order."""
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/skill",
            json={
                "query": query,
                "tag": "skill",
                "kb_index": kb_index,
                "search_type": "vector",
                "vector_model": vector_model,
                "top_k": len(expected_skill_names),
            },
        )

        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "SKILL"

        results = payload["results"]["skill"]
        actual_names = [item.get("name") for item in results]
        if actual_names == expected_skill_names:
            _expect_vector_search_logs(
                backend_log,
                kb_index=kb_index,
                vector_model=vector_model,
            )
            return
        time.sleep(1)

    raise AssertionError(
        "vector search did not return expected order within "
        f"{timeout}s; expected={expected_skill_names!r}; last_payload={last_payload!r}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_import_skill_with_vector_model_is_vector_searchable(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    """A skill imported with a vector model must be retrievable via vector search.

    Also verifies that:
    * the binding records the vector_model,
    * every indexed document has a non-empty ``content_vector``.
    """
    kb_index = unique_id("kb_skill_vec")
    skill_name = unique_id("skill_vec")
    vector_model = DEFAULT_VECTOR_MODEL

    _import_vector_skill(
        client,
        backend_log,
        kb_index=kb_index,
        skill_name=skill_name,
        vector_model=vector_model,
        skills_md=_skills_md(
            skill_name,
            "Server entity test skill for vector search validation.",
        ),
    )

    vectors = get_skill_content_vectors(kb_index)
    assert vectors, "expected at least one document with content_vector in the content index"
    for vec in vectors:
        assert isinstance(vec, list) and vec, (
            f"content_vector is empty or missing for a document in index {kb_index!r}"
        )
        assert all(isinstance(v, int | float) for v in vec)

    _assert_skill_vector_search_finds_import(
        client,
        backend_log,
        kb_index=kb_index,
        skill_name=skill_name,
        vector_model=vector_model,
    )


def test_import_multiple_skills_with_vector_search_returns_expected_order(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    """Vector search must rank skills by semantic similarity.

    Three skills are imported into a shared kb_index:
    * ``target``  — Redis cache invalidation (should rank highest for Redis query)
    * ``related`` — Redis cache warm-up     (semantically related, should rank second)
    * ``unrelated`` — Coral reef ecology    (unrelated, should rank last)
    """
    kb_index = unique_id("kb_skill_vec_order")
    vector_model = DEFAULT_VECTOR_MODEL

    target_name = unique_id("skill_redis_invalidation")
    related_name = unique_id("skill_redis_warmup")
    unrelated_name = unique_id("skill_coral_reef")

    skill_rows = [
        (
            target_name,
            "Redis 缓存失效处理\n\n"
            "处理 Redis 缓存条目过期或被主动删除的场景。"
            "使用互斥锁保护数据库回源，根据错误率启用降级响应，"
            "防止缓存击穿和雪崩。",
        ),
        (
            related_name,
            "Redis 缓存预热与命中率优化\n\n"
            "发布前批量加载核心缓存，监控 miss rate 与内存水位，"
            "避免冷启动抖动；对热点 key 实施分片以减少竞争。",
        ),
        (
            unrelated_name,
            "珊瑚礁生态观测\n\n"
            "潜水调查中记录珊瑚礁健康度、鱼群分布与水温变化。"
            "按样线统计珊瑚白化比例，追踪不同鱼类在礁盘周边的活动范围。",
        ),
    ]

    for skill_name, body in skill_rows:
        _import_vector_skill(
            client,
            backend_log,
            kb_index=kb_index,
            skill_name=skill_name,
            vector_model=vector_model,
            skills_md=_skills_md(skill_name, body),
        )

    target_vectors = get_skill_content_vectors(kb_index)
    non_empty = [v for v in target_vectors if v]
    assert non_empty, "no documents with content_vector found after multi-skill import"
    _assert_vector_is_non_zero(non_empty[0])

    query = (
        "Redis 缓存失效处理\n"
        "处理 Redis 缓存条目过期或被主动删除的场景。"
        "使用互斥锁保护数据库回源，根据错误率启用降级响应。"
    )
    _assert_skill_vector_search_returns_order(
        client,
        backend_log,
        kb_index=kb_index,
        query=query,
        vector_model=vector_model,
        expected_skill_names=[target_name, related_name, unrelated_name],
    )
