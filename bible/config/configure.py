from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator

from bible.common.consts import CONFIG_PATH_ENV_VAR
from bible.config.config_loader import (
    load_raw_config_from_file,
    resolve_config_path,
)


class LogConfig(BaseModel):
    # TO-DO: add log configuration logic here,
    # below are default in case no configuration found.
    level: str = "INFO"
    format: str = "[%(asctime)s][%(processName)s/%(threadName)s][%(levelname)s] %(filename)s:%(lineno)d: %(message)s"
    output: str = "stdout"
    log_dir: str = ""   #explicit log dir, if not set, will use: <>workspace_dir>/log/
    rotation: bool = False
    rotation_days: int = 7
    rotation_interval: str = "midnight"


class StorageConfig(BaseModel):
    workspace_dir: str = "./workspace/memory"

class FileSystemLocalConfig(BaseModel):
    root_dir: str = "./workspace/memory/files"
    has_algo: str = "sha256"
    chunk_size: int = 1024 * 1024  # 1MB
    use_atomic_rename: bool = True

class FileSystemMinioConfig(BaseModel):
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket_name: str = "bible-atlas"
    prefix: str = ""
    secret: bool = False  # whether the secret key is encrypted and needs to be decrypted before use
    region: str = ""
    hash_algo: str = "sha256"
    chunk_size: int = 1024 * 1024  # 1MB

class FileSystemS3Config(BaseModel):
    bucket_name: str = "bible-atlas"
    prefix: str = ""
    region: str = "us-east-1"
    endpoint_url: Optional[str] = None  # for S3-compatible services
    access_key: str = ""
    secret_key: str = ""
    hash_algo: str = "sha256"
    chunk_size: int = 1024 * 1024  # 1MB

class FileSystemConfig(BaseModel):
    #support backend: | Minio | S3 | Local
    backend: str = "local"  # "local", "minio", "s3"
    local: FileSystemLocalConfig = Field(
        default_factory=lambda: FileSystemLocalConfig(), description="Local filesystem configuration"
    )
    minio: FileSystemMinioConfig = Field(
        default_factory=lambda: FileSystemMinioConfig(), description="Minio filesystem configuration"
    )
    s3: FileSystemS3Config = Field(
        default_factory=lambda: FileSystemS3Config(), description="S3 filesystem configuration"
    )

class ImportMemoryConfig(BaseModel):
    parsers_dir: str = "./workspace/memory/parsers"
    import_work_dir: str = "./workspace/memory/import_work"
    task_timeout_seconds: int = 300  # 5 minutes
    sandbox_timeout_seconds: int = 60  # 1 minute
    workspace_ttl_hours: int = 24  # 24 hours
    sweep_interval_seconds: int = 3600  # 1 hour
    keep_alive_workspace: bool = False  # whether to keep the workspace after import, for debugging purpose

class AsyncTaskConfig(BaseModel):
    task_timeout_seconds: int = 300  # 5 minutes

class UploadConstraintsConfig(BaseModel):
    max_file_size: int = 1024 * 1024 * 10  # 10MB
    max_total_size: int = 1024 * 1024 * 200  # 200MB
    max_file_count: int = 2000
    allowed_extensions: list[str] = Field(default_factory=lambda: [".txt", ".pdf", ".docx", ".xlsx", ".pptx", ".md", ".mdx", ".csv", ".json", ".xml"])

class VectorModelEntry(BaseModel):
    id:             str
    name:           str
    description:    str = ""
    params:         str = ""
    dims:           int = 384
    languages:      list[str] = Field(default_factory=list)

class VectorConfig(BaseModel):
    available_models: list[VectorModelEntry] = Field(default_factory=list) # the available vector models, if empty, will use the default model of the vector search library.
    preload_on_startup: bool = False # whether to preload the vector model on startup, if false, will load the model at the first time it is used.
    hf_cache_dir: str = "" # the cache dir for HuggingFace models used for
    batch_size: int = 32 # the batch size for encoding documents, larger batch size can improve the encoding speed, but also require more memory.

class RerankModelEntry(BaseModel):
    id:             str
    name:           str
    description:    str = ""
    params:         str = ""
    languages:      list[str] = Field(default_factory=list)
    speed:          str = "fast"  # "fast", "medium", "slow"

class RerankConfig(BaseModel):
    enable: bool = False # whether rerank is applied at search time.
    preload_on_startup: bool = False # whether to preload the rerank model on startup, if false, will load the model at the first time it is used.
    default_model: str = "" # the default rerank model to use, if not set, will use the same model as vector search.
    top_k_multiplier: int = 3 # the multiplier for top_k when rerank is enabled, the actual top_k used for search will be top_k * top_k_multiplier, and then rerank will be applied to get the final top_k results.
    hf_cache_dir: str = "" # the cache dir for HuggingFace models used for rerank, if not set, will use the default cache dir of HuggingFace.
    available_models: list[RerankModelEntry] = Field(default_factory=list) # the available rerank models, if empty, will use the same model as vector search.

class SearchConfig(BaseModel):
    default_top_k: int = Field (
        default = 10,
        ge = 1,
        description = "The default number of top results to return for search queries. applied when client omits the field."
    )

    max_top_k: int = Field (
        default = 100,
        ge = 1,
        description = "The maximum number of top results that can be returned for search queries. applied when client requests a top_k larger than this value."
    )

    allowed_search_types: list[str] = Field(
        default_factory = lambda: ["keyword", "title", "text", "vector", "hybrid", "sparse"],
        description = "The allowed search types that clients can use when performing search queries. if empty, all search types are allowed."
    )

    @model_validator(mode="after")
    def max_top_k_covers_default(self) -> "SearchConfig":
        if self.max_top_k < self.default_top_k:
            raise ValueError(f"max_top_k ({self.max_top_k}) must be greater than or equal to default_top_k ({self.default_top_k})")
        return self


class OpenSearchDatabaseConfig(BaseModel):
    hosts: list[str] = Field(default_factory=lambda: ["localhost:9200"])
    timeout_seconds: int = 30
    use_ssl: bool = False
    verify_certs: bool = True
    username: str = ""
    password: str = ""
    binding_index: str = "v4_index_binding"
    async_task_index: str = "v4_async_tasks"
    refresh_policy: str = "false"
    bulk_chunk_size: int = 500
    request_timeout_seconds: int = 60

class ElasticsearchDatabaseConfig(BaseModel):
    hosts: list[str] = Field(default_factory=lambda: ["localhost:9200"])
    timeout_seconds: int = 30
    use_ssl: bool = False
    verify_certs: bool = True
    username: str = ""
    password: str = ""
    binding_index: str = "v4_index_binding"
    async_task_index: str = "v4_async_tasks"
    refresh_policy: str = "false"
    bulk_chunk_size: int = 500
    request_timeout_seconds: int = 60

class PostgresDatabaseConfig(BaseModel):
    dsn: str = ""
    pool_min_size: int = 1
    pool_max_size: int = 10
    pool_timeout_seconds: int = 30
    binding_table: str = "v4_index_binding"
    content_table: str = "v4_content_docs"
    file_registry_table: str = "v4_file_registry"
    async_task_table: str = "v4_async_tasks"
    bulk_chunk_size: int = 500

class DatabaseConfig(BaseModel):
    backend: str = "opensearch"
    opensearch: OpenSearchDatabaseConfig = Field(
        default_factory=lambda: OpenSearchDatabaseConfig(), description="OpenSearch database configuration"
    )
    elasticsearch: ElasticsearchDatabaseConfig = Field(
        default_factory=lambda: ElasticsearchDatabaseConfig(), description="Elasticsearch database configuration"
    )
    postgres: PostgresDatabaseConfig = Field(
        default_factory=lambda: PostgresDatabaseConfig(), description="PostgreSQL database configuration"
    )

class CeleryConfig(BaseModel):
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    task_acks_late: bool = True
    worker_prefetch_multiplier: int = 1
    worker_concurrency: int = 0

class BibleAtlasConfig(BaseModel):
    atlas_url: str = "https://bibleatlas.org"
    atlas_api_key: Optional[str] = None
    atlas_timeout: int = 10

    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(), description="Storage configuration"
    )
    
    log: LogConfig = Field(default_factory=lambda: LogConfig(), description="Logging configuration")

    vector: VectorConfig = Field(default_factory=lambda: VectorConfig(), description="Vector model configuration")
    rerank: RerankConfig = Field(default_factory=lambda: RerankConfig(), description="Rerank model configuration")
    upload: UploadConstraintsConfig = Field(default_factory=lambda: UploadConstraintsConfig(), description="Upload constraints configuration")
    async_task: AsyncTaskConfig = Field(default_factory=lambda: AsyncTaskConfig(), description="Asynchronous task configuration")
    import_memory: ImportMemoryConfig = Field(default_factory=lambda: ImportMemoryConfig(), description="Import memory configuration")
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig(), description="Database configuration")
    filesystem: FileSystemConfig = Field(default_factory=lambda: FileSystemConfig(), description="File system configuration")
    search: SearchConfig = Field(default_factory=lambda: SearchConfig(), description="Search configuration")
    celery: CeleryConfig = Field(default_factory=lambda: CeleryConfig(), description="Celery configuration")
    
    # add other config fields as needed

    @classmethod
    def load_config_from_dict(cls, config_dict: Dict[str, Any]) -> "BibleAtlasConfig":
        """Create a BibleAtlasConfig instance from a raw config dictionary."""
        config_copy = deepcopy(config_dict)

        return cls(**config_copy)  # TO-DO: change this to real function.


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
