"""Configuration utilities placeholder."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ClientConfig:
    """Runtime config object used by CLI bootstrap in later phases."""

    base_url: str = "http://127.0.0.1:8000"
    timeout_seconds: int = 30
