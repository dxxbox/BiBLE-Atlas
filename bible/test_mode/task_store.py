from __future__ import annotations

from copy import deepcopy
from itertools import count
from typing import Any

from bible.common.logger import get_logger
from bible.test_mode.schemas import Domain, TaskFixture

logger = get_logger(__name__)


class InMemoryTaskStore:
    def __init__(self, tasks: list[TaskFixture] | None = None) -> None:
        self._tasks: dict[str, TaskFixture] = {}
        self._counter = count(1)
        for task in tasks or []:
            self._tasks[task.task_id] = task.model_copy(deep=True)

    def create(
        self,
        *,
        operation: str,
        domain: Domain,
        tag: str | None,
        status: str = "queued",
        final_status: str | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> TaskFixture:
        task_id = task_id or f"{operation}_{domain.lower()}_{next(self._counter):06d}"
        task = TaskFixture(
            task_id=task_id,
            task_type=f"{operation}.{domain.lower()}",
            domain=domain,
            tag=tag,
            status=status,  # type: ignore[arg-type]
            final_status=final_status,  # type: ignore[arg-type]
            result=deepcopy(result),
            error=deepcopy(error),
        )
        self._tasks[task_id] = task
        logger.info(
            "Test Mode task created task_id=%s task_type=%s domain=%s status=%s final_status=%s",
            task.task_id,
            task.task_type,
            task.domain,
            task.status,
            task.final_status,
        )
        return task.model_copy(deep=True)

    def get(self, task_id: str, *, advance: bool = True) -> TaskFixture | None:
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning("Test Mode task not found task_id=%s", task_id)
            return None
        if advance and task.status == "queued":
            task.status = "running"  # type: ignore[assignment]
            task.query_count += 1
            logger.info("Test Mode task advanced task_id=%s status=running", task_id)
        elif advance and task.status == "running":
            task.status = task.final_status or "completed"  # type: ignore[assignment]
            task.query_count += 1
            logger.info("Test Mode task advanced task_id=%s status=%s", task_id, task.status)
        return task.model_copy(deep=True)

    def cancel(self, task_id: str) -> tuple[TaskFixture | None, str | None]:
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning("Test Mode task cancel failed task_id=%s reason=not_found", task_id)
            return None, "TASK_NOT_FOUND"
        if task.status in {"queued", "running"}:
            task.status = "cancelled"  # type: ignore[assignment]
            logger.info("Test Mode task cancelled task_id=%s", task_id)
            return task.model_copy(deep=True), None
        if task.status == "completed":
            logger.warning("Test Mode task cancel rejected task_id=%s status=completed", task_id)
            return task.model_copy(deep=True), "TASK_ALREADY_COMPLETED"
        if task.status == "failed":
            logger.warning("Test Mode task cancel rejected task_id=%s status=failed", task_id)
            return task.model_copy(deep=True), "TASK_ALREADY_FINISHED"
        return task.model_copy(deep=True), None

