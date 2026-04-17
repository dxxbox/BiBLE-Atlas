"""Async/sync bridge helper placeholder."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run async coroutine in a sync context."""
    return asyncio.run(coro)
