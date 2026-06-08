# MEMORY Download 详细开发指南（v4）

本文档给出 MEMORY 下载链路的落地实现方案，覆盖：

- 单文件下载任务提交（异步）
- 批量下载任务提交（异步）
- Celery Worker 执行与 artifact 生成
- artifact 拉取、过期控制与清理
- 错误码与测试清单

---

## 1. 适用范围

- 覆盖以下接口：
  - `POST /api/download/memory/file`
  - `POST /api/download/memory/batch`
  - `GET /api/download/memory/artifact/{artifact_id}`
- `tag` 固定为 `memory`。
- 单文件和批量都通过通用异步任务层执行。
- `by-search` 下载不在本篇范围内（后续演进）。

---

## 2. 组件清单（建议）

1. `app/api/download/memory_download_api.py`（`MemoryDownloadAPI`）
2. `app/features/async_task/service.py`（`AsyncTaskService`）
3. `app/features/async_task/tasks/dispatch_task.py`（`dispatch_task`）
4. `app/features/async_task/executors/registry.py`（执行器路由注册）
5. `app/features/async_task/executors/download_task_executor.py`（`DownloadTaskExecutor`）
6. `app/features/download/memory_download/memory_download_service.py`（`MemoryDownloadService`）
7. `app/features/download/common/artifact_store.py`（`DownloadArtifactStore`）
8. `app/features/download/common/zip_builder.py`（`DownloadZipBuilder`）
9. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
10. `app/infrastructure/database/base.py`（`IDatabaseWriter`）
11. `app/infrastructure/file_system/factory.py`（`FileSystemFactory`）
12. `app/infrastructure/file_system/base.py`（`IFileSystemGateway`）

---

## 3. 关键类型定义（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

@dataclass
class MemorySingleDownloadPayload:
    tag: Literal["memory"]
    storage_path: str
    download_name: str | None

@dataclass
class MemoryBatchDownloadPayload:
    tag: Literal["memory"]
    storage_paths: list[str]
    package_name: str | None
    include_metadata: bool

@dataclass
class ArtifactMeta:
    artifact_id: str
    artifact_name: str
    content_type: str
    storage_path: str
    size_bytes: int
    expires_at: str
    domain: Literal["MEMORY"]
    task_id: str
```

约束：

- `storage_path` 必须是导入阶段已注册路径。
- 禁止绝对路径和 `..` 等越界路径。
- `artifact_id` 与任务结果保持可追溯关联。

---

## 4. API 层实现（`MemoryDownloadAPI`）

文件：`app/api/download/memory_download_api.py`

建议接口：

```python
async def submit_memory_file_download(
    tag: str,
    storage_path: str,
    download_name: str | None = None,
) -> dict[str, Any]: ...

async def submit_memory_batch_download(
    tag: str,
    storage_paths: list[str],
    package_name: str | None = None,
    include_metadata: bool = False,
) -> dict[str, Any]: ...

async def fetch_memory_download_artifact(artifact_id: str) -> Any: ...
```

### 4.1 任务提交接口（`file/batch`）

通用流程：

1. 参数校验（tag、路径列表、数量上限）。
2. 强校验 `tag == "memory"`。
3. 调用 `AsyncTaskService.submit(...)`：
   - 单文件：`task_type="download.memory.file"`
   - 批量：`task_type="download.memory.batch"`
4. 返回 `202 + task_id + status=queued`。

### 4.2 artifact 拉取接口

流程：

1. `DownloadArtifactStore.get(artifact_id)` 获取元信息。
2. 校验 domain 是否为 `MEMORY`、artifact 是否过期。
3. 使用 `open_read(storage_path)` 读取文件流并返回。

---

## 5. 异步调度与执行器实现

### 5.1 任务类型注册

建议在 `registry.py` 注册：

- `download.memory.file` -> `DownloadTaskExecutor`
- `download.memory.batch` -> `DownloadTaskExecutor`

### 5.2 `DownloadTaskExecutor` 路由

```python
def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
```

内部映射：

- `download.memory.file` -> `MemoryDownloadService.execute_single_task(...)`
- `download.memory.batch` -> `MemoryDownloadService.execute_batch_task(...)`

---

## 6. 服务层实现（`MemoryDownloadService`）

文件：`app/features/download/memory_download/memory_download_service.py`

建议接口：

```python
def execute_single_task(self, task_id: str, payload: MemorySingleDownloadPayload) -> dict[str, Any]: ...
def execute_batch_task(self, task_id: str, payload: MemoryBatchDownloadPayload) -> dict[str, Any]: ...
def validate_memory_tag(self, tag: str) -> None: ...
def resolve_binding(self, tag: str) -> dict[str, Any]: ...
def resolve_registered_files(self, kb_index: str, storage_paths: list[str]) -> list[dict[str, Any]]: ...
```

### 6.1 单文件任务流程

1. `validate_memory_tag(tag)`。
2. `resolve_binding(tag)` 获取 `kb_index`。
3. 在 file registry 中按 `kb_index + storage_path` 查询记录。
4. 校验物理文件存在。
5. 生成单文件 artifact 并返回结果。

### 6.2 批量任务流程

1. 校验 `tag` 与批量数量限制。
2. 去重 `storage_paths`，避免重复打包。
3. 批量查询 file registry，校验归属与存在性。
4. 构建 ZIP artifact。
5. 写入 artifact 元信息，返回任务结果。

---

## 7. MEMORY 域特有约束

MEMORY 导入中通常把附件路径回填到 `metadata.related_storage_paths`；下载侧需兼容以下事实：

- 检索结果返回的路径可能来自同一 memory 记录的多个附件。
- 一个附件可被多个 memory 语义文档引用。
- 下载侧以“路径注册表”为准，不依赖 `memory_id` 唯一性。

建议在 `include_metadata=true` 时输出更丰富清单（可选）：

- `memory_id`
- `title`
- `task_ids`
- `feature_tags/domain_tags/component_tags`

以上字段若 file registry 不直接保存，可通过业务索引补查；无法补齐时可省略，不影响主流程。

---

## 8. Artifact 存储与生命周期

### 8.1 存储建议

- artifact 路径建议：
  - `download_artifacts/MEMORY/{yyyy-mm-dd}/{task_id}/{artifact_name}`
- 与导入附件目录隔离，避免误删影响原始数据。

### 8.2 生命周期管理

- `expires_at` 由配置统一控制。
- 拉取时实时判断是否过期。
- 定时清理过期 artifact 与元信息。

### 8.3 幂等建议

- 任务重试时建议复用同一个 `artifact_id`，避免并发重试产生多个可见产物。
- 若采用“新建覆盖”策略，必须保证最终只保留最后一次成功产物。

---

## 9. `DownloadZipBuilder`（批量）建议

建议与 SKILL 完全复用同一实现，不在 MEMORY 域分叉。

关键点：

- 重名文件自动重命名。
- 可选 `metadata.json`。
- 打包时记录每个输入项的处理状态，便于失败排障。

---

## 10. 响应与任务结果组装规则

### 10.1 提交响应

```json
{
  "success": true,
  "task_id": "download_20260506_101",
  "domain": "MEMORY",
  "tag": "memory",
  "status": "queued"
}
```

### 10.2 任务完成结果

```json
{
  "task_id": "download_20260506_101",
  "status": "completed",
  "result": {
    "artifact_id": "dl_artifact_a1c9e0",
    "artifact_name": "memory_bundle_20260506.zip",
    "content_type": "application/zip",
    "size_bytes": 95611,
    "expires_at": "2026-05-07T08:00:00Z",
    "item_count": 6
  }
}
```

---

## 11. 错误码建议（下载侧）

- `INVALID_ARGUMENT`
- `TAG_INVALID`
- `INDEX_NOT_BOUND`
- `FILE_REGISTRY_NOT_FOUND`
- `FILE_NOT_FOUND`
- `DOWNLOAD_LIMIT_EXCEEDED`
- `ZIP_BUILD_FAILED`
- `DOWNLOAD_ARTIFACT_NOT_FOUND`
- `DOWNLOAD_ARTIFACT_EXPIRED`
- `INTERNAL_ERROR`

说明：

- 语义与 `02_API接口文档.md` 保持一致，避免域间重复定义。

---

## 12. 测试清单（建议）

1. `tag=memory` 的单文件任务提交成功，返回 `202`
2. `tag!=memory` 返回 `TAG_INVALID`
3. 单文件路径未注册返回 `FILE_REGISTRY_NOT_FOUND`
4. 单文件路径注册但文件缺失返回 `FILE_NOT_FOUND`
5. 批量路径为空返回 `INVALID_ARGUMENT`
6. 批量路径超上限返回 `DOWNLOAD_LIMIT_EXCEEDED`
7. 批量 ZIP 构建成功并返回有效 artifact 元信息
8. `include_metadata=true` 时附带 metadata 清单
9. artifact 拉取成功返回正确响应头
10. artifact 不存在返回 `DOWNLOAD_ARTIFACT_NOT_FOUND`
11. artifact 过期返回 `DOWNLOAD_ARTIFACT_EXPIRED`
12. 过期清理后无法再次拉取
13. Worker 重试后状态与结果一致，无重复可见 artifact
