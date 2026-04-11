import os
from collections.abc import Generator
from pathlib import Path

import pytest

from bible.config.configure import (
    BibleAtlasConfig,
    get_bible_atlas_config,
    load_bible_atlas_config_from_file,
    _clear_bible_atlas_config_cache,
)
from bible.common.consts import CONFIG_PATH_ENV_VAR


@pytest.fixture(autouse=True)
def clear_config_cache() -> Generator[None, None, None]:
    _clear_bible_atlas_config_cache()
    yield
    _clear_bible_atlas_config_cache()


def test_load_config_from_dict_copies_and_parses_nested_log_section() -> None:
    config_dict = {
        "atlas_url": "https://dict.example.com",
        "storage": {"workspace_dir": "/tmp/bible-atlas-tests"},
        "log": {
            "level": "WARNING",
            "format": "%(levelname)s:%(message)s",
            "output": "stderr",
        },
        "parsers": {
            "markdown": {"enabled": True, "mode": "strict"},
        },
    }

    config = BibleAtlasConfig.load_config_from_dict(config_dict)

    assert config.atlas_url == "https://dict.example.com"
    assert config.storage.workspace_dir == "/tmp/bible-atlas-tests"
    assert config.log.level == "WARNING"
    assert config.log.format == "%(levelname)s:%(message)s"
    assert config.log.output == "stderr"
    assert config_dict["log"]["level"] == "WARNING"
    assert "parsers" in config_dict
    assert not hasattr(config, "parsers")


def test_load_config_from_yaml_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "bible_atlas_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atlas_url: https://example.com",
                "atlas_api_key: ${TEST_ATLAS_API_KEY}",
                "atlas_timeout: 42",
                "storage:",
                "  workspace_dir: /tmp/bible-atlas",
                "log:",
                "  level: DEBUG",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TEST_ATLAS_API_KEY", "secret-key")
    config = load_bible_atlas_config_from_file(config_path)

    assert config.atlas_url == "https://example.com"
    assert config.atlas_api_key == "secret-key"
    assert config.atlas_timeout == 42
    assert config.storage.workspace_dir == "/tmp/bible-atlas"
    assert config.log.level == "DEBUG"


def test_get_instance_loads_yaml_from_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "bible_atlas_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atlas_url: https://env.example.com",
                "atlas_timeout: 30",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(config_path))
    config = get_bible_atlas_config()

    assert config.atlas_url == "https://env.example.com"
    assert config.atlas_timeout == 30