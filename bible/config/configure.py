from __future__ import annotations

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
    format: str = "[%(asctime)s] [%(processName)s/%(threadName)s] %(levelname)s %(filename)s:%(lineno)d: %(message)s"
    output: str = "stdout"
    log_dir: str = ""  # explicit log directory; when empty, defaults to <workspace_dir>/log/
    rotation: bool = False
    rotation_days: int = 7
    rotation_interval: str = "midnight"


class StorageConfig(BaseModel):
    workspace_dir: str = "./workspace/memory"


class FileSystemLocalConfig(BaseModel):
    root_dir: str = "./workspace/memory/files"
    hash_algo: str = "sha256"
    chunk_size: int = 1024 * 1024
    use_atomic_rename: bool = True


class FileSystemMinioConfig(BaseModel):
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "bible-atlas"
    prefix: str = ""
    secure: bool = False
    region: str = ""
    hash_algo: str = "sha256"
    chunk_size: int = 1024 * 1024


class FileSystemS3Config(BaseModel):
    bucket: str = "bible-atlas"
    prefix: str = ""
    region: str = "us-east-1"
    endpoint_url: str = ""        # empty → real AWS; non-empty → custom S3-compatible endpoint
    access_key: str = ""          # empty → use IAM role / environment variables
    secret_key: str = ""
    hash_algo: str = "sha256"
    chunk_size: int = 1024 * 1024


class FileSystemConfig(BaseModel):
    # Supported backends: local | minio | s3
    backend: str = "local"
    local: FileSystemLocalConfig = Field(default_factory=FileSystemLocalConfig)
    minio: FileSystemMinioConfig = Field(default_factory=FileSystemMinioConfig)
    s3: FileSystemS3Config = Field(default_factory=FileSystemS3Config)


class ImportMemoryConfig(BaseModel):
    parsers_dir: str = "./workspace/memory/parsers"
    import_work_dir: str = "./workspace/memory/import_work"
    task_timeout_seconds: int = 300
    sandbox_timeout_seconds: int = 60
    workspace_ttl_hours: int = 24
    sweep_interval_seconds: int = 3600
    keep_failed_workspace: bool = False


class AsyncTaskConfig(BaseModel):
    task_timeout_seconds: int = 300


class UploadConstraintsConfig(BaseModel):
    max_file_size: int = 10 * 1024 * 1024   # 10 MB per file
    max_total_size: int = 200 * 1024 * 1024  # 200 MB total
    max_file_count: int = 2000
    allowed_extensions: list[str] = Field(default_factory=lambda: [".md", ".json"])


class VectorModelEntry(BaseModel):
    """One embedding model: ``id`` is the short handle; ``name`` is the HF / ST model id."""

    id: str
    name: str
    description: str = ""
    params: str = ""
    dims: int = 384
    languages: list[str] = Field(default_factory=list)


class VectorConfig(BaseModel):
    available_models: list[VectorModelEntry] = Field(default_factory=list)
    preload_on_startup: bool = False
    hf_cache_dir: str | None = None
    batch_size: int = 32


class RerankModelEntry(BaseModel):
    """One rerank model: ``id`` is the short handle; ``name`` is the HF model id."""

    id: str
    name: str
    description: str = ""
    params: str = ""
    languages: list[str] = Field(default_factory=list)
    speed: str = ""


class RerankConfig(BaseModel):
    enable: bool = False
    """Whether rerank is applied at search time."""

    preload_on_startup: bool = False
    """Whether to preload rerank models into memory at server/worker startup."""

    default_model: str = ""
    """Short model id (matches ``RerankModelEntry.id``) used when the caller does not specify one."""

    top_k_multiplier: int = 3
    """Initial retrieval = requested top_k × top_k_multiplier; top results are then reranked."""

    hf_cache_dir: str | None = None
    available_models: list[RerankModelEntry] = Field(default_factory=list)


class SearchConfig(BaseModel):
    """Search API defaults and limits.

    Aligned with the v3 ``dynamic_config.yaml`` ``search`` section and the
    v4 API spec (``02_API接口文档.md``).  The API layer reads these values to
    apply defaults and to validate/reject requests before calling the service.
    """

    default_top_k: int = Field(
        default=10,
        ge=1,
        description="Default top_k applied when the client omits the field.",
    )
    max_top_k: int = Field(
        default=100,
        ge=1,
        description="Inclusive upper bound for top_k; requests above this are rejected (400).",
    )
    allowed_search_types: list[str] = Field(
        default_factory=lambda: ["keyword", "title", "text", "vector", "hybrid"],
        description="search_type values accepted by the search API layer.",
    )

    @model_validator(mode="after")
    def max_top_k_covers_default(self) -> "SearchConfig":
        if self.max_top_k < self.default_top_k:
            raise ValueError(
                f"max_top_k ({self.max_top_k}) must be >= default_top_k ({self.default_top_k})"
            )
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
    opensearch: OpenSearchDatabaseConfig = Field(default_factory=OpenSearchDatabaseConfig)
    elasticsearch: ElasticsearchDatabaseConfig = Field(default_factory=ElasticsearchDatabaseConfig)
    postgres: PostgresDatabaseConfig = Field(default_factory=PostgresDatabaseConfig)


class CeleryConfig(BaseModel):
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    task_acks_late: bool = True
    worker_prefetch_multiplier: int = 1
    worker_concurrency: int = 0  # 0 = use CPU count (Celery default)


class BibleAtlasConfig(BaseModel):
    atlas_url: str = "https://bibleatlas.org"
    atlas_api_key: Optional[str] = None
    atlas_timeout: int = 10

    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(), description="Storage configuration"
    )
    log: LogConfig = Field(default_factory=lambda: LogConfig(), description="Logging configuration")
    vector: VectorConfig = Field(
        default_factory=lambda: VectorConfig(), description="Vector embedding models"
    )
    rerank: RerankConfig = Field(
        default_factory=lambda: RerankConfig(), description="Rerank (cross-encoder) models"
    )
    upload: UploadConstraintsConfig = Field(
        default_factory=lambda: UploadConstraintsConfig(), description="File upload constraints"
    )
    import_memory: ImportMemoryConfig = Field(
        default_factory=lambda: ImportMemoryConfig(), description="Memory import settings"
    )
    file_system: FileSystemConfig = Field(
        default_factory=FileSystemConfig, description="File system backend configuration"
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="Database backend configuration"
    )
    celery: CeleryConfig = Field(
        default_factory=CeleryConfig, description="Celery async task queue"
    )
    async_task: AsyncTaskConfig = Field(
        default_factory=AsyncTaskConfig, description="Global async task settings"
    )
    search: SearchConfig = Field(
        default_factory=SearchConfig,
        description=(
            "Search API defaults and limits used by the v4 KNOWLEDGE_BASE / skill / memory "
            "search endpoints (default_top_k, max_top_k, allowed_search_types)."
        )
    )

    # add other config fields as needed

    @classmethod
    def load_config_from_dict(cls, config_dict: Dict[str, Any]) -> "BibleAtlasConfig":
        """Create a BibleAtlasConfig instance from a raw config dictionary."""
        config_copy = deepcopy(config_dict)

        return cls(**config_copy)  # TO-DO: change this to real function.


def load_bible_atlas_config_from_file(file_path: Path | str) -> "BibleAtlasConfig":
    """Load a BibleAtlasConfig object from a JSON or YAML file."""
    try:
        config_data = load_raw_config_from_file(file_path)
        # [X-Comment]: 不要使用自定义结构体的形式，参照 x_config/yaml_config_manager.py 里的各种 get 方法
        return BibleAtlasConfig.load_config_from_dict(config_data)
    except Exception as e:
        raise RuntimeError(f"Failed to load configuration from file: {e}")


_config_instance: "BibleAtlasConfig | None" = None


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
