from __future__ import annotations

from functools import lru_cache

from bible.config.configure import BibleAtlasConfig, SearchConfig, get_bible_atlas_config
from bible.infrastructure.database import DatabaseFactory
from bible.infrastructure.file_system import FileSystemFactory


def get_config() -> BibleAtlasConfig:
    return get_bible_atlas_config()


def get_search_cfg(config: BibleAtlasConfig | None = None) -> SearchConfig:
    return (config or get_config()).search


@lru_cache(maxsize=1)
def _get_database_factory_cached() -> DatabaseFactory:
    return DatabaseFactory(get_config())


@lru_cache(maxsize=1)
def _get_file_system_factory_cached() -> FileSystemFactory:
    return FileSystemFactory(get_config())


def get_database_factory() -> DatabaseFactory:
    return _get_database_factory_cached()


def get_file_system_factory() -> FileSystemFactory:
    return _get_file_system_factory_cached()


def get_file_system_gateway():
    return get_file_system_factory().get_gateway()


def get_kb_search_service():
    from bible.features.search.knowledge_base_search.knowledge_base_search_service import (
        KnowledgeBaseSearchService,
    )

    return KnowledgeBaseSearchService(database_factory=get_database_factory(), search_config=get_search_cfg())


def get_memory_search_service():
    from bible.features.search.memory_search.memory_search_service import MemorySearchService

    return MemorySearchService(database_factory=get_database_factory(), search_config=get_search_cfg())


def reset_infrastructure_dependencies() -> None:
    if _get_database_factory_cached.cache_info().currsize:
        _get_database_factory_cached().reset()
    if _get_file_system_factory_cached.cache_info().currsize:
        _get_file_system_factory_cached().reset()
    _get_database_factory_cached.cache_clear()
    _get_file_system_factory_cached.cache_clear()
