from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from bible.common import _get_version
from bible.common.logger import get_logger
from bible.test_mode.artifact_store import ArtifactStore
from bible.test_mode.fixture_store import FixtureStore
from bible.test_mode.resolver import FixtureResolver
from bible.test_mode.routes import router
from bible.test_mode.task_store import InMemoryTaskStore

logger = get_logger(__name__)


def create_app(*, fixture_path: str | None = None, strict: bool = True) -> FastAPI:
    fixture_store = FixtureStore.load(fixture_path=fixture_path, strict=strict)
    app = FastAPI(
        title="BiBLE-Atlas Test Mode",
        description="Fixture-driven v4 HTTP API test server",
        version=_get_version(),
    )
    app.state.fixture_store = fixture_store
    app.state.fixture_resolver = FixtureResolver(fixture_store)
    app.state.task_store = InMemoryTaskStore(fixture_store.tasks)
    app.state.artifact_store = ArtifactStore(fixture_store.artifacts, repo_root=_repo_root())
    app.include_router(router)
    logger.info(
        "Created Test Mode app fixture=%s strict=%s builtin_routes=%d external_routes=%d merged_routes=%d tasks=%d artifacts=%d",
        fixture_path or "<builtin-only>",
        strict,
        len(fixture_store.builtin.routes),
        len(fixture_store.external.routes) if fixture_store.external else 0,
        len(fixture_store.merged.routes),
        len(fixture_store.tasks),
        len(fixture_store.artifacts),
    )
    return app


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
