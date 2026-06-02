from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .base import IFileSystemGateway
from .local import LocalFileSystemGateway
from .types import FileSystemError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class FileSystemFactory:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        self._cfg = cfg
        self._backend = cfg.file_system.backend.lower()
        self._gateway_cache: dict[str, IFileSystemGateway] = {}
        self._lock = threading.RLock()

    def get_gateway(self) -> IFileSystemGateway:
        cache_key = self._backend
        with self._lock:
            gateway = self._gateway_cache.get(cache_key)
            if gateway is not None:
                return gateway

            if self._backend == "local":
                gateway = self._build_local()
            elif self._backend == "minio":
                gateway = self._build_minio()
            elif self._backend == "s3":
                gateway = self._build_s3()
            else:
                raise FileSystemError(
                    code="FILE_SYSTEM_BACKEND_UNSUPPORTED",
                    message=f"Unknown file system backend: {self._backend!r}. "
                    "Supported values: local | minio | s3",
                )

            self._gateway_cache[cache_key] = gateway
            return gateway

    def reset(self) -> None:
        with self._lock:
            self._gateway_cache.clear()

    # ------------------------------------------------------------------
    # Backend builders
    # ------------------------------------------------------------------

    def _build_local(self) -> LocalFileSystemGateway:
        fs_cfg = self._cfg.file_system.local
        return LocalFileSystemGateway(
            root_dir=fs_cfg.root_dir,
            hash_algo=fs_cfg.hash_algo,
            chunk_size=fs_cfg.chunk_size,
            use_atomic_rename=fs_cfg.use_atomic_rename,
        )

    def _build_minio(self) -> "MinioFileSystemGateway":  # noqa: F821
        try:
            from minio import Minio  # type: ignore[import]
        except ImportError as exc:
            raise FileSystemError(
                code="FILE_SYSTEM_BACKEND_UNSUPPORTED",
                message="MinIO backend requires the 'minio' package. "
                "Install it with: pip install 'bible-atlas[minio]'",
            ) from exc

        from .minio import MinioFileSystemGateway

        minio_cfg = self._cfg.file_system.minio
        client = Minio(
            minio_cfg.endpoint,
            access_key=minio_cfg.access_key or None,
            secret_key=minio_cfg.secret_key or None,
            secure=minio_cfg.secure,
            region=minio_cfg.region or None,
        )
        return MinioFileSystemGateway(
            client=client,
            bucket=minio_cfg.bucket,
            prefix=minio_cfg.prefix,
            hash_algo=minio_cfg.hash_algo,
            chunk_size=minio_cfg.chunk_size,
        )

    def _build_s3(self) -> "S3FileSystemGateway":  # noqa: F821
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise FileSystemError(
                code="FILE_SYSTEM_BACKEND_UNSUPPORTED",
                message="S3 backend requires the 'boto3' package. "
                "Install it with: pip install 'bible-atlas[s3]'",
            ) from exc

        from .s3 import S3FileSystemGateway

        s3_cfg = self._cfg.file_system.s3
        kwargs: dict = {"region_name": s3_cfg.region or None}
        if s3_cfg.endpoint_url:
            kwargs["endpoint_url"] = s3_cfg.endpoint_url
        if s3_cfg.access_key and s3_cfg.secret_key:
            kwargs["aws_access_key_id"] = s3_cfg.access_key
            kwargs["aws_secret_access_key"] = s3_cfg.secret_key

        client = boto3.client("s3", **kwargs)
        return S3FileSystemGateway(
            client=client,
            bucket=s3_cfg.bucket,
            prefix=s3_cfg.prefix,
            hash_algo=s3_cfg.hash_algo,
            chunk_size=s3_cfg.chunk_size,
        )
