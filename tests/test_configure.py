import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bible.common.configure import (
    BibleAtlasConfig,
    get_bible_atlas_config,
    load_bible_atlas_config_from_file,
    _clear_bible_atlas_config_cache,
)
from bible.common.consts import CONFIG_PATH_ENV_VAR


class ConfigureTests(unittest.TestCase):
    def tearDown(self) -> None:
        _clear_bible_atlas_config_cache()

    def test_load_config_from_dict_copies_and_parses_nested_log_section(self) -> None:
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

        self.assertEqual(config.atlas_url, "https://dict.example.com")
        self.assertEqual(config.storage.workspace_dir, "/tmp/bible-atlas-tests")
        self.assertEqual(config.log.level, "WARNING")
        self.assertEqual(config.log.format, "%(levelname)s:%(message)s")
        self.assertEqual(config.log.output, "stderr")
        self.assertEqual(config_dict["log"]["level"], "WARNING")
        self.assertIn("parsers", config_dict)
        self.assertFalse(hasattr(config, "parsers"))

    def test_load_config_from_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "bible_atlas_config.yaml"
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

            with patch.dict(os.environ, {"TEST_ATLAS_API_KEY": "secret-key"}, clear=False):
                config = load_bible_atlas_config_from_file(config_path)

        self.assertEqual(config.atlas_url, "https://example.com")
        self.assertEqual(config.atlas_api_key, "secret-key")
        self.assertEqual(config.atlas_timeout, 42)
        self.assertEqual(config.storage.workspace_dir, "/tmp/bible-atlas")
        self.assertEqual(config.log.level, "DEBUG")

    def test_get_instance_loads_yaml_from_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "bible_atlas_config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "atlas_url: https://env.example.com",
                        "atlas_timeout: 30",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {CONFIG_PATH_ENV_VAR: str(config_path)}, clear=False):
                config = get_bible_atlas_config()

        self.assertEqual(config.atlas_url, "https://env.example.com")
        self.assertEqual(config.atlas_timeout, 30)


if __name__ == "__main__":
    unittest.main()