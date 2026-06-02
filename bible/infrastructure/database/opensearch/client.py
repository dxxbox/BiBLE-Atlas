from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from ..types import DatabaseError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from opensearchpy import OpenSearch


class OpenSearchClientProvider:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        os_cfg = cfg.database.opensearch
        self._hosts = os_cfg.hosts
        self._timeout_seconds = os_cfg.timeout_seconds
        self._use_ssl = os_cfg.use_ssl
        self._verify_certs = os_cfg.verify_certs
        self._username = os_cfg.username or None
        self._password = os_cfg.password or None
        self._client: "OpenSearch | None" = None
        self._lock = threading.RLock()

    def get_client(self) -> "OpenSearch":
        with self._lock:
            if self._client is not None:
                return self._client

            try:
                from opensearchpy import OpenSearch
            except ImportError as exc:
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="opensearch-py is not installed. "
                    "Install it with: pip install 'opensearch-py'",
                ) from exc

            kwargs: dict[str, Any] = {
                "hosts": self._hosts,
                "timeout": self._timeout_seconds,
                "use_ssl": self._use_ssl,
                "verify_certs": self._verify_certs,
            }
            if self._username and self._password:
                kwargs["http_auth"] = (self._username, self._password)

            client = OpenSearch(**kwargs)
            if not client.ping():
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="OpenSearch ping failed.",
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
