from __future__ import annotations

from typing import Any, Protocol

from bible.common.errors import DomainError, ErrorCode


class TaskHandler(Protocol):
    def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class AsyncTaskDispatcher:
    """Registry-based dispatcher for async tasks across business domains."""

    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, task_type: str, handler: TaskHandler) -> None:
        if not task_type:
            raise ValueError("task_type must not be empty")
        self._handlers[task_type] = handler

    def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(task_type)
        if handler is None:
            raise DomainError(
                ErrorCode.NOT_IMPLEMENTED,
                f"Unknown task type: {task_type}",
            )
        return handler.execute(task_id, task_type, payload)

    def registered_task_types(self) -> list[str]:
        return sorted(self._handlers)
