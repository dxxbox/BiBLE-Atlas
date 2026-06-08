from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from bible.api.deps import get_async_task_service
from bible.common.logger import get_logger
from bible.features.async_task.service import AsyncTaskService

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/control/admin/tasks/{task_id}", tags=["Control"])
async def get_task(
    task_id: str,
    task_service: AsyncTaskService = Depends(get_async_task_service),
) -> dict[str, Any]:
    """Return the current state of a generic async task."""
    task = task_service.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Task {task_id!r} not found"},
        )
    return task


@router.delete("/api/control/admin/tasks/{task_id}", tags=["Control"])
async def cancel_task(
    task_id: str,
    task_service: AsyncTaskService = Depends(get_async_task_service),
) -> dict[str, Any]:
    """Cancel a generic async task when it is still cancellable."""
    try:
        return task_service.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Task {task_id!r} not found"},
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error while cancelling task %s", task_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to cancel task"},
        ) from exc
