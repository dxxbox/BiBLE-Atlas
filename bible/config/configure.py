import logging
import sys
from copy import deepcopy
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from bible.config.config_loader import (
    load_raw_config_from_file,
    resolve_config_path,
)
from bible.common.consts import CONFIG_PATH_ENV_VAR

class LogConfig(BaseModel):
    #TO-DO: add log configuration logic here, 
    # below are default in case no configuration found.
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    output: str = "stdout"
    rotation: bool = False
    rotation_days: int = 7
    rotation_interval: str = "midnight"

class StorageConfig(BaseModel):
    workspace_dir: str = "./workspace"

class BibleAtlasConfig(BaseModel):
    atlas_url: str = "https://bibleatlas.org"
    atlas_api_key: Optional[str] = None
    atlas_timeout: int = 10

    storage: StorageConfig = Field(default_factory=lambda: StorageConfig(), description="Storage configuration")
    log: LogConfig = Field(default_factory=lambda: LogConfig(), description="Logging configuration")

    # add other config fields as needed

    @classmethod
    def load_config_from_dict(cls, config_dict: Dict[str, Any]) -> "BibleAtlasConfig":
        """Create a BibleAtlasConfig instance from a raw config dictionary."""
        config_copy = deepcopy(config_dict)

        return cls(**config_copy) # TO-DO: change this to real function.

_config_instance: Optional[BibleAtlasConfig] = None

def load_bible_atlas_config_from_file(file_path: Path | str) -> "BibleAtlasConfig":
    """Load a BibleAtlasConfig object from a JSON or YAML file."""
    try:
        config_data = load_raw_config_from_file(file_path)
        return BibleAtlasConfig.load_config_from_dict(config_data)
    except Exception as e:
        raise RuntimeError(f"Failed to load configuration from file: {e}")


def _clear_bible_atlas_config_cache() -> None:
    global _config_instance
    _config_instance = None

def get_bible_atlas_config() -> BibleAtlasConfig:
    global _config_instance

    if _config_instance is None:
        config_path = resolve_config_path()
        if config_path is None:
            raise RuntimeError(
                "Failed to resolve configuration path from default locations or "
                f"environment variable {CONFIG_PATH_ENV_VAR}"
            )
        _config_instance = load_bible_atlas_config_from_file(config_path)

    return _config_instance
