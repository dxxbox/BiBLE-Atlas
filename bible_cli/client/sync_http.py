"""Sync HTTP client wrapper placeholder for Phase-1."""

from __future__ import annotations

from typing import Any

from bible_cli.client.async_http import AsyncHTTPClient
from bible_cli.client.base import BaseClient
from bible_cli.utils.async_bridge import run_async


class SyncHTTPClient(BaseClient):
    """Sync adapter around AsyncHTTPClient."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config=config)

    def close(self) -> None:
        # Sync wrapper uses per-call async clients, so no persistent resources here.
        return None

    def health(self) -> dict[str, Any]:
        return run_async(self._run_with_async_client("health"))

    def status(self) -> dict[str, Any]:
        return run_async(self._run_with_async_client("status"))

    def info(self) -> dict[str, Any]:
        return run_async(self._run_with_async_client("info"))

    def knowledge_list(self) -> dict[str, Any]:
        return run_async(self._run_with_async_client("knowledge_list"))

    def knowledge_search(self, query: str | None = None) -> dict[str, Any]:
        return run_async(self._run_with_async_client("knowledge_search", query=query))

    async def _run_with_async_client(self, action: str, *, query: str | None = None) -> dict[str, Any]:
        client = AsyncHTTPClient(config=self.config)
        try:
            if action == "health":
                return await client.health()
            if action == "status":
                return await client.status()
            if action == "info":
                return await client.info()
            if action == "knowledge_list":
                return await client.knowledge_list()
            if action == "knowledge_search":
                return await client.knowledge_search(query=query)
            raise ValueError(f"Unsupported action: {action}")
        finally:
            await client.aclose()
