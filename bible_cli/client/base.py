"""Base client contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseClient(ABC):
    """Base contract for future local/http client implementations."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._initialize()

    def _initialize(self) -> None:
        """Optional initialization hook."""

    @abstractmethod
    def close(self) -> None:
        """Close client and release resources."""
