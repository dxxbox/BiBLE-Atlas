from __future__ import annotations

from bible_cli.utils.config import ClientConfig


def test_client_config_defaults() -> None:
    config = ClientConfig()
    assert config.base_url == "http://127.0.0.1:5555"
    assert config.timeout_seconds == 30
    assert config.trust_env is False


def test_client_config_from_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BIBLE_CLI_BASE_URL", "http://127.0.0.1:7777")
    monkeypatch.setenv("BIBLE_CLI_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("BIBLE_CLI_TRUST_ENV", "true")

    config = ClientConfig.from_env()
    assert config.base_url == "http://127.0.0.1:7777"
    assert config.timeout_seconds == 12
    assert config.trust_env is True
