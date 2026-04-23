# Import/Search 流程 — MEMORY 类型详细设计

本文档细化 `MEMORY` 类型的 import 与 search 详细设计。Import 使用独立端点 `POST /api/v1/memory/import`，完全独立于通用 upload 链路（后续可按需合并）；Search 接入通用 search 链路，通过 `MemorySearchRepository` 替换占位仓储。通用分层以 `01_架构总览.md` 为准，通用 Search 主链路以 `07_Search流程_no_session_skill_详细设计.md` 为准，OpenSearch 基础设施边界以 `06_OpenSearch部署和接口设计文档.md` 为准。流程图见 `pumls/memory_import_flow.puml`（import）和 `pumls/search_flow_with_hit_and_rerank.puml`（search）。

---

## 目录

- [1. 范围与非目标](#1-范围与非目标)
- [2. MEMORY 类型定位与两文件模型](#2-memory-类型定位与两文件模型)
- [3. 两文件格式规范](#3-两文件格式规范)
- [4. Import 分支详细设计](#4-import-分支详细设计)
- [5. 后台 AI 标签提取设计](#5-后台-ai-标签提取设计)
- [6. OpenSearch 索引契约](#6-opensearch-索引契约)
- [7. Search 分支详细设计](#7-search-分支详细设计)
- [8. Search API 兼容性分析与扩展方案](#8-search-api-兼容性分析与扩展方案)
- [9. 原始内容返回策略](#9-原始内容返回策略)
- [10. 目录结构与模块清单](#10-目录结构与模块清单)
- [11. 关键失败点与错误处理](#11-关键失败点与错误处理)
- [12. 实现检查清单](#12-实现检查清单)

---

## 1. 范围与非目标

### 1.1 本次细化范围

- MEMORY 类型在 import 中的两文件接收、校验、本地落盘、元数据写库、索引构建。
- MEMORY 类型在 search 中的查询字段设计、过滤支持、命中整形、返回边界控制。
- `message.json` 与 `meta.json` 两文件的格式规范与字段职责。
- 后台 AI 分析任务：提取 domain/feature/component 标签并回写索引。
- 现有 Search API 对 MEMORY 专属过滤需求的兼容性评估与最小扩展方案。
- 原始对话内容的返回边界与压缩折中方案评估。

### 1.2 非目标

- 不修改通用 `POST /api/v1/upload` 链路（MEMORY 使用独立端点，后续合并时再评估）。
- 不扩展 CODE、SCT、BUILD、SKILL 等其他类型的 import/search 设计。
- 不定义 download API 的完整协议，只说明 search 与 download 的边界。
- 不展开 memory merge、delete、全局权限控制、脱敏策略的完整实现。
- 不定义 client 侧如何从 Cursor/VSCode 导出对话内容，client 侧格式由 client 设计规范约定。

---

## 2. MEMORY 类型定位与两文件模型

### 2.1 业务背景

MEMORY 在 BiBLE-Atlas 中代表工程师与 AI 工具（Cursor、VSCode Copilot 等）进行的对话会话。这类对话通常包含对某个功能、任务、缺陷的分析与讨论，具有重要的知识复用价值，但单次对话原始内容可能较大（数十 KB 到数 MB）。

### 2.2 两文件设计原则

| 文件 | 角色 | 定位 | 主要消费方 |
|------|------|------|------|
| `message.json` | 原始事实源 | 完整对话内容，不承担列表摘要职责 | import 落盘、download、分块索引、AI 分析 |
| `meta.json` | 结构化元数据 + 轻量摘要载体 | 过滤、标签召回、排序、列表展示 | 全量写入 OpenSearch memory 级索引 |

**核心原则**：

- `message.json` 永远只做原始事实，不进入 search 主响应。
- `meta.json` 由 client 负责生成，server 负责校验与补充服务端字段。
- search 返回只携带 `meta.json` 中的摘要字段 + 服务端补充的 `storage_path_ref`，server 根据 `storage_path_ref` 直接定位并下载，不直接返回 `message.json` 内容。
- `meta.json` 内部直接承载 `abstract` 与 `overview` 字段，不再单独保存 `.abstract.md` 与 `.overview.md` 文件。

### 2.3 主链路衔接

Import 链路（独立端点，不复用通用 upload 链路）：
```
POST /api/v1/memory/import
  → memory_api.py (app/api/v1/memory_api.py)
    → MemoryImportService (features/memory/memory_import_service.py)
      → MemoryUploadRepository (features/memory/repositories/memory_upload_repository.py)
        → validator.py (校验两文件)
        → storage_mapper.py (规划落盘路径)
        → repository.py (本地落盘)
        → metadata_normalizer.py (规范化 meta.json)
        → index_document_builder.py (构建 memory 级文档 + message 级 chunks)
      → document_manager.bulk_import(...) (写入 OpenSearch，复用通用基础设施)
      → celery.submit(memory_ai_extraction_task, memory_id) (异步 AI 标签提取)
```

> **后续合并备注**：当前为独立链路，实现完成后可考虑通过 `tag=MEMORY` 接入通用 `POST /api/v1/upload` 链路，届时 `memory_api.py` 可作为 `upload_api.py` 的 MEMORY 分支入口。

Search 链路（独立端点，不接入通用 search 链路）：
```
POST /api/v1/memory/search
  → memory_api.py (app/api/v1/memory_api.py)
    → MemorySearchService (features/memory/memory_search_service.py)
      → MemorySearchRepository (features/memory/repositories/memory_search_repository.py)
        → filters.normalize_memory_filters(req.filters) → MemoryFilters
        → query_builder.detect_task_id_in_query(query)
        → query_builder.build_memory_query_spec(...) → MemoryQuerySpec
        → memory-level 检索（bible_atlas_memory）
        → message-level 检索（bible_atlas_memory_chunks，可选）
      → result_mapper.map_memory_hits(memory_hits, message_hits, ...)
    → MemorySearchResponse
```

> **后续合并备注**：Search 同样独立实现，后续可按需接入通用 Search 链路（通过注册 `MemorySearchRepository` 到 `SearchRepositoryFactory`）。

memory 完全独立，只复用 OpenSearch 基础设施：

- **memory 负责**：独立接收 import 和 search 请求；管理两文件落盘与元数据规范化；构建 memory 文档模型；搜索结果聚合、裁剪和 raw 内容返回边界控制。
- **通用框架负责**：异步任务状态机、Celery 提交与重试；OpenSearch 的底层 DSL、`bulk_import`、索引 mapping 管理；download、安全权限、全局治理。

---

## 3. 两文件格式规范

### 3.1 `message.json` 规范

**定位**：原始对话事实源，内容格式由 client 侧定义，server 侧只做最小校验。

**注意**：此文件不要求是 VSCode/Cursor 完整导出格式，client 可对原始导出进行裁剪、脱敏后上传。

**最小结构（server 校验的字段）**：

| 字段 | 类型 | 必填性 | 说明 |
|------|------|------|------|
| `schema_version` | string | 推荐必填 | 格式版本，便于后续演进，当前固定 `"1.0"` |
| `memory_id` | string | 必填 | 与 `meta.json.memory_id` 一致 |
| `tool` | string | 推荐必填 | 来源工具，如 `"cursor"`, `"vscode"`, `"custom"` |
| `messages` | array | 必填，非空 | 原始消息数组 |
| `messages[].role` | string | 推荐必填 | `"user"` / `"assistant"` / `"system"` |
| `messages[].content` | string \| array | 推荐必填 | 消息正文或分段内容 |
| `messages[].message_id` | string | 选填但推荐 | 单条消息唯一标识 |
| `messages[].created_at` | string (ISO8601) | 选填但推荐 | 消息时间戳 |
| `messages[].attachments` | array | 选填 | 附件引用列表 |

**示例**：

```json
{
  "schema_version": "1.0",
  "memory_id": "memory-20260408-cni12345",
  "tool": "cursor",
  "messages": [
    {
      "message_id": "m1",
      "role": "user",
      "content": "CNI-12345 里 allocate 函数报 NPE，帮我分析一下原因",
      "created_at": "2026-04-08T09:30:00Z"
    },
    {
      "message_id": "m2",
      "role": "assistant",
      "content": "从堆栈来看，NPE 发生在 allocate() 第 87 行，原因是 context 对象在并发场景下未做判空...",
      "created_at": "2026-04-08T09:31:30Z"
    },
    {
      "message_id": "m3",
      "role": "user",
      "content": "修复方案是什么？",
      "created_at": "2026-04-08T09:32:00Z"
    },
    {
      "message_id": "m4",
      "role": "assistant",
      "content": "建议在 allocate() 入口处增加 null 检查，并用 Optional 包装返回值...",
      "created_at": "2026-04-08T09:33:15Z",
      "attachments": [
        {"type": "code_ref", "path": "src/allocator.cpp", "line_range": "85-95"}
      ]
    }
  ]
}
```

**server 校验规则**：

1. `memory_id` 必须存在且与 `meta.json.memory_id` 一致。
2. `messages` 必须是非空数组。
3. 每条 message 必须有 `role` 字段，且为已知角色值（`user`/`assistant`/`system`/`tool`）。
4. `content` 必须存在且非空字符串（若为数组则数组非空）。
5. 文件大小上限：配置项 `memory.max_raw_file_size_mb`，默认 `50MB`。

---

### 3.2 `meta.json` 规范

**定位**：memory 检索、过滤、列表展示的结构化元数据，同时承载摘要字段。
**生成方**：client 侧生成（可借助 AI 辅助），server 侧补充服务端字段。

**字段规范**：

| 字段 | 类型 | 必填性 | 生成方 | 说明 |
|------|------|------|------|------|
| `memory_id` | string | **必填** | client | 唯一主键，与 `message.json.memory_id` 一致 |
| `title` | string | **必填** | client | memory 标题，search 展示主标题，不超过 200 字符 |
| `abstract` | string | **必填** | client | 一句话摘要（≤500 字符），用于列表展示 |
| `overview` | string | 推荐必填 | client | 段落级概览（≤2000 字符），描述本次 memory 讨论了什么、结论是什么 |
| `created_at` | string (ISO8601) | 推荐必填 | client | memory 开始时间 |
| `updated_at` | string (ISO8601) | 选填 | client | memory 最后更新时间 |
| `task_ids` | array[string] | 选填 | client | 相关任务/缺陷单号，如 `["CNI-12345", "TASK-9021"]` |
| `feature_tags` | array[string] | 选填 | client | feature 号或 feature 名，如 `["CNI", "memory-import"]` |
| `domain_tags` | array[string] | 选填 | client/AI | 领域标签，如 `["allocator", "concurrency"]` |
| `component_tags` | array[string] | 选填 | client/AI | 组件标签，如 `["cpnb", "search_service"]` |
| `source_client` | string | 选填 | client | 来源工具标识，如 `"cursor"`, `"vscode"` |
| `language` | string | 选填 | client | 会话主要语言，`"zh"` / `"en"` |
| `storage_path_ref` | string | 服务端补充 | server | 落盘后由 server 回填，格式 `memory://files/<memory_id>`；server 凭此定位并提供下载 |
| `raw_message_count` | integer | 服务端补充 | server | 由 server 从 `message.json` 统计后回填 |
| `ai_tags_extracted` | boolean | 服务端补充 | server | AI 标签提取是否完成，初始 `false` |
| `ai_tags_extracted_at` | string (ISO8601) | 服务端补充 | server | AI 标签提取完成时间 |

**示例**：

```json
{
  "memory_id": "memory-20260408-cni12345",
  "title": "CNI-12345 allocate 函数 NPE 根因分析与修复",
  "abstract": "分析 CNI-12345 中 allocate 函数在并发场景下因未判空导致 NPE 的根因，并给出修复方案。",
  "overview": "本次 memory 聚焦 CNI-12345 缺陷。用户提供了堆栈信息，AI 定位到 allocate() 第 87 行在并发场景下 context 对象未做判空。讨论了两种修复方案：入口判空 + Optional 包装，以及使用 lock 保护 context 初始化。最终推荐方案一，成本更低且不影响现有接口。",
  "created_at": "2026-04-08T09:30:00Z",
  "updated_at": "2026-04-08T09:45:00Z",
  "task_ids": ["CNI-12345"],
  "feature_tags": ["cni", "memory-allocator"],
  "domain_tags": ["concurrency", "memory-management"],
  "component_tags": ["cpnb", "allocator"],
  "source_client": "cursor",
  "language": "zh"
}
```

**字段约束补充规则**：

- `task_ids` 中的任务号建议统一大写，如 `"CNI-12345"` 而非 `"cni-12345"`，确保关键字检索准确性。
- `feature_tags` 与 `task_ids` 允许重叠，如 `task_ids: ["CNI-12345"]` 与 `feature_tags: ["CNI"]` 可同时存在。
- 禁止用占位符（如 `"N/A"`、`"unknown"`）填充缺失字段，缺失字段应直接省略。
- `abstract` 不允许为空字符串，若 client 无法生成请省略该字段，server 将从 `overview` 截取前 500 字符作为 fallback。

### 3.3 两文件跨校验规则

server 必须对以下一致性关系做校验：

| 校验项 | 规则 | 违反时行为 |
|------|------|------|
| memory_id 一致性 | `message.json.memory_id == meta.json.memory_id` | 直接拒绝 import |
| 时间合理性 | `meta.json.created_at` 不晚于 `message.json.messages[0].created_at`（若存在） | 记录 warning，不阻塞 |
| message 数量 | `meta.json.raw_message_count`（若提供）与实际 messages 长度一致 | 以实际长度覆盖，记录 warning |

---

## 4. Import 分支详细设计

### 4.1 目录结构

```text
app/
├── api/
│   └── v1/
│       ├── memory_api.py                    # 新增：MEMORY 独立入口
│       └── upload_api.py                    # 现有文件，不修改
├── features/
│   └── memory/                              # 全新目录
│       ├── __init__.py
│       ├── memory_import_service.py         # MEMORY import 编排服务
│       ├── schemas.py                       # MemoryImportAcceptedResponse 等
│       ├── validator.py                     # 两文件校验
│       ├── storage_mapper.py                # 落盘路径规划
│       ├── metadata_normalizer.py           # 规范化 meta.json
│       ├── index_document_builder.py        # 构建索引文档
│       └── repositories/
│           ├── __init__.py
│           └── memory_upload_repository.py  # 落盘 + 主编排（调用同目录子模块）
├── infrastructure/
│   └── opensearch/
│       └── document_manager.py              # 现有文件，继续复用
└── tasks/
    └── memory_ai_extraction.py              # 新增：AI 标签提取 Celery 任务
```

### 4.2 API 层（`memory_api.py`）

**端点**：`POST /api/v1/memory/import`（MEMORY 专属独立端点）

**请求格式**：`multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | file[] | 必填 | 必须同时包含 `message.json` 和 `meta.json` 两个文件 |
| `memory_id` | string | 选填 | 若提供，server 校验与文件内 `memory_id` 一致；不提供则从文件中读取 |

**函数签名**（`memory_api.py`）：

```python
router = APIRouter(prefix="/memory", tags=["memory"])

@router.post("/import", response_model=MemoryImportAcceptedResponse, status_code=202)
async def import_memory(
    files: list[UploadFile] = File(...),
    memory_id: Optional[str] = Form(default=None),
    service: MemoryImportService = Depends(get_memory_import_service),
) -> MemoryImportAcceptedResponse:
    """
    MEMORY 独立导入端点。
    接收 message.json + meta.json 两文件，校验后落盘并提交异步任务。
    """
```

**成功响应（202 Accepted）**：

```json
{
  "success": true,
  "task_id": "task-uuid-abc123",
  "memory_id": "memory-20260408-cni12345",
  "status": "processing",
  "accepted_files": ["message.json", "meta.json"],
  "warnings": [],
  "message": "Memory import task submitted"
}
```

**错误响应**：

| HTTP 状态码 | 错误码 | 触发场景 |
|------|------|------|
| 400 | `MEMORY_MISSING_MESSAGE` | 缺少 `message.json` |
| 400 | `MEMORY_MISSING_META` | 缺少 `meta.json` |
| 400 | `MEMORY_ID_MISMATCH` | 两文件 `memory_id` 不一致 |
| 400 | `MEMORY_INVALID_JSON` | 任一文件不可解析为 JSON |
| 400 | `MEMORY_MISSING_REQUIRED_FIELD` | `memory_id`/`title`/`messages` 等必填字段缺失 |
| 413 | `MEMORY_FILE_TOO_LARGE` | `message.json` 超过 `max_raw_file_size_mb` |
| 500 | `MEMORY_STORAGE_ERROR` | 落盘失败 |

### 4.3 Service 层（`memory_import_service.py`）

```python
class MemoryImportService:
    async def import_memory(
        self,
        files: list[UploadFile],
        memory_id_hint: Optional[str],
    ) -> MemoryImportAcceptedResponse:
        """
        MEMORY import 编排入口，完整链路：
        1. 读取文件字节流，解析 message_json / meta_json
        2. 顺序调用 MemoryUploadRepository：
           validate → build_storage_layout → store → normalize_metadata → build_index_documents
        3. 通过 document_manager.bulk_import 写入 OpenSearch
        4. 提交 Celery memory_ai_extraction_task（fire and forget）
        5. 返回 MemoryImportAcceptedResponse
        """
```

### 4.4 validator.py

**职责**：只做校验，不修改数据，不做 IO。

```python
@dataclass
class MemoryBundleValidationResult:
    is_valid: bool             # errors 为空时为 True
    memory_id: str             # 从 message_json 提取
    raw_message_count: int     # 从 message_json.messages 统计
    warnings: list[str]        # 不阻塞但需记录的问题
    errors: list[str]          # 阻塞导入的错误

def validate_memory_bundle(
    message_json: dict,        # 已解析的 message.json
    meta_json: dict,           # 已解析的 meta.json
    memory_id_hint: Optional[str] = None,
) -> MemoryBundleValidationResult:
    """
    校验规则（按优先级）：
    1. message_json.memory_id 必须存在且非空
    2. meta_json.memory_id 必须存在且与 message_json.memory_id 一致
    3. 若 memory_id_hint 提供，必须与上述 memory_id 一致
    4. message_json.messages 必须是非空列表
    5. 每条 message 必须有 role 且为合法值（user/assistant/system/tool）
    6. 每条 message 必须有非空 content
    7. meta_json.title 必须存在且非空字符串
    8. meta_json.abstract 若存在则不得为空字符串
    9. 跨校验：时间合理性、raw_message_count 一致性（warnings，不阻塞）
    返回 MemoryBundleValidationResult，errors 非空则上层 reject。
    """
```

### 4.5 storage_mapper.py

**职责**：规划落盘路径，不做实际 IO，输出可复用的路径对象。

```python
@dataclass
class MemoryStorageLayout:
    memory_id: str
    base_dir: str              # 例：/app/uploads/memory/memory-20260408-cni12345
    message_json_path: str     # 例：/app/uploads/memory/memory-20260408-cni12345/message.json
    meta_json_path: str        # 例：/app/uploads/memory/memory-20260408-cni12345/meta.json
    storage_path_ref: str      # 逻辑引用：memory://files/memory-20260408-cni12345

def build_memory_storage_layout(
    memory_id: str,
    base_upload_dir: str,      # 从配置读取，默认 /app/uploads
) -> MemoryStorageLayout:
    """
    规划 memory 文件集的落盘路径。
    路径结构：{base_upload_dir}/memory/{memory_id}/
    不创建目录，不写文件。
    """
```

### 4.6 repository.py（落盘）

**职责**：负责将两文件写入磁盘（或对象存储），返回落盘结果。

```python
@dataclass
class StoredMemoryBundle:
    memory_id: str
    storage_layout: MemoryStorageLayout
    message_json_bytes: int       # 写入的字节数
    meta_json_bytes: int
    message_checksum: str         # SHA-256 hex
    meta_checksum: str
    stored_at: datetime

class MemoryUploadRepository(BaseUploadRepository):
    async def store_memory_bundle(
        self,
        message_content: bytes,       # message.json 原始内容
        meta_content: bytes,          # meta.json 原始内容
        storage_layout: MemoryStorageLayout,
    ) -> StoredMemoryBundle:
        """
        1. 创建 storage_layout.base_dir（若不存在）
        2. 写入 message.json（原子写，先写临时文件再 rename）
        3. 写入 meta.json
        4. 计算并验证 checksum
        5. 返回 StoredMemoryBundle
        若写入失败抛出 MemoryStorageError，上层映射为 500。
        """
```

### 4.7 metadata_normalizer.py

**职责**：从 `meta.json` 中规范化所有字段，补充服务端字段，输出统一的元数据载荷。

```python
@dataclass
class MemoryMetadataPayload:
    memory_id: str
    title: str
    abstract: str                     # 优先从 meta_json 读取，fallback 从 overview 截取前 500 字符
    overview: Optional[str]
    overview_excerpt: Optional[str] = None  # 查询时由 result_mapper 从 overview 截取，不写入 OpenSearch
    created_at: datetime
    updated_at: Optional[datetime]
    task_ids: list[str]
    feature_tags: list[str]
    domain_tags: list[str]
    component_tags: list[str]
    source_client: Optional[str]
    language: Optional[str]
    storage_path_ref: str             # 服务端补充
    raw_message_count: int            # 服务端补充
    ai_tags_extracted: bool           # 初始 False
    document_key: str                 # = memory_id，供 OpenSearch 幂等写入

def normalize_memory_metadata(
    meta_json: dict,
    stored_bundle: StoredMemoryBundle,
) -> MemoryMetadataPayload:
    """
    1. 提取 meta_json 中所有字段并做类型规范化
    2. abstract fallback：若缺失则截取 overview 前 500 字符
    3. 补充服务端字段：storage_path_ref, raw_message_count
    5. task_ids 统一大写处理（如 "cni-12345" → "CNI-12345"）
    6. 所有 tags 列表去重、去空值
    7. ai_tags_extracted 初始化为 False
    """
```

### 4.8 index_document_builder.py

**职责**：生成两层索引文档（memory 级文档 + message 级 chunks），不直接调用 OpenSearch。

```python
@dataclass
class MemoryImportDocuments:
    memory_document: dict             # memory 级文档（写入 memory 主索引）
    message_chunks: list[dict]        # message 级 chunks（写入 chunks 索引）
    abstract_chunk: dict              # abstract 作为独立 chunk（写入 chunks 索引）
    overview_chunk: Optional[dict]    # overview 作为独立 chunk（若存在）

def build_memory_import_documents(
    metadata_payload: MemoryMetadataPayload,
    message_json: dict,               # 已解析的 message.json
    chunk_size: int = 500,            # token 数，从配置读取
    chunk_overlap: int = 50,          # overlap token 数
) -> MemoryImportDocuments:
    """
    1. 生成 memory 级文档（字段见 §6.1）
    2. 从 abstract 生成摘要 chunk（source="abstract"）
    3. 从 overview 生成概览 chunk（source="overview"）
    4. 从 message_json.messages[] 按 chunk_size 切分，生成 message chunks
       - 保留 message_id, role, content, created_at
       - source="message"
       - 附带 chunk_index, token_count
    5. 所有 chunks 带 memory_id, document_key
    禁止：将完整 message.json 内容放入 memory 级文档的任何可检索字段。
    """
```

**message 切分规则**：

- 单条 message content ≤ chunk_size tokens 时：单条 message 作为一个 chunk。
- 单条 message content > chunk_size tokens 时：按 chunk_size 切分，相邻 chunk 保留 overlap。
- role 信息附在每个 chunk 的 `role` 字段，不嵌入 content 正文（避免影响语义检索）。
- `chunk_id` 生成规则：`{memory_id}_{message_id}_{chunk_index}` 或 `{memory_id}_abstract_0`。

### 4.9 Import 调用时序

```
import_api.py
  ↓ 解析 multipart，提取 message.json / meta.json 两个文件流
  ↓ 读取为 bytes 并解析 JSON（失败 → 400）
  ↓ tag == "MEMORY" → upload_service.import_memory_bundle(...)
      ↓ validator.validate_memory_bundle(message_json, meta_json)
        → ValidationResult.errors 非空 → raise MemoryValidationError → 400
      ↓ storage_mapper.build_memory_storage_layout(memory_id)
      ↓ repository.store_memory_bundle(message_bytes, meta_bytes, layout)
        → 落盘失败 → raise MemoryStorageError → 500
      ↓ metadata_normalizer.normalize_memory_metadata(meta_json, stored_bundle)
      ↓ index_document_builder.build_memory_import_documents(metadata, message_json)
      ↓ document_manager.bulk_import(memory_index, [memory_document])
      ↓ document_manager.bulk_import(chunks_index, message_chunks + [abstract_chunk, overview_chunk])
      ↓ celery.apply_async(memory_ai_extraction_task, args=[memory_id, layout.message_json_path])
      ↓ return UploadAcceptedResponse(memory_id=memory_id, task_id=..., status="processing")
  ↓ 返回 202
```

---

## 5. 后台 AI 标签提取设计

### 5.1 设计目标

在 import 完成后，通过后台 Celery 任务异步分析 `message.json` 原始对话内容，提取以下信息并回写到 OpenSearch：

- `domain_tags`：如 `["concurrency", "memory-management", "scheduling"]`
- `feature_tags`：如 `["CNI", "cni-12345"]`（从对话正文中识别）
- `component_tags`：如 `["cpnb", "allocator", "search_service"]`
- 补充 `task_ids`（若对话中提到了未在 `meta.json` 声明的任务单号）

### 5.2 触发条件

- 每次 import 成功后均触发（`fire and forget`）。
- 若 `meta.json` 中 `ai_tags_extracted == true`（client 已提供完整标签），**仍然触发**但仅做补充（不覆盖 client 提供的标签，只做合并去重）。
- 任务失败后自动重试最多 3 次（Celery retry）。

### 5.3 Celery 任务定义（`tasks/memory_ai_extraction.py`）

```python
@celery_app.task(
    name="memory_ai_extraction",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 秒
)
def memory_ai_extraction_task(
    self,
    memory_id: str,
    message_json_path: str,
    ai_model: str = "gpt-5-mini",  # 从配置读取默认值
) -> dict:
    """
    1. 从磁盘读取 message.json
    2. 截取前 N 条消息（默认 50 条，避免超出 token 限制）
    3. 构建 prompt，调用 AI 模型提取结构化标签
    4. 合并 AI 提取结果与现有标签（去重）
    5. 更新 OpenSearch 中对应 memory 文档的标签字段
    6. 更新 ai_tags_extracted=true, ai_tags_extracted_at=now
    返回：{"memory_id": ..., "extracted_tags": {...}, "status": "success"}
    """
```

### 5.4 AI Prompt 设计

**系统 Prompt**（固定）：

```
你是一个代码工程知识提取专家。给定一段工程师与 AI 助手的对话记录，
请提取以下结构化信息：
1. domain_tags：技术领域标签（如 concurrency, memory, scheduling, networking）
2. feature_tags：功能模块或 feature 标识符（如功能名、模块名缩写）
3. component_tags：代码组件名（如函数名、模块名、子系统名）
4. task_ids：对话中明确提到的任务单号（格式如 CNI-12345, TASK-9021, BUG-456）

输出 JSON 格式，不输出任何其他内容。
```

**用户 Prompt 模板**：

```python
def build_extraction_prompt(messages: list[dict], max_messages: int = 50) -> str:
    truncated = messages[:max_messages]
    conversation = "\n".join(
        f"[{m['role']}]: {str(m['content'])[:500]}"  # 每条限 500 字符
        for m in truncated
    )
    return f"""请从以下对话中提取结构化标签：

{conversation}

输出 JSON 格式：
{{
  "domain_tags": ["...", "..."],
  "feature_tags": ["...", "..."],
  "component_tags": ["...", "..."],
  "task_ids": ["...", "..."]
}}"""
```

### 5.5 标签回写规则

```python
def merge_and_update_tags(
    existing_tags: dict,     # 从 OpenSearch 读取的现有标签
    ai_tags: dict,           # AI 提取的标签
) -> dict:
    """
    合并规则：
    - 对每个 tag 类型，取 existing 和 ai 的并集
    - 去重、去空值
    - 统一大小写（task_ids 全大写，其余 tags 全小写）
    - 不删除 client 已提供的任何标签
    """
```

---

## 6. OpenSearch 索引契约

### 6.1 Memory 级文档（主索引：`bible_atlas_memory`）

| 字段 | OpenSearch 类型 | 说明 |
|------|------|------|
| `memory_id` | `keyword` | 唯一主键 |
| `document_key` | `keyword` | 同 `memory_id`，供 document_manager 幂等写入 |
| `title` | `text` (analyzer: ik_max_word) + `keyword` | 标题，兼顾中文分词与精确匹配 |
| `abstract` | `text` (analyzer: ik_max_word) | 一句话摘要 |
| `overview` | `text` (analyzer: ik_max_word) | 段落级概览 |
| `task_ids` | `keyword` (array) | 任务单号，精确匹配 |
| `feature_tags` | `keyword` (array) + 子字段 `text` | 精确 + 模糊兜底 |
| `domain_tags` | `keyword` (array) | 领域标签 |
| `component_tags` | `keyword` (array) | 组件标签 |
| `source_client` | `keyword` | 来源工具 |
| `language` | `keyword` | 会话语言 |
| `storage_path_ref` | `keyword` | 逻辑存储路径，不索引 |
| `raw_message_count` | `integer` | 消息条数 |
| `ai_tags_extracted` | `boolean` | AI 标签提取状态 |
| `ai_tags_extracted_at` | `date` | AI 标签提取时间 |
| `created_at` | `date` | 创建时间 |
| `updated_at` | `date` | 更新时间 |
| `abstract_vector` | `dense_vector` (dim=1024) | abstract 的向量，用于 memory 级语义召回 |

**OpenSearch Mapping 片段**：

```json
{
  "mappings": {
    "properties": {
      "memory_id":     { "type": "keyword" },
      "document_key":  { "type": "keyword" },
      "title": {
        "type": "text", "analyzer": "ik_max_word",
        "fields": { "keyword": { "type": "keyword" } }
      },
      "abstract":  { "type": "text", "analyzer": "ik_max_word" },
      "overview":  { "type": "text", "analyzer": "ik_max_word" },
      "task_ids":  { "type": "keyword" },
      "feature_tags": {
        "type": "keyword",
        "fields": { "text": { "type": "text", "analyzer": "ik_max_word" } }
      },
      "domain_tags":    { "type": "keyword" },
      "component_tags": { "type": "keyword" },
      "storage_path_ref": { "type": "keyword", "index": false },
      "raw_message_count":  { "type": "integer" },
      "ai_tags_extracted":  { "type": "boolean" },
      "ai_tags_extracted_at": { "type": "date" },
      "created_at": { "type": "date" },
      "updated_at": { "type": "date" },
      "abstract_vector": {
        "type": "dense_vector", "dims": 1024,
        "index": true, "similarity": "cosine"
      }
    }
  }
}
```

### 6.2 Message 级 Chunks（chunks 索引：`bible_atlas_memory_chunks`）

| 字段 | OpenSearch 类型 | 说明 |
|------|------|------|
| `chunk_id` | `keyword` | `{memory_id}_{message_id}_{chunk_index}` |
| `memory_id` | `keyword` | 所属 memory |
| `document_key` | `keyword` | 同 `memory_id` |
| `message_id` | `keyword` | 原消息 ID（若存在） |
| `role` | `keyword` | `user`/`assistant`/`system` |
| `source` | `keyword` | `message`/`abstract`/`overview` |
| `content` | `text` (analyzer: ik_max_word) | chunk 正文 |
| `content_vector` | `dense_vector` (dim=1024) | chunk 语义向量 |
| `chunk_index` | `integer` | chunk 在 memory 中的序号 |
| `token_count` | `integer` | chunk token 数 |
| `created_at` | `date` | 消息时间（来自 message.created_at） |

### 6.3 向量化策略

| 内容 | 向量化 | 原因 |
|------|------|------|
| `abstract` | ✅ memory 级向量 | memory 级语义召回主字段 |
| `overview` | ✅ 独立 chunk 向量 | 段落级概览召回 |
| `messages[].content` | ✅ message 级向量 | 精细语义召回 |
| `title` | ❌（BM25 文本索引足够） | 标题通常较短，不做向量化 |
| `task_ids`, `feature_tags` 等 | ❌（keyword 过滤） | 结构化过滤，不需要向量 |

---

## 7. Search 分支详细设计

### 7.1 目录结构

Search 分支与 Import 分支共享 `features/memory/` 目录，不依赖 `features/search/` 公共链路。

```text
app/
├── api/
│   └── v1/
│       └── memory_api.py                    # 已有：新增 search 端点
├── features/
│   └── memory/
│       ├── memory_search_service.py         # 新增：Search 编排服务
│       ├── schemas.py                       # 已有：补充 MemorySearchRequest/MemorySearchResponse/MemoryFilters/MemorySearchItem
│       ├── filters.py                       # 新增：归一化 memory 专属过滤条件
│       ├── query_builder.py                 # 新增：生成 MemoryQuerySpec
│       ├── result_mapper.py                 # 新增：命中整形与返回边界控制
│       └── repositories/
│           └── memory_search_repository.py  # 新增：执行双路 OpenSearch 检索
```

### 7.2 API 层（`memory_api.py` 新增端点）

**端点**：`POST /api/v1/memory/search`

```python
@router.post("/search", response_model=MemorySearchResponse, status_code=200)
async def search_memory(
    req: MemorySearchRequest,
    service: MemorySearchService = Depends(get_memory_search_service),
) -> MemorySearchResponse:
    """MEMORY 独立检索端点。"""
```

### 7.3 schemas.py 扩展

**`MemoryFilters`（新增）**：

```python
class MemoryFilters(BaseModel):
    task_ids: Optional[list[str]] = None          # 精确匹配任务单号，支持多值 OR
    feature_tags: Optional[list[str]] = None
    domain_tags: Optional[list[str]] = None
    component_tags: Optional[list[str]] = None
    source_client: Optional[str] = None
    language: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    ai_tags_extracted: Optional[bool] = None
```

**`MemorySearchRequest`（新增）**：

```python
class MemorySearchRequest(BaseModel):
    query: str
    search_type: str = "hybrid"            # keyword / vector / hybrid
    top_k: int = 10
    filters: Optional[MemoryFilters] = None
    include_raw_preview: bool = False
```

**`MemorySearchItem`（新增）**：

```python
class MemorySearchItem(BaseModel):
    memory_id: str
    title: str
    abstract: str
    overview_excerpt: Optional[str]        # result_mapper 从 overview 截取 ≤300 字符，非 OpenSearch 存储字段
    feature_tags: list[str]
    task_ids: list[str]
    domain_tags: list[str]
    component_tags: list[str]
    created_at: Optional[datetime]
    source_client: Optional[str]
    score: float
    match_scope: Literal["memory", "message"]
    matched_message_id: Optional[str]
    matched_message_preview: Optional[str]  # ≤200 字符
    storage_path_ref: str
    match_reason: list[str]
    raw_content_preview: Optional[str] = None  # include_raw_preview=true 时，≤500 字符
    warnings: list[str] = []
```

**`MemorySearchResponse`（新增）**：

```python
class MemorySearchResponse(BaseModel):
    success: bool = True
    total: int
    memories: list[MemorySearchItem]
    warnings: list[str] = []
```

### 7.4 filters.py

```python
def normalize_memory_filters(
    raw_filters: Optional[dict],
) -> MemoryFilters:
    """
    将 SearchRequest.filters（dict 或 None）解析并校验为 MemoryFilters。
    - None 或空 dict → 返回全空 MemoryFilters（不做过滤）
    - 未知字段静默忽略
    - task_ids 统一大写
    - 时间字段解析为 datetime（失败则忽略，记录 warning）
    """
```

### 7.5 query_builder.py

```python
@dataclass
class MemoryQuerySpec:
    query_text: str
    search_type: str                   # keyword / vector / hybrid
    title_boost: float = 3.0
    abstract_boost: float = 2.0
    overview_boost: float = 1.5
    feature_tags_boost: float = 2.5
    task_ids_boost: float = 3.0
    use_vector: bool = True
    vector_field: str = "abstract_vector"
    message_vector_field: str = "content_vector"
    vector_weight: float = 0.7
    enable_message_level: bool = True  # top_k > 20 时建议仅做 memory 级
    top_k: int = 10
    filters: MemoryFilters = field(default_factory=MemoryFilters)
    include_raw_preview: bool = False

TASK_ID_PATTERN = re.compile(r'\b([A-Z]+-\d+)\b')

def detect_task_id_in_query(query_text: str) -> list[str]:
    """
    从 query 文本中提取任务单号（如 CNI-12345, TASK-9021）。
    若提取成功，在 query_builder 中将这些单号加入 task_ids 过滤条件（terms 精确匹配），
    同时保留全文检索作为兜底。
    """

def build_memory_query_spec(
    query_text: str,
    search_type: str,
    filters: MemoryFilters,
    top_k: int,
    vector_weight: float,
    include_raw_preview: bool = False,
) -> MemoryQuerySpec:
    """
    构建 memory 检索规格。
    - 当 query_text 匹配单号格式（如 CNI-\\d+）时，提升 task_ids_boost
    - 当 query_text 包含 feature 前缀（如 "CNI"）时，提升 feature_tags_boost
    - enable_message_level 默认 True，但 top_k > 20 时建议仅做 memory 级
    """
```

### 7.6 memory_search_repository.py

```python
class MemorySearchRepository:
    """MEMORY 专属检索仓储，不继承 BaseSearchRepository。"""

    async def search(
        self,
        req: MemorySearchRequest,
        query_vector: Optional[list[float]],
    ) -> tuple[list[dict], list[dict]]:
        """
        1. 调用 filters.normalize_memory_filters(req.filters) → MemoryFilters
        2. 调用 query_builder.detect_task_id_in_query(req.query) → auto_task_ids
        3. 调用 query_builder.build_memory_query_spec(...) → MemoryQuerySpec
        4. memory-level 检索：search_client.search("bible_atlas_memory", memory_dsl)
        5. 若 spec.enable_message_level：
           search_client.search("bible_atlas_memory_chunks", message_dsl)
        6. 返回 (memory_hits, message_hits)
        """

    def _build_memory_dsl(self, spec: MemoryQuerySpec, vector: Optional[list[float]]) -> dict:
        """构建 memory-level OpenSearch Query DSL。"""

    def _build_message_dsl(self, spec: MemoryQuerySpec, candidate_memory_ids: list[str], vector: Optional[list[float]]) -> dict:
        """构建 message-level OpenSearch Query DSL，可按候选 memory_id 范围缩小检索。"""
```

### 7.7 result_mapper.py

```python
def map_memory_hits(
    memory_hits: list[dict],           # memory-level OpenSearch hits
    message_hits: list[dict],          # message-level OpenSearch hits
    include_raw_preview: bool = False,
    raw_preview_max_chars: int = 500,
    message_preview_max_chars: int = 200,
) -> list[MemorySearchItem]:
    """
    整合两路命中，聚合为 memory 维度结果。

    Step 1：group_hits_by_memory — 按 memory_id 分组两路命中
    Step 2：merge_memory_and_message_hits
      - 只有 memory-level 命中 → match_scope="memory"
      - 有 message-level 命中 → match_scope="message"，取最高分 message
      - 两者都有 → 取较高分者决定 match_scope
    Step 3：build_match_reason — 生成命中原因标签
      title_fuzzy / title_exact / abstract_semantic /
      task_ids_exact / feature_tags_exact / feature_tags_fuzzy /
      message_semantic / message_keyword
    Step 4：build_preview
      - match_scope=="message" → 截取 matched_message content 前 N 字符
      - include_raw_preview → 截取 abstract 或 overview 前 N 字符
    Step 5：输出 list[MemorySearchItem]，按 score 降序
    """

def group_hits_by_memory(hits: list[dict]) -> dict[str, list[dict]]: ...
def merge_memory_and_message_hits(
    memory_groups: dict[str, list[dict]],
    message_groups: dict[str, list[dict]],
) -> dict[str, dict]: ...
def build_match_reason(hit: dict, source_index: str) -> list[str]: ...
def build_message_preview(content: str, max_chars: int) -> str: ...
```

### 7.8 Search 返回字段边界

| 字段 | 默认返回 | 条件返回 | 不返回 |
|------|------|------|------|
| `memory_id` | ✅ | | |
| `title` | ✅ | | |
| `abstract` | ✅ | | |
| `overview_excerpt` | | 由 result_mapper 从 `overview` 截取，≤300 字符 | |
| `feature_tags` / `task_ids` / `domain_tags` / `component_tags` | ✅ | | |
| `created_at` / `score` | ✅ | | |
| `match_scope` / `match_reason` | ✅ | | |
| `storage_path_ref` | ✅ | | |
| `matched_message_id` | | `match_scope=="message"` 时 | |
| `matched_message_preview` | | `match_scope=="message"` 时 | |
| `raw_content_preview` | | `include_raw_preview=true` 时，≤500 字符 | |
| `message.json` 完整内容 | | | ❌ 永不直接返回 |

### 7.9 Search 返回前的数据整合

1. 把 `memory-level hits` 与 `message-level hits` 分开接收。
2. 按 `memory_id` 合并多条命中。
3. 对同一 memory 的多条命中，保留最高分并汇总 `match_reason`。
4. 若 `memory-level` 命中占优，则设置 `match_scope="memory"`。
5. 若某个 `message_id` 命中占优，则设置 `match_scope="message"`，补充 `matched_message_id` 与 `matched_message_preview`。
6. 从 `title/abstract/overview` 中选择最适合列表展示的摘要字段。
7. 若命中的是 message chunk，则只回传受限长度的 preview，不回传完整 raw。
8. 最终输出统一的 `MemorySearchItem` 列表，由 `MemorySearchService` 封装为 `MemorySearchResponse` 返回。

---

## 8. MEMORY Search API 说明

MEMORY 使用独立端点 `POST /api/v1/memory/search`，请求字段原生支持所有过滤需求，无需兼容通用 Search API。

**客户端使用示例**：

```json
POST /api/v1/memory/search
{
  "query": "allocate NPE 并发",
  "search_type": "hybrid",
  "top_k": 10,
  "filters": {
    "task_ids": ["CNI-12345"],
    "feature_tags": ["cni"],
    "created_after": "2026-01-01T00:00:00Z"
  }
}
```

**任务单号自动识别**（无需 client 显式传 `filters.task_ids`）：

```
query = "CNI-12345 的 allocate 崩溃"
         ↓ query_builder.detect_task_id_in_query
自动在 task_ids 字段做 terms 精确匹配
+ 同时对 title/abstract/overview 做全文检索兜底
```

> 后续若需要与通用 `enable_hit` 机制联动（跨类型检索），可注册 `MemorySearchRepository` 到 `SearchRepositoryFactory`。

---

## 9. 原始内容返回策略

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 直接返回完整 raw | 简单 | 响应体过大，影响 search 性能 | ❌ 不采用 |
| 压缩后 base64 返回 | 一次请求 | 压缩比不稳定，base64 再增大 33%，client 需解压 | ❌ 不采用 |
| 返回 preview 截取 | 体积可控 | 信息不完整 | ✅ 作为默认行为 |
| 二阶段 download | 解耦 search 与 download | 需要两次网络请求 | ✅ **推荐方案** |

**推荐方案：二阶段 Download**

- **第一阶段（search）**：返回 `memory_id`、`storage_path_ref`、`matched_message_preview`（≤200 字符）；可选返回 `raw_content_preview`（≤500 字符，需 `include_raw_preview=true`）。
- **第二阶段（download）**：client 使用 `memory_id` 调用 `GET /api/v1/download/memory/{memory_id}`，server 根据 `storage_path_ref` 定位文件并返回完整 `message.json`。响应 `Content-Type: application/json`，支持流式下载。

**`storage_path_ref` 格式**：`memory://files/{memory_id}`（server 内部解析为实际磁盘路径，client 无需关心）

**压缩折中方案（备选，暂不实现）**：对前 10 条 messages 做 JSON + gzip + base64，压缩比约 3-8x，10 条消息约 0.7-2KB，待产品明确需要时再启用。

---

## 10. 目录结构与模块清单

### 10.1 完整目录结构

```text
app/
├── api/v1/
│   ├── memory_api.py                            # 新增：import + search 两个独立端点，~80 行
│   └── upload_api.py                            # 不变
├── features/
│   └── memory/                                  # 全新目录（import + search 独立链路）
│       ├── __init__.py
│       ├── memory_import_service.py             # 新增：import 编排，~50 行
│       ├── memory_search_service.py             # 新增：search 编排，~40 行
│       ├── schemas.py                           # 新增：所有 MEMORY 相关 schema，~100 行
│       ├── validator.py                         # 新增：两文件校验，~90 行
│       ├── storage_mapper.py                    # 新增：落盘路径规划，~50 行
│       ├── metadata_normalizer.py               # 新增：规范化 meta.json，~100 行
│       ├── index_document_builder.py            # 新增：构建索引文档，~120 行
│       ├── filters.py                           # 新增：search 过滤归一化，~60 行
│       ├── query_builder.py                     # 新增：生成 MemoryQuerySpec，~100 行
│       ├── result_mapper.py                     # 新增：命中整形与边界控制，~150 行
│       └── repositories/
│           ├── __init__.py
│           ├── memory_upload_repository.py      # 新增：落盘 + import 编排，~80 行
│           └── memory_search_repository.py      # 新增：双路 OpenSearch 检索，~120 行
└── tasks/memory_ai_extraction.py                # 新增：AI 标签提取 Celery 任务，~120 行
```

### 10.2 函数清单

| 模块 | 函数 | 输入 | 输出 | 估计行数 |
|------|------|------|------|------|
| `memory_api.py` | `import_memory` | `files`, `memory_id` | `MemoryImportAcceptedResponse` | ~40 |
| `memory_api.py` | `search_memory` | `MemorySearchRequest` | `MemorySearchResponse` | ~20 |
| `memory/memory_import_service.py` | `MemoryImportService.import_memory` | `files`, `memory_id_hint` | `MemoryImportAcceptedResponse` | ~50 |
| `memory/memory_search_service.py` | `MemorySearchService.search` | `MemorySearchRequest` | `MemorySearchResponse` | ~40 |
| `memory/validator.py` | `validate_memory_bundle` | `message_json`, `meta_json`, `memory_id_hint` | `MemoryBundleValidationResult` | ~90 |
| `memory/storage_mapper.py` | `build_memory_storage_layout` | `memory_id`, `base_upload_dir` | `MemoryStorageLayout` | ~40 |
| `memory/repositories/memory_upload_repository.py` | `MemoryUploadRepository.store` | `message_bytes`, `meta_bytes`, `layout` | `StoredMemoryBundle` | ~60 |
| `memory/metadata_normalizer.py` | `normalize_memory_metadata` | `meta_json`, `stored_bundle` | `MemoryMetadataPayload` | ~100 |
| `memory/index_document_builder.py` | `build_memory_import_documents` | `metadata_payload`, `message_json` | `MemoryImportDocuments` | ~120 |
| `tasks/memory_ai_extraction.py` | `memory_ai_extraction_task` | `memory_id`, `message_json_path` | `dict` | ~100 |
| `tasks/memory_ai_extraction.py` | `build_extraction_prompt` | `messages`, `max_messages` | `str` | ~20 |
| `tasks/memory_ai_extraction.py` | `merge_and_update_tags` | `existing_tags`, `ai_tags` | `dict` | ~30 |
| `memory/filters.py` | `normalize_memory_filters` | `raw_filters: MemoryFilters \| None` | `MemoryFilters` | ~50 |
| `memory/query_builder.py` | `build_memory_query_spec` | `query_text`, `search_type`, `filters`, ... | `MemoryQuerySpec` | ~80 |
| `memory/query_builder.py` | `detect_task_id_in_query` | `query_text` | `list[str]` | ~15 |
| `memory/repositories/memory_search_repository.py` | `MemorySearchRepository.search` | `req`, `query_vector` | `(memory_hits, message_hits)` | ~80 |
| `memory/repositories/memory_search_repository.py` | `_build_memory_dsl` | `spec`, `vector` | `dict` | ~40 |
| `memory/repositories/memory_search_repository.py` | `_build_message_dsl` | `spec`, `candidate_ids`, `vector` | `dict` | ~40 |
| `memory/result_mapper.py` | `map_memory_hits` | `memory_hits`, `message_hits`, ... | `list[MemorySearchItem]` | ~80 |
| `memory/result_mapper.py` | `group_hits_by_memory` | `hits` | `dict[str, list[dict]]` | ~15 |
| `memory/result_mapper.py` | `merge_memory_and_message_hits` | `memory_groups`, `message_groups` | `dict[str, dict]` | ~40 |
| `memory/result_mapper.py` | `build_match_reason` | `hit`, `source_index` | `list[str]` | ~30 |
| `memory/result_mapper.py` | `build_message_preview` | `content`, `max_chars` | `str` | ~15 |

---

## 11. 关键失败点与错误处理

### 11.1 Import 失败点

| 失败点 | 行为 | HTTP 状态 | 错误码 |
|------|------|------|------|
| `message.json` 缺失 | 立即拒绝，不落盘 | 400 | `MEMORY_MISSING_MESSAGE` |
| `meta.json` 缺失 | 立即拒绝，不落盘 | 400 | `MEMORY_MISSING_META` |
| 任一文件 JSON 解析失败 | 立即拒绝，不落盘 | 400 | `MEMORY_INVALID_JSON` |
| `memory_id` 不一致 | 立即拒绝，不落盘 | 400 | `MEMORY_ID_MISMATCH` |
| `messages` 为空数组 | 立即拒绝，不落盘 | 400 | `MEMORY_EMPTY_MESSAGES` |
| `title` 缺失或为空 | 立即拒绝，不落盘 | 400 | `MEMORY_MISSING_TITLE` |
| 文件大小超限 | 立即拒绝，不落盘 | 413 | `MEMORY_FILE_TOO_LARGE` |
| 磁盘写入失败 | 抛出 MemoryStorageError | 500 | `MEMORY_STORAGE_ERROR` |
| `abstract` + `overview` 均缺失 | 拒绝构建索引，文件已落盘（可重试） | 422 | `MEMORY_MISSING_SUMMARY_TEXT` |
| OpenSearch bulk import 失败 | 沿用通用 Import 异步失败状态 | — | 异步任务状态 `failed` |
| AI 标签提取失败 | Celery 重试 3 次，最终 `ai_tags_extracted=false`，不影响 search | — | 任务日志 |

### 11.2 Search 失败点

| 失败点 | 行为 | HTTP 状态 |
|------|------|------|
| `filters` 字段格式非法 | 忽略非法字段，记录 warning，继续检索 | 200（带 warnings） |
| `task_ids` 过滤匹配不到结果 | 返回空分桶，不报错 | 200 |
| memory-level 检索超时 | 返回部分结果 + warning | 200 |
| message-level 检索超时 | 仅返回 memory-level 结果 + warning | 200 |
| OpenSearch 连接异常 | 向上抛出，映射为 503 | 503 |

---

## 12. 实现检查清单

### Import 子任务

- [ ] **T1**：定义所有数据类（`MemoryBundleValidationResult`、`MemoryStorageLayout`、`StoredMemoryBundle`、`MemoryMetadataPayload`、`MemoryImportDocuments`）
- [ ] **T2**：实现 `memory/validator.validate_memory_bundle`
- [ ] **T3**：实现 `memory/storage_mapper.build_memory_storage_layout`
- [ ] **T4**：实现 `memory/repository.MemoryUploadRepository.store_memory_bundle`（原子写 + checksum）
- [ ] **T5**：实现 `memory/metadata_normalizer.normalize_memory_metadata`（含 abstract fallback、task_ids 大写）
- [ ] **T6**：实现 `memory/index_document_builder.build_memory_import_documents`
- [ ] **T7**：实现 `features/memory/memory_import_service.py`（`MemoryImportService.import_memory` 完整编排）
- [ ] **T8**：实现 `features/memory/repositories/memory_upload_repository.py`（调用各内部子模块）
- [ ] **T9**：实现 `app/api/v1/memory_api.py`（独立端点、参数提取、错误映射、注册 router）
- [ ] **T10**：在 `features/memory/schemas.py` 中添加 `MemoryImportAcceptedResponse`

### AI 标签提取子任务

- [ ] **T11**：实现 `tasks/memory_ai_extraction.py`（Celery 任务、prompt 构建、AI 调用、结果回写）
- [ ] **T12**：在 Celery worker 配置中注册 `memory_ai_extraction` 任务

### Search 子任务

- [ ] **T13**：在 `memory/schemas.py` 中添加 `MemoryFilters`、`MemorySearchRequest`、`MemorySearchItem`、`MemorySearchResponse`
- [ ] **T14**：实现 `memory/filters.py`（`normalize_memory_filters`）
- [ ] **T15**：实现 `memory/query_builder.py`（`detect_task_id_in_query`、`build_memory_query_spec`）
- [ ] **T16**：实现 `memory/repositories/memory_search_repository.py`（`MemorySearchRepository`，双路检索）
- [ ] **T17**：实现 `memory/result_mapper.py`（全部 5 个函数）
- [ ] **T18**：实现 `memory/memory_search_service.py`（`MemorySearchService.search` 编排）
- [ ] **T19**：在 `memory_api.py` 中添加 `POST /api/v1/memory/search` 端点

### OpenSearch 子任务

- [ ] **T20**：添加 `bible_atlas_memory` 索引 mapping 定义
- [ ] **T21**：添加 `bible_atlas_memory_chunks` 索引 mapping 定义
- [ ] **T22**：在系统启动流程中注册 MEMORY 相关索引自动创建逻辑

---

## 附录 A：Search Response 示例

```json
{
  "success": true,
  "total": 1,
  "memories": [
    {
      "memory_id": "memory-20260408-cni12345",
      "title": "CNI-12345 allocate 函数 NPE 根因分析与修复",
      "abstract": "分析 CNI-12345 中 allocate 函数在并发场景下因未判空导致 NPE 的根因，并给出修复方案。",
      "overview_excerpt": "本次 memory 聚焦 CNI-12345 缺陷。用户提供了堆栈信息，AI 定位到 allocate() 第 87 行...",
      "feature_tags": ["cni", "memory-allocator"],
      "task_ids": ["CNI-12345"],
      "domain_tags": ["concurrency", "memory-management"],
      "component_tags": ["cpnb", "allocator"],
      "created_at": "2026-04-08T09:30:00Z",
      "score": 0.945,
      "match_scope": "message",
      "matched_message_id": "m2",
      "matched_message_preview": "从堆栈来看，NPE 发生在 allocate() 第 87 行，原因是 context 对象在并发场景下未做判空...",
      "storage_path_ref": "memory://files/memory-20260408-cni12345",
      "match_reason": ["task_ids_exact", "title_fuzzy", "message_semantic"],
      "warnings": []
    }
  ]
}
```

---

## 附录 B：Import 成功响应示例

```json
{
  "success": true,
  "task_id": "task-uuid-abc123",
  "memory_id": "memory-20260408-cni12345",
  "status": "processing",
  "accepted_files": ["message.json", "meta.json"],
  "warnings": [
    "raw_message_count in meta.json (8) does not match actual message count (9), using actual count"
  ],
  "message": "Memory import task submitted. AI tag extraction will run in background."
}
```

---

## 附录 C：待讨论项

- `meta.json.abstract` 与 `meta.json.overview` 的最小长度、格式规范和是否允许空值，需要团队统一。
- `message.json` 的脱敏规则、最大体积、截断策略，需要形成通用规范。
- `task_ids`、`feature_tags`、`domain_tags` 缺失后的回填机制与 SLA 尚未定义。
- `raw_content_preview` 的默认长度、权限控制和 `raw_content_ref` 的使用方式仍需结合前端与安全方案继续讨论。
- feature 号究竟统一建模为 `feature_tags` 还是 `task_ids` 的一个子类，需要团队统一，否则查询字段会漂移。
