# Memory 信息上传详细设计

> 版本：v2.0
> 状态：设计阶段
> 关联文档：
> - [`01_架构总览.md`](../server_part/v4/01_架构总览.md) — 服务端架构总览
> - [`02_API接口文档.md`](../server_part/v4/02_API接口文档.md) — API 契约（**权威**）
> - [`import_implementations/memory_import_implementation.md`](../server_part/v4/import_implementations/memory_import_implementation.md) — MEMORY Import 详细实现
> - [`import_implementations/memory_meta_parser_implementation.md`](../server_part/v4/import_implementations/memory_meta_parser_implementation.md) — `parse_memory.py` 实现规范（meta.json 字段约束权威）
> - [`search_implementation/memory_search_implementation.md`](../server_part/v4/search_implementation/memory_search_implementation.md) — MEMORY Search 实现
> - [`download_implementation/memory_download_implementation.md`](../server_part/v4/download_implementation/memory_download_implementation.md) — MEMORY Download 实现
> - [`07_Celery通用异步任务机制设计与实现.md`](../server_part/v4/07_Celery通用异步任务机制设计与实现.md) — 通用异步任务机制
> - [`message-json-acquisition-design.md`](./message-json-acquisition-design.md) — 多客户端 message.json 采集规范

---

## 1. 设计定位与范围

### 1.1 本文档定位

MEMORY 域用于会话类记忆；导入使用专属端点 `POST /api/import/memory`，与同域 search/download 配套。
import/download 均改为 Celery 通用异步任务模型（立即返回 `202 + task_id`），通过 `/api/control/admin/tasks/{task_id}` 统一查询任务状态。

**本文档填补以下空白**：

- client 端如何构造符合约定的 `meta.json` 和 `message.json`，并**上传到服务端**；
- 上传的 **API 协议**（端点、请求格式、响应格式）与异步任务查询；
- `bible-cli` 的 **memory 命令设计**；
- client 端实现时与 **Skill 上传共享的基础设施**以及差异点；
- 幂等性、去重、失败重试、安全校验规则。

### 1.2 非目标

- 不重写服务端 import 分支实现（`parse_memory.py`、`store_memory.py` 等）。
- 不重写 `message-json-acquisition-design.md` 中的采集/转换逻辑。
- 不设计服务端解析脚本（`parser_script`）上传方案（采用服务端默认 `parse_memory.py`）。
- 不扩展 memory delete、权限控制的完整设计。

### 1.3 文件集合基线

MEMORY Import 的核心约定（来自 `memory_meta_parser_implementation.md`）：

| 文件 | 角色 | 生成方 | 约束 |
|------|------|------|------|
| `meta.json` | 结构化元数据主文件（**必须**，有且仅一个） | **client 端构造并上传** | `memory_id`、`title`、`abstract` 为必填字段 |
| `message.json` | 原始会话事实源（**附件**，可选） | client 端采集器产出 | 通过 `local_file_storage_plan` 落盘，不参与检索内容生成 |
| 其他附件 | 辅助文件（可选） | client 端提供 | 同 `message.json`，作为附件存储 |

> **约定摘要**：
> - `meta.json` 是服务端 `parse_memory.py` 解析的**主体输入**，其中 `abstract`/`overview` 字段由 **client 端构造**后传入（不再由服务端 LLM 事后生成）。
> - `message.json` 从原来的"必须主文件"降格为"附件"，仅落盘到文件系统，不参与检索 chunk 生成。
> - 当前 API 不使用 `files_config`、`validation_mode`、`import_options` 等字段。
> - 每次请求必须携带 `kb_index`（知识库索引名）和 `tag="memory"`。

---

## 2. 与 Skill 上传的重叠分析

### 2.1 两者在 client 端的定位对比

| 维度 | Memory 上传 | Skill 上传 |
|------|------|------|
| 触发方式 | 手动（CLI 命令 / LM 工具调用） | 手动（CLI）+ CI 流程 |
| 上传内容 | `meta.json`（主文件）+ 可选 `message.json`/其他附件 | `.skill` ZIP 包（包含 `SKILL.md`） |
| 内容来源 | 多客户端采集（VS Code / Cursor / Copilot CLI）后 client 端构造 | skill-creator 脚本打包 |
| 上传端点 | `POST /api/import/memory` | `POST /api/import/skill` |
| 同步/异步 | 异步（Celery），立即返回 `task_id`，状态机：`queued/running/retrying/completed/failed/cancelled` | 异步（Celery），立即返回 `task_id` |
| 幂等键 | `memory_id`（来自 `meta.json`，client 端生成）+ `kb_index` 绑定 | `kb_index` 绑定 + `SKILL.md` 中的 `name` |
| 大小范围 | `meta.json` 通常 < 10 KB；`message.json` 附件 10 KB–20 MB | 通常 < 10 MB（含辅助脚本） |
| 必填参数 | `files[]`、`kb_index`、`tag="memory"` | `files[]`、`kb_index`、`tag="skill"` |
| 任务状态查询 | `GET /api/control/admin/tasks/{task_id}` | `GET /api/control/admin/tasks/{task_id}` |

### 2.2 client 端可共享的基础设施

以下模块在 memory 上传和 skill 上传中的逻辑几乎相同，**推荐共享**：

| 模块 | 位置建议 | 说明 |
|------|------|------|
| `BibleAPIClient` | `bible-cli/core/api_client.py` | 统一 HTTP 客户端，管理 `BIBLE_SERVER_URL`、认证头、超时、重试 |
| 配置加载 | `bible-cli/core/config.py` | 读取 `~/.bible/config.yaml` 或环境变量 |
| 进度显示 | `bible-cli/core/progress.py` | 上传进度条、状态轮询提示 |
| 错误处理映射 | `bible-cli/core/errors.py` | HTTP 4xx/5xx → CLI 友好错误消息 |
| 哈希计算 | `bible-cli/core/hash_utils.py` | SHA-256 内容指纹（用于幂等性判断） |
| 任务轮询 | `bible-cli/core/task_poller.py` | 通用 `GET /api/control/admin/tasks/{task_id}` 轮询（memory/skill/download 共用） |

### 2.3 client 端不应共享的部分

| 差异点 | Memory | Skill |
|------|------|------|
| 文件准备逻辑 | 构造 `meta.json`（约定格式）、准备 `message.json` 等附件、构建 multipart | 读取 `.skill` ZIP、解析 `SKILL.md`、校验 frontmatter |
| API 端点 | `/api/import/memory` | `/api/import/skill` |
| 必填请求字段 | `kb_index`、`tag="memory"` | `kb_index`、`tag="skill"` |
| 幂等性依据 | `memory_id`（client 端生成，写入 `meta.json`）+ `kb_index` 绑定冲突检测 | `kb_index` 绑定 + `.skill` 包内容 |
| meta.json 构造 | client 端必须构造（约定格式），含 `memory_id/title/abstract/overview/tags` | 不涉及 |
| 本地缓存文件 | `.bible-memory-cache.json`（含 `task_id`、`memory_id`、`kb_index`） | `.bible-skill-cache.json` |

---

## 3. 上传包格式规范

### 3.1 上传包内容

client 上传时以 **multipart/form-data** 发送，核心字段如下：

| 字段名 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File（JSON） | **必填** | 约定格式 `meta.json`（有且仅一个，含 `memory_id/title/abstract` 等字段） |
| `files` | File（JSON/任意格式） | 可选 | `message.json` 或其他附件（可多个），作为关联附件落盘 |
| `kb_index` | string | **必填** | 知识库索引名（如 `kb_memory_main`），同一 `kb_index` 首次导入时与解析配置绑定 |
| `tag` | string | **必填** | 固定为 `memory` |
| `parser_script` | File（`.py`） | 可选 | 自定义解析脚本（通常不传，使用服务端默认 `parse_memory.py`） |
| `vector_model` | string | 可选 | 向量模型名（首次使用时与 `kb_index` 绑定，后续必须一致） |
| `parser_context` | string（JSON） | 可选 | 透传给解析脚本的上下文参数 |

> **重要约束**：
> - `meta.json` 在上传的 `files[]` 中**有且仅有一个**（由服务端 `file_classifier.py` 按文件名识别）。
> - 不再使用 `files_config`、`validation_mode`、`import_options`、`X-Content-Hash` 等字段。
> - `kb_index` 与 `tag`、`parser_script`、`vector_model` 在首次导入时绑定后**不可修改**；修改须删除索引重建。

### 3.2 约定格式 `meta.json` 构造规范

`meta.json` 是服务端解析的**核心主文件**，client 必须在上传前完整构造。

#### 3.2.1 字段定义

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| `memory_id` | string | **必填** | 非空，全局唯一 | memory 文档唯一标识；推荐从 `session_id` 派生 |
| `title` | string | **必填** | ≤ 200 字符 | session 标题 |
| `abstract` | string | **必填** | ≤ 500 字符 | 一句话摘要（由 client 构造） |
| `overview` | string | 可选 | ≤ 2000 字符 | 段落级总结（可为空） |
| `created_at` | string | 可选 | ISO8601 格式 | session 创建时间 |
| `updated_at` | string | 可选 | ISO8601 格式 | session 最后更新时间 |
| `task_ids` | string[] | 可选 | — | 关联任务/工单 ID 列表（用于 keyword 检索） |
| `feature_tags` | string[] | 可选 | — | 功能特性标签（用于 keyword 检索） |
| `domain_tags` | string[] | 可选 | — | 业务域标签（用于 keyword 检索） |
| `component_tags` | string[] | 可选 | — | 组件标签（用于 keyword 检索） |
| `source_client` | string | 可选 | — | 采集来源（如 `"cursor"`、`"vscode"`、`"copilot-cli"`） |
| `language` | string | 可选 | 默认 `"zh"` | 内容语言 |

#### 3.2.2 `meta.json` 样例

```json
{
  "memory_id": "mem_request_0b60e0ce-782c-4b6d-9ec1-e66b097e5007",
  "title": "CNI allocator 并发锁竞争问题排查",
  "abstract": "排查 CNI allocator 在高并发场景下的死锁问题，定位到 LockManager 中竞态条件，修复方案为引入读写锁分离。",
  "overview": "本次 session 覆盖：1) 复现并发死锁场景；2) 使用 pprof 采集 goroutine stack；3) 定位 LockManager.Acquire() 竞态；4) 验证读写锁修复效果。涉及组件：CNI-allocator v2.3、LockManager、pprof 工具链。",
  "created_at": "2026-04-23T10:00:00Z",
  "updated_at": "2026-04-23T11:30:00Z",
  "task_ids": ["CNI-12345", "BUG-9876"],
  "feature_tags": ["cni", "allocator", "concurrency"],
  "domain_tags": ["networking", "scheduler"],
  "component_tags": ["LockManager", "CniAllocator"],
  "source_client": "cursor",
  "language": "zh"
}
```

#### 3.2.3 client 端 `meta.json` 构造策略

从 `message.json` 自动构造 `meta.json` 的推荐策略：

| 字段 | 构造来源 | 降级策略 |
|------|------|------|
| `memory_id` | `"mem_" + message.json.session_id`（去掉 `request_` 前缀后保留） | 若无 `session_id`，使用 `"mem_" + sha256(file_path)[:16]` |
| `title` | message.json 中第一条用户消息前 100 字符 | 使用文件名或 `"Session {date}"` |
| `abstract` | message.json 中第一条用户消息前 300 字符（+ 截断提示） | 使用 title 内容 |
| `overview` | 可选：聚合 session 中前 N 轮问答摘要 | 留空 |
| `created_at` | `message.json.requests[0].timestamp` 或文件 `mtime` | 当前时间 |
| `task_ids` | 从消息内容提取（正则匹配任务编号格式） | 留空 |
| `feature_tags` / `domain_tags` | 用户可在 CLI 命令行显式传入 | 留空 |
| `source_client` | `message.json.sourceClient.kind` | `"unknown"` |

### 3.3 本地输出目录结构（client 端）

```text
<output_base>/
└── <session_id>/
    ├── message.json              # 必须：采集器主要产出（作为附件上传）
    ├── meta.json                 # 必须：client 端构造，上传主文件
    ├── message.source.json.gz    # 可选：原始 JSONL 快照（仅本地保留，不上传）
    ├── message.convert.log       # 可选：转换告警（仅本地保留，不上传）
    └── .bible-memory-cache.json  # 上传后写入：上传状态缓存
```

`.bible-memory-cache.json` 格式：

```json
{
  "memory_id": "mem_request_0b60e0ce-782c-4b6d-9ec1-e66b097e5007",
  "kb_index": "kb_memory_main",
  "meta_hash": "sha256:7a3f...",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "upload_status": "completed",
  "uploaded_at": "2026-04-23T10:00:00Z",
  "server_url": "http://bible-atlas.example.com"
}
```

> **本地缓存字段**：记录 `task_id`、`memory_id`、`kb_index`、`meta_hash`（对 `meta.json` 的稳定哈希，用于去重）等。

---

## 4. 上传 API 协议

### 4.1 端点设计

MEMORY 导入使用独立端点 `POST /api/import/memory`（multipart），与同域其他能力拆分。

```
POST /api/import/memory
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

> `POST /api/import/memory` 为 MEMORY 导入入口；`tag="memory"` 固定；multipart 须包含 `meta.json`（主文件）与 `message.json` 等附件。

### 4.2 请求示例

```
POST /api/import/memory HTTP/1.1
Authorization: Bearer eyJ...
Content-Type: multipart/form-data; boundary=----FormBoundaryXYZ

------FormBoundaryXYZ
Content-Disposition: form-data; name="files"; filename="meta.json"
Content-Type: application/json

{
  "memory_id": "mem_request_0b60e0ce-782c-4b6d-9ec1-e66b097e5007",
  "title": "CNI allocator 并发锁竞争问题排查",
  "abstract": "排查 CNI allocator 在高并发场景下的死锁问题，定位到竞态条件，修复方案为引入读写锁分离。",
  "overview": "...",
  "created_at": "2026-04-23T10:00:00Z",
  "task_ids": ["CNI-12345"],
  "feature_tags": ["cni", "allocator"],
  "domain_tags": ["networking"],
  "source_client": "cursor"
}
------FormBoundaryXYZ
Content-Disposition: form-data; name="files"; filename="message.json"
Content-Type: application/json

{ "schema_version": "1.0", "session_id": "request_0b60e0ce-...", "requests": [...] }
------FormBoundaryXYZ
Content-Disposition: form-data; name="kb_index"

kb_memory_main
------FormBoundaryXYZ
Content-Disposition: form-data; name="tag"

memory
------FormBoundaryXYZ--
```

### 4.3 成功响应（202 Accepted）

服务端立即返回 `task_id`，Celery Worker 异步执行解析、向量化和入库：

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "domain": "MEMORY",
  "kb_index": "kb_memory_main",
  "tag": "memory",
  "status": "queued"
}
```

> **202 响应体**：含 `task_id`、`domain`、`kb_index`、`tag`；`status` 初始为 `"queued"`。

### 4.4 幂等命中响应

幂等处理基于 `kb_index` 绑定机制。若相同 `memory_id`（在 `meta.json` 中）已存在于同一 `kb_index`，服务端执行幂等 upsert（不报错，覆盖写入）。若首次导入时 `kb_index` 已绑定但请求参数与绑定不一致（如 `vector_model` 冲突），则返回冲突错误：

```json
{
  "success": false,
  "error_code": "INDEX_BINDING_CONFLICT",
  "message": "kb_index 'kb_memory_main' is already bound with different configuration",
  "current_binding": {
    "vector_model": "bge-large-zh-v1.5",
    "tag": "memory"
  }
}
```

### 4.5 错误响应（错误码）

| HTTP 状态码 | 错误码 | 场景 |
|------|------|------|
| 400 | `INVALID_ARGUMENT` | 参数格式或取值错误 |
| 400 | `TAG_REQUIRED` | 未提供 `tag` |
| 400 | `TAG_INVALID` | `tag` 非 `memory` |
| 400 | `PARSER_SCRIPT_RISK` | 上传的自定义脚本安全检查失败 |
| 408 | `PARSER_SCRIPT_TIMEOUT` | 脚本执行超时 |
| 409 | `INDEX_BINDING_CONFLICT` | `kb_index` 已绑定，参数不一致（如 `vector_model` 冲突） |
| 409 | `VECTOR_MODEL_CONFLICT` | 请求 `vector_model` 与索引绑定不一致 |
| 422 | `PARSER_SCRIPT_RUNTIME_ERROR` | 脚本执行失败 |
| 422 | `PARSE_RESULT_SCHEMA_INVALID` | `meta.json` 格式校验失败（必填字段缺失/超长） |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |

#### client 端 meta.json 校验失败的典型错误

| 服务端错误码 | 触发条件 | client 提示 |
|------|------|------|
| `PARSE_RESULT_SCHEMA_INVALID` | `memory_id`/`title`/`abstract` 缺失 | "meta.json 缺少必填字段，请补充后重试" |
| `PARSE_RESULT_SCHEMA_INVALID` | `abstract` 超过 500 字符 | "abstract 过长（>500字符），请截断后重试" |
| `PARSE_RESULT_SCHEMA_INVALID` | `meta.json` 不存在或多于一个 | "上传文件中必须有且仅有一个 meta.json" |
| `INDEX_BINDING_CONFLICT` | `vector_model` 与绑定不一致 | "kb_index 已绑定不同的向量模型，如需变更请联系管理员删除索引后重建" |

### 4.6 异步任务状态查询

```
GET /api/control/admin/tasks/{task_id}
Authorization: Bearer <token>
```

> 与 import/download 等异步任务共用同一套任务查询接口。

响应（任务进行中）：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "import.memory",
  "status": "running",
  "retry_count": 0,
  "max_retries": 3,
  "result": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-04-23T10:00:00Z",
  "updated_at": "2026-04-23T10:00:12Z"
}
```

响应（任务完成）：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "import.memory",
  "status": "completed",
  "retry_count": 0,
  "max_retries": 3,
  "result": {
    "local_store_count": 1,
    "content_store_result": {
      "indexed_chunks": 1
    }
  },
  "error_code": null,
  "error_message": null,
  "created_at": "2026-04-23T10:00:00Z",
  "updated_at": "2026-04-23T10:00:45Z"
}
```

响应（任务失败）：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "import.memory",
  "status": "failed",
  "retry_count": 3,
  "max_retries": 3,
  "result": null,
  "error_code": "PARSE_RESULT_SCHEMA_INVALID",
  "error_message": "meta.json missing required field: abstract",
  "created_at": "2026-04-23T10:00:00Z",
  "updated_at": "2026-04-23T10:01:20Z"
}
```

任务状态机完整流转：`queued → running → retrying（可选）→ completed | failed | cancelled`

### 4.7 幂等性与去重设计

| 场景 | 处理策略 |
|------|------|
| 相同 `memory_id` + 相同 `kb_index`（内容更新） | 服务端执行幂等 upsert，覆盖原有文档；client 检查本地缓存 `meta_hash` 决定是否跳过网络请求 |
| 相同 `kb_index` 但首次绑定参数冲突（`vector_model` 不一致） | 服务端返回 `409 INDEX_BINDING_CONFLICT`；client 不重试，提示用户检查配置 |
| `meta.json` 缺失或格式错误 | 服务端返回 `422 PARSE_RESULT_SCHEMA_INVALID`；client 不重试，提示修复后重试 |
| 网络超时 / 5xx 错误 | client 执行指数退避重试（≤ 3 次）；task_id 若已创建，可通过查询接口续查状态 |
| 本地缓存 `upload_status=completed` + `meta_hash` 未变 | client 跳过上传，不发送网络请求 |

> client 端幂等策略要点：
> 1. 上传前计算 `meta.json` 的 SHA-256（`meta_hash`）。
> 2. 检查本地 `.bible-memory-cache.json`：若 `upload_status=completed` 且 `meta_hash` 匹配，直接跳过。
> 3. 去重以 `memory_id` + `kb_index` 为准，不依赖 import jobs 列表查询。
> 4. `memory_id` 必须由 client 端稳定生成（同一 session 每次生成结果一致），用于服务端 upsert 的 document key。

---

## 5. bible-cli Memory 命令设计

### 5.1 命令清单

```bash
# 上传单个 session 目录（含 meta.json + message.json）
bible-cli memory upload <session_dir> [options]

# 批量上传（扫描目录下所有 session 子目录）
bible-cli memory upload-all <base_dir> [options]

# 查询上传任务状态
bible-cli memory status <task_id_or_memory_id>

# 列出已上传的 memory（语义搜索 + 过滤）
bible-cli memory list [--page N] [--limit N] [--tag TAG] [--since DATE]

# 搜索 memory（语义搜索）
bible-cli memory search <query> [--top-k N] [--search-type keyword|title|text|vector|hybrid]

# 查看本地缓存状态（已上传/未上传/待重试）
bible-cli memory cache-status [<base_dir>]

# 下载 memory 文件（两阶段异步）
bible-cli memory download <memory_id_or_storage_path> [--wait] [--output <dir>]
```

### 5.2 memory upload 命令详解

**命令格式**：

```bash
bible-cli memory upload <session_dir> \
  [--kb-index <kb_index>] \
  [--skip-if-exists] \
  [--vector-model <model>] \
  [--task-ids <id1,id2>] \
  [--feature-tags <tag1,tag2>] \
  [--domain-tags <tag1,tag2>] \
  [--wait] \
  [--output json|table]
```

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|------|------|
| `<session_dir>` | 必填 | 包含 `message.json`（可选 `meta.json`）的目录路径 |
| `--kb-index` | 来自配置 `memory.upload.kb_index` | 知识库索引名，同一 kb_index 首次导入时绑定配置 |
| `--skip-if-exists` | `true` | 若本地缓存 `upload_status=completed` 且 `meta_hash` 未变，跳过上传 |
| `--vector-model` | 来自配置 `memory.upload.vector_model` | 向量模型（首次绑定后不可改） |
| `--task-ids` | 无 | 附加任务 ID 标签（追加到 meta.json `task_ids`） |
| `--feature-tags` | 无 | 附加功能标签（追加到 meta.json `feature_tags`） |
| `--domain-tags` | 无 | 附加业务域标签（追加到 meta.json `domain_tags`） |
| `--wait` | `false` | 等待异步 task 完成后再退出，显示最终状态 |
| `--output` | `table` | 输出格式 |

**执行流程（伪代码）**：

```python
async def cmd_memory_upload(
    session_dir: Path,
    kb_index: str,
    skip_if_exists: bool,
    vector_model: str | None,
    extra_task_ids: list[str],
    extra_feature_tags: list[str],
    wait: bool,
):
    config = load_config()
    kb_index = kb_index or config.memory.upload.kb_index

    # 1. 检查 message.json 存在
    message_json_path = session_dir / "message.json"
    if not message_json_path.exists():
        raise CliError("message.json not found in session dir")

    # 2. 构造或加载 meta.json（约定格式）
    meta_json_path = session_dir / "meta.json"
    if not meta_json_path.exists():
        meta = build_meta_from_message_json(
            message_json_path,
            extra_task_ids=extra_task_ids,
            extra_feature_tags=extra_feature_tags,
        )
        save_meta_json(meta_json_path, meta)
    else:
        meta = load_meta_json(meta_json_path)
        # 追加命令行传入的额外标签
        meta = merge_tags(meta, extra_task_ids, extra_feature_tags)
        save_meta_json(meta_json_path, meta)

    # 3. 校验 meta.json 必填字段
    validate_meta_json(meta)  # 检查 memory_id/title/abstract

    # 4. 计算 meta_hash 并检查本地缓存
    meta_hash = sha256_file(meta_json_path)
    cache = load_local_cache(session_dir)
    if skip_if_exists and cache:
        if (cache.get("meta_hash") == meta_hash
                and cache.get("upload_status") == "completed"
                and cache.get("kb_index") == kb_index):
            print(f"[SKIP] {meta['memory_id']}: already uploaded with same meta content.")
            return

    # 5. 构建 multipart 请求（约定格式）
    upload_files = [
        ("files", ("meta.json", open(meta_json_path, "rb"), "application/json")),
        ("files", ("message.json", open(message_json_path, "rb"), "application/json")),
    ]
    form_data = {
        "kb_index": kb_index,
        "tag": "memory",
    }
    if vector_model:
        form_data["vector_model"] = vector_model

    # 6. 调用 BibleAPIClient 发起上传
    response = await api_client.post(
        "/api/import/memory",
        files=upload_files,
        data=form_data,
    )

    task_id = response.get("task_id")
    status = response.get("status", "unknown")
    print(f"[OK] {meta['memory_id']}: status={status}, task_id={task_id}")

    # 7. 写本地缓存（约定格式）
    save_local_cache(session_dir, {
        "memory_id": meta["memory_id"],
        "kb_index": kb_index,
        "meta_hash": meta_hash,
        "task_id": task_id,
        "upload_status": "pending",
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "server_url": api_client.base_url,
    })

    # 8. 若 --wait，轮询任务状态
    if wait and task_id:
        final = await poll_task_status(task_id)
        update_local_cache(session_dir, {"upload_status": final["status"]})
        print_task_result(final)
```

**`build_meta_from_message_json` 参考实现**：

```python
def build_meta_from_message_json(
    message_json_path: Path,
    extra_task_ids: list[str] | None = None,
    extra_feature_tags: list[str] | None = None,
) -> dict:
    data = json.loads(message_json_path.read_text(encoding="utf-8"))

    session_id = (
        data.get("session_id")
        or data.get("requestId")
        or data.get("sourceClient", {}).get("sessionId")
        or ""
    )
    memory_id = f"mem_{session_id}" if session_id else f"mem_{sha256_str(str(message_json_path))[:16]}"

    # 提取第一条用户消息作为 title 和 abstract
    first_user_text = ""
    for req in data.get("requests", []):
        text = req.get("message", {}).get("text", "")
        if text:
            first_user_text = text
            break

    title = first_user_text[:100].strip() or f"Session {date.today()}"
    abstract = first_user_text[:300].strip() or title

    source_client = data.get("sourceClient", {}).get("kind", "unknown")
    created_at = _extract_timestamp(data)

    return {
        "memory_id": memory_id,
        "title": title,
        "abstract": abstract,
        "overview": "",
        "created_at": created_at,
        "task_ids": list(extra_task_ids or []),
        "feature_tags": list(extra_feature_tags or []),
        "domain_tags": [],
        "component_tags": [],
        "source_client": source_client,
        "language": "zh",
    }
```

### 5.3 memory upload-all 命令详解

```bash
bible-cli memory upload-all ~/.cursor/projects/var-fpwork-linpan-gnb/agent-transcripts \
  --kb-index kb_memory_main \
  --skip-if-exists \
  --workers 3
```

- 扫描 `<base_dir>` 下每个子目录，若包含 `message.json` 则视为 session 目录。
- 若目录内不存在 `meta.json`，自动构造并写入后再上传。
- 并发上传，默认 `--workers 3`。
- 汇总打印上传结果：`success N / skipped N / failed N`。

### 5.4 memory status 命令详解

```bash
bible-cli memory status 550e8400-e29b-41d4-a716-446655440000      # 按 task_id 查询
bible-cli memory status --memory-id mem_request_0b60e0ce-...      # 从本地缓存查 task_id
```

- 按 `task_id` 调用 `GET /api/control/admin/tasks/{task_id}`；
- 若传入 `--memory-id`，先从本地 `.bible-memory-cache.json` 查找 `task_id` 再请求服务端；
- 输出 `status / task_type / retry_count / result / error_code / error_message`。

> 任务状态查询：`GET /api/control/admin/tasks/{task_id}`。

### 5.5 memory search 命令详解

```bash
bible-cli memory search "CNI allocator 锁竞争" \
  --top-k 5 \
  --search-type hybrid \
  --vector-model bge-large-zh-v1.5
```

调用 `POST /api/search/memory`：

```json
{
  "query": "CNI allocator 锁竞争",
  "tag": "memory",
  "search_type": "hybrid",
  "top_k": 5,
  "vector_model": "bge-large-zh-v1.5"
}
```

Search 返回字段（最小稳定字段集）：

| 字段 | 说明 |
|------|------|
| `memory_id` | memory 文档唯一标识 |
| `title` | 标题 |
| `abstract` | 一句话摘要 |
| `overview` | 段落级总结 |
| `task_ids` / `*_tags` | 关联标签 |
| `metadata.related_storage_paths` | 关联文件路径（用于二阶段下载） |
| `score` | 检索相关度分数 |

> **响应约定**：不返回 `chunk_id`，不返回 `took_ms`。

CLI 输出示例（`--output table`）：

```
memory_id                                    score  title
mem_request_0b60e0ce-...                     0.912  CNI allocator 并发锁竞争问题排查
mem_request_1a2b3c4d-...                     0.841  scheduler 死锁分析与修复
```

### 5.6 memory download 命令详解（两阶段异步）

Download 全异步，分两阶段：

```bash
# 提交下载任务（单文件）
bible-cli memory download \
  --storage-path "/mnt/memory/2026/05/kb_memory_main/task_001/message.json" \
  --wait \
  --output-dir ~/downloads
```

**两阶段流程**：

1. 调用 `POST /api/download/memory/file`（或 `/api/download/memory/batch`），获取 `task_id`；
2. 轮询 `GET /api/control/admin/tasks/{task_id}`，等待 `status=completed`；
3. 从 `result.artifact_id` 调用 `GET /api/download/memory/artifact/{artifact_id}` 拉取文件流。

> `storage_path` 通常来自 `memory search` 结果中的 `metadata.related_storage_paths`。

### 5.7 共享基础设施复用策略

```text
bible-cli/
├── core/
│   ├── api_client.py       # BibleAPIClient（memory 和 skill 共用）
│   ├── config.py           # 配置加载（BIBLE_SERVER_URL、auth token、kb_index 等）
│   ├── progress.py         # 进度显示（上传 bytes / task 轮询）
│   ├── errors.py           # HTTP 错误 → CLI 错误消息映射（含服务端错误码）
│   ├── hash_utils.py       # SHA-256 内容指纹
│   ├── task_poller.py      # 通用任务轮询（GET /api/control/admin/tasks/{task_id}）
│   └── meta_builder.py     # meta.json 构造工具（memory 专用）
├── commands/
│   ├── memory.py           # memory upload / upload-all / status / search / list / cache-status / download
│   └── skills.py           # skill upload / ls-skills / search-skills（已有）
└── hooks/
    └── skill_auto_download.py    # Skill 自动下载 hook（已有）
```

`task_poller.py` 是新增共享组件，memory/skill/download 三类异步任务都通过此模块轮询：

```python
class TaskPoller:
    def __init__(self, client: BibleAPIClient) -> None:
        self._client = client

    async def poll_until_done(
        self,
        task_id: str,
        interval: float = 2.0,
        timeout: float = 300.0,
    ) -> dict:
        """轮询 /api/control/admin/tasks/{task_id} 直到终态或超时"""
        terminal_states = {"completed", "failed", "cancelled"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await self._client.get(f"/api/control/admin/tasks/{task_id}")
            if result.get("status") in terminal_states:
                return result
            await asyncio.sleep(interval)
        raise TimeoutError(f"task {task_id} did not complete within {timeout}s")
```

---

## 6. 从采集到上传的完整链路

### 7.1 VS Code Copilot Chat 场景

```text
VS Code 插件 session 结束
  │
  │  插件通过 chat session API 导出 message.json（已是标准格式）
  ▼
<output_base>/<session_id>/message.json
  │
  │  bible-cli memory upload <session_dir>
  │  ├─ 自动构造 meta.json（约定格式）
  │  └─ POST /api/import/memory（multipart：meta.json + message.json）
  ▼
服务端：parse_memory.py（解析 manifest）
  │  meta.json → chunks（语义 chunk）
  │  message.json → local_file_storage_plan（附件落盘）
  ▼
store_memory.store(...)
  │  先执行文件系统落盘（message.json）
  │  后执行数据库入库（meta.json 语义字段 + 可选向量化）
  ▼
OpenSearch（kb_memory_main 索引，含 related_storage_paths 回填）
```

### 7.2 Cursor Agent Chat 场景

```text
Cursor session 执行中
  │  postToolUse hook 持续写入 tool-results.jsonl
  │
Session 结束后，用户手动执行
  │
  │  bible session export cursor
  │  → 合并 agent-transcripts/<uuid>.jsonl + tool-results.jsonl
  │  → 转换为标准 message.json
  ▼
<output_base>/<session_id>/message.json
  │
  │  bible-cli memory upload <session_dir>
  │  ├─ 构造 meta.json（从 message.json 提取 title/abstract/session_id）
  │  └─ POST /api/import/memory
  ▼
服务端处理（同上）
```

### 7.3 Copilot CLI 场景

```text
Copilot CLI session 执行
  │  events.jsonl 实时写入 ~/.copilot/session-state/<id>/
  │
Session 结束后，用户手动执行
  │
  │  bible session export copilot-cli
  │  → 转换 events.jsonl 为标准 message.json
  ▼
<output_base>/<session_id>/message.json
  │
  │  bible-cli memory upload <session_dir>
  ▼
POST /api/import/memory
  │
  ▼
服务端处理（同上）
```

---

## 8. 错误处理与降级策略

### 8.1 网络失败重试

`BibleAPIClient` 内置指数退避重试：

| 重试次数 | 等待时间 | 适用条件 |
|------|------|------|
| 第 1 次 | 1 秒 | 网络超时、连接被拒绝 |
| 第 2 次 | 4 秒 | 同上 |
| 第 3 次 | 16 秒 | 同上 |
| 超过 3 次 | 放弃 | 写失败日志，保留本地文件 |

HTTP 429（限流）时，使用服务端返回的 `Retry-After` 头等待。  
HTTP 5xx 时重试；HTTP 4xx（400、409、422）时**不重试**，直接输出错误信息。

### 8.2 服务端拒绝处理（错误码映射）

| 错误码 | client 处理 |
|------|------|
| `INVALID_ARGUMENT` | 输出错误详情，提示检查 `kb_index`/`tag` 参数 |
| `TAG_INVALID` | 提示：`tag 必须为 "memory"，请检查命令参数` |
| `PARSE_RESULT_SCHEMA_INVALID` | 输出 `error_message` 详情（含缺失字段名），提示修复 `meta.json` 后重试 |
| `INDEX_BINDING_CONFLICT` | 输出当前绑定信息，提示：`kb_index 配置已锁定，如需变更请联系管理员删除索引后重建` |
| `VECTOR_MODEL_CONFLICT` | 提示：`向量模型与 kb_index 绑定不一致，请使用 {current_binding.vector_model} 或不传 vector_model 参数` |
| `PARSER_SCRIPT_RISK` | 提示：`自定义解析脚本安全检查失败，请检查脚本内容` |
| `INTERNAL_ERROR` | 输出 `task_id`（如有），提示联系管理员并提供 `task_id` 供排查 |

### 8.3 meta.json 构造失败处理

| 场景 | 处理策略 |
|------|------|
| `message.json` 中无法提取 `session_id` | 使用 `sha256(file_path)[:16]` 生成 `memory_id`，继续上传 |
| `message.json` 无任何用户消息 | 使用文件名作为 `title`，`abstract` 使用 `"[空会话]"` |
| `meta.json` 已存在但格式不合法 | 备份原文件为 `meta.json.bak`，重新构造并覆盖 |
| `abstract` 超过 500 字符 | 自动截断至 497 字符并追加 `"..."` |
| `title` 超过 200 字符 | 自动截断至 197 字符并追加 `"..."` |

### 8.4 部分上传与状态持久化

当前设计不支持分片续传。对于大文件（`message.json` > 10 MB）：

1. client 在上传前检查文件大小；若 `message.json` 超过限制，提示用户是否继续（附件过大不影响 `meta.json` 本身导入）；
2. 若上传中断，本地 `.bible-memory-cache.json` 的 `upload_status` 保持 `"pending"`，下次 `upload-all` 时自动重试；
3. 已获取 `task_id` 的情况下，可通过 `bible-cli memory status {task_id}` 查询任务是否已完成（服务端任务状态独立于 client 缓存）。

---

## 9. 安全校验规则

### 9.1 client 端校验（上传前）

| 校验项 | 规则 | 失败处理 |
|------|------|------|
| meta.json 存在性 | 上传前必须存在 `meta.json`（不存在则自动构造） | 自动构造，构造失败则拒绝上传 |
| meta.json 必填字段 | `memory_id`、`title`、`abstract` 非空 | 拒绝上传，输出缺失字段提示 |
| 字段长度 | `title ≤ 200`，`abstract ≤ 500`，`overview ≤ 2000` | 自动截断（可配置是否截断或报错） |
| meta.json JSON 合法性 | 必须是合法 JSON | 拒绝上传，提示修复 |
| 附件文件大小 | 单文件 ≤ 20 MB（默认，可配置） | 警告提示，可跳过过大附件继续上传 |
| 路径安全 | 上传的文件路径不得包含 `../` 或绝对路径 | 强制拒绝（防止路径穿越） |
| `kb_index` 合法性 | 非空，不含特殊字符 | 拒绝上传，提示检查配置 |
| 敏感信息检测 | **可选**：扫描 `meta.json` 是否含明文密钥（正则匹配） | 提示确认，不强制阻断 |

### 9.2 服务端校验（`parse_memory.py` + `ast_guard.py` 负责，此处仅作引用）

服务端在 `parse_memory.py` 中：

- 校验 `meta.json` 有且仅有一个；
- 校验 `memory_id/title/abstract` 必填且不超长；
- `created_at/updated_at` 若提供则必须是 ISO8601 格式；
- 若上传了 `parser_script`，先经 `ASTGuard` 安全检查再在沙箱中执行。

---

## 10. 配置管理

memory 上传相关配置统一纳入 `~/.bible/config.yaml` 或环境变量：

```yaml
server:
  url: "http://bible-atlas.example.com"
  token: "<auth_token>"

memory:
  upload:
    kb_index: "kb_memory_main"          # 必填：知识库索引名
    vector_model: ""                    # 可选；首次导入时与 kb_index 绑定，留空则不做向量化
    skip_if_exists: true                # 本地缓存命中且 meta_hash 未变时跳过上传
    max_attachment_size_mb: 20          # 单附件文件大小限制（meta.json 不受此限制）
    abstract_truncate: true             # abstract 超长时是否自动截断（否则报错）
    workers: 3                          # upload-all 时的并发数
    retry_max: 3                        # 最大重试次数
    retry_backoff: "exponential"        # exponential | linear | fixed

  search:
    default_search_type: "hybrid"       # keyword | title | text | vector | hybrid
    default_top_k: 10
    vector_model: ""                    # 检索时使用的向量模型（需与导入时一致）

  download:
    poll_interval_seconds: 2.0          # 下载任务轮询间隔
    poll_timeout_seconds: 300.0         # 下载任务轮询超时

skill:
  search:
    passive_top_k: 3
    passive_threshold: 0.6
```

**环境变量覆盖**（优先级高于配置文件）：

| 环境变量 | 对应配置 |
|------|------|
| `BIBLE_SERVER_URL` | `server.url` |
| `BIBLE_TOKEN` | `server.token` |
| `BIBLE_MEMORY_KB_INDEX` | `memory.upload.kb_index` |
| `BIBLE_MEMORY_VECTOR_MODEL` | `memory.upload.vector_model` |

---

## 11. 小结

本文档归纳 Memory 信息上传在 client 端的设计要点如下：

1. **API 端点**：导入使用 `POST /api/import/memory`；任务状态查询使用 `GET /api/control/admin/tasks/{task_id}`。

2. **请求格式**：必填字段为 `files[]`、`kb_index`、`tag="memory"`；不使用 `files_config`、`validation_mode`、`import_options` 等旁路控制字段。

3. **文件角色**：`meta.json` 为必须的主文件（含 `memory_id/title/abstract/overview/tags`），由 **client 端构造**；`message.json` 为附件，通过 `local_file_storage_plan` 落盘，不参与检索内容生成。

4. **meta.json 构造工具**：新增 `meta_builder.py` 模块，从 `message.json` 自动提取 `session_id/title/abstract` 构造约定格式 `meta.json`；支持 CLI 命令行追加 `task_ids`/`feature_tags`/`domain_tags` 等标签。

5. **异步任务模型**：Import/Download 均返回 `202 + task_id`，任务状态机为 `queued → running → retrying → completed | failed | cancelled`；通用 `TaskPoller` 组件复用于 memory/skill/download 三类异步任务。

6. **幂等性**：以 `memory_id`（client 端从 `session_id` 派生）+ `kb_index` 绑定机制双重保障；本地 `.bible-memory-cache.json` 缓存（`meta_hash`）避免重复网络请求；服务端以 `memory_id` 为 document key 做幂等 upsert。

7. **kb_index 绑定机制**：首次导入某 `kb_index` 时绑定 `parser_script`、`search_profile`、`vector_model`，后续不可修改；client 必须配置并固定 `kb_index`，避免意外创建不同绑定。

8. **Search**：使用 `POST /api/search/memory`；支持 `keyword/title/text/vector/hybrid` 五种检索类型；返回 `memory_id/title/abstract/overview/tags/related_storage_paths/score`（不返回 `chunk_id`/`took_ms`）。

9. **Download（两阶段）**：先提交 `POST /api/download/memory/file`（或 `/batch`）获取 `task_id`，轮询完成后拉取 `GET /api/download/memory/artifact/{artifact_id}`。

10. **安全边界**：client 端强制校验 `meta.json` 必填字段、字段长度、文件大小和路径安全；服务端 `parse_memory.py` 仍是最终校验权威。
