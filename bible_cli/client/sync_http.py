"""Sync HTTP client wrapper placeholder for Phase-1."""

from __future__ import annotations

from typing import Any

from bible_cli.client.async_http import AsyncHTTPClient
from bible_cli.client.base import BaseClient


class SyncHTTPClient(BaseClient):
    """Planned sync adapter around AsyncHTTPClient."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._async_client = AsyncHTTPClient(config=config)
        super().__init__(config=config)

    def close(self) -> None:
        self._async_client.close()
