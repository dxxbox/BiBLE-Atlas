from __future__ import annotations

"""Lightweight dependency-injection container for the upload feature."""

from typing import Any


from bible.features.async_task.container import get_task_dispatcher
from bible.features.async_task.dispatcher import AsyncTaskDispatcher
from .memory_upload.memory_upload_service import MemoryUploadService
from .memory_upload.storage.store_memory import StoreMemory
from .skill_upload.skill_upload_service import SkillImportService
from .skill_upload.storage.store_skill import StoreSkill
from .parser_runtime.ast_guard import ASTGuard
from .parser_runtime.sandbox_runner import SandboxRunner
from .upload_task_executor import UploadTaskExecutor
from .workspace_sweeper import WorkspaceSweeper

_upload_executor: UploadTaskExecutor | None = None
_workspace_sweeper: WorkspaceSweeper | None = None
_skill_workspace_sweeper: WorkspaceSweeper | None = None


def build_upload_container(
    config: Any,
    task_dispatcher: AsyncTaskDispatcher | None = None,
) -> UploadTaskExecutor:
    global _upload_executor, _workspace_sweeper, _skill_workspace_sweeper
    if _upload_executor is not None:
        dispatcher = task_dispatcher or get_task_dispatcher()
        dispatcher.register("import.memory", _upload_executor)
        dispatcher.register("import.skill", _upload_executor)
        return _upload_executor

    workspace_dir: str = config.workspace.root

    # --- Memory upload service ---
    memory_parsers_dir: str = config.import_memory.parsers_dir
    store_memory = StoreMemory(workspace_dir=workspace_dir, config=config)
    ast_guard = ASTGuard()
    memory_sandbox_runner = SandboxRunner(timeout_seconds=config.import_memory.sandbox_timeout_seconds)

    memory_upload_service = MemoryUploadService(
        store_memory=store_memory,
        ast_guard=ast_guard,
        sandbox_runner=memory_sandbox_runner,
        parsers_dir=memory_parsers_dir,
        config=config,
    )

    # --- Skill upload service ---
    skill_parsers_dir: str = config.import_skill.parsers_dir
    store_skill = StoreSkill(workspace_dir=workspace_dir, config=config)
    skill_sandbox_runner = SandboxRunner(timeout_seconds=config.import_skill.sandbox_timeout_seconds)

    skill_import_service = SkillImportService(
        store_skill=store_skill,
        ast_guard=ast_guard,
        sandbox_runner=skill_sandbox_runner,
        parsers_dir=skill_parsers_dir,
        config=config,
    )

    _upload_executor = UploadTaskExecutor(
        memory_upload_service=memory_upload_service,
        skill_import_service=skill_import_service,
    )
    dispatcher = task_dispatcher or get_task_dispatcher()
    dispatcher.register("import.memory", _upload_executor)
    dispatcher.register("import.skill", _upload_executor)

    _workspace_sweeper = WorkspaceSweeper(
        store=store_memory,
        ttl_hours=config.import_memory.workspace_ttl_hours,
        interval_seconds=config.import_memory.sweep_interval_seconds,
    )
    _workspace_sweeper.start()

    _skill_workspace_sweeper = WorkspaceSweeper(
        store=store_skill,
        ttl_hours=config.import_skill.workspace_ttl_hours,
        interval_seconds=config.import_skill.sweep_interval_seconds,
    )
    _skill_workspace_sweeper.start()

    return _upload_executor


def shutdown_upload_container() -> None:
    """Stop background services gracefully (call during application shutdown)."""
    global _upload_executor, _workspace_sweeper, _skill_workspace_sweeper
    if _workspace_sweeper is not None:
        _workspace_sweeper.stop()
        _workspace_sweeper = None
    if _skill_workspace_sweeper is not None:
        _skill_workspace_sweeper.stop()
        _skill_workspace_sweeper = None
    _upload_executor = None


def get_task_service() -> Any:
    """Compatibility shim; task service ownership lives in async_task.container."""
    from bible.features.async_task.container import get_task_service as _get_task_service

    return _get_task_service()


def get_task_repository() -> Any:
    """Compatibility shim; task repository ownership lives in async_task.container."""
    from bible.features.async_task.container import get_task_repository as _get_task_repository

    return _get_task_repository()
