from __future__ import annotations

from datetime import datetime
from typing import Any

from bible.features.async_task.repository import AsyncTask
from bible.infrastructure.database.base import IDatabaseWriter


class DatabaseAsyncTaskRepository:
    """Async task repository backed by the v4 database writer protocol."""

    def __init__(self, writer: IDatabaseWriter) -> None:
        self._writer = writer

    def create(self, task_id: str, task_type: str, payload: dict[str, Any]) -> AsyncTask:
        task_doc = {
            "task_id": task_id,
            "task_type": task_type,
            "status": "queued",
            "payload": payload,
        }
        self._writer.create_async_task(task_doc)
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id!r} was not created")
        return task

    def get(self, task_id: str) -> AsyncTask | None:
        raw = self._writer.get_async_task(task_id)
        if raw is None:
            return None
        return self._task_from_dict(raw)

    def update_status(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AsyncTask:
        patch: dict[str, Any] = {"status": status}
        if result is not None:
            patch["result"] = result
        if error is not None:
            patch["error"] = error
        updated = self._writer.update_async_task(task_id, patch)
        if not updated:
            raise KeyError(f"Task {task_id!r} not found")
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id!r} not found after update")
        return task

    def list_by_type(self, task_type: str) -> list[AsyncTask]:
        # The database writer protocol intentionally avoids exposing broad scans for v4 phase one.
        del task_type
        return []

    def _task_from_dict(self, data: dict[str, Any]) -> AsyncTask:
        return AsyncTask(
            task_id=data["task_id"],
            task_type=data["task_type"],
            status=data["status"],
            payload=data.get("payload") or {},
            result=data.get("result"),
            error=data.get("error"),
            created_at=self._parse_datetime(data.get("created_at")),
            updated_at=self._parse_datetime(data.get("updated_at")),
        )

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return datetime.now().astimezone()
