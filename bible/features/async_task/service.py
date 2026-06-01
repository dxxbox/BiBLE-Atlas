from __future__ import annotations

import uuid
from typing import Any

from bible.common.logger import get_logger
from bible.features.async_task.celery_app import celery_app
from bible.features.async_task.repository import AsyncTask, AsyncTaskRepository

logger = get_logger(__name__)

class AsyncTaskService:
    def __init__(
        self,
        repository: AsyncTaskRepository,
        task_timeout_seconds: int = 0,
    ) -> None:
        self._repository = repository
        # 0 or negative means no timeout
        self._task_timeout: int | None = task_timeout_seconds if task_timeout_seconds > 0 else None

    def submit(
        self,
        task_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        from bible.features.async_task.tasks.dispatch_task import dispatch_task

        task_id = idempotency_key or str(uuid.uuid4())
        task = self._repository.create(task_id=task_id, task_type=task_type, payload=payload)

        apply_kwargs: dict[str, Any] = {"task_id": task_id}
        if self._task_timeout is not None:
            apply_kwargs["soft_time_limit"] = self._task_timeout

        try:
            dispatch_task.apply_async(args=[task_id, task_type, payload], **apply_kwargs)
        except Exception as exc:
            self._repository.update_status(task_id, "cancelled")
            logger.error("Failed to enqueue task %s: %s", task_id, exc)
            from bible.common.errors import DomainError, ErrorCode
            raise DomainError(
                ErrorCode.INTERNAL,
                f"Task broker unavailable: {exc}",
            ) from exc

        return {"task_id": task.task_id, "status": task.status}

    def get(self, task_id: str) -> dict[str, Any] | None:
        task = self._repository.get(task_id)
        if task is None:
            return None
        return self._task_to_dict(task)
    
    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self._repository.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id!r} not found")
        if task.status == "queued":
            celery_app.control.revoke(task_id)
            self._repository.update_status(task_id, "cancelled")
        elif task.status == "running":
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        task = self._repository.get(task_id)
        return self._task_to_dict(task)

    @staticmethod
    def _task_to_dict(task: AsyncTask) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }        