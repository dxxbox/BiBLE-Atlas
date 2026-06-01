from __future__ import annotations

from bible.config.configure import SearchConfig
from bible.features.search.service_base import InfrastructureSearchService
from bible.infrastructure.database import DatabaseFactory


class KnowledgeBaseSearchService(InfrastructureSearchService):
    def __init__(self, *, database_factory: DatabaseFactory, search_config: SearchConfig) -> None:
        super().__init__(
            domain="KNOWLEDGE_BASE",
            database_factory=database_factory,
            search_config=search_config,
        )
