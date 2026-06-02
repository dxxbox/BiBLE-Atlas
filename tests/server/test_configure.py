import os
from collections.abc import Generator
from pathlib import Path

import pytest

from bible.config.configure import (
    BibleAtlasConfig,
    CeleryConfig,
    RerankConfig,
    RerankModelEntry,
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


# ---------------------------------------------------------------------------
# CeleryConfig defaults and yaml override
# ---------------------------------------------------------------------------

class TestCeleryConfig:
    def test_defaults(self) -> None:
        cfg = CeleryConfig()
        assert cfg.broker_url == "redis://localhost:6379/0"
        assert cfg.result_backend == "redis://localhost:6379/1"
        assert cfg.task_acks_late is True
        assert cfg.worker_prefetch_multiplier == 1

    def test_yaml_celery_section_overrides_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "cfg.yaml"
        config_path.write_text(
            "\n".join([
                "celery:",
                "  broker_url: redis://myhost:6380/2",
                "  result_backend: redis://myhost:6380/3",
            ]),
            encoding="utf-8",
        )
        config = load_bible_atlas_config_from_file(config_path)
        assert config.celery.broker_url == "redis://myhost:6380/2"
        assert config.celery.result_backend == "redis://myhost:6380/3"


# ---------------------------------------------------------------------------
# RerankConfig defaults and YAML override
# ---------------------------------------------------------------------------

class TestRerankConfig:
    def test_defaults(self) -> None:
        cfg = RerankConfig()
        assert cfg.enable is False
        assert cfg.preload_on_startup is False
        assert cfg.default_model == ""
        assert cfg.top_k_multiplier == 3
        assert cfg.hf_cache_dir is None
        assert cfg.available_models == []

    def test_rerank_model_entry_fields(self) -> None:
        entry = RerankModelEntry(id="bge-reranker-base", name="BAAI/bge-reranker-base")
        assert entry.id == "bge-reranker-base"
        assert entry.name == "BAAI/bge-reranker-base"
        assert entry.description == ""
        assert entry.params == ""
        assert entry.languages == []
        assert entry.speed == ""

    def test_bible_atlas_config_has_rerank_field_with_defaults(self) -> None:
        config = BibleAtlasConfig()
        assert hasattr(config, "rerank")
        assert isinstance(config.rerank, RerankConfig)
        assert config.rerank.available_models == []
        assert config.rerank.preload_on_startup is False

    def test_yaml_rerank_section_parsed_correctly(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.yaml"
        config_path.write_text(
            "\n".join([
                "rerank:",
                "  enable: true",
                "  preload_on_startup: true",
                "  default_model: bge-reranker-base",
                "  top_k_multiplier: 6",
                "  hf_cache_dir: /data/hf_cache",
                "  available_models:",
                "    - id: bge-reranker-base",
                "      name: BAAI/bge-reranker-base",
                "      description: 中英文轻量 reranker",
                "      params: 278M",
                "      speed: '~200 对/秒'",
                "    - id: bge-reranker-large",
                "      name: BAAI/bge-reranker-large",
                "      params: 560M",
            ]),
            encoding="utf-8",
        )
        config = load_bible_atlas_config_from_file(config_path)
        assert config.rerank.enable is True
        assert config.rerank.preload_on_startup is True
        assert config.rerank.default_model == "bge-reranker-base"
        assert config.rerank.top_k_multiplier == 6
        assert config.rerank.hf_cache_dir == "/data/hf_cache"
        assert len(config.rerank.available_models) == 2
        assert config.rerank.available_models[0].name == "BAAI/bge-reranker-base"
        assert config.rerank.available_models[0].speed == "~200 对/秒"
        assert config.rerank.available_models[1].id == "bge-reranker-large"

    def test_no_rerank_section_in_yaml_defaults_to_empty(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.yaml"
        config_path.write_text("atlas_url: https://example.com\n", encoding="utf-8")
        config = load_bible_atlas_config_from_file(config_path)
        assert config.rerank.available_models == []
        assert config.rerank.preload_on_startup is False