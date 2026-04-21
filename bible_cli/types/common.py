"""Common typed models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CLIResponse:
    """Basic structured response container for future command output."""

    status: str
    result: Any | None = None
    error: dict[str, Any] | None = None
