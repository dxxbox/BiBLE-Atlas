import json
import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path
from pydantic import BaseModel, Field

class LogConfig(BaseModel):
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

    @classmethod
    def load_config_from_dict(cls, config_dict: Dict[str, Any]) -> "BibleAtlasConfig":
        """Create a BibleAtlasConfig instance from a dictionary."""
        return cls(**config_dict)

class BibleAtlasConfigSingleton:
    _instance: Optional[BibleAtlasConfig] = None

    _default_config_path = "./config/bible_atlas_config.json"  # Default path to the configuration file

    @classmethod
    def get_instance(cls) -> BibleAtlasConfig:
        if cls._instance is None:
            cls._instance = cls._load_config_from_file(cls._default_config_path)
        return cls._instance
    
    @classmethod
    def _load_config_from_file(cls, file_path: str) -> BibleAtlasConfig:
        """Load configuration from a JSON or YAML file."""
        try:
            config_path = Path(file_path)
            if not config_path.exists():
                raise FileNotFoundError(f"Configuration file not found: {file_path}")
            
            with open(config_path, 'r', encoding="utf-8") as f:
                raw = f.read()
            
            raw = os.path.expandvars(raw)  # Expand environment variables
            config_data = yaml.safe_load(raw) if file_path.endswith(('.yaml', '.yml')) else json.loads(raw)
            return BibleAtlasConfig.load_config_from_dict(config_data)

        except Exception as e:
            raise RuntimeError(f"Failed to load configuration from file: {e}")


def get_bible_atlas_config() -> BibleAtlasConfig:
    # In a real implementation, you might load this from a file or environment variables
    return BibleAtlasConfigSingleton.get_instance()