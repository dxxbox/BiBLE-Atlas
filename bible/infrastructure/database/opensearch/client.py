from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from opensearchpy import OpenSearch

from bible.common.errors import ErrorCode
from bible.common.logger import get_logger
from bible.infrastructure.database.types import DatabaseError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class OpenSearchClientProvider:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        self._cfg = cfg
        self._config = cfg.database.opensearch
        self._client: OpenSearch | None = None
        self._lock = threading.RLock()
        self._logger = get_logger(__name__)

    def get_client(self) -> OpenSearch:
        with self._lock:
            if self._client is not None:
                return self._client

            kwargs: dict[str, Any] = {
                "hosts": self._config.hosts,
                "timeout": self._config.timeout_seconds,
                "use_ssl": self._config.use_ssl,
                "verify_certs": self._config.verify_certs,
            }
            if self._config.username and self._config.password:
                kwargs["http_auth"] = (self._config.username, self._config.password)

            client = OpenSearch(**kwargs)
            try:
                ping_ok = bool(client.ping())
            except Exception as exc:
                raise DatabaseError(
                    ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                    "OpenSearch ping failed.",
                    details=self._diagnostic_details(),
                ) from exc

            if not ping_ok:
                raise DatabaseError(
                    ErrorCode.DATABASE_BACKEND_UNAVAILABLE,
                    "OpenSearch ping returned false.",
                    details=self._diagnostic_details(),
                )

            self._logger.info(
                "OpenSearch client initialized",
                extra=self._diagnostic_details(include_hosts=True),
            )
            self._client = client
            return client

    def close(self) -> None:
        with self._lock:
            if self._client is None:
                return
            transport = getattr(self._client, "transport", None)
            close = getattr(transport, "close", None)
            if callable(close):
                close()
            self._client = None

    def _diagnostic_details(self, *, include_hosts: bool = True) -> dict[str, Any]:
        details: dict[str, Any] = {
            "timeout_seconds": self._config.timeout_seconds,
            "use_ssl": self._config.use_ssl,
            "verify_certs": self._config.verify_certs,
        }
        if include_hosts:
            details["hosts"] = self._config.hosts
        return details
