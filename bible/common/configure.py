from typing import Any, Dict, Optional
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

class BibleAtlasConfigSingleton:
    _instance: Optional[BibleAtlasConfig] = None

    @classmethod
    def get_instance(cls) -> BibleAtlasConfig:
        if cls._instance is None:
            cls._instance = get_bible_atlas_config()
        return cls._instance

def get_bible_atlas_config() -> BibleAtlasConfig:
    # In a real implementation, you might load this from a file or environment variables
    return BibleAtlasConfigSingleton.get_instance()