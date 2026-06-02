from __future__ import annotations

from typing import TYPE_CHECKING, Any

from celery.exceptions import SoftTimeLimitExceeded

from bible.common.errors import DomainError, ErrorCode
from bible.common.logger import get_logger
from bible.features.async_task.celery_app import celery_app
from bible.features.async_task.dispatcher import AsyncTaskDispatcher

if TYPE_CHECKING:
    from bible.features.async_task.repository import AsyncTaskRepository

logger = get_logger(__name__)

_repository: "AsyncTaskRepository | None" = None
_dispatcher: AsyncTaskDispatcher | None = None


def configure_dispatch(
    repository: "AsyncTaskRepository",
    dispatcher: AsyncTaskDispatcher,
) -> None:
    global _repository, _dispatcher
    _repository = repository
    _dispatcher = dispatcher


def clear_dispatch() -> None:
    global _repository, _dispatcher
    _repository = None
    _dispatcher = None


@celery_app.task(name="bible_atlas.dispatch_task", ignore_result=True)
def dispatch_task(task_id: str, task_type: str, payload: dict[str, Any]) -> None:
    if _repository is None or _dispatcher is None:
        raise RuntimeError("dispatch_task not configured; call configure_dispatch() first")

    # Guard against the cancel-race: if the task was cancelled between submit() and
    # the worker picking it up, skip execution entirely.
    task = _repository.get(task_id)
    if task is not None and task.status == "cancelled":
        logger.info("Task %s was cancelled before execution started; skipping.", task_id)
        return

    _repository.update_status(task_id, "running")
    try:
        result = _dispatcher.execute(task_id, task_type, payload)
        _repository.update_status(task_id, "completed", result=result)
    except SoftTimeLimitExceeded:
        logger.error("Task %s timed out (soft time limit reached).", task_id)
        _repository.update_status(task_id, "failed", error="Task exceeded configured timeout")
    except DomainError as exc:
        logger.warning("Task %s failed with domain error: %s", task_id, exc.message)
        _repository.update_status(
            task_id,
            "failed",
            error=exc.message,
            result={"code": exc.code.value, "details": exc.details},
        )
    except Exception as exc:
        logger.exception("Task %s failed with unexpected error", task_id)
        _repository.update_status(
            task_id,
            "failed",
            error=str(exc),
            result={"code": ErrorCode.INTERNAL.value},
        )
