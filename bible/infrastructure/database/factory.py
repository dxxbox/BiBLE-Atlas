from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from bible.common.errors import ErrorCode
from bible.infrastructure.database.base import IDatabaseWriter
from bible.infrastructure.database.opensearch.client import OpenSearchClientProvider
from bible.infrastructure.database.opensearch.writer import OpenSearchWriter
from bible.infrastructure.database.types import DatabaseError, DomainType

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class DatabaseFactory:
    def __init__(self, config: "BibleAtlasConfig") -> None:
        self._cfg = config
        self._backend_type = config.database.backend.lower()
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
                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = OpenSearchClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = OpenSearchWriter(provider.get_client(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            if self._backend_type in {"postgres", "elasticsearch"}:
                raise DatabaseError(
                    ErrorCode.NOT_IMPLEMENTED,
                    f"Database backend is planned but not implemented yet: {self._backend_type}.",
                    details={"backend": self._backend_type},
                )

            raise DatabaseError(
                ErrorCode.DATABASE_INVALID_ARGUMENT,
                f"Unsupported database backend: {self._backend_type}.",
                details={"backend": self._backend_type},
            )

    def get_async_task_writer(self) -> IDatabaseWriter:
        return self.get_writer(domain="KNOWLEDGE_BASE")

    def reset(self) -> None:
        with self._lock:
            self._writer_cache.clear()
            for provider in self._provider_cache.values():
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
            self._provider_cache.clear()
