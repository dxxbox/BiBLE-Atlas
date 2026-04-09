
from pathlib import Path


DEFAULT_CONFIG_DIR = Path.home() / ".bible_atlas"
DEFAULT_CONFIG_PATH_JSON = DEFAULT_CONFIG_DIR / "bible_atlas_config.json"
DEFAULT_CONFIG_PATH_YAML = DEFAULT_CONFIG_DIR / "bible_atlas_config.yaml"
CONFIG_PATH_ENV_VAR = "BIBLE_ATLAS_CONFIG_PATH"