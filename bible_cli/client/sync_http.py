"""Sync HTTP client wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bible_cli.client.async_http import AsyncHTTPClient
from bible_cli.client.base import BaseClient
from bible_cli.utils.async_bridge import run_async


class SyncHTTPClient(BaseClient):
    """Sync adapter around AsyncHTTPClient."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config=config)

    def close(self) -> None:
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

    # ------------------------------------------------------------------
    # Memory v4
    # ------------------------------------------------------------------

    def memory_import(
        self,
        meta_path: Path,
        kb_index: str,
        *,
        message_path: Path | None = None,
        vector_model: str | None = None,
    ) -> dict[str, Any]:
        return run_async(
            self._run_memory_import(
                meta_path=meta_path,
                kb_index=kb_index,
                message_path=message_path,
                vector_model=vector_model,
            )
        )

    def memory_task_status(self, task_id: str) -> dict[str, Any]:
        return run_async(self._run_memory_task_status(task_id))

    def memory_search(
        self,
        kb_index: str,
        query: str,
        *,
        search_type: str = "hybrid",
        top_k: int = 10,
        tag: str | None = None,
    ) -> dict[str, Any]:
        return run_async(
            self._run_memory_search(
                kb_index=kb_index,
                query=query,
                search_type=search_type,
                top_k=top_k,
                tag=tag,
            )
        )

    # ------------------------------------------------------------------
    # Internal async runners
    # ------------------------------------------------------------------

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

    async def _run_memory_import(
        self,
        meta_path: Path,
        kb_index: str,
        *,
        message_path: Path | None,
        vector_model: str | None,
    ) -> dict[str, Any]:
        client = AsyncHTTPClient(config=self.config)
        try:
            return await client.memory_import(
                meta_path=meta_path,
                kb_index=kb_index,
                message_path=message_path,
                vector_model=vector_model,
            )
        finally:
            await client.aclose()

    async def _run_memory_task_status(self, task_id: str) -> dict[str, Any]:
        client = AsyncHTTPClient(config=self.config)
        try:
            return await client.memory_task_status(task_id)
        finally:
            await client.aclose()

    async def _run_memory_search(
        self,
        kb_index: str,
        query: str,
        *,
        search_type: str,
        top_k: int,
        tag: str | None,
    ) -> dict[str, Any]:
        client = AsyncHTTPClient(config=self.config)
        try:
            return await client.memory_search(
                kb_index=kb_index,
                query=query,
                search_type=search_type,
                top_k=top_k,
                tag=tag,
            )
        finally:
            await client.aclose()
