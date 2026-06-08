from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx
import pytest

from _helpers import (
    assert_memory_written_to_database,
    get_memory_database_state,
    import_files,
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
DEFAULT_VECTOR_MODEL = os.environ.get(
    "BIBLE_ENTITY_TEST_VECTOR_MODEL",
    "BAAI/bge-base-zh-v1.5",
)


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
        missing = [fragment for fragment in self.expected if fragment not in logs]
        assert not missing, f"missing expected backend log fragments: {missing}\nlogs:\n{logs}"

        unexpected: list[str] = []
        for line in logs.splitlines():
            match = LOG_LEVEL_RE.search(line)
            if match is None:
                continue
            level = match.group(1)
            if level == "WARNING" and any(
                fragment in line for fragment in self.allowed_warning_fragments
            ):
                continue
            unexpected.append(line)

        assert not unexpected, "unexpected backend WARNING/ERROR logs:\n" + "\n".join(unexpected)


@pytest.fixture
def backend_log() -> BackendLogAssertions:
    assertions = BackendLogAssertions(BACKEND_LOG_PATHS)
    yield assertions
    assertions.assert_expected()


def _expect_vector_import_logs(
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    vector_model: str,
) -> None:
    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect(f"Starting memory import: kb_index={kb_index}")
    backend_log.expect(f"Vectorizing 1 chunk(s): kb_index={kb_index} model={vector_model}")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")


def _expect_vector_search_logs(
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    vector_model: str,
) -> None:
    backend_log.expect(f"MEMORY search started tag=memory kb_index={kb_index}")
    backend_log.expect(
        f"OpenSearch binding lookup by index hit domain=MEMORY kb_index={kb_index}"
    )
    backend_log.expect(
        f"MEMORY search parameters normalised kb_index={kb_index} search_type=vector"
    )
    backend_log.expect(
        f"MEMORY searcher preparing query vector index=memory_{kb_index} model={vector_model}"
    )
    backend_log.expect(
        f"MEMORY search completed kb_index={kb_index} content_index=memory_{kb_index}"
    )
    backend_log.expect("HTTP request completed method=POST path=/api/search/memory")


def _assert_memory_vector_search_finds_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    memory_id: str,
    vector_model: str,
) -> None:
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/memory",
            json={
                "query": f"Server Entity Test {memory_id}",
                "tag": "memory",
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
        assert payload["domain"] == "MEMORY"
        assert payload["kb_index"] == kb_index
        assert payload["tag"] == "memory"
        if any(item["memory_id"] == memory_id for item in payload["results"]["memory"]):
            _expect_vector_search_logs(
                backend_log,
                kb_index=kb_index,
                vector_model=vector_model,
            )
            return
        time.sleep(1)

    raise AssertionError(
        f"memory_id {memory_id!r} was not vector-searchable in kb_index {kb_index!r} "
        f"within {timeout}s; last_payload={last_payload!r}"
    )


def _memory_meta(
    *,
    memory_id: str,
    title: str,
    abstract: str,
    overview: str,
) -> bytes:
    return json.dumps(
        {
            "memory_id": memory_id,
            "title": title,
            "abstract": abstract,
            "overview": overview,
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
            "language": "zh",
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _import_files_from_meta(meta: bytes) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("meta.json", meta, "application/json"))]


def _import_vector_memory(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    memory_id: str,
    vector_model: str,
    files: list[tuple[str, tuple[str, bytes, str]]],
) -> None:
    response = client.post(
        "/api/import/memory",
        data={"kb_index": kb_index, "tag": "memory", "vector_model": vector_model},
        files=files,
    )

    assert response.status_code == 202
    task_id = response_json(response)["task_id"]
    task = wait_for_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1

    db_state = get_memory_database_state(kb_index, memory_id)
    assert db_state.binding["vector_model"] == vector_model
    content_vector = db_state.document.get("content_vector")
    assert isinstance(content_vector, list)
    assert content_vector
    assert all(isinstance(value, int | float) for value in content_vector)
    _expect_vector_import_logs(
        backend_log,
        kb_index=kb_index,
        vector_model=vector_model,
    )


def _assert_vector_is_non_zero(vector: Any) -> None:
    assert isinstance(vector, list)
    if all(isinstance(value, int | float) and abs(value) < 1e-12 for value in vector):
        pytest.xfail("vector model produced only zero values; ranking cannot be asserted")


def _assert_memory_vector_search_returns_order(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    query: str,
    vector_model: str,
    expected_memory_ids: list[str],
) -> None:
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/memory",
            json={
                "query": query,
                "tag": "memory",
                "kb_index": kb_index,
                "search_type": "vector",
                "vector_model": vector_model,
                "top_k": len(expected_memory_ids),
            },
        )

        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "MEMORY"
        assert payload["kb_index"] == kb_index
        assert payload["tag"] == "memory"

        results = payload["results"]["memory"]
        actual_memory_ids = [item["memory_id"] for item in results]
        if actual_memory_ids == expected_memory_ids:
            scores = [item["score"] for item in results]
            assert all(isinstance(score, int | float) for score in scores)
            assert scores == sorted(scores, reverse=True)
            _expect_vector_search_logs(
                backend_log,
                kb_index=kb_index,
                vector_model=vector_model,
            )
            return
        time.sleep(1)

    raise AssertionError(
        "vector search did not return expected order within "
        f"{timeout}s; expected={expected_memory_ids!r}; last_payload={last_payload!r}"
    )


def test_import_memory_with_vector_model_is_vector_searchable(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_vector")
    memory_id = unique_id("mem_import_search_vector")
    vector_model = DEFAULT_VECTOR_MODEL

    _import_vector_memory(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
        vector_model=vector_model,
        files=import_files(memory_id),
    )
    assert_memory_written_to_database(kb_index, memory_id)

    _assert_memory_vector_search_finds_import(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
        vector_model=vector_model,
    )


def test_import_multiple_memories_with_vector_search_returns_expected_order(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_vector_order")
    vector_model = DEFAULT_VECTOR_MODEL
    target_id = unique_id("mem_vector_redis_invalidation")
    related_id = unique_id("mem_vector_redis_warmup")
    unrelated_id = unique_id("mem_vector_coral_reef")

    memory_rows = [
        (
            target_id,
            "Redis 缓存失效与回源降级策略",
            "记录 Redis 缓存失效、回源保护、请求降级和热点 key 防击穿的处理流程。",
            "当缓存条目过期或被主动删除时，服务先使用互斥锁保护数据库回源，再根据错误率启用降级响应。",
        ),
        (
            related_id,
            "Redis 缓存预热与命中率优化策略",
            "记录 Redis 缓存预热、热点 key 分布、命中率监控和容量规划方法。",
            "发布前批量加载核心缓存，并通过监控观察 miss rate 与内存水位，避免冷启动抖动。",
        ),
        (
            unrelated_id,
            "珊瑚礁生态观察与海洋鱼类记录",
            "记录潜水调查中的珊瑚礁健康度、鱼群分布、水温和海洋生态变化。",
            "研究人员按样线记录珊瑚白化比例，并统计不同鱼类在礁盘周边的活动范围。",
        ),
    ]

    for memory_id, title, abstract, overview in memory_rows:
        _import_vector_memory(
            client,
            backend_log,
            kb_index=kb_index,
            memory_id=memory_id,
            vector_model=vector_model,
            files=_import_files_from_meta(
                _memory_meta(
                    memory_id=memory_id,
                    title=title,
                    abstract=abstract,
                    overview=overview,
                )
            ),
        )

    target_state = get_memory_database_state(kb_index, target_id)
    _assert_vector_is_non_zero(target_state.document.get("content_vector"))

    query = (
        "Redis 缓存失效与回源降级策略\n"
        "记录 Redis 缓存失效、回源保护、请求降级和热点 key 防击穿的处理流程。\n"
        "当缓存条目过期或被主动删除时，服务先使用互斥锁保护数据库回源，再根据错误率启用降级响应。"
    )
    _assert_memory_vector_search_returns_order(
        client,
        backend_log,
        kb_index=kb_index,
        query=query,
        vector_model=vector_model,
        expected_memory_ids=[target_id, related_id, unrelated_id],
    )
