"""Async HTTP client placeholder for Phase-1."""

from __future__ import annotations

from bible_cli.client.base import BaseClient
from bible_cli.exceptions import CommandNotImplementedError


class AsyncHTTPClient(BaseClient):
    """Planned async HTTP client implementation."""

    def close(self) -> None:
        return None

    async def health(self) -> dict[str, str]:
        """Placeholder API to signal unimplemented state."""
        raise CommandNotImplementedError("system health")
