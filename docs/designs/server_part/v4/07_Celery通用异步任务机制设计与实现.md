# 通用异步任务机制设计与实现（v4，基于 Celery）

> 本文档将 Celery 作为 v4 默认异步任务框架。  
> `import` 只是一个接入方，机制可复用于任意业务流程。

---

## 1. 异步原理（先讲清楚“异步在哪”）

异步不是 `while/for`，也不要求业务代码必须写 `async/await`。  
这里的异步是**执行解耦**：

1. API 请求线程只负责：校验参数 -> 落库任务 -> 投递 Celery 消息。
2. API 立刻返回 `202 + task_id`，不等待耗时任务完成。
3. Celery Worker 在后台进程执行真实业务。
4. 客户端通过 `task_id` 查询任务状态/结果。

这就是现代后端异步机制的核心：**消息驱动 + 后台执行 + 状态可观测**。

---

## 2. 设计目标

- 以 Celery 提供统一异步能力：投递、路由、并发、重试、取消。
- 不把业务 API 直接绑死到 Celery 的内部结果结构。
- 支持多业务线接入：`import.*`、`search.reindex`、离线批处理等。
- 支持无 Redis 的开发模式（包括本地内存模式）。
- 支持稳定运维：状态追踪、失败分类、幂等、可观测。

---

## 3. 架构总览

```text
Client
  |
  v
API Controller
  |
  v
AsyncTaskService --------------------> AsyncTaskRepository (业务任务表)
  |                                            ^
  | apply_async(task_id=业务task_id)           | 更新状态
  v                                            |
Celery Broker ---------------------------- Celery Worker
                                                  |
                                                  v
                                           Task Dispatcher
                                                  |
                                                  v
                                           Business Executor
```

分层职责：

- `AsyncTaskService`：统一入口（submit/get/cancel）。
- `Celery`：分发、并发、重试、撤销。
- `Executor`：业务执行逻辑（import/search/...）。
- `AsyncTaskRepository`：业务态任务记录（对 API 稳定暴露）。

---

## 4. Celery 运行模式（回答“Celery 不一定要 Redis”）

Celery 不强制 Redis，可以按环境切换：

1. **单元测试模式**
   - `task_always_eager=true`
   - 无需单独 worker，任务在当前进程直接执行。

2. **本地开发（内存模式）**
   - `broker_url=memory://`
   - `result_backend=cache+memory://`
   - 适合本地快速验证，不适合生产持久化与高可靠。

3. **生产模式（推荐）**
   - broker：`redis://...` 或 `amqp://...`（RabbitMQ）
   - backend：`redis://...` 或数据库 backend

---

## 5. 代码目录建议（可直接落地）

```text
app/features/async_task/
├── settings.py
├── celery_app.py
├── models.py
├── repository.py
├── service.py
├── routing.py
├── errors.py
├── executors/
│   ├── base.py
│   ├── registry.py
│   └── import_executors.py
└── tasks/
    ├── dispatch_task.py
    └── maintenance_task.py
```

---

## 6. 业务任务存储（通过数据库抽象，建议保留）

即使启用 Celery，仍建议维护独立的 `async_tasks` 业务任务存储，保证 API 查询稳定性与可审计性。

字段建议：

- `task_id`（主键，同时作为 celery task_id）
- `task_type`（如 `import.skill`）
- `status`（`queued/running/retrying/completed/failed/cancelled`）
- `payload_json` / `result_json`
- `error_code` / `error_message`
- `retry_count` / `max_retries`
- `queue_name`
- `idempotency_key`（可选）
- `created_at/updated_at/started_at/finished_at`

约束建议：

- 业务主键：`task_id`
- 幂等键：`task_type + idempotency_key`（空值不参与幂等）

## 6.1 `AsyncTaskRepository` 的职责边界

`AsyncTaskRepository` 不只是“记录一条状态”：

1. 对外提供稳定业务状态模型（`queued/running/retrying/completed/failed/cancelled`）。
2. 承载提交幂等（`task_type + idempotency_key`）。
3. 记录业务级错误码、错误信息、重试次数、审计字段。
4. 为 API 查询与运维统计提供稳定数据源（不直接依赖 Celery backend 字段格式）。

## 6.2 去掉 `AsyncTaskRepository` 会有什么影响

分两种目标看：

1. **只关心任务能执行**：理论上可以去掉，直接依赖 Celery backend。
2. **关心业务稳定性与可运维**：不建议去掉，会带来以下代价：
   - 难以提供稳定的业务查询接口（状态/字段受 backend 实现影响）。
   - 幂等提交能力缺失或实现复杂度显著增加。
   - 业务错误码与审计信息难以统一沉淀。
   - backend 过期后历史任务难以追溯。

---

## 7. 详细实现（代码级）

## 7.1 配置实现（`settings.py`）

```python
from pydantic_settings import BaseSettings


class AsyncTaskSettings(BaseSettings):
    # Celery
    celery_broker_url: str = "memory://"
    celery_result_backend: str = "cache+memory://"
    celery_task_default_queue: str = "async.default"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: list[str] = ["json"]
    celery_task_acks_late: bool = True
    celery_worker_prefetch_multiplier: int = 1
    celery_task_track_started: bool = True
    celery_task_soft_time_limit: int = 3300
    celery_task_time_limit: int = 3600

    # Retry
    default_max_retries: int = 3
    backoff_base_seconds: int = 5
    backoff_factor: float = 2.0
    backoff_jitter_seconds: int = 3
```

## 7.2 Celery 初始化（`celery_app.py`）

```python
from celery import Celery
from kombu import Queue
from .settings import AsyncTaskSettings

settings = AsyncTaskSettings()
celery_app = Celery("v4_async")

celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_default_queue=settings.celery_task_default_queue,
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content,
    task_acks_late=settings.celery_task_acks_late,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    task_track_started=settings.celery_task_track_started,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    task_queues=(Queue("async.default"), Queue("import"), Queue("search"), Queue("maintenance")),
)
```

## 7.3 执行器协议与 `registry` 实现（`executors/base.py` + `executors/registry.py`）

`registry` 不是“抽象概念”，它是一个运行时映射表：`task_type -> executor`。  
`registry.get(task_type)` 的用途是：在 worker 执行 `dispatch_task` 时，根据任务类型拿到对应业务执行器。

```python
# executors/base.py
from typing import Protocol, Any


class AsyncTaskExecutor(Protocol):
    task_type: str

    def execute(self, payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        ...

    def is_retryable(self, exc: Exception) -> bool:
        ...
```

```python
# executors/registry.py
from app.features.async_task.executors.base import AsyncTaskExecutor


class UnknownTaskTypeError(RuntimeError):
    def __init__(self, task_type: str) -> None:
        super().__init__(f"unknown task_type: {task_type}")
        self.task_type = task_type


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, AsyncTaskExecutor] = {}

    def register(self, executor: AsyncTaskExecutor) -> None:
        task_type = executor.task_type.strip()
        if not task_type:
            raise ValueError("executor.task_type is empty")
        if task_type in self._executors:
            raise ValueError(f"duplicate executor for task_type={task_type}")
        self._executors[task_type] = executor

    def get(self, task_type: str) -> AsyncTaskExecutor:
        try:
            return self._executors[task_type]
        except KeyError as exc:
            raise UnknownTaskTypeError(task_type) from exc

    def list_types(self) -> list[str]:
        return sorted(self._executors.keys())


registry = ExecutorRegistry()
```

```python
# executors/bootstrap.py（进程启动时调用一次）
from app.features.async_task.executors.registry import registry
from app.features.async_task.executors.import_executors import (
    ImportKnowledgeBaseExecutor,
    ImportSkillExecutor,
    ImportMemoryExecutor,
)


def register_default_executors() -> None:
    registry.register(ImportKnowledgeBaseExecutor())
    registry.register(ImportSkillExecutor())
    registry.register(ImportMemoryExecutor())
```

---

## 7.4 `AsyncTaskRepository` 具体实现（基于 `app/infrastructure/database/base.py`）

`AsyncTaskRepository` 应该和业务一样通过数据库抽象层隔离后端，而不是直接依赖某个数据库 client。

### 7.4.1 在 `base.py` 增加异步任务能力接口

> 推荐方案：在 `IDatabaseWriter` 上增加 async-task 相关方法（或拆成 `IAsyncTaskWriter` 并由 `IDatabaseWriter` 继承）。

```python
# app/infrastructure/database/base.py
from typing import Any, Protocol


class IDatabaseWriter(Protocol):
    # 现有接口（binding/content/file_registry）省略
    # ...

    # async task 新增接口
    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        ...

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def find_async_task_by_idempotency(
        self,
        task_type: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        ...

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        ...
```

### 7.4.2 在 `DatabaseFactory` 增加异步任务 writer 入口

```python
# app/infrastructure/database/factory.py
class DatabaseFactory:
    # ...
    def get_async_task_writer(self) -> IDatabaseWriter:
        # 当前实现可直接复用既有 writer；
        # 若未来 async task 迁移到独立 backend，可在此处切换，不影响业务层。
        return self.get_writer(domain="KNOWLEDGE_BASE")
```

### 7.4.3 在各后端 writer 里实现新增接口

实现约束：

1. OpenSearchWriter 实现：
   - 文档 `_id` 建议 `task::{task_id}`；
   - `update_async_task(..., expected_statuses=...)` 使用 painless 脚本做条件更新；
   - `find_async_task_by_idempotency(...)` 用 `term` 过滤 + `created_at desc`。

2. PostgresWriter 实现：
   - `task_id` 主键；
   - `update_async_task(...expected_statuses...)` 使用 `WHERE status IN (...)` 条件更新；
   - 幂等键可用 `(task_type, idempotency_key)` 唯一约束（非空时）。

### 7.4.4 `AsyncTaskRepository` 只依赖抽象接口

```python
# repository.py
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.database.base import IDatabaseWriter


@dataclass
class AsyncTaskRecord:
    task_id: str
    task_type: str
    status: str
    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    retry_count: int
    max_retries: int
    queue_name: str
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    def to_view(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "result": self.result_json,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class AsyncTaskRepository:
    def __init__(self, writer: IDatabaseWriter) -> None:
        self._writer = writer

    def create_queued(
        self,
        task_id: str,
        task_type: str,
        payload: dict[str, Any],
        queue_name: str,
        max_retries: int,
        idempotency_key: str | None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._writer.create_async_task(
            {
                "task_id": task_id,
                "task_type": task_type,
                "status": "queued",
                "payload_json": payload,
                "result_json": None,
                "error_code": None,
                "error_message": None,
                "retry_count": 0,
                "max_retries": max_retries,
                "queue_name": queue_name,
                "idempotency_key": idempotency_key,
                "worker_id": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
            }
        )

    def find_by_idempotency(self, task_type: str, idempotency_key: str) -> AsyncTaskRecord | None:
        raw = self._writer.find_async_task_by_idempotency(task_type, idempotency_key)
        return self._to_record(raw) if raw else None

    def get(self, task_id: str) -> AsyncTaskRecord | None:
        raw = self._writer.get_async_task(task_id)
        return self._to_record(raw) if raw else None

    def mark_running(self, task_id: str, worker_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        ok = self._writer.update_async_task(
            task_id,
            patch_doc={"status": "running", "worker_id": worker_id, "started_at": now, "updated_at": now},
            expected_statuses=["queued", "retrying"],
        )
        if not ok:
            raise RuntimeError(f"mark_running failed, task_id={task_id}")

    def mark_retrying(self, task_id: str, retry_count: int, countdown_sec: int, err_msg: str) -> None:
        del countdown_sec
        now = datetime.now(UTC).isoformat()
        ok = self._writer.update_async_task(
            task_id,
            patch_doc={
                "status": "retrying",
                "retry_count": retry_count,
                "error_message": err_msg[:2000],
                "updated_at": now,
            },
            expected_statuses=["running"],
        )
        if not ok:
            raise RuntimeError(f"mark_retrying failed, task_id={task_id}")

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        ok = self._writer.update_async_task(
            task_id,
            patch_doc={"status": "completed", "result_json": result, "finished_at": now, "updated_at": now},
            expected_statuses=["running", "retrying"],
        )
        if not ok:
            raise RuntimeError(f"mark_completed failed, task_id={task_id}")

    def mark_failed(self, task_id: str, error_code: str, error_message: str) -> None:
        now = datetime.now(UTC).isoformat()
        ok = self._writer.update_async_task(
            task_id,
            patch_doc={
                "status": "failed",
                "error_code": error_code,
                "error_message": error_message[:2000],
                "finished_at": now,
                "updated_at": now,
            },
            expected_statuses=["running", "retrying", "queued"],
        )
        if not ok:
            raise RuntimeError(f"mark_failed failed, task_id={task_id}")

    def mark_cancelled(self, task_id: str, reason: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._writer.update_async_task(
            task_id,
            patch_doc={"status": "cancelled", "error_message": reason[:2000], "finished_at": now, "updated_at": now},
            expected_statuses=["queued", "retrying", "running"],
        )

    def get_max_retries(self, task_id: str, default_value: int) -> int:
        record = self.get(task_id)
        if not record:
            return default_value
        return int(record.max_retries or default_value)

    def _to_record(self, raw: dict[str, Any]) -> AsyncTaskRecord:
        return AsyncTaskRecord(
            task_id=str(raw.get("task_id", "")),
            task_type=str(raw.get("task_type", "")),
            status=str(raw.get("status", "")),
            payload_json=raw.get("payload_json") or {},
            result_json=raw.get("result_json"),
            error_code=raw.get("error_code"),
            error_message=raw.get("error_message"),
            retry_count=int(raw.get("retry_count", 0) or 0),
            max_retries=int(raw.get("max_retries", 0) or 0),
            queue_name=str(raw.get("queue_name", "")),
            idempotency_key=raw.get("idempotency_key"),
            created_at=self._parse_dt(raw.get("created_at")),
            updated_at=self._parse_dt(raw.get("updated_at")),
            started_at=self._parse_dt_opt(raw.get("started_at")),
            finished_at=self._parse_dt_opt(raw.get("finished_at")),
        )

    def _parse_dt(self, value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _parse_dt_opt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
```

---

## 7.5 通用派发任务（`tasks/dispatch_task.py`）

```python
import random
from celery import Task
from app.core.config_manager import ConfigManager
from app.infrastructure.database.factory import DatabaseFactory
from app.features.async_task.celery_app import celery_app
from app.features.async_task.repository import AsyncTaskRepository
from app.features.async_task.executors.registry import registry, UnknownTaskTypeError
from app.features.async_task.errors import NonRetryableError
from app.features.async_task.settings import AsyncTaskSettings

settings = AsyncTaskSettings()
cfg = ConfigManager()
db_writer = DatabaseFactory(cfg).get_async_task_writer()


def backoff(retry_count: int) -> int:
    delay = settings.backoff_base_seconds * (settings.backoff_factor ** (retry_count - 1))
    return int(delay + random.randint(0, settings.backoff_jitter_seconds))


@celery_app.task(bind=True, name="async.dispatch", acks_late=True)
def dispatch_task(self: Task, task_type: str, payload: dict, task_id: str) -> dict:
    repo = AsyncTaskRepository(writer=db_writer)

    # 防御性检查：提交时 task_id 与运行时 request.id 一致
    runtime_id = str(self.request.id or "")
    if runtime_id and runtime_id != task_id:
        repo.mark_failed(task_id, "TASK_ID_MISMATCH", f"runtime={runtime_id}, payload={task_id}")
        raise RuntimeError("task_id mismatch")

    repo.mark_running(task_id, worker_id=self.request.hostname or "unknown")

    try:
        executor = registry.get(task_type)
        result = executor.execute(payload, {"task_id": task_id, "retries": self.request.retries or 0})
        repo.mark_completed(task_id, result)
        return result
    except UnknownTaskTypeError as exc:
        repo.mark_failed(task_id, "UNKNOWN_TASK_TYPE", str(exc))
        raise
    except NonRetryableError as exc:
        repo.mark_failed(task_id, error_code=exc.code, error_message=str(exc))
        raise
    except Exception as exc:
        retry_count = (self.request.retries or 0) + 1
        max_retries = repo.get_max_retries(task_id, settings.default_max_retries)
        if executor.is_retryable(exc) and retry_count <= max_retries:
            countdown = backoff(retry_count)
            repo.mark_retrying(task_id, retry_count, countdown, str(exc))
            raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)
        repo.mark_failed(task_id, error_code="TASK_EXEC_FAILED", error_message=str(exc))
        raise
```

---

## 7.6 `dispatch_task.apply_async` 到底是不是对的

是对的，不是瞎写。  
原因：被 `@celery_app.task(...)` 修饰后，`dispatch_task` 在运行时是 Celery Task 对象（或其代理），因此有 `delay/apply_async/signature` 等方法。

但是为了可读性和减少“函数 vs Task 对象”的歧义，文档建议提交侧统一写成 `celery_app.send_task(...)`。

等价写法有三种：

1. `dispatch_task.apply_async(...)`（可用）
2. `dispatch_task.s(...).apply_async(...)`（可用，显式 signature）
3. `celery_app.send_task("async.dispatch", ...)`（推荐，最清晰）

---

## 7.7 提交任务（`service.py`）

```python
import uuid
from app.core.config_manager import ConfigManager
from app.infrastructure.database.factory import DatabaseFactory
from app.features.async_task.celery_app import celery_app
from app.features.async_task.routing import route_queue
from app.features.async_task.repository import AsyncTaskRepository


class AsyncTaskService:
    def __init__(self) -> None:
        cfg = ConfigManager()
        db_writer = DatabaseFactory(cfg).get_async_task_writer()
        self.repo = AsyncTaskRepository(writer=db_writer)

    def submit(self, task_type: str, payload: dict, max_retries: int = 3, idempotency_key: str | None = None) -> dict:
        if idempotency_key:
            existed = self.repo.find_by_idempotency(task_type, idempotency_key)
            if existed:
                return existed.to_view()

        task_id = str(uuid.uuid4())
        queue_name = route_queue(task_type)
        self.repo.create_queued(task_id, task_type, payload, queue_name, max_retries, idempotency_key)

        celery_app.send_task(
            "async.dispatch",
            args=[task_type, payload, task_id],
            task_id=task_id,
            queue=queue_name,
        )
        return self.repo.get(task_id).to_view()
```

---

## 7.8 查询与取消（`service.py`）

```python
from celery.result import AsyncResult
from app.features.async_task.celery_app import celery_app


class AsyncTaskService:
    # ...
    def get(self, task_id: str) -> dict:
        record = self.repo.get(task_id)
        if not record:
            raise KeyError("TASK_NOT_FOUND")

        celery_state = AsyncResult(task_id, app=celery_app).state
        return {
            **record.to_view(),
            "celery_state": celery_state,  # 仅做诊断，业务状态仍以 repository 为准
        }

    def cancel(self, task_id: str, force_terminate: bool = False) -> bool:
        record = self.repo.get(task_id)
        if not record:
            return False

        AsyncResult(task_id, app=celery_app).revoke(terminate=force_terminate)
        self.repo.mark_cancelled(task_id, reason="cancelled by user")
        return True
```

---

## 8. import 接入方式（示例）

任务类型：

- `import.knowledge_base`
- `import.skill`
- `import.memory`

导入 API 流程：

1. 先执行 `stage_upload_files` + `build_parse_manifest`。
2. 调用 `AsyncTaskService.submit(task_type="import.skill", payload=...)`。
3. API 返回 `202 + task_id`。
4. Worker 里 `ImportSkillExecutor.execute(...)` 调用 `SkillUploadService.execute_task(...)`。

执行器示例：

```python
class ImportSkillExecutor:
    task_type = "import.skill"

    def execute(self, payload: dict, ctx: dict) -> dict:
        return SkillUploadService().execute_task(payload["task_payload"])

    def is_retryable(self, exc: Exception) -> bool:
        return isinstance(exc, (TimeoutError, ConnectionError))
```

---

## 9. 运行与部署

## 9.1 为什么 `app.py` 不能替代 Celery worker

在 Celery 架构中，`app.py`（如 `uvicorn app:app`）启动的是 Web 进程，职责是接收请求并投递任务；  
异步任务真正执行发生在 Celery worker 进程中。

也就是说：

1. `app.py` 是 producer（生产任务）。
2. `celery worker` 是 consumer（消费任务）。

两者可以部署在同一机器，但通常是两个独立进程。  
例外是测试/本地调试设置 `task_always_eager=true`，这时任务在请求进程内同步执行，可不单独启动 worker（但这不是生产形态）。

## 9.2 启动 worker

启动 worker：

```bash
celery -A app.features.async_task.celery_app:celery_app worker -l INFO -Q async.default,import,search --concurrency=4
```

## 9.3 启动 beat（可选）

启动 beat（可选）：

```bash
celery -A app.features.async_task.celery_app:celery_app beat -l INFO
```

## 9.4 本地内存模式（无 Redis）

本地内存模式（无 Redis）：

```env
CELERY_BROKER_URL=memory://
CELERY_RESULT_BACKEND=cache+memory://
```

## 9.5 生产模式（示例）

生产模式（示例）：

```env
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
```

---

## 10. 关键工程约束

- `payload` 只传元数据与路径，不传大文件二进制。
- 外部副作用操作必须使用 `task_id` 做幂等键。
- 默认软取消，强制终止只对管理接口开放。
- 队列按业务隔离（`import`/`search`）避免互相拖慢。
- 保留 `staged/` 清理与失败保留策略（沿用现有 import 设计）。

---

## 11. 验收清单

1. API 提交后毫秒级返回 `202`，不阻塞业务线程。
2. 任务状态可完整流转：`queued -> running -> retrying/completed/failed/cancelled`。
3. 重试行为符合 backoff 规则并可观测。
4. `idempotency_key` 生效，不重复创建任务。
5. 三域 import 可通过同一异步机制执行。
6. 内存模式可本地跑通，生产模式只改配置即可切换。
