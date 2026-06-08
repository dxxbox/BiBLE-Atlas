import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request

from bible.api import control_router, knowledge_router, search_router, system_router
from bible.api.upload import upload_router
from bible.common import _get_version
from bible.common.logger import get_logger
from bible.features.async_task.container import build_task_container, shutdown_task_container
from bible.features.upload.container import shutdown_upload_container

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        from bible.config.configure import get_bible_atlas_config
        config = get_bible_atlas_config()

        from bible.features.upload.container import build_upload_container

        build_task_container(config)
        build_upload_container(config)
        logger.info("Async task and upload containers initialised.")

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
        shutdown_upload_container()
        shutdown_task_container()
        logger.info("Async task and upload containers shut down.")
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

    @app.middleware("http")
    async def log_http_request(request: Request, call_next):  # noqa: ANN001, ANN202
        started = time.perf_counter()
        method = request.method
        path = request.url.path
        query = request.url.query
        client_host = request.client.host if request.client else "-"
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "HTTP request failed method=%s path=%s query=%s client=%s duration_ms=%.2f",
                method,
                path,
                query or "-",
                client_host,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "HTTP request completed method=%s path=%s query=%s status_code=%d client=%s duration_ms=%.2f",
            method,
            path,
            query or "-",
            response.status_code,
            client_host,
            duration_ms,
        )
        return response

    app.include_router(system_router)
    app.include_router(knowledge_router)
    app.include_router(upload_router)
    app.include_router(search_router)
    app.include_router(control_router)

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
