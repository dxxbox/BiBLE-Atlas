from __future__ import annotations

import multiprocessing

from celery.signals import worker_init, worker_process_init

from bible.common.logger import get_logger
from bible.features.async_task.celery_app import celery_app  # noqa: F401 – registers the app
import bible.features.async_task.tasks.dispatch_task  # noqa: F401 – registers the task

logger = get_logger(__name__)

@worker_init.connect
def _bootstrap_worker(**_kwargs: object) -> None:
    multiprocessing.current_process().name = "celery-main"
    try:
        import importlib

        from bible.config.configure import get_bible_atlas_config
        from bible.features.async_task.container import build_task_container

        container = importlib.import_module("bible.features.import.container")

        config = get_bible_atlas_config()
        build_task_container(config)
        container.build_import_container(config)
        logger.info("Celery worker: import container initialized.")

        _preload_vector = bool(config.vector.preload_on_startup and config.vector.available_models)
        _preload_rerank = bool(config.rerank.preload_on_startup and config.rerank.available_models)
        if _preload_vector or _preload_rerank:
            from bible.infrastructure.vector.vector_tool import VectorTool
            from bible.infrastructure.vector.rerank_tool import RerankTool
            from bible.infrastructure.vector.model_preloader import VectorModelPreloader

            vector_tool = VectorTool(
                workspace_dir=config.storage.workspace_dir,
                hf_cache_dir=config.vector.hf_cache_dir,
            ) if _preload_vector else None
            rerank_tool = RerankTool(
                workspace_dir=config.storage.workspace_dir,
                hf_cache_dir=config.rerank.hf_cache_dir,
            ) if _preload_rerank else None
            preloader = VectorModelPreloader(
                config=config,
                vector_tool=vector_tool,
                rerank_tool=rerank_tool,
            )
            logger.info(
                "Celery worker: preloading models synchronously (vector=%s, rerank=%s)…",
                _preload_vector,
                _preload_rerank,
            )
            preloader.preload_all_models()
            logger.info("Celery worker: model preload complete.")
    except Exception:
        logger.exception("Celery worker: failed to initialize import container.")

@worker_process_init.connect
def _reset_db_connections(**_kwargs: object) -> None:
    try:
        import importlib
        container = importlib.import_module("bible.features.import.container")
        executor = getattr(container, "_import_executor", None)
        if executor is None:
            return

        mem_service = getattr(executor, "_memory_import_service", None)
        if mem_service is None:
            return
        store = getattr(mem_service, "_store_memory", None)
        if store is None:
            return
        db_factory = getattr(store, "_db_factory", None)
        if db_factory is None:
            return

        db_factory.reset()

        proc = multiprocessing.current_process()
        proc.name = proc.name.replace("ForkPoolWorker-", "Worker-")
        logger.info("Celery pool worker: DatabaseFactory reset after fork.")
    except Exception:
        logger.warning("Celery pool worker: skipped DB reset after fork due to initialization mismatch.")
