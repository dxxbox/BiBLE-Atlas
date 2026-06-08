# SKILL Download 详细开发指南（v4）

本文档给出 SKILL 下载链路的落地实现方案，覆盖：

- 单文件下载任务提交（异步）
- 批量下载任务提交（异步）
- Celery Worker 执行与 artifact 生成
- artifact 拉取与过期清理
- 错误码与测试清单

---

## 1. 适用范围

- 覆盖以下接口：
  - `POST /api/download/skill/file`
  - `POST /api/download/skill/batch`
  - `GET /api/download/skill/artifact/{artifact_id}`
- `tag` 固定为 `skill`。
- 单文件和批量都通过 `features/async_task` 提交异步任务，不在请求线程直接返回文件流。
- `by-search` 下载不在本篇范围内（见 `06_未来演进规划.md`）。

---

## 2. 组件清单（建议）

1. `app/api/download/skill_download_api.py`（`SkillDownloadAPI`）
2. `app/features/async_task/service.py`（`AsyncTaskService`）
3. `app/features/async_task/tasks/dispatch_task.py`（`dispatch_task`）
4. `app/features/async_task/executors/registry.py`（执行器路由注册）
5. `app/features/async_task/executors/download_task_executor.py`（`DownloadTaskExecutor`）
6. `app/features/download/skill_download/skill_download_service.py`（`SkillDownloadService`）
7. `app/features/download/common/artifact_store.py`（`DownloadArtifactStore`）
8. `app/features/download/common/zip_builder.py`（`DownloadZipBuilder`）
9. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
10. `app/infrastructure/database/base.py`（`IDatabaseWriter`）
11. `app/infrastructure/file_system/factory.py`（`FileSystemFactory`）
12. `app/infrastructure/file_system/base.py`（`IFileSystemGateway`）
13. `app/infrastructure/file_system/local.py`（`LocalFileSystemGateway`）

---

## 3. 关键类型定义（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

DownloadTaskType = Literal["download.skill.file", "download.skill.batch"]

@dataclass
class SkillSingleDownloadPayload:
    tag: Literal["skill"]
    storage_path: str
    download_name: str | None

@dataclass
class SkillBatchDownloadPayload:
    tag: Literal["skill"]
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
    domain: Literal["SKILL"]
    task_id: str
```

补充约束：

- 下载任务 payload 内 `tag` 必须固定为 `skill`。
- `storage_path` 必须是逻辑路径（相对路径），禁止绝对路径和目录穿越。
- `artifact_id` 与 `task_id` 建议一一关联，便于审计和排障。

---

## 4. API 层实现（`SkillDownloadAPI`）

文件：`app/api/download/skill_download_api.py`

建议接口：

```python
async def submit_skill_file_download(
    tag: str,
    storage_path: str,
    download_name: str | None = None,
) -> dict[str, Any]: ...

async def submit_skill_batch_download(
    tag: str,
    storage_paths: list[str],
    package_name: str | None = None,
    include_metadata: bool = False,
) -> dict[str, Any]: ...

async def fetch_skill_download_artifact(artifact_id: str) -> Any: ...
```

### 4.1 任务提交接口（`file/batch`）

通用流程：

1. 参数校验（`tag`、路径格式、数量上限、可选文件名）。
2. 强校验 `tag == "skill"`。
3. 调用 `AsyncTaskService.submit(...)`：
   - 单文件：`task_type="download.skill.file"`
   - 批量：`task_type="download.skill.batch"`
4. 返回 `202 + task_id + status=queued`。

### 4.2 artifact 拉取接口（`GET /artifact/{artifact_id}`）

流程：

1. 通过 `DownloadArtifactStore.get(artifact_id)` 读取元信息。
2. 校验 domain、过期时间、状态（可拉取）。
3. 通过 `IFileSystemGateway.open_read(storage_path)` 打开流。
4. 返回流式响应并设置：
   - `Content-Type`
   - `Content-Disposition`
   - `Content-Length`（可选）

---

## 5. 异步调度与执行器实现

### 5.1 任务类型注册

建议在 `registry.py` 注册：

- `download.skill.file` -> `DownloadTaskExecutor`
- `download.skill.batch` -> `DownloadTaskExecutor`

### 5.2 `DownloadTaskExecutor` 建议接口

```python
def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
```

内部路由：

- `download.skill.file` -> `SkillDownloadService.execute_single_task(...)`
- `download.skill.batch` -> `SkillDownloadService.execute_batch_task(...)`

### 5.3 任务结果约定

执行成功返回：

```json
{
  "artifact_id": "dl_artifact_9d7c1a",
  "artifact_name": "skill_bundle_20260506.zip",
  "content_type": "application/zip",
  "size_bytes": 128734,
  "expires_at": "2026-05-07T08:00:00Z",
  "item_count": 4
}
```

---

## 6. 服务层实现（`SkillDownloadService`）

文件：`app/features/download/skill_download/skill_download_service.py`

建议接口：

```python
def execute_single_task(self, task_id: str, payload: SkillSingleDownloadPayload) -> dict[str, Any]: ...
def execute_batch_task(self, task_id: str, payload: SkillBatchDownloadPayload) -> dict[str, Any]: ...
def validate_skill_tag(self, tag: str) -> None: ...
def resolve_binding(self, tag: str) -> dict[str, Any]: ...
def resolve_registered_files(self, kb_index: str, storage_paths: list[str]) -> list[dict[str, Any]]: ...
```

### 6.1 单文件任务流程

1. `validate_skill_tag(tag)`。
2. `resolve_binding(tag)` 获取 `kb_index`（`domain=SKILL`）。
3. 调用文件注册查询接口校验 `storage_path` 属于该 `kb_index`。
4. 校验物理文件存在（`file_system.exists`）。
5. 生成单文件 artifact（可选重命名）。
6. 写入 artifact 元信息并返回任务结果。

### 6.2 批量任务流程

1. `validate_skill_tag(tag)`。
2. `resolve_binding(tag)`。
3. 校验 `storage_paths` 非空、去重后数量不超过上限。
4. 批量查询 file registry 并校验归属。
5. 校验每个物理文件存在。
6. 调用 `DownloadZipBuilder` 打包生成 ZIP artifact。
7. 写入 artifact 元信息并返回任务结果。

---

## 7. 数据读取与一致性约束

下载侧依赖 import 写入的两类数据：

1. **绑定记录**（`domain + tag -> kb_index`）
2. **文件注册表**（`kb_index + storage_path` 对应文件元数据）

### 7.1 建议新增的数据库读接口

`IDatabaseWriter`（或独立 Reader 接口）建议新增：

```python
def get_file_registry_by_storage_paths(self, index: str, storage_paths: list[str]) -> list[dict[str, Any]]: ...
def get_file_registry_by_storage_path(self, index: str, storage_path: str) -> dict[str, Any] | None: ...
```

语义要求：

- 只返回当前索引的有效记录。
- 批量接口必须能识别“部分缺失”场景并返回可诊断信息。

### 7.2 路径与归属校验

- 必须先校验注册记录归属，再访问文件系统。
- 禁止直接信任调用方传入路径访问磁盘。
- 若注册存在但文件缺失，返回 `FILE_NOT_FOUND`（不是 `FILE_REGISTRY_NOT_FOUND`）。

---

## 8. Artifact 存储与生命周期

### 8.1 `DownloadArtifactStore` 建议接口

```python
def create_from_single_file(
    self,
    task_id: str,
    domain: str,
    source_storage_path: str,
    artifact_name: str,
    expires_at: str,
) -> ArtifactMeta: ...

def create_from_zip_bytes(
    self,
    task_id: str,
    domain: str,
    zip_bytes: bytes,
    artifact_name: str,
    expires_at: str,
) -> ArtifactMeta: ...

def get(self, artifact_id: str) -> ArtifactMeta | None: ...
def sweep_expired(self, now_iso: str, limit: int = 1000) -> int: ...
```

### 8.2 路径建议

artifact 文件建议按如下路径分层：

- `download_artifacts/SKILL/{yyyy-mm-dd}/{task_id}/{artifact_name}`

说明：

- 与导入附件存储路径隔离，避免相互影响。
- artifact 仅用于下载交付，不回写业务索引。

### 8.3 过期策略

- 过期时间建议由配置控制（如 `download.artifact_ttl_hours`）。
- API 拉取时做实时过期判断。
- 定时任务调用 `sweep_expired(...)` 删除过期 artifact。

---

## 9. `DownloadZipBuilder` 实现建议

文件：`app/features/download/common/zip_builder.py`

建议接口：

```python
def build_zip(
    self,
    items: list[dict[str, Any]],
    package_name: str,
    include_metadata: bool,
) -> tuple[bytes, int]:
    ...
```

关键要求：

- ZIP 内文件名冲突时自动重命名（例如追加序号）。
- 支持可选 `metadata.json`，记录每个文件的：
  - `storage_path`
  - `filename`
  - `size_bytes`
  - `file_hash`
- ZIP 构建失败返回 `ZIP_BUILD_FAILED`。

---

## 10. 响应与任务结果组装规则

### 10.1 提交响应（同步返回）

```json
{
  "success": true,
  "task_id": "download_20260506_001",
  "domain": "SKILL",
  "tag": "skill",
  "status": "queued"
}
```

### 10.2 完成结果（任务查询返回）

```json
{
  "task_id": "download_20260506_001",
  "status": "completed",
  "result": {
    "artifact_id": "dl_artifact_9d7c1a",
    "artifact_name": "skill_bundle_20260506.zip",
    "content_type": "application/zip",
    "size_bytes": 128734,
    "expires_at": "2026-05-07T08:00:00Z",
    "item_count": 4
  }
}
```

---

## 11. 错误码建议（下载侧）

- `INVALID_ARGUMENT`：参数错误（空路径、批量为空、名称非法）
- `TAG_INVALID`：`tag != "skill"`
- `INDEX_NOT_BOUND`：未找到 `SKILL` 绑定
- `FILE_REGISTRY_NOT_FOUND`：指定路径未注册到索引
- `FILE_NOT_FOUND`：注册存在但物理文件不存在
- `DOWNLOAD_LIMIT_EXCEEDED`：批量数量超过上限
- `ZIP_BUILD_FAILED`：批量打包失败
- `DOWNLOAD_ARTIFACT_NOT_FOUND`：artifact 不存在
- `DOWNLOAD_ARTIFACT_EXPIRED`：artifact 已过期
- `INTERNAL_ERROR`：未知内部错误

---

## 12. 测试清单（建议）

1. `tag=skill` 的单文件任务提交成功，返回 `202 + task_id`
2. `tag!=skill` 被拒绝并返回 `TAG_INVALID`
3. 单文件路径未注册返回 `FILE_REGISTRY_NOT_FOUND`
4. 单文件注册存在但文件丢失返回 `FILE_NOT_FOUND`
5. 批量路径列表去重后超上限返回 `DOWNLOAD_LIMIT_EXCEEDED`
6. 批量任务正常产出 ZIP artifact，结果包含 `artifact_id/expires_at`
7. `include_metadata=true` 时 ZIP 内包含 `metadata.json`
8. ZIP 内重名文件处理正确（不覆盖）
9. artifact 拉取成功返回流与正确 `Content-Disposition`
10. artifact 不存在返回 `DOWNLOAD_ARTIFACT_NOT_FOUND`
11. artifact 过期返回 `DOWNLOAD_ARTIFACT_EXPIRED`
12. 过期清理任务可删除超期 artifact
13. 任务状态流转正确（`queued -> running -> completed/failed`）
14. 重试场景下任务结果最终一致（不会生成重复可见 artifact）
