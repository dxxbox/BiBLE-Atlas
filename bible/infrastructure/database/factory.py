from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from .base import IDatabaseWriter
from .types import DatabaseError, DomainType

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class DatabaseFactory:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        self._cfg = cfg
        self._backend_type = cfg.database.backend.lower()
        self._writer_cache: dict[str, IDatabaseWriter] = {}
        self._provider_cache: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get_writer(self, domain: DomainType) -> IDatabaseWriter:
        del domain
        cache_key = self._backend_type
        with self._lock:
            writer = self._writer_cache.get(cache_key)
            if writer is not None:
                return writer

            if self._backend_type == "opensearch":
                from .opensearch.client import OpenSearchClientProvider
                from .opensearch.writer import OpenSearchWriter

                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = OpenSearchClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = OpenSearchWriter(provider.get_client(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            if self._backend_type == "elasticsearch":
                from .elasticsearch.client import ElasticsearchClientProvider
                from .elasticsearch.writer import ElasticsearchWriter

                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = ElasticsearchClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = ElasticsearchWriter(provider.get_client(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            if self._backend_type == "postgres":
                from .postgres.client import PostgresClientProvider
                from .postgres.writer import PostgresWriter

                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = PostgresClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = PostgresWriter(provider.get_pool(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            if self._backend_type == "elasticsearch":
                from .elasticsearch.client import ElasticsearchClientProvider
                from .elasticsearch.writer import ElasticsearchWriter

                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = ElasticsearchClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = ElasticsearchWriter(provider.get_client(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message=f"Unsupported database backend: {self._backend_type!r}. "
                "Supported values: opensearch | elasticsearch | postgres",
            )

    def get_async_task_writer(self) -> IDatabaseWriter:
        return self.get_writer(domain="KNOWLEDGE_BASE")

    def reset(self) -> None:
        with self._lock:
            self._writer_cache.clear()
            for provider in self._provider_cache.values():
                close_fn = getattr(provider, "close", None)
                if callable(close_fn):
                    close_fn()
            self._provider_cache.clear()
