# MEMORY Import 详细开发指南（v4）

本文档对应流程图：`import_pumls/memory_import_flow.puml`。  
目标是把 MEMORY 导入流程中的类与接口做落地实现说明。

---

## 1. 适用范围

- 仅覆盖 `POST /api/import/memory`。
- 包括：
  - 启动时向量预加载
  - 上传文件校验与任务入队
  - MEMORY 专属解析脚本链路
  - 原始文件落盘（`meta.json` + 其他附件）
  - `parse_memory.py` 基于 manifest 处理整批上传并区分 `meta.json`/附件
  - 绑定读写
  - 向量化（可选）
  - 内容写库（`meta.json` 语义 chunk）
  - 按解析结果执行附件本地存储计划

---

## 2. 组件清单

1. `app/main.py`（`AppStartup`）
2. `app/config/config_manager.py`（`ConfigManager`）
3. `app/infrastructure/vector/model_preloader.py`（`VectorModelPreloader`）
4. `app/infrastructure/vector/vector_tool.py`（`VectorTool`）
5. `app/api/import/memory_import_api.py`（`MemoryImportAPI`）
6. `app/features/async_task/service.py`（`AsyncTaskService`）
7. `app/features/async_task/tasks/dispatch_task.py`（`dispatch_task`）
8. `app/features/import/import_task_executor.py`（`ImportTaskExecutor`）
9. `app/features/import/memory_import/memory_import_service.py`（`MemoryImportService`）
10. `app/features/import/parser_runtime/ast_guard.py`（`ASTGuard`）
11. `app/features/import/parser_runtime/sandbox_runner.py`（`SandboxRunner`）
12. `app/features/import/memory_import/storage/store_memory.py`（`StoreMemory`）
13. `app/infrastructure/file_system/factory.py`（`FileSystemFactory`）
14. `app/infrastructure/file_system/base.py`（`IFileSystemGateway`）
15. `app/infrastructure/file_system/local.py`（`LocalFileSystemGateway`）
16. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
17. `app/infrastructure/database/base.py`（`IDatabaseWriter`）
18. `app/infrastructure/database/opensearch/writer.py`（`OpenSearchWriter`）

---

## 3. 类型定义（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

@dataclass
class MemoryImportPayload:
    kb_index: str
    tag: Literal["memory"]
    vector_model: str | None
    parser_context: dict[str, Any] | None

@dataclass
class FileStoreResult:
    filename: str
    storage_path: str
    file_hash: str
    size_bytes: int

@dataclass
class ParseResult:
    chunks: list[dict[str, Any]]
    search_profile: dict[str, Any]
    local_file_storage_plan: dict[str, Any] | None
```

注意点：
- `tag` 必须固定为 `memory`。
- MEMORY 流程和 SKILL 结构相同，但 domain、默认脚本和注册语义不同。

---

## 4. 启动流程实现

### 4.1 `AppStartup`

```python
def bootstrap() -> None: ...
```

内部步骤：
1. `ConfigManager.initialize()`
2. `ConfigManager.get_bool("vector.preload_on_startup")`
3. 条件触发 `VectorModelPreloader.preload_all_models_async()`

### 4.2 `VectorModelPreloader` + `VectorTool`

```python
def preload_all_models_async(self) -> None: ...
def ensure_model_ready(self, model_name: str) -> dict[str, Any]: ...
def download_from_huggingface(self, model_name: str) -> str: ...
```

实现参考（当前工程）：
- `x_logic/model_preloader.py`
- `x_data/vector_generator.py`

---

## 5. API 层实现

文件：`app/api/import/memory_import_api.py`

```python
async def import_memory(
    files: list[UploadFile],
    kb_index: str,
    tag: str,
    parser_script: UploadFile | None,
    vector_model: str | None,
    parser_context: str | None,
) -> dict[str, Any]: ...
```

参数说明：
- `files`: 必填
- `kb_index`: 必填
- `tag`: 必须为 `memory`
- `parser_script`: 可选
- `vector_model`: 可选
- `parser_context`: 可选 JSON

内部逻辑：
1. 获取 `import.memory.upload` 限制并校验
2. 强校验 `tag == "memory"`
3. 通过 `AsyncTaskService.submit(task_type="import.memory", ...)` 创建异步任务并返回 `202`

---

## 6. 异步调度与服务层实现

### 6.1 通用异步调度（Celery）

涉及文件：

- `app/features/async_task/service.py`
- `app/features/async_task/tasks/dispatch_task.py`
- `app/features/import/import_task_executor.py`

建议接口：

```python
# app/features/async_task/service.py
def submit(self, task_type: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]: ...
def get(self, task_id: str) -> dict[str, Any] | None: ...
def cancel(self, task_id: str) -> dict[str, Any]: ...

# app/features/import/import_task_executor.py
def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
```

调度关系：

1. API 提交 `task_type=import.memory` 到 `AsyncTaskService`。
2. `dispatch_task` 在 Celery Worker 进程中消费并分发给 `ImportTaskExecutor`。
3. `ImportTaskExecutor` 调用 `MemoryImportService.execute_task(...)` 完成导入。
4. 状态机统一由通用异步层维护（`queued/running/completed/failed/cancelled`）。

### 6.2 `MemoryImportService`

```python
def execute_task(self, task_id: str, payload: MemoryImportPayload, files: list[Any]) -> None: ...
def save_uploaded_parser(self, parser_script: Any, parsers_dir: str, target_name: str = "parse_memory.py") -> str: ...
def validate_parse_result_schema(self, result: ParseResult) -> None: ...
def merge_chunks_and_check_profile_consistency(self, all_results: list[ParseResult]) -> ParseResult: ...
def cleanup_staged_workspace(self, task_id: str, keep_failed_workspace: bool) -> None: ...
```

调用关系（`memory_import_service.py` 内）：

- `execute_task`（对外入口）：
  1. 选择并保存最终解析脚本（必要时调用 `save_uploaded_parser`）
  2. 调用 `ASTGuard.validate(...)`
  3. 调用 `StoreMemory.stage_upload_files(...)`
  4. 调用 `StoreMemory.build_parse_manifest(...)`
  5. 调用 `SandboxRunner.run_parse(...)`
  6. 调用 `validate_parse_result_schema(...)`
  7. 调用 `StoreMemory.store(...)`（存储总入口）
  8. 在 `finally` 调用 `cleanup_staged_workspace(...)`（内部委托 `StoreMemory.cleanup_task_workspace(...)`）
- `save_uploaded_parser`：仅由 `execute_task` 调用
- `validate_parse_result_schema`：仅由 `execute_task` 调用，校验 `chunks/search_profile/local_file_storage_plan`
- `merge_chunks_and_check_profile_consistency`：兼容保留；当前 MEMORY 默认单次 parse，可不经过多结果合并
- `cleanup_staged_workspace`：仅由 `execute_task` 的 `finally` 调用，封装 `StoreMemory.cleanup_task_workspace(...)` 并处理失败保留策略

关键逻辑：

1. **脚本选择**
   - 上传脚本 -> `parsers/parse_memory.py`
   - 否则查 `parsers/parse_memory.py`
   - 否则回退 `parsers/parse_default.py`
   - 均无 -> `PARSER_SCRIPT_NOT_FOUND`

2. **安全检查**
   - `ASTGuard.validate(script_path)` 不通过直接失败

3. **临时落地 + manifest 构建**
   - 将上传文件先落到任务工作目录（临时区）
   - 生成 `memory_request_manifest.json`

4. **解析执行（全量入口）**
   - `SandboxRunner.run_parse(manifest_path, parser_context)`
   - `parse_memory.py` 内部完成 `meta.json`/附件分类
   - 返回 `chunks/search_profile/local_file_storage_plan`
   - 校验 `ParseResult` 契约

5. **调用 `store_memory` 总入口**
   - `store_memory.store(kb_index, parse_result, vector_model, ...)`
   - `store_memory` 内部必须按顺序执行：
     1. 执行 `local_file_storage_plan`（附件本地存储）
     2. 回填 `chunk.metadata.related_storage_paths`
     3. 查询/创建绑定
     4. 可选向量化
     5. 写内容索引（`meta.json` 语义 chunk）
   - MEMORY 的语义内容来自 `meta.json`；附件不生成内容 chunk

6. **staging 目录清理（新增约束）**
   - `execute_task(...)` 必须使用 `try/except/finally`；`finally` 中执行清理，不能因异常跳过
   - 清理目标建议为整任务目录：`<import_work_root>/<task_id>/`（包含 `staged/` 与 `memory_request_manifest.json`）
   - 默认策略：成功/失败都清理，避免临时文件长期堆积
   - 可配置失败保留：`import.memory.staging.keep_failed_workspace=true` 时，失败任务保留目录用于排障
   - 必须提供 TTL 兜底清理任务：周期扫描并删除超过保留时长（例如 24h）的遗留任务目录

注意点：
- 文件落盘路径建议按 `domain/kb_index/date/task_id` 分层，降低目录热点。
- `parser_context` 应透传到脚本执行环境，但不能覆盖系统保留字段。
- 详细的全量 `parse_memory.py` 解析实现与样例见：
  - `doc/new_framework_python/v4/import_implementations/memory_meta_parser_implementation.md`

---

## 7. 存储层实现（MEMORY）

文件：`app/features/import/memory_import/storage/store_memory.py`

建议接口：

```python
# public（由 service 调用）
def stage_upload_files(self, files: list[Any], task_id: str) -> list[dict[str, Any]]: ...
def build_parse_manifest(self, staged_files: list[dict[str, Any]], task_id: str, kb_index: str, tag: str) -> str: ...
def store(self, kb_index: str, parse_result: ParseResult, vector_model: str | None, parser_script_source: str, parser_script_sha256: str) -> dict[str, Any]: ...
def cleanup_task_workspace(self, task_id: str) -> None: ...
def sweep_expired_task_workspaces(self, ttl_hours: int, limit: int = 1000) -> int: ...

# private（仅 store(...) 内部调用，建议使用 "_" 前缀）
def _save_files_by_plan(self, kb_index: str, tag: str, local_file_storage_plan: dict[str, Any]) -> dict[str, FileStoreResult]: ...
def _hydrate_chunks_with_storage_paths(self, chunks: list[dict[str, Any]], ref_to_store_result: dict[str, FileStoreResult]) -> list[dict[str, Any]]: ...
def _get_or_create_binding(self, kb_index: str, tag: str, parser_script_source: str, parser_script_sha256: str, vector_model: str | None, search_profile: dict[str, Any]) -> dict[str, Any]: ...
def _vectorize_if_needed(self, chunks: list[dict[str, Any]], vector_model: str | None, search_profile: dict[str, Any]) -> list[dict[str, Any]]: ...
def _store_parsed_content(self, kb_index: str, chunks: list[dict[str, Any]]) -> dict[str, Any]: ...
```

### 7.1 文件系统落盘

`store_memory.py` 是存储总入口：先本地存储附件，再组织数据库写入。  
其中本地阶段按 `local_file_storage_plan` 存储附件并返回映射结果。  
文件系统类初始化、成员与接口实现细节请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/file_system_implementation.md`

### 7.2 绑定逻辑

业务侧调用链：
1. `DatabaseFactory.get_writer(domain="MEMORY")`
2. `IDatabaseWriter.get_binding_by_domain_index(...)`
3. 无绑定则创建绑定
4. 有绑定则做一致性校验

数据库类初始化、成员与接口实现细节请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

### 7.3 向量化逻辑

仅当 `vector_model` 提供时：
1. `VectorTool.ensure_model_ready(...)`
2. 本地无模型则 `download_from_huggingface(...)`
3. `VectorTool.embed_chunks(...)` 生成 `content_vector`

### 7.4 数据入库

1. `bulk_upsert_content_docs(index=kb_index, docs=...)`

注意点：
- MEMORY 当前方案只写 `meta.json` 语义 chunk；附件路径通过 `metadata.related_storage_paths` 回填。
- `local_file_storage_plan` 是解析与存储解耦的关键契约，建议保持向后兼容。
- 数据库存储动作必须发生在本地附件存储成功之后。
- `cleanup_task_workspace(...)` 仅负责删除任务临时目录，不可删除最终附件存储目录。
- `sweep_expired_task_workspaces(...)` 仅作为兜底，正常路径仍应依赖 `finally` 即时清理。

### 7.5 调用关系（按文件）

- `app/features/import/import_task_executor.py`
  - `execute(...)` -> `MemoryImportService.execute_task(...)`
- `app/features/import/memory_import/memory_import_service.py`
  - `execute_task(...)` -> `StoreMemory.stage_upload_files(...)`
  - `execute_task(...)` -> `StoreMemory.build_parse_manifest(...)`
  - `execute_task(...)` -> `SandboxRunner.run_parse(...)`
  - `execute_task(...)` -> `StoreMemory.store(...)`
  - `execute_task(...)` -> `cleanup_staged_workspace(...)` -> `StoreMemory.cleanup_task_workspace(...)`（finally）
- `app/features/import/memory_import/storage/store_memory.py`
  - `store(...)` -> `_save_files_by_plan(...)` -> `FileSystemFactory.get_gateway()` -> `IFileSystemGateway.store(...)`
  - `store(...)` -> `_hydrate_chunks_with_storage_paths(...)`
  - `store(...)` -> `_get_or_create_binding(...)` -> `DatabaseFactory.get_writer(...)` -> `IDatabaseWriter.get_binding_by_domain_index/create_index_binding(...)`
  - `store(...)` -> `_vectorize_if_needed(...)` -> `VectorTool.ensure_model_ready/embed_chunks(...)`
  - `store(...)` -> `_store_parsed_content(...)` -> `IDatabaseWriter.bulk_upsert_content_docs(...)`
  - `cleanup_task_workspace(...)` -> 删除 `<import_work_root>/<task_id>/`
  - `sweep_expired_task_workspaces(...)` -> 扫描并清理超期任务目录

---

## 8. 通用实现引导（跨类型复用）

以下组件在 `KNOWLEDGE_BASE/SKILL/MEMORY` 三域复用，本篇不再展开开发细节：

1. 解析运行时（通用）
   - `ASTGuard`
   - `SandboxRunner`
   - 详见：`doc/new_framework_python/v4/import_implementations/parser_runtime_implementation.md`

2. 数据库基础设施
   - `DatabaseFactory` / `IDatabaseWriter` / `OpenSearchWriter`
   - 详见：`doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

3. 文件系统基础设施
   - `FileSystemFactory` / `IFileSystemGateway` / `LocalFileSystemGateway`
   - 详见：`doc/new_framework_python/v4/infrastructure_implementation/file_system_implementation.md`

---

## 9. 错误码建议

- `TAG_INVALID`（tag 非 memory）
- `PARSER_SCRIPT_NOT_FOUND`
- `PARSER_SCRIPT_RISK`
- `PARSER_SCRIPT_TIMEOUT`
- `PARSER_SCRIPT_RUNTIME_ERROR`
- `PARSE_RESULT_SCHEMA_INVALID`
- `INDEX_BINDING_CONFLICT`
- `VECTOR_MODEL_PREPARE_FAILED`
- `INTERNAL_ERROR`

---

## 10. 测试清单

1. `tag=memory` 的正常导入
2. `tag` 错误拒绝
3. 上传脚本优先 / 目录脚本 / 默认脚本三链路
4. `meta.json` 缺失或重复时拒绝
5. 绑定首次创建与冲突拒绝
6. 向量模型本地命中
7. 向量模型本地缺失下载成功
8. 不带 `vector_model` 时跳过向量字段
9. `parse_memory` 返回 `local_file_storage_plan` 正确
10. 附件按 `local_file_storage_plan` 落盘成功并回填 storage path
11. 检索结果中可返回 `metadata.related_storage_paths` 并定位附件
12. 成功任务结束后，`<import_work_root>/<task_id>/`（含 `staged/`）被清理
13. 失败任务在 `keep_failed_workspace=true` 时保留，在 `false` 时被清理
14. 定时清理可删除超过 TTL 的遗留任务目录

