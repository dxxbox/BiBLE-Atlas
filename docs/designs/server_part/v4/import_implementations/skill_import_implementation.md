# SKILL Import 详细开发指南（v4）

本文档对应流程图：`import_pumls/skill_import_flow.puml`。  
目标是把 SKILL 导入链路涉及的类/接口实现细化为可编码说明。

---

## 1. 适用范围

- 仅覆盖 `POST /api/import/skill`。
- 包含：
  - 启动阶段向量模型预加载
  - 导入阶段脚本解析
  - `.skill` 包上传约束与解压安全校验
  - `SKILL.md` 结构化解析（`name/description/正文` 等）
  - 原始文件落盘
  - 绑定写入
  - 可选向量化 + 内容入库
  - 文件注册表入库

---

## 2. 组件清单

1. `app/main.py`（`AppStartup`）
2. `app/config/config_manager.py`（`ConfigManager`）
3. `app/infrastructure/vector/model_preloader.py`（`VectorModelPreloader`）
4. `app/infrastructure/vector/vector_tool.py`（`VectorTool`）
5. `app/api/upload/skill_upload_api.py`（`SkillUploadAPI`）
6. `app/features/async_task/service.py`（`AsyncTaskService`）
7. `app/features/async_task/tasks/dispatch_task.py`（`dispatch_task`）
8. `app/features/upload/upload_task_executor.py`（`UploadTaskExecutor`）
9. `app/features/upload/skill_upload/skill_upload_service.py`（`SkillUploadService`）
10. `app/features/upload/parser_runtime/ast_guard.py`（`ASTGuard`）
11. `app/features/upload/parser_runtime/sandbox_runner.py`（`SandboxRunner`）
12. `app/features/upload/skill_upload/storage/store_skill.py`（`StoreSkill`）
13. `app/infrastructure/file_system/factory.py`（`FileSystemFactory`）
14. `app/infrastructure/file_system/base.py`（`IFileSystemGateway`）
15. `app/infrastructure/file_system/local.py`（`LocalFileSystemGateway`）
16. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
17. `app/infrastructure/database/base.py`（`IDatabaseWriter`）
18. `app/infrastructure/database/opensearch/writer.py`（`OpenSearchWriter`）

---

## 3. 关键类型定义（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

@dataclass
class FileStoreResult:
    filename: str
    storage_path: str
    file_hash: str
    size_bytes: int

@dataclass
class SkillUploadPayload:
    kb_index: str
    tag: Literal["skill"]
    vector_model: str | None
    parser_context: dict[str, Any] | None
    parser_script_path: str | None = None
    parser_script_filename: str | None = None
    session_upload_dir: str | None = None

@dataclass
class ParseResult:
    chunks: list[dict[str, Any]]
    search_profile: dict[str, Any]
    local_file_storage_plan: dict[str, Any] | None
```

注意点：
- SKILL 的 `tag` 必须固定为 `skill`。
- `parse_skill.py` 是 SKILL 的唯一解析总入口；服务层不应先按文件类型分流再解析。
- `import_skill.parsers_dir` 是预注册脚本目录，`import_skill.custom_parsers_dir` 是上传脚本通过校验并导入成功后的持久化目录。
- `parser_script` 上传文件不直接写入 `custom_parsers_dir`；它先进入任务临时目录，当前任务成功后才覆盖保存为 `custom_parsers_dir/parse_skill.py`。

---

## 4. 启动阶段实现

SKILL 与 KB 一致，启动逻辑复用。

### 4.1 `AppStartup`

```python
def bootstrap() -> None: ...
```

流程：
1. `ConfigManager.initialize()`
2. `ConfigManager.get_bool("vector.preload_on_startup")`
3. 开启时调用 `VectorModelPreloader.preload_all_models_async()`

### 4.2 `VectorModelPreloader` / `VectorTool`

建议接口：

```python
def preload_all_models_async(self) -> None: ...
def ensure_model_ready(self, model_name: str) -> dict[str, Any]: ...
def download_from_huggingface(self, model_name: str) -> str: ...
```

参考实现来源：
- `x_logic/model_preloader.py`
- `x_data/vector_generator.py`

---

## 5. API 层实现

文件：`app/api/upload/skill_upload_api.py`

建议接口：

```python
async def import_skill(
    files: list[UploadFile],
    kb_index: str,
    tag: str,
    parser_script: UploadFile | None,
    vector_model: str | None,
    parser_context: str | None,
) -> dict[str, Any]: ...
```

内部逻辑：
1. 读取 `import.skill.upload` 限制
2. 校验文件
3. 强校验 `tag == "skill"`
4. `AsyncTaskService.submit(task_type="import.skill", ...)`

返回：
- `202 Accepted` + `{task_id, domain=SKILL, kb_index, tag, status}`。

---

## 6. 异步调度与服务层实现

### 6.1 通用异步调度（Celery）

涉及文件：

- `app/features/async_task/service.py`
- `app/features/async_task/tasks/dispatch_task.py`
- `app/features/upload/upload_task_executor.py`

建议接口：

```python
# app/features/async_task/service.py
def submit(self, task_type: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]: ...
def get(self, task_id: str) -> dict[str, Any] | None: ...
def cancel(self, task_id: str) -> dict[str, Any]: ...

# app/features/upload/upload_task_executor.py
def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
```

调度关系：

1. API 提交 `task_type=import.skill` 到 `AsyncTaskService`。
2. `dispatch_task` 在 Celery Worker 进程中消费并分发给 `UploadTaskExecutor`。
3. `UploadTaskExecutor` 调用 `SkillUploadService.execute_task(...)` 完成导入。
4. 任务状态由通用异步层统一维护（`queued/running/completed/failed/cancelled`）。

### 6.2 `SkillUploadService`

建议接口：

```python
def execute_task(self, task_id: str, payload: SkillUploadPayload, files: list[Any]) -> None: ...
def validate_parse_result_schema(self, result: ParseResult) -> None: ...
def merge_chunks_and_check_profile_consistency(self, all_results: list[ParseResult]) -> ParseResult: ...
def cleanup_staged_workspace(self, task_id: str, keep_failed_workspace: bool) -> None: ...
```

内部逻辑：
1. 脚本选择链路：
   - 本次请求携带 `parser_script`：API 先保存到任务 session 临时目录；本任务只使用该临时脚本执行。
   - 本次请求不携带 `parser_script`：先查 `custom_parsers_dir/parse_skill.py`
   - custom 目录未命中：查 `parsers_dir/parse_skill.py`
   - 仍未命中：回退 `parsers_dir/parse_default.py`
   - 均无 -> `PARSER_SCRIPT_NOT_FOUND`
2. 对上传脚本和 custom parser 执行 `ASTGuard.validate(...)`；预注册 `parsers_dir` 脚本视为可信脚本
3. 调用 `StoreSkill.stage_upload_files(...)`（仅临时落地，不做类型分流）
4. 调用 `StoreSkill.build_parse_manifest(...)`
5. 调用 `SandboxRunner.run_parse(...)`（单次，输入 manifest_path）
6. `parse_skill.py` 内部作为唯一总入口执行：
   - 读取 manifest 的全部上传文件
   - 校验 `.skill` 文件必须且仅有一个（允许其他类型文件共存）
   - 对 `.skill` 执行标准 ZIP 解压（防 Zip Slip、解压炸弹、软链接穿越）
   - 校验解压后必须且只能包含一个顶层目录 `<skill-name>/`
   - 定位并解析固定文件 `<skill-name>/SKILL.md`（提取 `name/description/正文`）
   - 构建 `chunks/search_profile/local_file_storage_plan`
7. 调用 `validate_parse_result_schema(...)`（校验 `chunks/search_profile/local_file_storage_plan`）
8. 调用 `StoreSkill.store(...)`（执行本地存储计划、回填存储位置、绑定/向量化/写库/文件注册）
9. 若本次请求携带上传脚本且导入成功，则原子覆盖保存到 `custom_parsers_dir/parse_skill.py`
10. 在 `finally` 调用 `cleanup_staged_workspace(...)`（内部委托 `StoreSkill.cleanup_task_workspace(...)`）

注意点：
- SKILL 文件落盘失败应直接终止任务，不继续解析。
- 解析输入建议统一使用 manifest（全量上传文件），避免在服务层提前做 `.skill` / 非 `.skill` 分流。
- `.skill` 是业务包扩展名，本质 ZIP；实现上应按 ZIP 标准解析，不建议自研解压格式。
- `<skill-name>/SKILL.md` 为必需文件；缺失、重复或不可解析都应作为明确业务错误返回。
- root-level `SKILL.md` 与多个顶层目录均视为非法包结构，避免多个 skill 解压到 `.skills/` 时发生覆盖。
- 非 `.skill` 文件也由 `parse_skill.py` 统一处理与分类；它们不生成语义 chunk，但应进入 `local_file_storage_plan`。
- 上传脚本 ASTGuard 失败、Sandbox 失败、ParseResult schema 校验失败或后续 store 失败时，不得覆盖已有 custom parser。
- custom parser 保存目标固定为 `custom_parsers_dir/parse_skill.py`，不保留上传文件原名；覆盖应使用原子替换。
- binding 中 `parser_script_source` 建议记录为 `parse_skill.py`，`parser_script_sha256` 记录本次实际执行脚本内容摘要。
- `execute_task(...)` 必须使用 `try/except/finally`，所有失败分支都需进入 `finally` 执行临时目录清理。
- 清理目标建议为 `<import_work_root>/<task_id>/`（如包含 `staged/`、中间清单文件，也应一并删除）。
- 默认成功/失败都清理；支持 `import.skill.staging.keep_failed_workspace=true` 保留失败现场用于排障。
- 需要配置 TTL 兜底清理任务，定期删除超期遗留任务目录（例如 24h）。
- `.skill`/`<skill-name>/SKILL.md` 的全量解析实现建议见：
  - `doc/new_framework_python/v4/import_implementations/skill_package_parser_implementation.md`

---

## 7. 存储层实现（SKILL）

文件：`app/features/upload/skill_upload/storage/store_skill.py`

建议接口：

```python
def stage_upload_files(self, files: list[Any], task_id: str) -> list[dict[str, Any]]: ...
def build_parse_manifest(self, staged_files: list[dict[str, Any]], task_id: str, kb_index: str, tag: str) -> str: ...
def store(self, kb_index: str, parse_result: ParseResult, vector_model: str | None, parser_script_source: str, parser_script_sha256: str) -> dict[str, Any]: ...
def get_binding_by_domain_index(self, domain: str, kb_index: str) -> dict[str, Any] | None: ...
def create_binding(self, kb_index: str, tag: str, parser_script_source: str, parser_script_sha256: str, vector_model: str | None, search_profile: dict[str, Any]) -> dict[str, Any]: ...
def assert_binding_consistency(self, existing_binding: dict[str, Any], parser_script_sha256: str, vector_model: str | None, search_profile_sha256: str) -> None: ...
def cleanup_task_workspace(self, task_id: str) -> None: ...
def sweep_expired_task_workspaces(self, ttl_hours: int, limit: int = 1000) -> int: ...
```

### 7.1 文件系统落盘

`store_skill.py` 是存储总入口：先按 `local_file_storage_plan` 存储文件，再组织数据库写入。  
`FileSystemFactory`、`IFileSystemGateway`、`LocalFileSystemGateway` 的初始化与内部实现请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/file_system_implementation.md`

### 7.2 绑定处理

业务侧调用链与 KB 一致：`DatabaseFactory -> IDatabaseWriter`。  
数据库实现细节请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

### 7.3 向量化处理

当 `vector_model` 非空：
1. `VectorTool.ensure_model_ready(vector_model)`
2. `VectorTool.embed_chunks(...)`
3. 合并 `content_vector` 后写库

当 `vector_model` 为空：
- 跳过向量化，直接写 `chunks`。

### 7.4 内容 + 文件注册写库

1. 执行 `local_file_storage_plan` 并生成 `file_ref -> storage_path` 映射
2. 回填 `chunk.metadata.related_storage_paths`
3. `bulk_upsert_content_docs(index=kb_index, docs=...)`
4. `bulk_upsert_file_registry(index=kb_index, file_records=...)`

返回建议（业务收敛）：
- `database_write_status`
- `file_write_status`

补充约束：
- `local_file_storage_plan` 应覆盖全部上传文件（包含非 `.skill` 文件）。
- `bulk_upsert_file_registry(...)` 应记录 `storage_path` 等存储位置信息。
- 语义内容只来自 `.skill` -> `SKILL.md`，非 `.skill` 文件不生成语义 chunk，但其 `storage_path` 需可回填到语义文档（`metadata.related_storage_paths`）。
- `chunks` 建议保留 `name/description/body` 三字段，并同步 `title=name`、`content=name+description+body` 便于兼容展示与检索。
- `search_profile` 建议固定规则：
  - `keyword`：匹配 `name`
  - `text`：匹配 `name/description/body`
  - `vector`：向量源模板为 `name+description+body`
  - `hybrid`：文本与向量混合

清理约束：
- `cleanup_task_workspace(...)` 仅删除任务临时目录，不得删除 `store(...)` 已完成持久化的文件。
- `sweep_expired_task_workspaces(...)` 作为兜底补偿，正常路径仍以 `finally` 即时清理为准。

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

## 9. 错误处理建议

- `TAG_INVALID`：`tag != "skill"`
- `SKILL_PACKAGE_MISSING`
- `SKILL_PACKAGE_MULTIPLE`
- `SKILL_PACKAGE_INVALID_FORMAT`
- `SKILL_PACKAGE_UNSAFE_PATH`
- `SKILL_MD_NOT_FOUND`
- `SKILL_MD_MULTIPLE`
- `SKILL_MD_PARSE_INVALID`
- `PARSER_SCRIPT_NOT_FOUND`
- `PARSER_SCRIPT_RISK`
- `PARSE_RESULT_SCHEMA_INVALID`
- `INDEX_BINDING_CONFLICT`
- `VECTOR_MODEL_PREPARE_FAILED`
- `INTERNAL_ERROR`

---

## 10. 测试清单

1. `tag=skill` 正常入队与执行
2. 错误 `tag` 拒绝
3. 上传缺少 `.skill` 文件时拒绝
4. 上传包含多个 `.skill` 文件时拒绝
5. 上传中包含一个 `.skill` + 多个其他文件时，由 `parse_skill.py` 统一处理并返回完整 `local_file_storage_plan`
6. 脚本三段选择链路（upload/dir_discovery/default）
7. 原始文件落盘成功并可用于后续解析
8. `.skill` 解压安全校验（路径穿越/解压炸弹）有效
9. 解压后缺少 `SKILL.md` 时失败
10. `SKILL.md` 解析出 `name/description/正文` 并生成有效 `chunks/search_profile`
11. `keyword` 检索命中 `name`
12. `text` 检索命中 `name/description/正文`
13. `vector` 检索使用 `name/description/正文` 向量
14. `hybrid` 检索走文本+向量混合
15. 绑定首次创建、重复一致导入、冲突拒绝
16. `vector_model` 本地命中向量化
17. `vector_model` 缺失触发 HuggingFace 下载
18. 内容与文件注册双写结果正确回传
19. 语义文档中 `metadata.related_storage_paths` 回填正确
20. 成功任务结束后，`<import_work_root>/<task_id>/`（含 `staged/` 若存在）被清理
21. 失败任务在 `keep_failed_workspace=true` 时保留，在 `false` 时被清理
22. 定时清理可删除超过 TTL 的遗留任务目录

