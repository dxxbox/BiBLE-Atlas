from pathlib import Path

import pytest

from bible.common.config_loader import load_raw_config_from_file, resolve_config_path
from bible.common.consts import CONFIG_PATH_ENV_VAR



def test_resolve_config_path_prefers_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit_path = tmp_path / "explicit.yaml"
    env_path = tmp_path / "env.yaml"
    explicit_path.write_text("atlas_timeout: 1\n", encoding="utf-8")
    env_path.write_text("atlas_timeout: 2\n", encoding="utf-8")

    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(env_path))
    resolved_path = resolve_config_path(str(explicit_path))

    assert resolved_path == explicit_path.resolve()


def test_load_raw_config_from_file_supports_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "raw.yaml"
    config_path.write_text("atlas_timeout: 7\natlas_url: https://raw.example.com\n", encoding="utf-8")

    config_data = load_raw_config_from_file(config_path)

    assert config_data["atlas_timeout"] == 7
    assert config_data["atlas_url"] == "https://raw.example.com"