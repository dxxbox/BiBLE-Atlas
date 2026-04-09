import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bible.common.config_loader import load_raw_config_from_file, resolve_config_path
from bible.common.consts import CONFIG_PATH_ENV_VAR


class ConfigLoaderTests(unittest.TestCase):
    def test_resolve_config_path_prefers_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            explicit_path = Path(temp_dir) / "explicit.yaml"
            env_path = Path(temp_dir) / "env.yaml"
            explicit_path.write_text("atlas_timeout: 1\n", encoding="utf-8")
            env_path.write_text("atlas_timeout: 2\n", encoding="utf-8")

            with patch.dict(os.environ, {CONFIG_PATH_ENV_VAR: str(env_path)}, clear=False):
                resolved_path = resolve_config_path(str(explicit_path))

        self.assertEqual(resolved_path, explicit_path.resolve())

    def test_load_raw_config_from_file_supports_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "raw.yaml"
            config_path.write_text("atlas_timeout: 7\natlas_url: https://raw.example.com\n", encoding="utf-8")

            config_data = load_raw_config_from_file(config_path)

        self.assertEqual(config_data["atlas_timeout"], 7)
        self.assertEqual(config_data["atlas_url"], "https://raw.example.com")


if __name__ == "__main__":
    unittest.main()