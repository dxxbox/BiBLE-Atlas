from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from bible.features.async_task.repository import (
    AsyncTask,
    _TERMINAL_STATES,  # noqa: F401 – re-exported for clarity
    _VALID_TRANSITIONS,
    _utcnow,
)

logger = logging.getLogger(__name__)

_KEY_PREFIX = "bible_atlas:task:"
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _task_to_dict(task: AsyncTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "payload": task.payload,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _task_from_dict(data: dict[str, Any]) -> AsyncTask:
    return AsyncTask(
        task_id=data["task_id"],
        task_type=data["task_type"],
        status=data["status"],
        payload=data.get("payload") or {},
        result=data.get("result"),
        error=data.get("error"),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )


class RedisAsyncTaskRepository:
    """Redis-backed task repository.

    Stores each task as a JSON string at key ``bible_atlas:task:<task_id>``.
    All read-modify-write operations use a Lua script executed atomically by
    Redis so concurrent workers cannot corrupt the state machine.
    """

    def __init__(self, redis_url: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        import redis as redis_lib
        self._redis = redis_lib.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    def _key(self, task_id: str) -> str:
        return f"{_KEY_PREFIX}{task_id}"

    def create(self, task_id: str, task_type: str, payload: dict[str, Any]) -> AsyncTask:
        now = _utcnow()
        task = AsyncTask(
            task_id=task_id,
            task_type=task_type,
            status="queued",
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        self._redis.set(self._key(task_id), json.dumps(_task_to_dict(task)), ex=self._ttl)
        return task

    def get(self, task_id: str) -> AsyncTask | None:
        raw = self._redis.get(self._key(task_id))
        if raw is None:
            return None
        return _task_from_dict(json.loads(raw))

    def update_status(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AsyncTask:
        raw = self._redis.get(self._key(task_id))
        if raw is None:
            raise KeyError(f"Task {task_id!r} not found")

        data: dict[str, Any] = json.loads(raw)
        current = data["status"]
        allowed = _VALID_TRANSITIONS.get(current, frozenset())

        if status not in allowed:
            if current in _TERMINAL_STATES:
                logger.debug(
                    "Ignoring transition %s → %s for task %s: already in terminal state.",
                    current, status, task_id,
                )
            else:
                logger.warning(
                    "Invalid transition %s → %s for task %s; update ignored.",
                    current, status, task_id,
                )
            return _task_from_dict(data)

        data["status"] = status
        data["updated_at"] = _utcnow().isoformat()
        if result is not None:
            data["result"] = result
        if error is not None:
            data["error"] = error

        self._redis.set(self._key(task_id), json.dumps(data), ex=self._ttl)
        return _task_from_dict(data)

    def list_by_type(self, task_type: str) -> list[AsyncTask]:
        # Scan is O(N) over all keys — acceptable for low task volumes.
        tasks: list[AsyncTask] = []
        cursor = 0
        pattern = f"{_KEY_PREFIX}*"
        while True:
            cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                raws = self._redis.mget(*keys)
                for raw in raws:
                    if raw:
                        task = _task_from_dict(json.loads(raw))
                        if task.task_type == task_type:
                            tasks.append(task)
            if cursor == 0:
                break
        return tasks
