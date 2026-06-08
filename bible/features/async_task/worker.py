"""Celery worker entry point.

Start the worker with:
    celery -A bible.features.async_task.worker worker --loglevel=info
"""
from __future__ import annotations

import multiprocessing

from celery.signals import worker_init, worker_process_init

from bible.common.logger import get_logger
from bible.features.async_task.celery_app import celery_app  # noqa: F401 – registers the app
import bible.features.async_task.tasks.dispatch_task  # noqa: F401 – registers the task
from bible.features.upload import container as upload_container

logger = get_logger(__name__)


@worker_init.connect
def _bootstrap_worker(**_kwargs: object) -> None:
    """Initialize the upload container when the Celery main worker process starts."""
    multiprocessing.current_process().name = "celery-main"
    try:
        from bible.config.configure import get_bible_atlas_config
        from bible.features.async_task.container import build_task_container

        config = get_bible_atlas_config()
        build_task_container(config)
        upload_container.build_upload_container(config)
        logger.info("Celery worker: upload container initialized.")

        # Worker 独立进程，需在 fork pool workers 之前同步预加载所有模型。
        # fork 后的 pool workers 直接继承已填充的 _model_cache，
        # 不需要在任务执行时重复加载（每个大模型冷启动需 10-15s）。
        # 代价：deploy.sh 等待 PID 文件的超时需要足够长（见 worker_start）。
        _preload_vector = bool(config.vector.preload_on_startup and config.vector.available_models)
        _preload_rerank = bool(config.rerank.preload_on_startup and config.rerank.available_models)
        if _preload_vector or _preload_rerank:
            from bible.infrastructure.vector.vector_tool import VectorTool
            from bible.infrastructure.vector.rerank_tool import RerankTool
            from bible.infrastructure.vector.model_preloader import VectorModelPreloader

            vector_tool = VectorTool(
                workspace_dir=config.workspace.root,
                hf_cache_dir=config.vector.hf_cache_dir,
            ) if _preload_vector else None
            rerank_tool = RerankTool(
                workspace_dir=config.workspace.root,
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
        logger.exception("Celery worker: failed to initialize upload container.")


@worker_process_init.connect
def _reset_db_connections(**_kwargs: object) -> None:
    """Reset database connection pool in each forked pool worker.

    Celery uses a prefork pool: the main process builds the container, then forks
    worker subprocesses. Forking after threading can leave internal locks (e.g.
    import locks, urllib3 connection pool locks) in a partially-acquired state in
    the child, causing the first OpenSearch call to deadlock indefinitely.

    Resetting the DatabaseFactory in every forked worker ensures each subprocess
    opens its own fresh connections rather than inheriting potentially-broken ones.
    """
    try:
        executor = getattr(upload_container, "_upload_executor", None)
        if executor is None:
            return

        mem_service = getattr(executor, "_memory_upload_service", None)
        if mem_service is not None:
            store_mem = getattr(mem_service, "_store_memory", None)
            db_factory_mem = getattr(store_mem, "_db_factory", None) if store_mem is not None else None
            if db_factory_mem is not None:
                db_factory_mem.reset()

        skill_service = getattr(executor, "_skill_import_service", None)
        if skill_service is not None:
            store_skill = getattr(skill_service, "_store_skill", None)
            db_factory_skill = getattr(store_skill, "_db_factory", None) if store_skill is not None else None
            if db_factory_skill is not None:
                db_factory_skill.reset()

        # Shorten the default name "ForkPoolWorker-N" → "Worker-N" for cleaner log output.
        proc = multiprocessing.current_process()
        proc.name = proc.name.replace("ForkPoolWorker-", "Worker-")
        logger.info("Celery pool worker: DatabaseFactory reset after fork.")
    except Exception:
        logger.warning("Celery pool worker: skipped DB reset after fork due to initialization mismatch.")
