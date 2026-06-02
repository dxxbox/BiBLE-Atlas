from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ..types import DatabaseError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from elasticsearch import Elasticsearch


class ElasticsearchClientProvider:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        es_cfg = cfg.database.elasticsearch
        self._hosts = es_cfg.hosts
        self._timeout_seconds = es_cfg.timeout_seconds
        self._use_ssl = es_cfg.use_ssl
        self._verify_certs = es_cfg.verify_certs
        self._username = es_cfg.username or None
        self._password = es_cfg.password or None
        self._client: "Elasticsearch | None" = None
        self._lock = threading.RLock()

    def get_client(self) -> "Elasticsearch":
        with self._lock:
            if self._client is not None:
                return self._client

            try:
                from elasticsearch import Elasticsearch
            except ImportError as exc:
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="elasticsearch is not installed. "
                    "Install it with: pip install 'elasticsearch'",
                ) from exc

            kwargs: dict[str, Any] = {
                "hosts": self._hosts,
                "request_timeout": self._timeout_seconds,
                "verify_certs": self._verify_certs,
            }
            if self._use_ssl:
                kwargs["use_ssl"] = True
            if self._username and self._password:
                kwargs["basic_auth"] = (self._username, self._password)

            client = Elasticsearch(**kwargs)
            if not client.ping():
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="Elasticsearch ping failed.",
                    details={
                        "hosts": self._hosts,
                        "timeout_seconds": self._timeout_seconds,
                        "use_ssl": self._use_ssl,
                    },
                )

            self._client = client
            return client

    def close(self) -> None:
        with self._lock:
            if self._client is None:
                return
            transport = getattr(self._client, "transport", None)
            if transport is not None and hasattr(transport, "close"):
                transport.close()
            self._client = None
