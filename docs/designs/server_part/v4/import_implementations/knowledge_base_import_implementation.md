# KNOWLEDGE_BASE Import 详细开发指南（v4）

本文档对应流程图：`import_pumls/knowledge_base_import_flow.puml`。  
目标是把流程图中的类与接口落成可直接编码的实现说明，覆盖：用途、参数、返回值、内部逻辑与注意点。

---

## 1. 适用范围与职责边界

- 仅覆盖 `POST /api/import/knowledge-base` 导入链路。
- 涵盖启动阶段向量预加载（`infrastructure/vector/`）与导入阶段按需向量化。
- `search_profile` 绑定与内容入库统一收敛在 `store_knowledge_base.py`，不单独拆 `search_profile_store.py`。

---

## 2. 组件清单（按调用顺序）

1. `app/main.py`（`AppStartup`）
2. `app/config/config_manager.py`（`ConfigManager`）
3. `app/infrastructure/vector/model_preloader.py`（`VectorModelPreloader`）
4. `app/infrastructure/vector/vector_tool.py`（`VectorTool`）
5. `app/api/upload/knowledge_base_upload_api.py`（`KnowledgeBaseUploadAPI`）
6. `app/features/async_task/service.py`（`AsyncTaskService`）
7. `app/features/async_task/tasks/dispatch_task.py`（`dispatch_task`）
8. `app/features/upload/upload_task_executor.py`（`UploadTaskExecutor`）
9. `app/features/upload/knowledge_base_upload/knowledge_base_upload_service.py`（`KnowledgeBaseUploadService`）
10. `app/features/upload/parser_runtime/ast_guard.py`（`ASTGuard`）
11. `app/features/upload/parser_runtime/sandbox_runner.py`（`SandboxRunner`）
12. `app/features/upload/knowledge_base_upload/storage/store_knowledge_base.py`（`StoreKnowledgeBase`）
13. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
14. `app/infrastructure/database/base.py`（`IDatabaseWriter`）
15. `app/infrastructure/database/opensearch/writer.py`（`OpenSearchWriter`）

---

## 3. 核心数据类型（建议）

```python
from dataclasses import dataclass
from typing import Any, Literal

ParserScriptSource = Literal["upload", "dir_discovery", "default"]

@dataclass
class UploadConstraints:
    supported_types: list[str]
    max_file_size: int
    max_total_size: int
    max_file_count: int

@dataclass
class ImportTaskPayload:
    kb_index: str
    tag: str
    vector_model: str | None
    parser_context: dict[str, Any] | None
    parser_script_path: str | None

@dataclass
class ParseResult:
    chunks: list[dict[str, Any]]
    search_profile: dict[str, Any]

@dataclass
class IndexBinding:
    domain_type: str
    kb_index: str
    tag: str
    parser_script_source: ParserScriptSource
    parser_script_sha256: str
    vector_model: str | None
    search_profile_json: dict[str, Any]
    search_profile_sha256: str
```

注意点：
- `chunks` 不能为空，`search_profile` 必须符合 v4 契约。
- `vector_model` 允许为空（不做向量化）。

---

## 4. 启动阶段实现

### 4.1 `AppStartup`（`app/main.py`）

用途：在应用启动时完成配置加载与可选模型预加载。

建议接口：

```python
def bootstrap() -> None: ...
```

内部逻辑：
1. 调用 `ConfigManager.initialize()`
2. 调用 `ConfigManager.get_bool("vector.preload_on_startup")`
3. 若为 `True`，调用 `VectorModelPreloader.preload_all_models_async()`

注意点：
- 预加载建议异步后台执行，避免阻塞 API 就绪。
- 预加载失败只记录告警，不阻断服务启动。

### 4.2 `ConfigManager`

建议接口：

```python
def initialize(self) -> None: ...
def load(self) -> dict[str, Any]: ...
def build_cache(self) -> None: ...
def get_bool(self, scope: str) -> bool: ...
def get_list(self, scope: str) -> list[str]: ...
def get_upload_constraints(self, scope: str) -> UploadConstraints: ...
```

返回说明：
- `get_upload_constraints(...)` 返回上传限制四元组（类型/单文件/总大小/数量）。

注意点：
- `initialize()` 应幂等，多次调用不重复读盘。
- `scope` 不存在时给明确异常与默认策略。

### 4.3 `VectorModelPreloader` + `VectorTool`

建议接口：

```python
def preload_all_models_async(self) -> None: ...
def ensure_model_ready(self, model_name: str) -> dict[str, Any]: ...
def download_from_huggingface(self, model_name: str) -> str: ...
```

返回说明：
- `ensure_model_ready` 返回 `{"status": "ready", "source": "local_cache|downloaded", "local_path": "..."}`。

内部逻辑（参考现网）：
- 优先查本地模型缓存路径；若不存在再下载。
- 可参考当前工程：
  - `x_data/vector_generator.py`
  - `x_logic/model_preloader.py`

注意点：
- 模型加载要有并发锁，避免并发重复下载。
- 下载失败抛出可识别业务错误（建议 `VECTOR_MODEL_PREPARE_FAILED`）。

---

## 5. API 层实现

文件：`app/api/upload/knowledge_base_upload_api.py`

建议接口：

```python
async def import_knowledge_base(
    files: list[UploadFile],
    kb_index: str,
    tag: str,
    parser_script: UploadFile | None,
    vector_model: str | None,
    parser_context: str | None,
) -> dict[str, Any]: ...
```

参数说明：
- `files`: 导入文件列表（必填）
- `kb_index`: 物理索引名（必填）
- `tag`: 逻辑标签（必填）
- `parser_script`: 自定义解析脚本（可选）
- `vector_model`: 向量模型名（可选）
- `parser_context`: JSON 字符串（可选）

返回说明：
- 成功返回 `202` + `{task_id, domain, kb_index, tag, status}`。

内部逻辑：
1. `ConfigManager.get_upload_constraints("import.knowledge_base.upload")`
2. 校验文件类型/大小/数量
3. 校验 `kb_index/tag`
4. 调用 `AsyncTaskService.submit(task_type="import.knowledge_base", ...)`

注意点：
- API 层不执行业务导入，仅入参校验 + 入队。
- `parser_context` 要做 JSON 解析失败处理（`INVALID_ARGUMENT`）。

---

## 6. 异步调度层（Celery）

文件：

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

1. API 调用 `AsyncTaskService.submit(...)` 创建业务任务记录并投递 Celery 消息。
2. Celery Worker 执行 `dispatch_task`，按 `task_type` 路由到 `UploadTaskExecutor`。
3. `UploadTaskExecutor` 再调用 `KnowledgeBaseUploadService.execute_task(...)`。
4. `dispatch_task` 负责统一状态流转：`queued -> running -> completed|failed|cancelled`。

注意点：

- 业务服务层应返回结果或抛出明确业务异常；任务状态落库由通用异步层统一处理。
- 若使用幂等键，重复提交应返回既有 `task_id`，不重复投递。

---

## 7. 服务层实现

文件：`app/features/upload/knowledge_base_upload/knowledge_base_upload_service.py`

建议接口：

```python
def execute_task(self, task_id: str, payload: ImportTaskPayload, files: list[Any]) -> None: ...
def save_uploaded_parser(self, parser_script: Any, parsers_dir: str, target_name: str) -> str: ...
def validate_parse_result_schema(self, result: ParseResult) -> None: ...
def merge_chunks_and_check_profile_consistency(self, all_results: list[ParseResult]) -> ParseResult: ...
def cleanup_task_workspace(self, task_id: str, keep_failed_workspace: bool) -> None: ...
def sweep_expired_task_workspaces(self, ttl_hours: int, limit: int = 1000) -> int: ...
```

内部逻辑分解：

1. **解析脚本选择**
   - 有上传脚本：保存为 `parsers/parse_<tag>.py`，`source=upload`
   - 否则查 `parsers/parse_<tag>.py`，命中 `source=dir_discovery`
   - 否则回退 `parsers/parse_default.py`，`source=default`
   - 都不存在 -> `PARSER_SCRIPT_NOT_FOUND`

2. **脚本安全门禁**
   - `ASTGuard.validate(parser_script_path)` 失败即终止

3. **逐文件解析**
   - `SandboxRunner.run_parse(script_path, file_path, parser_context)`
   - 调 `validate_parse_result_schema`

4. **结果合并**
   - 聚合 `chunks`
   - 校验多文件 `search_profile` 一致性（否则失败）

5. **调用存储层**
   - 查询/创建绑定
   - 可选向量化
   - 写内容索引
6. **任务临时目录清理（新增约束）**
   - `execute_task(...)` 必须使用 `try/except/finally`，`finally` 中执行 `cleanup_task_workspace(...)`
   - 清理目标建议为 `<import_work_root>/<task_id>/`（如存在 `staged/`、中间清单与解析中间产物，应一并删除）
   - 默认成功/失败都清理；支持 `import.knowledge_base.staging.keep_failed_workspace=true` 保留失败现场
   - 必须配置 `sweep_expired_task_workspaces(...)` 作为 TTL 兜底清理（例如 24h）

注意点：
- 脚本文件保存后建议计算 `sha256`，用于绑定一致性校验。
- `merge_chunks` 前后都要考虑内存上限（大批量文件）。
- `cleanup_task_workspace(...)` 仅清理任务临时目录，不可影响内容索引中的持久化数据。

---

## 8. 通用解析运行时引导

`ASTGuard` 与 `SandboxRunner` 是跨 `KNOWLEDGE_BASE/SKILL/MEMORY` 的通用能力，不在本篇重复展开实现细节。  
请直接参考：

- `doc/new_framework_python/v4/import_implementations/parser_runtime_implementation.md`

本篇只约束调用方式：

1. `ASTGuard.validate(parser_script_path)` 必须在 `run_parse` 前执行
2. `SandboxRunner.run_parse(...)` 的输出必须经过 `validate_parse_result_schema`
3. 运行时异常必须映射为统一错误码
4. `execute_task(...)` 必须在 `finally` 执行临时目录清理，保证失败分支不泄漏临时文件

---

## 9. 存储层实现（重点）

文件：`app/features/upload/knowledge_base_upload/storage/store_knowledge_base.py`

建议接口：

```python
def get_binding_by_domain_index(self, domain: str, kb_index: str) -> IndexBinding | None: ...
def create_binding(
    self,
    kb_index: str,
    tag: str,
    parser_script_source: ParserScriptSource,
    parser_script_sha256: str,
    vector_model: str | None,
    search_profile: dict[str, Any],
) -> IndexBinding: ...
def assert_binding_consistency(
    self,
    existing_binding: IndexBinding,
    parser_script_sha256: str,
    vector_model: str | None,
    search_profile_sha256: str,
) -> None: ...
def store(
    self,
    chunks: list[dict[str, Any]],
    kb_index: str,
    tag: str,
    vector_model: str | None,
    search_profile: dict[str, Any],
) -> dict[str, Any]: ...
```

### 9.1 绑定读写逻辑（业务侧）

`store_knowledge_base.py` 只负责业务编排，不承担数据库适配细节。

业务侧步骤：
1. 读取既有绑定
2. 无绑定则创建绑定
3. 有绑定则执行一致性校验（脚本 hash、向量模型、profile hash）
4. 冲突直接抛 `INDEX_BINDING_CONFLICT`

数据库类初始化、成员与接口实现细节请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

### 9.2 向量化逻辑

内部步骤（当 `vector_model` 非空）：
1. `VectorTool.ensure_model_ready(vector_model)`
2. `VectorTool.embed_chunks(..., source_template=search_profile["..."]["vector"]["source_template"])`
3. 将向量写入 `content_vector` 字段

无 `vector_model`：
- 跳过向量字段生成，直接写文档。

注意点：
- `source_template` 缺失时应回退默认模板（如 `{title}\n{content}`）。
- 向量维度需和索引 mapping 对齐，避免写入失败。

### 9.3 内容写库（业务侧）

`store_knowledge_base.py` 仅通过 `DatabaseFactory` 获取 `IDatabaseWriter` 并调用批量写接口。  
返回值由业务侧统一收敛为导入结果，不在本篇定义数据库底层协议。

数据库批量写实现细节请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

---

## 10. 基础设施实现引导

本篇不再描述 `infrastructure/database/` 的类初始化、成员与接口内部实现。  
请参考：

- `doc/new_framework_python/v4/infrastructure_implementation/database_implementation.md`

`KNOWLEDGE_BASE` 导入链路不依赖 `infrastructure/file_system/` 落盘，可忽略文件系统实现文档。  
任务临时目录清理属于服务层运行时治理，不改变该链路“无业务文件系统落盘”的约束。

---

## 11. 错误码映射建议

- `PARSER_SCRIPT_NOT_FOUND`：脚本选择链路失败
- `PARSER_SCRIPT_RISK`：AST 不通过
- `PARSE_RESULT_SCHEMA_INVALID`：解析结果契约不合法
- `INDEX_BINDING_CONFLICT`：绑定冲突
- `VECTOR_MODEL_CONFLICT`：请求模型与绑定模型不一致
- `VECTOR_MODEL_PREPARE_FAILED`：模型准备失败（本地+下载均失败）
- `INTERNAL_ERROR`：未知异常

---

## 12. 测试清单（必须）

1. 上传脚本命中（`upload`）路径
2. 目录脚本命中（`dir_discovery`）路径
3. 默认脚本回退（`default`）路径
4. AST 拒绝危险脚本
5. 多文件 `search_profile` 不一致失败
6. 首次绑定成功 + 重复导入一致性通过
7. 绑定冲突拒绝（脚本 hash 或模型不一致）
8. `vector_model` 本地命中向量化成功
9. `vector_model` 本地缺失触发下载并成功向量化
10. 不传 `vector_model` 走非向量化写入
11. 成功任务结束后，`<import_work_root>/<task_id>/`（含 `staged/` 若存在）被清理
12. 失败任务在 `keep_failed_workspace=true` 时保留，在 `false` 时被清理
13. 定时清理可删除超过 TTL 的遗留任务目录

