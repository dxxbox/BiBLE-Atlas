from __future__ import annotations

from typing import Any

from bible.features.async_task.celery_app import configure_celery_app
from bible.features.async_task.dispatcher import AsyncTaskDispatcher
from bible.features.async_task.redis_repository import RedisAsyncTaskRepository
from bible.features.async_task.service import AsyncTaskService
from bible.features.async_task.tasks.dispatch_task import clear_dispatch, configure_dispatch

_task_service: AsyncTaskService | None = None
_task_repository: Any | None = None
_task_dispatcher: AsyncTaskDispatcher | None = None


def build_task_container(config: Any) -> AsyncTaskService:
    """Build the global async-task infrastructure shared by all business domains."""

    global _task_service, _task_repository, _task_dispatcher
    if _task_service is not None:
        return _task_service

    configure_celery_app(
        broker_url=config.celery.broker_url,
        result_backend=config.celery.result_backend,
        task_acks_late=config.celery.task_acks_late,
        worker_prefetch_multiplier=config.celery.worker_prefetch_multiplier,
        worker_concurrency=config.celery.worker_concurrency,
    )

    _task_repository = RedisAsyncTaskRepository(redis_url=config.celery.broker_url)
    _task_dispatcher = AsyncTaskDispatcher()
    configure_dispatch(repository=_task_repository, dispatcher=_task_dispatcher)

    _task_service = AsyncTaskService(
        repository=_task_repository,
        task_timeout_seconds=_get_task_timeout_seconds(config),
    )
    return _task_service


def shutdown_task_container() -> None:
    global _task_service, _task_repository, _task_dispatcher
    clear_dispatch()
    _task_service = None
    _task_repository = None
    _task_dispatcher = None


def get_task_service() -> AsyncTaskService:
    if _task_service is None:
        from bible.config.configure import get_bible_atlas_config

        config = get_bible_atlas_config()
        return build_task_container(config)
    return _task_service


def get_task_repository() -> Any:
    service = get_task_service()
    if _task_repository is not None:
        return _task_repository
    return service._repository  # type: ignore[attr-defined]


def get_task_dispatcher() -> AsyncTaskDispatcher:
    if _task_dispatcher is None:
        from bible.config.configure import get_bible_atlas_config

        config = get_bible_atlas_config()
        build_task_container(config)
    if _task_dispatcher is None:
        raise RuntimeError("Async task dispatcher was not initialized")
    return _task_dispatcher


def _get_task_timeout_seconds(config: Any) -> int:
    async_task_config = getattr(config, "async_task", None)
    if async_task_config is not None:
        return async_task_config.task_timeout_seconds
    return getattr(config.import_memory, "task_timeout_seconds", 0)
