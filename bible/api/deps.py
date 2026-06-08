"""Centralised FastAPI dependency providers for the bible API layer.

All ``Depends(...)`` callables live here so that:
  - Multiple API modules (knowledge-base / memory search) can share
    the same provider functions without duplication.
  - Unit tests can override any provider via ``app.dependency_overrides``
    without patching module-level globals.

Lifecycle note
--------------
Each provider is a plain function (not a generator / context-manager), so
FastAPI calls it once per request.  The config singleton returned by
``get_bible_atlas_config()`` is cached at the application level, making
repeated calls cheap.
"""

from __future__ import annotations

from bible.config.configure import SearchConfig, get_bible_atlas_config


def get_config():
    """Return the application-wide BibleAtlasConfig."""
    return get_bible_atlas_config()


def get_async_task_service():
    """Return the shared async task service."""
    from bible.features import get_task_service

    return get_task_service()


def get_search_cfg() -> SearchConfig:
    """Return the ``search`` section of the application config.

    Falls back to default SearchConfig values when no config file is present
    (e.g. in unit-test environments that only test the API layer).
    """
    try:
        return get_bible_atlas_config().search
    except Exception:
        return SearchConfig()


def get_database_factory():
    """Return a DatabaseFactory wired to the current config."""
    from bible.infrastructure.database.factory import DatabaseFactory

    cfg = get_bible_atlas_config()
    return DatabaseFactory(cfg)


def get_vector_tool():
    """Return a VectorTool wired to the current config paths."""
    from bible.infrastructure.vector.vector_tool import VectorTool

    cfg = get_bible_atlas_config()
    return VectorTool(
        workspace_dir=cfg.workspace.root,
        hf_cache_dir=cfg.vector.hf_cache_dir,
    )


def get_skill_search_service():
    """Build and return a SkillSearchService for the current request."""
    from bible.features.search.skill_search.skill_search_service import SkillSearchService
    from bible.infrastructure.database.factory import DatabaseFactory
    from bible.infrastructure.vector.vector_tool import VectorTool

    cfg = get_bible_atlas_config()
    db_factory = DatabaseFactory(cfg)
    vector_tool = VectorTool(
        workspace_dir=cfg.workspace.root,
        hf_cache_dir=cfg.vector.hf_cache_dir,
    )
    return SkillSearchService(
        db_factory=db_factory,
        vector_tool=vector_tool,
        search_cfg=cfg.search,
    )


def get_memory_search_service():
    """Build and return a MemorySearchService for the current request."""
    from bible.features.search.memory_search.memory_search_service import MemorySearchService
    from bible.infrastructure.database.factory import DatabaseFactory
    from bible.infrastructure.vector.vector_tool import VectorTool

    cfg = get_bible_atlas_config()
    db_factory = DatabaseFactory(cfg)
    vector_tool = VectorTool(
        workspace_dir=cfg.workspace.root,
        hf_cache_dir=cfg.vector.hf_cache_dir,
    )
    return MemorySearchService(
        db_factory=db_factory,
        vector_tool=vector_tool,
        search_cfg=cfg.search,
    )


def get_kb_search_service():
    """Build and return a KnowledgeBaseSearchService for the current request.

    Constructs DatabaseFactory and VectorTool from live config so that
    the service is fully wired to real infrastructure in production, but
    can be replaced wholesale via ``app.dependency_overrides`` in tests.
    """
    from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
        KnowledgeBaseSearchService,
    )
    from bible.infrastructure.database.factory import DatabaseFactory
    from bible.infrastructure.vector.vector_tool import VectorTool

    cfg = get_bible_atlas_config()
    db_factory = DatabaseFactory(cfg)
    vector_tool = VectorTool(
        workspace_dir=cfg.workspace.root,
        hf_cache_dir=cfg.vector.hf_cache_dir,
    )
    return KnowledgeBaseSearchService(
        db_factory=db_factory,
        vector_tool=vector_tool,
        search_cfg=cfg.search,
    )
