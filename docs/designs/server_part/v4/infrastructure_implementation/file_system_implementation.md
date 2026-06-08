# file_system/ 详细实现指南（v4）

本文档描述 `app/infrastructure/file_system/` 的开发细节：类初始化、成员、接口参数/返回值与内部实现逻辑。  
该模块主要服务 `SKILL/MEMORY` 导入中的原始文件落盘与读取。

---

## 1. 目录建议

```text
app/infrastructure/file_system/
├── base.py
├── factory.py
├── types.py                    # 可选：FileStoreResult 定义
├── local.py
├── minio.py                    # 可选扩展
└── s3.py                       # 可选扩展
```

---

## 2. 通用类型定义（建议）

```python
from dataclasses import dataclass
from typing import BinaryIO

@dataclass
class FileStoreResult:
    storage_path: str
    file_hash: str
    size_bytes: int
    filename: str
    domain: str
    kb_index: str
```

---

## 3. `FileSystemFactory` 详细实现

文件：`app/infrastructure/file_system/factory.py`

### 3.1 初始化

```python
class FileSystemFactory:
    def __init__(self, cfg: "ConfigManager") -> None:
        self._cfg = cfg
        self._backend = cfg.get_str("file_system.backend", default="local")
        self._gateway_cache: dict[str, "IFileSystemGateway"] = {}
        self._lock = threading.RLock()
```

成员用途：

- `_backend`: 后端类型（`local|minio|s3`）
- `_gateway_cache`: 网关实例缓存
- `_lock`: 并发保护

### 3.2 对外接口

```python
def get_gateway(self) -> "IFileSystemGateway": ...
def reset(self) -> None: ...
```

内部逻辑：
1. 按 `_backend` 选择网关实现类
2. 延迟初始化并缓存实例
3. 不支持类型时抛配置异常

---

## 4. `IFileSystemGateway` 接口定义

文件：`app/infrastructure/file_system/base.py`

建议接口：

```python
class IFileSystemGateway(Protocol):
    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult: ...

    def open_read(self, storage_path: str) -> BinaryIO: ...
    def exists(self, storage_path: str) -> bool: ...
    def delete(self, storage_path: str) -> bool: ...
```

参数说明：
- `file_stream`: 输入文件流（从 API UploadFile 派生）
- `domain`: `SKILL|MEMORY`
- `kb_index`: 索引名
- `filename`: 原始文件名
- `task_id`: 可选，用于路径分层

返回说明：
- `FileStoreResult`，包含路径、hash、大小等元信息

---

## 5. `LocalFileSystemGateway` 详细实现

文件：`app/infrastructure/file_system/local.py`

### 5.1 初始化

```python
class LocalFileSystemGateway(IFileSystemGateway):
    def __init__(
        self,
        root_dir: str,
        hash_algo: str = "sha256",
        chunk_size: int = 1024 * 1024,
        use_atomic_rename: bool = True,
    ) -> None:
        self._root_dir = root_dir
        self._hash_algo = hash_algo
        self._chunk_size = chunk_size
        self._use_atomic_rename = use_atomic_rename
        self._logger = get_logger(__name__)
```

成员用途：

- `_root_dir`: 文件存储根目录
- `_hash_algo`: 摘要算法
- `_chunk_size`: 分块写入大小
- `_use_atomic_rename`: 是否先写临时文件再原子重命名

### 5.2 核心接口：`store`

```python
def store(
    self,
    file_stream: BinaryIO,
    domain: str,
    kb_index: str,
    filename: str,
    task_id: str | None = None,
) -> FileStoreResult: ...
```

内部逻辑建议：

1. **路径构建与清洗**
   - 生成逻辑路径：`{domain}/{kb_index}/{date}/{task_id}/`
   - 清洗文件名（去路径穿越字符）

2. **目录准备**
   - `mkdir(parents=True, exist_ok=True)`

3. **流式写入**
   - 分块读取 `file_stream`
   - 实时累计 `size_bytes`
   - 同步计算 `sha256`

4. **原子落盘**
   - 临时文件写完后 `rename` 到目标路径

5. **结果返回**
   - 返回 `storage_path/file_hash/size_bytes/...`

注意点：
- 必须防目录穿越（`../`）与非法绝对路径。
- 对大文件使用流式写入，避免内存峰值过高。

### 5.3 `open_read` / `exists` / `delete`

```python
def open_read(self, storage_path: str) -> BinaryIO: ...
def exists(self, storage_path: str) -> bool: ...
def delete(self, storage_path: str) -> bool: ...
```

注意点：
- `storage_path` 必须校验在 `_root_dir` 下。
- 删除失败应记录日志并返回 `False`，不抛未捕获异常。

---

## 6. 扩展后端（MinIO/S3）约束

`minio.py`、`s3.py` 实现同一接口，不改变上层调用方式。

必须保证：

- `store` 返回字段与 `LocalFileSystemGateway` 一致
- `storage_path` 可作为后续解析/下载定位符
- 错误语义兼容（如上传失败、对象不存在）

---

## 7. 错误处理建议

建议异常分类：

- `FILE_STORE_FAILED`：写入失败
- `FILE_NOT_FOUND`：读取路径不存在
- `FILE_DELETE_FAILED`：删除失败
- `INVALID_STORAGE_PATH`：路径越界或非法

建议日志字段：

- `request_id`
- `domain`
- `kb_index`
- `filename`
- `storage_path`
- `size_bytes`
- `file_hash`
- `elapsed_ms`

---

## 8. 测试清单

1. `FileSystemFactory` 返回正确网关
2. `store` 正常写入并返回有效 `FileStoreResult`
3. 大文件流式写入内存稳定
4. 文件 hash 与实际内容一致
5. 文件名含特殊字符时路径清洗正确
6. 原子写入失败可回滚（无脏半文件）
7. `open_read/exists/delete` 行为正确
8. 非法路径（目录穿越）被拒绝

---

## 9. 可直接落地的参考实现（完整代码）

以下代码用于补齐“可执行粒度”的实现细节。你可以按当前目录直接拆分成对应文件。

### 9.1 `types.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FileSystemErrorCode = Literal[
    "FILE_STORE_FAILED",
    "FILE_NOT_FOUND",
    "FILE_DELETE_FAILED",
    "INVALID_STORAGE_PATH",
    "FILE_SYSTEM_BACKEND_UNSUPPORTED",
]


@dataclass(slots=True)
class FileStoreResult:
    storage_path: str
    file_hash: str
    size_bytes: int
    filename: str
    domain: str
    kb_index: str


@dataclass(slots=True)
class FileSystemError(RuntimeError):
    code: FileSystemErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
```

### 9.2 `base.py`

```python
from __future__ import annotations

from typing import BinaryIO, Protocol

from .types import FileStoreResult


class IFileSystemGateway(Protocol):
    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult:
        ...

    def open_read(self, storage_path: str) -> BinaryIO:
        ...

    def exists(self, storage_path: str) -> bool:
        ...

    def delete(self, storage_path: str) -> bool:
        ...
```

### 9.3 `factory.py`

```python
from __future__ import annotations

import threading

from .base import IFileSystemGateway
from .local import LocalFileSystemGateway
from .types import FileSystemError


class FileSystemFactory:
    def __init__(self, cfg: "ConfigManager") -> None:
        self._cfg = cfg
        self._backend = cfg.get_str("file_system.backend", default="local").lower()
        self._gateway_cache: dict[str, IFileSystemGateway] = {}
        self._lock = threading.RLock()

    def get_gateway(self) -> IFileSystemGateway:
        cache_key = self._backend
        with self._lock:
            gateway = self._gateway_cache.get(cache_key)
            if gateway is not None:
                return gateway

            if self._backend == "local":
                gateway = LocalFileSystemGateway(
                    root_dir=self._cfg.get_str("file_system.local.root_dir"),
                    hash_algo=self._cfg.get_str("file_system.local.hash_algo", default="sha256"),
                    chunk_size=self._cfg.get_int("file_system.local.chunk_size", default=1024 * 1024),
                    use_atomic_rename=self._cfg.get_bool(
                        "file_system.local.use_atomic_rename",
                        default=True,
                    ),
                    logger=self._cfg.get_logger(__name__),
                )
            else:
                raise FileSystemError(
                    code="FILE_SYSTEM_BACKEND_UNSUPPORTED",
                    message=f"Unsupported file system backend: {self._backend}",
                )

            self._gateway_cache[cache_key] = gateway
            return gateway

    def reset(self) -> None:
        with self._lock:
            self._gateway_cache.clear()
```

### 9.4 `local.py`

```python
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from .base import IFileSystemGateway
from .types import FileStoreResult, FileSystemError


class LocalFileSystemGateway(IFileSystemGateway):
    _SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")

    def __init__(
        self,
        root_dir: str,
        hash_algo: str = "sha256",
        chunk_size: int = 1024 * 1024,
        use_atomic_rename: bool = True,
        logger=None,
    ) -> None:
        self._root_dir = Path(root_dir).resolve()
        self._hash_algo = hash_algo
        self._chunk_size = chunk_size
        self._use_atomic_rename = use_atomic_rename
        self._logger = logger
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        file_stream: BinaryIO,
        domain: str,
        kb_index: str,
        filename: str,
        task_id: str | None = None,
    ) -> FileStoreResult:
        started_at = time.monotonic()
        safe_domain = self._sanitize_segment(domain, fallback="UNKNOWN")
        safe_kb_index = self._sanitize_segment(kb_index, fallback="default")
        safe_task_id = self._sanitize_segment(task_id or "default", fallback="default")
        safe_filename = self._sanitize_filename(filename)
        date_part = datetime.now(UTC).strftime("%Y%m%d")

        relative_dir = Path(safe_domain) / safe_kb_index / date_part / safe_task_id
        relative_path = relative_dir / f"{uuid4().hex}_{safe_filename}"
        final_path = self._resolve_storage_path(relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.new(self._hash_algo)
        size_bytes = 0
        temp_path: Path | None = None

        try:
            if hasattr(file_stream, "seek"):
                try:
                    file_stream.seek(0)
                except Exception:
                    pass

            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=str(final_path.parent),
                prefix=".upload-",
                suffix=".tmp",
            ) as temp_file:
                temp_path = Path(temp_file.name)
                while True:
                    chunk = file_stream.read(self._chunk_size)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    temp_file.write(chunk)
                    hasher.update(chunk)
                    size_bytes += len(chunk)

            if temp_path is None:
                raise FileSystemError(
                    code="FILE_STORE_FAILED",
                    message="Temporary file was not created.",
                )

            if self._use_atomic_rename:
                os.replace(temp_path, final_path)
            else:
                shutil.move(str(temp_path), str(final_path))

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            if self._logger:
                self._logger.info(
                    "Stored file successfully",
                    extra={
                        "domain": safe_domain,
                        "kb_index": safe_kb_index,
                        "filename": safe_filename,
                        "storage_path": relative_path.as_posix(),
                        "size_bytes": size_bytes,
                        "elapsed_ms": elapsed_ms,
                    },
                )

            return FileStoreResult(
                storage_path=relative_path.as_posix(),
                file_hash=hasher.hexdigest(),
                size_bytes=size_bytes,
                filename=safe_filename,
                domain=safe_domain,
                kb_index=safe_kb_index,
            )
        except FileSystemError:
            raise
        except Exception as exc:
            raise FileSystemError(
                code="FILE_STORE_FAILED",
                message="Failed to store file stream to local filesystem.",
                details={
                    "domain": safe_domain,
                    "kb_index": safe_kb_index,
                    "filename": safe_filename,
                },
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def open_read(self, storage_path: str) -> BinaryIO:
        abs_path = self._resolve_storage_path(storage_path)
        if not abs_path.exists() or not abs_path.is_file():
            raise FileSystemError(
                code="FILE_NOT_FOUND",
                message=f"File not found for storage path: {storage_path}",
            )
        return abs_path.open("rb")

    def exists(self, storage_path: str) -> bool:
        try:
            abs_path = self._resolve_storage_path(storage_path)
        except FileSystemError:
            return False
        return abs_path.exists() and abs_path.is_file()

    def delete(self, storage_path: str) -> bool:
        try:
            abs_path = self._resolve_storage_path(storage_path)
            if not abs_path.exists():
                return False
            abs_path.unlink()
            return True
        except FileSystemError:
            return False
        except Exception as exc:
            if self._logger:
                self._logger.warning(
                    "Delete file failed",
                    extra={"storage_path": storage_path, "error": repr(exc)},
                )
            return False

    def _resolve_storage_path(self, storage_path: str | Path) -> Path:
        relative = Path(storage_path)
        if relative.is_absolute():
            raise FileSystemError(
                code="INVALID_STORAGE_PATH",
                message=f"Absolute path is not allowed: {storage_path}",
            )

        abs_path = (self._root_dir / relative).resolve(strict=False)
        root = str(self._root_dir)
        candidate = str(abs_path)
        if os.path.commonpath([root, candidate]) != root:
            raise FileSystemError(
                code="INVALID_STORAGE_PATH",
                message=f"Storage path escapes root_dir: {storage_path}",
            )
        return abs_path

    def _sanitize_segment(self, value: str, fallback: str) -> str:
        text = (value or "").strip()
        if not text:
            return fallback
        cleaned = self._SEGMENT_RE.sub("_", text)
        cleaned = cleaned.strip("._-")
        return cleaned or fallback

    def _sanitize_filename(self, filename: str) -> str:
        basename = Path(filename or "").name.strip()
        if not basename:
            return "unnamed.bin"
        cleaned = self._SEGMENT_RE.sub("_", basename)
        cleaned = cleaned.strip()
        if cleaned in {".", "..", ""}:
            return "unnamed.bin"
        return cleaned
```

### 9.5 `minio.py` / `s3.py` 适配骨架（可选）

```python
# 以 S3/MinIO 为例，建议复用同一实现：
# - boto3 客户端指向 AWS S3 -> s3.py
# - boto3 客户端指向 MinIO Endpoint -> minio.py

class S3FileSystemGateway(IFileSystemGateway):
    def __init__(self, client, bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def store(...): ...
    def open_read(...): ...
    def exists(...): ...
    def delete(...): ...
```

适配要求：

1. `storage_path` 仍用逻辑相对路径（便于跨后端迁移）。
2. `store` 返回字段必须与本地实现一致（`FileStoreResult`）。
3. 错误码语义保持一致（`FILE_STORE_FAILED/FILE_NOT_FOUND/...`）。

---

## 10. 实施建议（落地时注意）

1. `store` 中先写临时文件再 `os.replace`，能规避并发读取“半文件”。
2. `storage_path` 永远存相对路径，不存绝对路径，避免部署迁移困难。
3. `open_read` 返回文件句柄时，上层必须 `with` 语句关闭，避免 FD 泄漏。
4. 对大文件上传，`chunk_size` 建议在 `1MB~8MB` 间做压测后再定值。

