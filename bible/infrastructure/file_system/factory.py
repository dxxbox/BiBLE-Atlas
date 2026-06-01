from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from bible.common.errors import ErrorCode
from bible.infrastructure.file_system.base import IFileSystemGateway
from bible.infrastructure.file_system.local import LocalFileSystemGateway
from bible.infrastructure.file_system.types import FileSystemError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig


class FileSystemFactory:
    def __init__(self, config: "BibleAtlasConfig") -> None:
        self._cfg = config
        self._backend = config.filesystem.backend.lower()
        self._gateway_cache: dict[str, IFileSystemGateway] = {}
        self._lock = threading.RLock()

    def get_gateway(self) -> IFileSystemGateway:
        cache_key = self._backend
        with self._lock:
            gateway = self._gateway_cache.get(cache_key)
            if gateway is not None:
                return gateway

            if self._backend == "local":
                local_config = self._cfg.filesystem.local
                gateway = LocalFileSystemGateway(
                    root_dir=local_config.root_dir,
                    hash_algo=local_config.hash_algo,
                    chunk_size=local_config.chunk_size,
                    use_atomic_rename=local_config.use_atomic_rename,
                )
            elif self._backend in {"minio", "s3"}:
                raise FileSystemError(
                    ErrorCode.NOT_IMPLEMENTED,
                    f"File system backend is planned but not implemented yet: {self._backend}.",
                    details={"backend": self._backend},
                )
            else:
                raise FileSystemError(
                    ErrorCode.FILE_SYSTEM_BACKEND_UNSUPPORTED,
                    f"Unsupported file system backend: {self._backend}.",
                    details={"backend": self._backend},
                )

            self._gateway_cache[cache_key] = gateway
            return gateway

    def reset(self) -> None:
        with self._lock:
            self._gateway_cache.clear()
