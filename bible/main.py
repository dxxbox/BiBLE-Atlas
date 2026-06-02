from contextlib import asynccontextmanager
import importlib
import os
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from bible.api import knowledge_router, search_router, system_router

# Subpackage is bible.api.import; plain "from bible.api.import import ..." is invalid syntax.
import_router = importlib.import_module("bible.api.import").import_router
from bible.common import _get_version
from bible.common.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        from bible.config.configure import get_bible_atlas_config
        config = get_bible_atlas_config()

        from bible.features import build_import_container, build_task_container

        build_task_container(config)
        build_import_container(config)
        logger.info("Async task and import containers initialised.")

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
            preloader.preload_all_models_async()
            logger.info(
                "Model preloading triggered (vector=%s, rerank=%s).",
                _preload_vector,
                _preload_rerank,
            )
    except Exception:
        logger.exception("Error during startup initialisation")

    yield

    # ---- shutdown ----
    try:
        shutdown_task_container = importlib.import_module("bible.features.async_task.container").shutdown_task_container
        shutdown_import_container = importlib.import_module("bible.features.import.container").shutdown_import_container
        shutdown_import_container()
        shutdown_task_container()
        logger.info("Async task and import containers shut down.")
    except Exception:
        logger.exception("Error during shutdown")


def create_app() -> FastAPI:
    """Factory function to create and configure the FastAPI application."""
    app = FastAPI(
        title="BiBLE-Atlas",
        description="BiBLE-Atlas: Agent-native context DB",
        version=_get_version(),
        lifespan=_lifespan,
    )

    app.include_router(system_router)
    app.include_router(knowledge_router)
    app.include_router(import_router)
    app.include_router(search_router)

    return app


def main() -> None:
    """Main entry point for the BiBLE-Atlas application."""
    app = create_app()
    host = os.environ.get("BIBLE_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("BIBLE_SERVER_PORT", "5555"))
    logger.info("Starting BiBLE-Atlas application on %s:%d...", host, port)
    uvicorn.run(app, host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
