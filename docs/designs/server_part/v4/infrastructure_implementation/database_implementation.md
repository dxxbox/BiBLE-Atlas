# database/ 详细实现指南（v4）

本文档描述 `app/infrastructure/database/` 的开发细节：类初始化、成员、接口参数/返回值与内部实现逻辑。  
目标是对上层 `features/*` 暴露稳定接口，同时支持多后端可替换实现。

---

## 1. 目录建议

```text
app/infrastructure/database/
├── base.py
├── factory.py
├── types.py                      # 可选：统一类型定义
├── opensearch/
│   ├── client.py
│   ├── reader.py
│   └── writer.py
├── elasticsearch/                # 可选扩展
└── postgres/                     # 可选扩展
```

---

## 2. 通用数据类型（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

DomainType = Literal["KNOWLEDGE_BASE", "SKILL", "MEMORY"]

@dataclass
class IndexBinding:
    domain_type: DomainType
    kb_index: str
    tag: str
    parser_script_source: str
    parser_script_sha256: str
    vector_model: str | None
    search_profile_json: dict[str, Any]
    search_profile_sha256: str
    is_active: bool = True

@dataclass
class BulkWriteResult:
    success_count: int
    fail_count: int
    errors: list[dict[str, Any]]
```

---

## 3. `DatabaseFactory` 详细实现

文件：`app/infrastructure/database/factory.py`

### 3.1 初始化

```python
class DatabaseFactory:
    def __init__(self, config_manager: "ConfigManager") -> None:
        self._cfg = config_manager
        self._backend_type: str = self._cfg.get_str("database.backend")
        self._writer_cache: dict[str, "IDatabaseWriter"] = {}
        self._lock = threading.RLock()
```

成员用途：

- `_backend_type`: 当前后端类型（如 `opensearch`）
- `_writer_cache`: writer 单例缓存，避免重复初始化 client
- `_lock`: 并发安全

### 3.2 对外接口

```python
def get_writer(self, domain: DomainType) -> "IDatabaseWriter": ...
def get_async_task_writer(self) -> "IDatabaseWriter": ...
def reset(self) -> None: ...
```

参数说明：
- `domain`: 用于路由不同索引策略（如内容索引、绑定索引）

返回说明：
- 返回实现了 `IDatabaseWriter` 的实例

补充说明：
- `get_async_task_writer()`: 为异步任务仓储提供统一注入入口，避免业务层直接感知具体后端

### 3.3 内部逻辑

1. 读取 `database.backend`
2. 根据后端类型创建对应 writer（当前默认 `OpenSearchWriter`）
3. 缓存 writer 并复用
4. 不支持后端类型时抛出配置异常

注意点：
- `get_writer` 必须线程安全。
- `reset` 用于测试隔离或配置热更新。

---

## 4. `IDatabaseWriter` 接口定义

文件：`app/infrastructure/database/base.py`

建议最小接口：

```python
class IDatabaseWriter(Protocol):
    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None: ...
    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None: ...
    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]: ...
    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]: ...
    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult: ...
    def bulk_upsert_file_registry(self, index: str, file_records: list[dict[str, Any]]) -> BulkWriteResult: ...
    def create_async_task(self, task_doc: dict[str, Any]) -> None: ...
    def get_async_task(self, task_id: str) -> dict[str, Any] | None: ...
    def find_async_task_by_idempotency(self, task_type: str, idempotency_key: str) -> dict[str, Any] | None: ...
    def update_async_task(self, task_id: str, patch_doc: dict[str, Any], expected_statuses: list[str] | None = None) -> bool: ...
```

接口语义：

- `get_binding_*`: 查询有效绑定
- `create_index_binding`: 首次绑定（应保证不可覆盖）
- `deactivate_binding`: 软删除绑定
- `bulk_upsert_content_docs`: 内容文档写入
- `bulk_upsert_file_registry`: 文件注册表写入（SKILL/MEMORY）
- `create/get/find/update_async_task`: 通用异步任务状态存储与流转（供 `AsyncTaskRepository` 使用）

---

## 5. `OpenSearchWriter` 详细实现

文件：`app/infrastructure/database/opensearch/writer.py`

### 5.1 初始化

```python
class OpenSearchWriter(IDatabaseWriter):
    def __init__(self, client: "OpenSearch", cfg: "ConfigManager") -> None:
        self._client = client
        self._cfg = cfg
        self._binding_index = cfg.get_str("database.opensearch.binding_index")  # e.g. v4_index_binding
        self._refresh_policy = cfg.get_str("database.opensearch.refresh_policy", default="false")
        self._bulk_chunk_size = cfg.get_int("database.opensearch.bulk_chunk_size", default=500)
        self._logger = get_logger(__name__)
```

成员用途：

- `_binding_index`: 绑定元数据索引
- `_refresh_policy`: 写入刷新策略
- `_bulk_chunk_size`: 批量写入分片大小

### 5.2 关键私有方法（建议）

```python
def _binding_doc_id(self, domain: DomainType, kb_index: str) -> str: ...
def _to_binding(self, hit_source: dict[str, Any]) -> IndexBinding: ...
def _bulk(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult: ...
```

实现要点：
- `_binding_doc_id`: 推荐 `{domain}::{kb_index}`
- `_bulk`: 统一封装 bulk upsert、错误汇总与日志

### 5.3 接口实现细节

#### 5.3.1 `get_binding_by_domain_index`

参数：
- `domain`: 业务域
- `kb_index`: 物理索引名

返回：
- 命中返回 `IndexBinding`
- 未命中返回 `None`

内部逻辑：
1. 按 `_id` 或 `bool.filter` 查询
2. 强制 `is_active=true`
3. 映射到 `IndexBinding`

#### 5.3.2 `get_binding_by_domain_tag`

参数：
- `domain`
- `tag`

返回：
- 单条绑定或 `None`

内部逻辑：
1. `bool.filter` 查询 `domain + tag + is_active`
2. `size=1`
3. 如命中多条应记录错误（理论不应发生）

#### 5.3.3 `create_index_binding`

参数：
- `binding_doc`: 完整绑定文档（含 `search_profile_json`）

返回：
- `{created: True, _id: "..."}`

内部逻辑：
1. 计算 `_id = {domain}::{kb_index}`
2. `op_type=create` 写入，保证首次绑定原子性
3. 冲突抛业务异常 `INDEX_BINDING_CONFLICT`

#### 5.3.4 `deactivate_binding`

参数：
- `domain`
- `kb_index`

返回：
- 更新结果

内部逻辑：
1. 查 `_id`
2. 更新 `is_active=false`、`deleted_at=now`

#### 5.3.5 `bulk_upsert_content_docs`

参数：
- `index`: 内容索引名
- `docs`: 文档列表（可含 `content_vector`）

返回：
- `BulkWriteResult`

内部逻辑：
1. 按 `_bulk_chunk_size` 分片
2. 构造 `update + doc_as_upsert=true`
3. 汇总成功/失败计数与错误详情

#### 5.3.6 `bulk_upsert_file_registry`

参数：
- `index`
- `file_records`

返回：
- `BulkWriteResult`

实现与 `bulk_upsert_content_docs` 一致，仅数据模型不同。

---

## 6. `opensearch/client.py`（建议）

建议类：

```python
class OpenSearchClientProvider:
    def __init__(self, cfg: "ConfigManager") -> None:
        self._hosts = cfg.get_list("database.opensearch.hosts")
        self._auth = cfg.get_optional_auth(...)
        self._timeout = cfg.get_int("database.opensearch.timeout_seconds", default=30)
        self._client = None

    def get_client(self) -> "OpenSearch": ...
```

注意点：
- client 连接要单例复用。
- 连接失败要快速失败并输出可诊断日志（host、timeout、tls）。

---

## 7. 错误处理与可观测性

建议统一异常映射：

- 绑定冲突 -> `INDEX_BINDING_CONFLICT`
- 索引不存在 -> `INDEX_NOT_BOUND` / `INTERNAL_ERROR`（按场景）
- 后端不可用 -> `INTERNAL_ERROR`

日志建议字段：
- `request_id`
- `domain_type`
- `kb_index`
- `tag`
- `operation`（get_binding/create_binding/bulk_upsert/...）
- `success_count/fail_count`
- `elapsed_ms`

---

## 8. 测试清单

1. `DatabaseFactory` 按配置返回正确 writer
2. 绑定首次创建成功（`op_type=create`）
3. 二次创建冲突拒绝
4. `get_binding_by_domain_index/tag` 查询正确
5. `deactivate_binding` 生效
6. `bulk_upsert_content_docs` 成功与部分失败统计正确
7. `bulk_upsert_file_registry` 成功与失败统计正确
8. `create/get/find/update_async_task` 在 OpenSearch/Postgres 两后端行为一致
9. 并发 `get_writer` 不重复初始化 client

---

## 9. 可直接落地的参考实现（完整代码）

以下代码用于补齐“可执行粒度”的实现细节。你可以按当前目录直接拆成对应文件。

### 9.1 `types.py`

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DomainType = Literal["KNOWLEDGE_BASE", "SKILL", "MEMORY"]

DatabaseErrorCode = Literal[
    "INDEX_BINDING_CONFLICT",
    "INDEX_NOT_BOUND",
    "DATABASE_BACKEND_UNAVAILABLE",
    "DATABASE_WRITE_PARTIAL_FAILED",
    "DATABASE_INVALID_ARGUMENT",
]


@dataclass(slots=True)
class IndexBinding:
    domain_type: DomainType
    kb_index: str
    tag: str
    parser_script_source: str
    parser_script_sha256: str
    vector_model: str | None
    search_profile_json: dict[str, Any]
    search_profile_sha256: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BulkWriteResult:
    success_count: int = 0
    fail_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class DatabaseError(RuntimeError):
    code: DatabaseErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
```

### 9.2 `base.py`

```python
from __future__ import annotations

from typing import Any, Protocol

from .types import BulkWriteResult, DomainType, IndexBinding


class IDatabaseWriter(Protocol):
    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        ...

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        ...

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        ...

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        ...

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        ...

    def bulk_upsert_file_registry(self, index: str, file_records: list[dict[str, Any]]) -> BulkWriteResult:
        ...

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        ...

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def find_async_task_by_idempotency(self, task_type: str, idempotency_key: str) -> dict[str, Any] | None:
        ...

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        ...
```

### 9.3 `factory.py`

```python
from __future__ import annotations

import threading
from typing import Any

from .base import IDatabaseWriter
from .opensearch.client import OpenSearchClientProvider
from .opensearch.writer import OpenSearchWriter
from .postgres.client import PostgresClientProvider
from .postgres.writer import PostgresWriter
from .types import DatabaseError, DomainType


class DatabaseFactory:
    def __init__(self, config_manager: "ConfigManager") -> None:
        self._cfg = config_manager
        self._backend_type = self._cfg.get_str("database.backend", default="opensearch").lower()
        self._writer_cache: dict[str, IDatabaseWriter] = {}
        self._provider_cache: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get_writer(self, domain: DomainType) -> IDatabaseWriter:
        del domain
        cache_key = self._backend_type
        with self._lock:
            writer = self._writer_cache.get(cache_key)
            if writer is not None:
                return writer

            if self._backend_type == "opensearch":
                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = OpenSearchClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = OpenSearchWriter(provider.get_client(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            if self._backend_type == "postgres":
                provider = self._provider_cache.get(cache_key)
                if provider is None:
                    provider = PostgresClientProvider(self._cfg)
                    self._provider_cache[cache_key] = provider
                writer = PostgresWriter(provider.get_pool(), self._cfg)
                self._writer_cache[cache_key] = writer
                return writer

            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message=f"Unsupported database backend: {self._backend_type}",
            )

    def get_async_task_writer(self) -> IDatabaseWriter:
        # 目前复用统一 writer；
        # 若未来 async task 迁移独立 backend，可在此扩展
        return self.get_writer(domain="KNOWLEDGE_BASE")

    def reset(self) -> None:
        with self._lock:
            self._writer_cache.clear()
            for provider in self._provider_cache.values():
                close_fn = getattr(provider, "close", None)
                if callable(close_fn):
                    close_fn()
            self._provider_cache.clear()
```

### 9.4 `opensearch/client.py`

```python
from __future__ import annotations

import threading
from typing import Any

from opensearchpy import OpenSearch

from ..types import DatabaseError


class OpenSearchClientProvider:
    def __init__(self, cfg: "ConfigManager") -> None:
        self._cfg = cfg
        self._hosts = cfg.get_list("database.opensearch.hosts")
        self._timeout_seconds = cfg.get_int("database.opensearch.timeout_seconds", default=30)
        self._use_ssl = cfg.get_bool("database.opensearch.use_ssl", default=False)
        self._verify_certs = cfg.get_bool("database.opensearch.verify_certs", default=True)
        self._username = cfg.get_optional_str("database.opensearch.username")
        self._password = cfg.get_optional_str("database.opensearch.password")
        self._client: OpenSearch | None = None
        self._lock = threading.RLock()

    def get_client(self) -> OpenSearch:
        with self._lock:
            if self._client is not None:
                return self._client

            kwargs: dict[str, Any] = {
                "hosts": self._hosts,
                "timeout": self._timeout_seconds,
                "use_ssl": self._use_ssl,
                "verify_certs": self._verify_certs,
            }
            if self._username and self._password:
                kwargs["http_auth"] = (self._username, self._password)

            client = OpenSearch(**kwargs)
            if not client.ping():
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="OpenSearch ping failed.",
                    details={
                        "hosts": self._hosts,
                        "timeout_seconds": self._timeout_seconds,
                        "use_ssl": self._use_ssl,
                    },
                )

            self._client = client
            return client

    def close(self) -> None:
        with self._lock:
            if self._client is None:
                return
            transport = getattr(self._client, "transport", None)
            if transport is not None and hasattr(transport, "close"):
                transport.close()
            self._client = None
```

### 9.5 `opensearch/writer.py`

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConflictError, NotFoundError, TransportError
from opensearchpy.helpers import bulk

from ..base import IDatabaseWriter
from ..types import BulkWriteResult, DatabaseError, DomainType, IndexBinding


class OpenSearchWriter(IDatabaseWriter):
    def __init__(self, client: OpenSearch, cfg: "ConfigManager") -> None:
        self._client = client
        self._cfg = cfg
        self._binding_index = cfg.get_str("database.opensearch.binding_index", default="v4_index_binding")
        self._refresh_policy = cfg.get_str("database.opensearch.refresh_policy", default="false")
        self._bulk_chunk_size = cfg.get_int("database.opensearch.bulk_chunk_size", default=500)
        self._request_timeout = cfg.get_int("database.opensearch.request_timeout_seconds", default=60)
        self._logger = cfg.get_logger(__name__)

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        doc_id = self._binding_doc_id(domain, kb_index)
        try:
            resp = self._client.get(index=self._binding_index, id=doc_id)
        except NotFoundError:
            return None
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/index.",
                details={"domain": domain, "kb_index": kb_index},
            ) from exc

        source = resp.get("_source", {})
        if not source.get("is_active", True):
            return None
        return self._to_binding(source)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        query = {
            "size": 2,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"domain_type.keyword": domain}},
                        {"term": {"tag.keyword": tag}},
                        {"term": {"is_active": True}},
                    ]
                }
            },
        }
        try:
            resp = self._client.search(index=self._binding_index, body=query)
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/tag.",
                details={"domain": domain, "tag": tag},
            ) from exc

        hits = (resp.get("hits") or {}).get("hits") or []
        if not hits:
            return None
        if len(hits) > 1:
            self._logger.error(
                "Duplicated active bindings found for same domain/tag",
                extra={"domain_type": domain, "tag": tag, "count": len(hits)},
            )
        return self._to_binding(hits[0].get("_source", {}))

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        required = {
            "domain_type",
            "kb_index",
            "tag",
            "parser_script_source",
            "parser_script_sha256",
            "search_profile_json",
            "search_profile_sha256",
        }
        missing = [key for key in required if key not in binding_doc]
        if missing:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_index_binding requires complete binding_doc.",
                details={"missing_fields": missing},
            )

        domain = binding_doc["domain_type"]
        kb_index = binding_doc["kb_index"]
        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        payload = {
            **binding_doc,
            "is_active": bool(binding_doc.get("is_active", True)),
            "created_at": binding_doc.get("created_at", now),
            "updated_at": now,
            "deleted_at": None,
        }
        try:
            resp = self._client.index(
                index=self._binding_index,
                id=doc_id,
                body=payload,
                op_type="create",
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except ConflictError as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Index binding already exists for {domain}::{kb_index}.",
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc

        return {"created": True, "_id": resp.get("_id", doc_id)}

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        doc_id = self._binding_doc_id(domain, kb_index)
        now = self._now_iso()
        script = {
            "source": (
                "ctx._source.is_active = false; "
                "ctx._source.deleted_at = params.now; "
                "ctx._source.updated_at = params.now;"
            ),
            "lang": "painless",
            "params": {"now": now},
        }
        try:
            resp = self._client.update(
                index=self._binding_index,
                id=doc_id,
                body={"script": script},
                refresh=self._refresh_policy,
                request_timeout=self._request_timeout,
            )
        except NotFoundError as exc:
            raise DatabaseError(
                code="INDEX_NOT_BOUND",
                message=f"Binding not found for {domain}::{kb_index}.",
            ) from exc
        except TransportError as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to deactivate index binding.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": resp.get("_id", doc_id)}

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        return self._bulk(index=index, docs=docs)

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk(index=index, docs=file_records)

    def _bulk(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        if not index:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="bulk upsert requires index.",
            )
        if not docs:
            return BulkWriteResult()

        result = BulkWriteResult()
        for chunk in self._chunked(docs, self._bulk_chunk_size):
            actions: list[dict[str, Any]] = []
            for doc in chunk:
                doc_id = str(doc.get("_id") or doc.get("doc_id") or "").strip()
                if not doc_id:
                    result.fail_count += 1
                    result.errors.append(
                        {"reason": "missing _id/doc_id", "doc_preview": list(doc.keys())[:10]}
                    )
                    continue

                payload = {k: v for k, v in doc.items() if k != "_id"}
                actions.append(
                    {
                        "_op_type": "update",
                        "_index": index,
                        "_id": doc_id,
                        "doc": payload,
                        "doc_as_upsert": True,
                    }
                )

            if not actions:
                continue

            try:
                success_count, errors = bulk(
                    self._client,
                    actions,
                    refresh=self._refresh_policy,
                    raise_on_error=False,
                    raise_on_exception=False,
                    request_timeout=self._request_timeout,
                )
            except TransportError as exc:
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="Bulk upsert failed due to backend transport error.",
                    details={"index": index, "batch_size": len(actions)},
                ) from exc

            result.success_count += int(success_count)
            if errors:
                result.fail_count += len(errors)
                result.errors.extend(errors)

        if result.fail_count > 0:
            self._logger.warning(
                "Bulk upsert partial failed",
                extra={
                    "operation": "bulk_upsert",
                    "index": index,
                    "success_count": result.success_count,
                    "fail_count": result.fail_count,
                },
            )
        return result

    def _binding_doc_id(self, domain: DomainType, kb_index: str) -> str:
        return f"{domain}::{kb_index}"

    def _to_binding(self, source: dict[str, Any]) -> IndexBinding:
        return IndexBinding(
            domain_type=source["domain_type"],
            kb_index=source["kb_index"],
            tag=source["tag"],
            parser_script_source=source["parser_script_source"],
            parser_script_sha256=source["parser_script_sha256"],
            vector_model=source.get("vector_model"),
            search_profile_json=source["search_profile_json"],
            search_profile_sha256=source["search_profile_sha256"],
            is_active=bool(source.get("is_active", True)),
            created_at=source.get("created_at"),
            updated_at=source.get("updated_at"),
            deleted_at=source.get("deleted_at"),
        )

    def _chunked(self, docs: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
        for idx in range(0, len(docs), size):
            yield docs[idx : idx + size]

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()
```

### 9.6 `postgres/client.py`

```python
from __future__ import annotations

import threading

from psycopg_pool import ConnectionPool

from ..types import DatabaseError


class PostgresClientProvider:
    def __init__(self, cfg: "ConfigManager") -> None:
        self._cfg = cfg
        self._dsn = cfg.get_str("database.postgres.dsn")
        self._pool_min_size = cfg.get_int("database.postgres.pool_min_size", default=1)
        self._pool_max_size = cfg.get_int("database.postgres.pool_max_size", default=10)
        self._pool_timeout_seconds = cfg.get_int("database.postgres.pool_timeout_seconds", default=30)
        self._pool: ConnectionPool | None = None
        self._lock = threading.RLock()

    def get_pool(self) -> ConnectionPool:
        with self._lock:
            if self._pool is not None:
                return self._pool

            pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=self._pool_min_size,
                max_size=self._pool_max_size,
                timeout=self._pool_timeout_seconds,
            )
            try:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
            except Exception as exc:
                pool.close()
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="Postgres connectivity check failed.",
                    details={
                        "dsn": self._mask_dsn(self._dsn),
                        "pool_min_size": self._pool_min_size,
                        "pool_max_size": self._pool_max_size,
                    },
                ) from exc

            self._pool = pool
            return pool

    def close(self) -> None:
        with self._lock:
            if self._pool is None:
                return
            self._pool.close()
            self._pool = None

    def _mask_dsn(self, dsn: str) -> str:
        if "@" not in dsn:
            return dsn
        prefix, suffix = dsn.split("@", 1)
        if ":" in prefix:
            user = prefix.split(":", 1)[0]
            return f"{user}:***@{suffix}"
        return f"{prefix}@{suffix}"
```

### 9.7 `postgres/writer.py`

```python
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Iterable

from psycopg import errors as pg_errors
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..base import IDatabaseWriter
from ..types import BulkWriteResult, DatabaseError, DomainType, IndexBinding


class PostgresWriter(IDatabaseWriter):
    _TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def __init__(self, pool: ConnectionPool, cfg: "ConfigManager") -> None:
        self._pool = pool
        self._cfg = cfg
        self._binding_table = cfg.get_str("database.postgres.binding_table", default="v4_index_binding")
        self._content_table = cfg.get_str("database.postgres.content_table", default="v4_content_docs")
        self._file_registry_table = cfg.get_str(
            "database.postgres.file_registry_table",
            default="v4_file_registry",
        )
        self._bulk_chunk_size = cfg.get_int("database.postgres.bulk_chunk_size", default=500)
        self._logger = cfg.get_logger(__name__)

        self._validate_table_name(self._binding_table)
        self._validate_table_name(self._content_table)
        self._validate_table_name(self._file_registry_table)

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        query = sql.SQL(
            """
            SELECT
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            FROM {}
            WHERE domain_type = %s AND kb_index = %s AND is_active = TRUE
            LIMIT 1
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (domain, kb_index))
                    row = cur.fetchone()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/index from Postgres.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        if row is None:
            return None
        return self._to_binding(row)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        query = sql.SQL(
            """
            SELECT
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            FROM {}
            WHERE domain_type = %s AND tag = %s AND is_active = TRUE
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 2
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (domain, tag))
                    rows = cur.fetchall()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/tag from Postgres.",
                details={"domain_type": domain, "tag": tag},
            ) from exc
        if not rows:
            return None
        if len(rows) > 1:
            self._logger.error(
                "Duplicated active bindings found for same domain/tag in Postgres",
                extra={"domain_type": domain, "tag": tag, "count": len(rows)},
            )
        return self._to_binding(rows[0])

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        required = {
            "domain_type",
            "kb_index",
            "tag",
            "parser_script_source",
            "parser_script_sha256",
            "search_profile_json",
            "search_profile_sha256",
        }
        missing = [key for key in required if key not in binding_doc]
        if missing:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_index_binding requires complete binding_doc.",
                details={"missing_fields": missing},
            )

        now = self._now_iso()
        payload = {
            **binding_doc,
            "is_active": bool(binding_doc.get("is_active", True)),
            "created_at": binding_doc.get("created_at", now),
            "updated_at": now,
            "deleted_at": None,
        }
        query = sql.SQL(
            """
            INSERT INTO {} (
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            """
        ).format(sql.Identifier(self._binding_table))
        params = (
            payload["domain_type"],
            payload["kb_index"],
            payload["tag"],
            payload["parser_script_source"],
            payload["parser_script_sha256"],
            payload.get("vector_model"),
            Jsonb(payload["search_profile_json"]),
            payload["search_profile_sha256"],
            payload["is_active"],
            payload["created_at"],
            payload["updated_at"],
            payload["deleted_at"],
        )
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                conn.commit()
        except pg_errors.UniqueViolation as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Index binding already exists for {payload['domain_type']}::{payload['kb_index']}.",
            ) from exc
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create index binding in Postgres.",
                details={
                    "domain_type": payload["domain_type"],
                    "kb_index": payload["kb_index"],
                    "tag": payload["tag"],
                },
            ) from exc

        return {"created": True, "_id": self._binding_doc_id(payload["domain_type"], payload["kb_index"])}

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        now = self._now_iso()
        query = sql.SQL(
            """
            UPDATE {}
               SET is_active = FALSE,
                   deleted_at = %s,
                   updated_at = %s
             WHERE domain_type = %s
               AND kb_index = %s
               AND is_active = TRUE
         RETURNING domain_type, kb_index
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (now, now, domain, kb_index))
                    updated = cur.fetchone()
                conn.commit()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to deactivate index binding in Postgres.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        if updated is None:
            raise DatabaseError(
                code="INDEX_NOT_BOUND",
                message=f"Binding not found for {domain}::{kb_index}.",
            )
        return {"updated": True, "_id": self._binding_doc_id(domain, kb_index)}

    def bulk_upsert_content_docs(self, index: str, docs: list[dict[str, Any]]) -> BulkWriteResult:
        return self._bulk_upsert_json_records(
            table_name=self._content_table,
            index=index,
            records=docs,
            id_fields=("_id", "doc_id"),
        )

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk_upsert_json_records(
            table_name=self._file_registry_table,
            index=index,
            records=file_records,
            id_fields=("_id", "file_id", "storage_path"),
        )

    def _bulk_upsert_json_records(
        self,
        table_name: str,
        index: str,
        records: list[dict[str, Any]],
        id_fields: tuple[str, ...],
    ) -> BulkWriteResult:
        if not index:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="bulk upsert requires index.",
            )
        if not records:
            return BulkWriteResult()

        query = sql.SQL(
            """
            INSERT INTO {} (index_name, row_id, payload, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (index_name, row_id)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
            """
        ).format(sql.Identifier(table_name))

        result = BulkWriteResult()
        for chunk in self._chunked(records, self._bulk_chunk_size):
            params: list[tuple[str, str, Jsonb]] = []
            for record in chunk:
                row_id = self._extract_row_id(record, id_fields)
                if not row_id:
                    result.fail_count += 1
                    result.errors.append(
                        {
                            "reason": f"missing id fields: {id_fields}",
                            "record_preview": list(record.keys())[:10],
                        }
                    )
                    continue
                payload = {k: v for k, v in record.items() if k != "_id"}
                params.append((index, row_id, Jsonb(payload)))

            if not params:
                continue
            try:
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.executemany(query, params)
                    conn.commit()
                result.success_count += len(params)
            except Exception as exc:
                result.fail_count += len(params)
                result.errors.append(
                    {
                        "reason": repr(exc),
                        "batch_size": len(params),
                    }
                )
                self._logger.warning(
                    "Postgres bulk upsert batch failed",
                    extra={
                        "table": table_name,
                        "index": index,
                        "batch_size": len(params),
                        "error": repr(exc),
                    },
                )
        return result

    def _extract_row_id(self, data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
        for field in fields:
            value = data.get(field)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _binding_doc_id(self, domain: DomainType, kb_index: str) -> str:
        return f"{domain}::{kb_index}"

    def _to_binding(self, row: dict[str, Any]) -> IndexBinding:
        return IndexBinding(
            domain_type=row["domain_type"],
            kb_index=row["kb_index"],
            tag=row["tag"],
            parser_script_source=row["parser_script_source"],
            parser_script_sha256=row["parser_script_sha256"],
            vector_model=row.get("vector_model"),
            search_profile_json=row["search_profile_json"],
            search_profile_sha256=row["search_profile_sha256"],
            is_active=bool(row.get("is_active", True)),
            created_at=self._iso_if_datetime(row.get("created_at")),
            updated_at=self._iso_if_datetime(row.get("updated_at")),
            deleted_at=self._iso_if_datetime(row.get("deleted_at")),
        )

    def _iso_if_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        return str(value)

    def _chunked(self, docs: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
        for idx in range(0, len(docs), size):
            yield docs[idx : idx + size]

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _validate_table_name(self, table_name: str) -> None:
        if not self._TABLE_RE.match(table_name):
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message=f"Invalid postgres table name: {table_name}",
            )
```

### 9.8 `postgres/schema.sql`（建议）

```sql
-- 索引绑定表：一条绑定代表 domain + kb_index 的唯一活动配置
CREATE TABLE IF NOT EXISTS v4_index_binding (
    domain_type TEXT NOT NULL,
    kb_index TEXT NOT NULL,
    tag TEXT NOT NULL,
    parser_script_source TEXT NOT NULL,
    parser_script_sha256 TEXT NOT NULL,
    vector_model TEXT NULL,
    search_profile_json JSONB NOT NULL,
    search_profile_sha256 TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL,
    PRIMARY KEY (domain_type, kb_index)
);

-- 确保同一 domain + tag 只能有一条 active 绑定
CREATE UNIQUE INDEX IF NOT EXISTS uq_v4_binding_domain_tag_active
    ON v4_index_binding(domain_type, tag)
    WHERE is_active = TRUE;

-- 内容文档 upsert 表（按 index_name + row_id 幂等）
CREATE TABLE IF NOT EXISTS v4_content_docs (
    index_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_v4_content_docs_index
    ON v4_content_docs(index_name);

-- 文件注册表 upsert 表（按 index_name + row_id 幂等）
CREATE TABLE IF NOT EXISTS v4_file_registry (
    index_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_v4_file_registry_index
    ON v4_file_registry(index_name);
```

---

## 10. 实施建议（落地时注意）

1. `create_index_binding` 必须保留 `op_type=create`，这是“首次绑定不可覆盖”的关键。
2. `bulk_upsert_*` 建议统一要求 `_id` 或 `doc_id`，避免重复写入导致脏数据。
3. `DatabaseFactory.reset()` 在测试 teardown 必须调用，防止连接泄漏。
4. 继续扩展更多后端（如 ES/MySQL）时，建议保持 `IDatabaseWriter` 不变，仅新增实现类与 provider 分支。

