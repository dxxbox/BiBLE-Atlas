"""
Tests for RedisAsyncTaskRepository.

Uses fakeredis so no real Redis server is required.

Covers:
1. create → stores task with status "queued"
2. get → returns None for unknown task_id
3. get → deserialises all fields correctly
4. update_status → valid transition succeeds
5. update_status → invalid non-terminal transition is silently ignored
6. update_status → terminal state cannot be overwritten
7. update_status → raises KeyError for unknown task_id
8. update_status → result and error fields are written
9. list_by_type → returns only matching task_type
"""

from __future__ import annotations

import json
from unittest.mock import patch

import fakeredis
import pytest

from bible.features.async_task.redis_repository import RedisAsyncTaskRepository


# ---------------------------------------------------------------------------
# Fixture: in-process fake Redis (no server needed)
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo() -> RedisAsyncTaskRepository:
    fake = fakeredis.FakeRedis(decode_responses=True)
    r = RedisAsyncTaskRepository.__new__(RedisAsyncTaskRepository)
    r._redis = fake
    r._ttl = 3600
    return r


# ---------------------------------------------------------------------------
# 1 & 3. create / get round-trip
# ---------------------------------------------------------------------------

class TestCreateAndGet:
    def test_create_returns_queued_task(self, repo: RedisAsyncTaskRepository) -> None:
        task = repo.create("t1", "import.memory", {"k": "v"})
        assert task.task_id == "t1"
        assert task.task_type == "import.memory"
        assert task.status == "queued"
        assert task.payload == {"k": "v"}

    def test_get_returns_stored_task(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {"x": 1})
        task = repo.get("t1")
        assert task is not None
        assert task.task_id == "t1"
        assert task.payload == {"x": 1}

    def test_get_returns_none_for_unknown(self, repo: RedisAsyncTaskRepository) -> None:
        assert repo.get("ghost") is None

    def test_result_and_error_default_none(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        task = repo.get("t1")
        assert task is not None
        assert task.result is None
        assert task.error is None


# ---------------------------------------------------------------------------
# 4–8. update_status
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    def test_valid_transition_queued_to_running(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        task = repo.update_status("t1", "running")
        assert task.status == "running"
        assert repo.get("t1").status == "running"

    def test_valid_transition_running_to_completed(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        repo.update_status("t1", "running")
        task = repo.update_status("t1", "completed", result={"ok": True})
        assert task.status == "completed"
        assert task.result == {"ok": True}

    def test_valid_transition_running_to_failed(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        repo.update_status("t1", "running")
        task = repo.update_status("t1", "failed", error="boom")
        assert task.status == "failed"
        assert task.error == "boom"

    def test_valid_transition_queued_to_cancelled(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        task = repo.update_status("t1", "cancelled")
        assert task.status == "cancelled"

    def test_invalid_transition_is_ignored(self, repo: RedisAsyncTaskRepository) -> None:
        """queued → completed skips running; must be silently ignored."""
        repo.create("t1", "import.memory", {})
        task = repo.update_status("t1", "completed")
        assert task.status == "queued"  # unchanged

    def test_terminal_state_cannot_be_overwritten(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        repo.update_status("t1", "running")
        repo.update_status("t1", "completed", result={"ok": True})
        # Second write after terminal must be silently ignored
        task = repo.update_status("t1", "failed", error="late")
        assert task.status == "completed"
        assert task.error is None

    def test_raises_key_error_for_unknown_task(self, repo: RedisAsyncTaskRepository) -> None:
        with pytest.raises(KeyError):
            repo.update_status("ghost", "running")

    def test_error_field_is_persisted(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        repo.update_status("t1", "running")
        repo.update_status("t1", "failed", error="timeout")
        assert repo.get("t1").error == "timeout"


# ---------------------------------------------------------------------------
# 9. list_by_type
# ---------------------------------------------------------------------------

class TestListByType:
    def test_returns_only_matching_type(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        repo.create("t2", "import.skill", {})
        repo.create("t3", "import.memory", {})

        results = repo.list_by_type("import.memory")
        ids = {t.task_id for t in results}
        assert ids == {"t1", "t3"}

    def test_returns_empty_when_no_match(self, repo: RedisAsyncTaskRepository) -> None:
        repo.create("t1", "import.memory", {})
        assert repo.list_by_type("import.skill") == []
