from __future__ import annotations

"""Lightweight dependency-injection container for the import feature."""

from typing import Any

from bible.features.async_task.container import get_task_dispatcher
from bible.features.async_task.dispatcher import AsyncTaskDispatcher
from .import_task_executor import ImportTaskExecutor
from .memory_import.memory_import_service import MemoryImportService
from .memory_import.storage.store_memory import StoreMemory
from .parser_runtime.ast_guard import ASTGuard
from .parser_runtime.sandbox_runner import SandboxRunner
from .workspace_sweeper import WorkspaceSweeper

_import_executor: ImportTaskExecutor | None = None
_workspace_sweeper: WorkspaceSweeper | None = None


def build_import_container(
    config: Any,
    task_dispatcher: AsyncTaskDispatcher | None = None,
) -> ImportTaskExecutor:
    global _import_executor, _workspace_sweeper
    if _import_executor is not None:
        dispatcher = task_dispatcher or get_task_dispatcher()
        dispatcher.register("import.memory", _import_executor)
        return _import_executor

    workspace_dir: str = config.storage.workspace_dir
    parsers_dir: str = config.import_memory.parsers_dir

    store_memory = StoreMemory(workspace_dir=workspace_dir, config=config)
    ast_guard = ASTGuard()
    sandbox_runner = SandboxRunner(timeout_seconds=config.import_memory.sandbox_timeout_seconds)

    memory_import_service = MemoryImportService(
        store_memory=store_memory,
        ast_guard=ast_guard,
        sandbox_runner=sandbox_runner,
        parsers_dir=parsers_dir,
        config=config,
    )

    _import_executor = ImportTaskExecutor(memory_import_service=memory_import_service)
    dispatcher = task_dispatcher or get_task_dispatcher()
    dispatcher.register("import.memory", _import_executor)

    _workspace_sweeper = WorkspaceSweeper(
        store=store_memory,
        ttl_hours=config.import_memory.workspace_ttl_hours,
        interval_seconds=config.import_memory.sweep_interval_seconds,
    )
    _workspace_sweeper.start()

    return _import_executor


def shutdown_import_container() -> None:
    """Stop background services gracefully (call during application shutdown)."""
    global _import_executor, _workspace_sweeper
    if _workspace_sweeper is not None:
        _workspace_sweeper.stop()
        _workspace_sweeper = None
    _import_executor = None


def get_task_service() -> Any:
    """Compatibility shim; task service ownership lives in async_task.container."""
    from bible.features.async_task.container import get_task_service as _get_task_service

    return _get_task_service()


def get_task_repository() -> Any:
    """Compatibility shim; task repository ownership lives in async_task.container."""
    from bible.features.async_task.container import get_task_repository as _get_task_repository

    return _get_task_repository()
