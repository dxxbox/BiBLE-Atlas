from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Valid state machine transitions.
# Terminal states (completed / failed / cancelled) have no outgoing edges.
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued":    frozenset({"running", "cancelled"}),
    "running":   frozenset({"completed", "failed"}),
    "completed": frozenset(),
    "failed":    frozenset(),
    "cancelled": frozenset(),
}
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AsyncTask:
    task_id: str
    task_type: str
    status: str  # queued / running / completed / failed / cancelled
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


class AsyncTaskRepository:
    def __init__(self) -> None:
        self._store: dict[str, AsyncTask] = {}
        self._lock = threading.Lock()

    def create(self, task_id: str, task_type: str, payload: dict[str, Any]) -> AsyncTask:
        task = AsyncTask(
            task_id=task_id,
            task_type=task_type,
            status="queued",
            payload=payload,
        )
        with self._lock:
            self._store[task_id] = task
        return task

    def get(self, task_id: str) -> AsyncTask | None:
        with self._lock:
            return self._store.get(task_id)

    def update_status(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AsyncTask:
        with self._lock:
            task = self._store.get(task_id)
            if task is None:
                raise KeyError(f"Task {task_id!r} not found")

            current = task.status
            allowed = _VALID_TRANSITIONS.get(current, frozenset())

            if status not in allowed:
                if current in _TERMINAL_STATES:
                    # Race condition: another path already reached a terminal state.
                    # Silently ignore so callers don't need to coordinate.
                    logger.debug(
                        "Ignoring transition %s → %s for task %s: already in terminal state.",
                        current, status, task_id,
                    )
                else:
                    logger.warning(
                        "Invalid transition %s → %s for task %s; update ignored.",
                        current, status, task_id,
                    )
                return task

            task.status = status
            task.updated_at = _utcnow()
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            return task

    def list_by_type(self, task_type: str) -> list[AsyncTask]:
        with self._lock:
            return [t for t in self._store.values() if t.task_type == task_type]
