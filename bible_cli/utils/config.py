"""Configuration utilities placeholder."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(slots=True)
class ClientConfig:
    """Runtime config object used by CLI bootstrap in later phases."""

    base_url: str = "http://127.0.0.1:5555"
    timeout_seconds: int = 30
    trust_env: bool = False

    @classmethod
    def from_env(cls) -> "ClientConfig":
        """Load minimal runtime overrides from environment variables."""
        base_url = (
            os.getenv("BIBLE_CLI_BASE_URL")
            or os.getenv("BIBLE_ATLAS_BASE_URL")
            or "http://127.0.0.1:5555"
        )
        raw_timeout = os.getenv("BIBLE_CLI_TIMEOUT_SECONDS")
        timeout_seconds = int(raw_timeout) if raw_timeout else 30
        trust_env = _parse_bool_env(os.getenv("BIBLE_CLI_TRUST_ENV"), default=False)
        return cls(base_url=base_url, timeout_seconds=timeout_seconds, trust_env=trust_env)

    def as_client_dict(self) -> dict[str, str | int | bool]:
        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "trust_env": self.trust_env,
        }


def _parse_bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
