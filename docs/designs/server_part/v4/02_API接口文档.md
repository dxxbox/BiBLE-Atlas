# API 接口文档（v4）

本文档给出 v4 的 API 详细契约。  
v4 不是 v3 的“参数兼容版”，而是按 `KNOWLEDGE_BASE/SKILL/MEMORY` 三域独立演进的新接口体系。

---

## 1. 路由组织规则

### 1.1 目录规则

- 不使用 `app/api/v1/`
- 路由目录固定为：
  - `app/api/import/`
  - `app/api/search/`
  - `app/api/download/`
  - `app/api/control/`

### 1.2 文件命名规则

- 文件统一 `*_api.py`
- 三域接口即使请求体相近也分开实现，便于后续按域独立调整

---

## 2. API 文件映射

### 2.1 Import APIs

| 文件 | 方法 | 路径 | 说明 |
|---|---|---|---|
| `app/api/import/knowledge_base_import_api.py` | `POST` | `/api/import/knowledge-base` | KNOWLEDGE_BASE 导入 |
| `app/api/import/skill_import_api.py` | `POST` | `/api/import/skill` | SKILL 导入 |
| `app/api/import/memory_import_api.py` | `POST` | `/api/import/memory` | MEMORY 导入 |

### 2.2 Search APIs

| 文件 | 方法 | 路径 | 说明 |
|---|---|---|---|
| `app/api/search/knowledge_base_search_api.py` | `POST` | `/api/search/knowledge-base` | KNOWLEDGE_BASE 检索 |
| `app/api/search/skill_search_api.py` | `POST` | `/api/search/skill` | SKILL 检索 |
| `app/api/search/memory_search_api.py` | `POST` | `/api/search/memory` | MEMORY 检索 |

### 2.3 Download APIs

| 文件 | 方法 | 路径 | 说明 |
|---|---|---|---|
| `app/api/download/skill_download_api.py` | `POST` | `/api/download/skill/file` | 提交 SKILL 单文件下载任务（异步） |
| `app/api/download/skill_download_api.py` | `POST` | `/api/download/skill/batch` | 提交 SKILL 批量下载任务（异步） |
| `app/api/download/skill_download_api.py` | `GET` | `/api/download/skill/artifact/{artifact_id}` | 拉取 SKILL 下载产物文件流 |
| `app/api/download/memory_download_api.py` | `POST` | `/api/download/memory/file` | 提交 MEMORY 单文件下载任务（异步） |
| `app/api/download/memory_download_api.py` | `POST` | `/api/download/memory/batch` | 提交 MEMORY 批量下载任务（异步） |
| `app/api/download/memory_download_api.py` | `GET` | `/api/download/memory/artifact/{artifact_id}` | 拉取 MEMORY 下载产物文件流 |

> `KNOWLEDGE_BASE` 不支持下载（非设计范围）。

### 2.4 Control APIs

| 文件 | 方法 | 路径 | 说明 |
|---|---|---|---|
| `app/api/control/docs_api.py` | `GET/PUT/DELETE` | `/api/control/docs/*` | 文档管理 |
| `app/api/control/statistics_api.py` | `GET` | `/api/control/statistics/*` | 统计与观测 |
| `app/api/control/admin_api.py` | `GET/POST` | `/api/control/admin/*` | 配置与运维 |
| `app/api/control/admin_api.py` | `GET/DELETE` | `/api/control/admin/tasks/{task_id}` | 通用异步任务状态查询/取消（含 download 任务） |

---

## 3. 统一字段定义

- `kb_index`：知识库索引（必须）。一个 `kb_index` 绑定一个解析脚本、一个 `search_profile`、一个向量模型。
- `tag`：自定义知识库索引标识（逻辑标签）。
  - KNOWLEDGE_BASE：由调用方提供（如 `design`、`flow`、`alg`）
  - SKILL：固定 `skill`
  - MEMORY：固定 `memory`
- `parser_script`：可选上传脚本文件。
- `vector_model`：可选；若首次创建索引时指定，则与索引绑定，不允许后续修改。导入落库前会触发向量化链路（本地模型检查，缺失则下载后再向量化）。

---

## 4. Import API 详细契约

请求编码统一为 `multipart/form-data`。

### 4.0 通用异步规则（KNOWLEDGE_BASE/SKILL/MEMORY）

- Import API 只负责参数校验与任务提交，不在请求线程内执行解析/入库。
- 服务端通过 `features/async_task` 将任务投递到 Celery（`task_type=import.*`），立即返回 `202 + task_id + status=queued`。
- 任务实际执行由 Celery Worker 完成；API 进程与 Worker 进程可部署在同机或不同节点。
- 若仅启动 API 未启动 Worker，请求仍可返回 `queued`，但任务不会被消费（需部署运维侧保证 Worker 常驻）。
- 测试/本地调试可使用 eager 模式（`task_always_eager=true`）避免单独起 Worker；生产环境不建议。

### 4.1 KNOWLEDGE_BASE Import

**路径**  
`POST /api/import/knowledge-base`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `files[]` | file[] | 是 | 待导入文件列表 |
| `kb_index` | string | 是 | 知识库索引名 |
| `tag` | string | 是 | 自定义知识库索引标识（如 `design/flow/alg`） |
| `parser_script` | file | 否 | 自定义解析脚本文件（`.py`） |
| `vector_model` | string | 否 | 向量模型 |
| `parser_context` | string(JSON) | 否 | 解析上下文参数 |

**请求处理规则**

1. 选择最终解析脚本：
   - 若请求包含 `parser_script`：优先使用上传脚本
   - 否则在对应域的 `parsers/` 目录查找 `parse_{tag}.py`（`SKILL/MEMORY` 分别固定为 `parse_skill.py` / `parse_memory.py`）
   - 若仍未找到：使用默认解析脚本 `parse_default.py`
2. 索引绑定规则：
   - 索引首次创建时，绑定 `kb_index -> parser_script -> search_profile -> vector_model`
   - 绑定后不可修改；若需修改必须删除索引重建
   - 绑定读写逻辑收敛在 `storage/store_knowledge_base.py`，不单独拆 `search_profile_store.py`
3. 向量化规则（仅在请求带 `vector_model` 时启用）：
   - 调用 `infrastructure/vector/vector_tool.py` 检查本地模型缓存
   - 本地不存在指定模型时，从 HuggingFace 下载后加载
   - 使用选定模型对 `chunks` 生成向量字段（如 `content_vector`）再写库
   - 启动时若 `vector.preload_on_startup=true`，会由预加载流程提前检查并加载全部配置模型
4. `KNOWLEDGE_BASE` 是总类；通过不同 `tag` 支持多类型知识索引（如 `design/flow/alg`）

**成功响应示例**

```json
{
  "success": true,
  "task_id": "import_20260422_001",
  "domain": "KNOWLEDGE_BASE",
  "kb_index": "kb_design_main",
  "tag": "design",
  "status": "queued"
}
```

### 4.2 SKILL Import

**路径**  
`POST /api/import/skill`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `files[]` | file[] | 是 | 待导入文件列表（必须且仅有一个 `.skill`，可携带其他文件） |
| `kb_index` | string | 是 | 知识库索引名 |
| `tag` | string | 是 | 固定为 `skill` |
| `parser_script` | file | 否 | 自定义解析脚本文件（`.py`） |
| `vector_model` | string | 否 | 向量模型 |
| `parser_context` | string(JSON) | 否 | 解析上下文参数 |

**规则差异**

- `tag` 必须为 `skill`
- `files[]` 中 `.skill` 包必须且仅有一个（ZIP 改后缀）
- 允许携带其他文件类型；这些文件在 `parse_skill.py` 中统一分类处理，语义解析以 `.skill`/`SKILL.md` 为主
- `.skill` 解压后必须存在固定文件 `SKILL.md`
- `parse_skill.py` 是 SKILL 唯一解析总入口：`.skill` 个数校验、非 `.skill` 分类与 `SKILL.md` 解析均在脚本内完成
- 脚本选择规则与 KNOWLEDGE_BASE 相同（先上传，再 `parse_skill.py`，最后默认脚本）
- 若请求携带 `vector_model`，同样走 `infrastructure/vector/vector_tool.py` 的“本地检查 -> 缺失下载 -> 向量化”流程

### 4.3 MEMORY Import

**路径**  
`POST /api/import/memory`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `files[]` | file[] | 是 | 待导入文件列表 |
| `kb_index` | string | 是 | 知识库索引名 |
| `tag` | string | 是 | 固定为 `memory` |
| `parser_script` | file | 否 | 自定义解析脚本文件（`.py`） |
| `vector_model` | string | 否 | 向量模型 |
| `parser_context` | string(JSON) | 否 | 解析上下文参数 |

**规则差异**

- `tag` 必须为 `memory`
- 脚本选择规则与 KNOWLEDGE_BASE 相同（先上传，再 `parse_memory.py`，最后默认脚本）
- 若请求携带 `vector_model`，同样走 `infrastructure/vector/vector_tool.py` 的“本地检查 -> 缺失下载 -> 向量化”流程

---

## 5. Search API 详细契约

请求编码统一为 `application/json`。  
三域请求体字段保持一致，但路由独立。

### 5.1 请求字段（通用）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 查询文本 |
| `tag` | string | 是 | 检索标签，决定选用哪个索引和 `search_profile` |
| `search_type` | string | 否 | `keyword/title/text/vector/hybrid` |
| `top_k` | int | 否 | 返回数量 |
| `vector_model` | string | 否 | 向量模型（若提供，必须与索引绑定模型一致） |
| `vector_weight` | float | 否 | 混合检索向量权重 |

> 不使用 `filters` 字段。

### 5.2 KNOWLEDGE_BASE Search

**路径**  
`POST /api/search/knowledge-base`

**规则**

- `query` 与 `tag` 必填
- `tag` 指向 KNOWLEDGE_BASE 某个自定义知识索引
- 服务端按 `tag` 加载绑定的 `kb_index` 和 `search_profile`，据此构造检索语句

### 5.3 SKILL Search

**路径**  
`POST /api/search/skill`

**规则**

- `query` 与 `tag` 必填
- `tag` 必须为 `skill`
- 服务端按 `skill` 绑定关系加载 `kb_index` 与 `search_profile`
- `SKILL.md` 的 `name/description/正文` 都参与检索：
  - `search_type=keyword`：主要匹配 `name`
  - `search_type=text`：匹配 `name/description/正文`
  - `search_type=vector`：向量源为 `name/description/正文`
  - `search_type=hybrid`：文本与向量混合

### 5.4 MEMORY Search

**路径**  
`POST /api/search/memory`

**规则**

- `query` 与 `tag` 必填
- `tag` 必须为 `memory`
- 服务端按 `memory` 绑定关系加载 `kb_index` 与 `search_profile`

### 5.5 检索处理流程

1. 根据路由确定域（KNOWLEDGE_BASE/SKILL/MEMORY）
2. 根据 `tag` 查找绑定记录：`kb_index + search_profile + vector_model`
3. 基于 `search_profile` 编译检索 DSL
4. 执行检索并返回结果

**检索响应示例**

```json
{
  "success": true,
  "domain": "KNOWLEDGE_BASE",
  "kb_index": "kb_design_main",
  "tag": "design",
  "total": 2,
  "results": {
    "knowledge_base": [
      {
        "doc_id": "doc_abc#1.2",
        "section_id": "1.2",
        "section_title": "周期分配入口",
        "score": 0.8731,
        "content": "......"
      }
    ]
  }
}
```

约束：

- 不返回 `chunk_id`
- 不返回 `took_ms`

---

## 6. Download API 详细契约

请求编码统一为 `application/json`。  
仅支持 `SKILL/MEMORY`，且 **单文件与批量都走异步任务**。

### 6.0 通用异步规则（SKILL/MEMORY）

- Download API 只负责参数校验与任务提交，不在请求线程内直接返回文件流。
- 服务端通过 `features/async_task` 将任务投递到 Celery（`task_type=download.*`），立即返回 `202 + task_id + status=queued`。
- 客户端通过 `/api/control/admin/tasks/{task_id}` 轮询任务状态；状态机与 import 保持一致（`queued/running/completed/failed/cancelled`）。
- 下载任务完成后，`result` 中返回 `artifact_id`、`artifact_name`、`expires_at`；客户端再调用 `/api/download/{domain}/artifact/{artifact_id}` 拉取产物。
- 下载产物按 TTL 自动清理；过期后应返回 `DOWNLOAD_ARTIFACT_EXPIRED`。
- `by-search` 下载不在当前范围，作为未来演进能力处理。

### 6.1 SKILL 单文件下载（异步）

**路径**  
`POST /api/download/skill/file`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tag` | string | 是 | 固定为 `skill` |
| `storage_path` | string | 是 | 待下载文件逻辑路径（通常来自检索结果的 `related_storage_paths`） |
| `download_name` | string | 否 | 下载文件名覆盖 |

**规则**

- `tag` 必须为 `skill`。
- 服务端按 `tag` 解析绑定得到 `kb_index`，并校验 `storage_path` 属于该索引注册文件。
- 任务完成后产出单文件 artifact（透传原始内容，文件名可由 `download_name` 覆盖）。

### 6.2 SKILL 批量下载（异步）

**路径**  
`POST /api/download/skill/batch`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tag` | string | 是 | 固定为 `skill` |
| `storage_paths` | string[] | 是 | 待打包文件路径列表 |
| `package_name` | string | 否 | ZIP 包名（默认由服务端生成） |
| `include_metadata` | bool | 否 | 是否附带元数据清单（默认 `false`） |

**规则**

- `storage_paths` 数量上限由配置控制（建议 `download.max_batch_size`）。
- 任务执行时逐项校验路径归属与存在性，失败策略按配置（全失败或跳过缺失项）执行。
- 成功后产出 ZIP artifact。

### 6.3 MEMORY 单文件下载（异步）

**路径**  
`POST /api/download/memory/file`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tag` | string | 是 | 固定为 `memory` |
| `storage_path` | string | 是 | 待下载文件逻辑路径（通常来自检索结果的 `related_storage_paths`） |
| `download_name` | string | 否 | 下载文件名覆盖 |

**规则**

- `tag` 必须为 `memory`。
- 绑定读取、路径归属校验、artifact 产出流程与 SKILL 单文件一致。

### 6.4 MEMORY 批量下载（异步）

**路径**  
`POST /api/download/memory/batch`

**请求字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tag` | string | 是 | 固定为 `memory` |
| `storage_paths` | string[] | 是 | 待打包文件路径列表 |
| `package_name` | string | 否 | ZIP 包名（默认由服务端生成） |
| `include_metadata` | bool | 否 | 是否附带元数据清单（默认 `false`） |

### 6.5 下载产物拉取

**路径**

- `GET /api/download/skill/artifact/{artifact_id}`
- `GET /api/download/memory/artifact/{artifact_id}`

**规则**

- 仅允许拉取已完成且未过期的 artifact。
- 响应为二进制流（单文件或 ZIP），并返回 `Content-Disposition`。
- 拉取成功后是否立即删除产物由配置控制（默认不立即删除，按 TTL 清理）。

### 6.6 提交响应示例（单文件/批量一致）

```json
{
  "success": true,
  "task_id": "download_20260506_001",
  "domain": "SKILL",
  "tag": "skill",
  "status": "queued"
}
```

### 6.7 任务完成结果示例（通过任务查询接口查看）

```json
{
  "task_id": "download_20260506_001",
  "status": "completed",
  "result": {
    "artifact_id": "dl_artifact_9d7c1a",
    "artifact_name": "skill_bundle_20260506.zip",
    "content_type": "application/zip",
    "size_bytes": 128734,
    "expires_at": "2026-05-07T08:00:00Z"
  }
}
```

---

## 7. 错误码

| 错误码 | HTTP | 说明 |
|---|---|---|
| `INVALID_ARGUMENT` | 400 | 参数格式或取值错误 |
| `TAG_REQUIRED` | 400 | 未提供 `tag` |
| `TAG_INVALID` | 400 | `tag` 与路由域不匹配 |
| `INDEX_BINDING_CONFLICT` | 409 | 索引已绑定，且请求绑定信息不一致 |
| `INDEX_NOT_BOUND` | 404 | 未找到 `tag` 对应绑定 |
| `PARSER_SCRIPT_RISK` | 400 | 脚本安全检查失败 |
| `PARSER_SCRIPT_TIMEOUT` | 408 | 脚本执行超时 |
| `PARSER_SCRIPT_RUNTIME_ERROR` | 422 | 脚本执行失败 |
| `PARSE_RESULT_SCHEMA_INVALID` | 422 | 解析结果结构不合法 |
| `VECTOR_MODEL_CONFLICT` | 409 | 请求向量模型与索引绑定模型不一致 |
| `FILE_REGISTRY_NOT_FOUND` | 404 | 未找到对应文件注册记录 |
| `FILE_NOT_FOUND` | 404 | 文件注册存在但存储层文件不存在 |
| `DOWNLOAD_LIMIT_EXCEEDED` | 400 | 批量下载数量超出限制 |
| `ZIP_BUILD_FAILED` | 500 | 批量打包失败 |
| `DOWNLOAD_ARTIFACT_NOT_FOUND` | 404 | 下载产物不存在 |
| `DOWNLOAD_ARTIFACT_EXPIRED` | 410 | 下载产物已过期 |
| `INTERNAL_ERROR` | 500 | 服务内部错误 |

