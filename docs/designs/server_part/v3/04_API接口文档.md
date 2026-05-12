# API 接口文档（v3）

本文档详细说明 FastAPI 架构的所有 API 端点，消息格式与现有 API 保持一致。

---

## 服务信息

- **API 版本**: v1
- **基础路径**: `/api/v1`
- **Content-Type**: `application/json`

---

## 1. 健康检查 API

### 基本信息
- **规范端点**: `GET /api/v1/health`
- **功能**: 查询系统健康状态

### 兼容端点（当前实现保留）

为兼容 CLI 与历史调用路径，当前版本同时保留以下健康/系统探针端点：

- `GET /health`：轻量探针（`{ "status": "ok" }`）
- `GET /api/v1/system/status`：轻量探针（`{ "status": "ok" }`）
- `GET /api/v1/system/info`：系统信息 envelope（`{ "status": "ok", "result": {...} }`）

说明：

- 外部集成建议优先使用 `GET /api/v1/health` 作为健康检查规范入口。
- `system` 路径用于客户端兼容与最小探针，后续若收敛端点会在变更日志中提前声明。

### 请求示例
```bash
curl http://localhost:8000/api/v1/health
```

兼容端点示例：

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/system/status
curl http://localhost:8000/api/v1/system/info
```

### 成功响应 (200)
```json
{
  "status": "healthy",
  "elasticsearch": {
    "connected": true,
    "cluster_name": "elasticsearch",
    "version": "8.11.0",
    "nodes": 3
  },
  "redis": {
    "connected": true,
    "ping": "PONG"
  },
  "models": {
    "loaded": ["mini", "bge-large"],
    "count": 2,
    "default": "bge-large"
  },
  "version": "3.0.0",
  "timestamp": "2026-03-30T10:30:45.123Z"
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 系统状态：`healthy`, `degraded`, `unhealthy` |
| `elasticsearch` | object | ES 连接状态和版本信息 |
| `redis` | object | Redis 连接状态 |
| `models` | object | 向量模型加载状态 |
| `version` | string | 应用版本 |
| `timestamp` | string | 响应时间戳（ISO 8601） |

兼容端点响应（示例）：

```json
{
  "status": "ok"
}
```

```json
{
  "status": "ok",
  "result": {
    "version": "0.1.dev51",
    "description": "BiBLE-Atlas: Agent-native context DB"
  }
}
```

---

## 2. 检索 API

### 基本信息
- **端点**: `POST /api/v1/search`
- **功能**: 执行文档检索

### 请求参数

#### 必填参数
| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `index_name` | string | 索引名称（可被 tag 覆盖） | `"test_feng"` |
| `query` | string | 查询文本（支持 [TAG] 前缀） | `"allocate函数"` 或 `"[SCT] allocate"` |

#### 可选参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tag` | string | `null` | 知识库标签。支持: `CODE`, `SCT`, `BUILD`, `SYNTAX`, `SPEC`, `ALG`, `DESIGN`, `FLOW`, `SESSION`, `SKILL` |
| `search_type` | string | `"hybrid"` | 检索类型: `keyword`, `title`, `text`, `vector`, `hybrid` |
| `vector_model` | string | `"bge-large"` | 向量模型: `mini`, `mpnet`, `bge-base`, `bge-large`, `bge-m3`, `e5-large` |
| `top_k` | integer | `10` | 返回结果数量 (1-100) |
| `vector_weight` | float | `0.8` | 向量权重 (0.1-0.9)，仅混合检索需要 |
| `enable_relation_search` | boolean | `true` | 是否启用关联函数查询 |
| `enable_hit` | boolean | `false` | 是否启用关联知识库检索（在主检索基础上增加 CODE、BUILD、SESSION、SKILL 等知识库） |
| `filter_mode` | string | `"none"` | 过滤模式: `none`, `elbow`, `gap_statistic` |
| `ai_enable` | boolean | `false` | 是否启用 AI 增强检索 |
| `ai_model` | string | `"gpt-5-mini"` | AI 模型。可选: `gpt-4.1`, `gpt-5-mini`, `gpt-5.1`, `claude-sonnet-4.5`, `claude-sonnet-4.6` |

#### tag 字段说明

`tag` 字段用于指定要检索的知识库类型，系统会自动路由到相应的 ES 索引。

**支持的 tag 值**:
| Tag 值 | 含义 | 目标索引 | 附加内容 |
|-------|------|----------|----------|
| `CODE` | 代码库（默认） | `index_name` 参数指定的索引 | 否 |
| `SCT` | 测试用例 | `test_sct_testcase` | 否 |
| `BUILD` | 编译方法 | `test_build_method` | 否 |
| `SYNTAX` | 编码规范 | `test_coding_standards` | 否 |
| `SPEC` | 需求规格 | `test_requirement` | 否 |
| `ALG` | 算法库 | `test_algorithm` | 否 |
| `DESIGN` | 设计文档 | `test_framework` | 否 |
| `FLOW` | 流程文档 | `test_business_flow` | 否 |
| `SESSION` | 会话记录 | `test_session` | 否 |
| `SKILL` | 技能库 | `test_skill` | 否 |
| `null`/未指定 | 无标签 | `index_name` 参数指定的索引 | 取决于配置 |

#### enable_hit 字段说明

`enable_hit` 字段用于启用关联知识库检索功能。当设置为 `true` 时，系统会在主检索基础上，额外检索配置中指定的关联知识库。

**工作机制**:
1. 系统先按照 `tag` 或 `index_name` 确定主检索索引
2. 如果 `enable_hit` 为 `true`，系统会读取配置中的 `hit_list`（默认包含 `CODE`, `BUILD`, `SESSION`, `SKILL`）
3. 将 `hit_list` 中的 tag 转换为对应的索引名（通过 `tag_to_index_mapping`）
4. 对所有索引（主检索索引 + hit_list 索引）进行并行检索
5. 合并所有检索结果并返回

**适用场景**:
- 需要在多个知识库中同时搜索相关内容
- 希望获得更全面的检索结果（例如同时查询代码、编译方法、会话记录等）

**示例**:
```json
{
  "index_name": "test_feng",
  "query": "内存分配",
  "tag": "CODE",
  "enable_hit": true,
  "top_k": 10
}
```
此请求会同时检索：`test_feng`（CODE）+ `test_build_method`（BUILD）+ `test_session`（SESSION）+ `test_skill`（SKILL）

**tag 提取规则**:
1. **query 前缀优先**: 如果 `query` 以 `[TAG]` 开头（如 `[SCT] allocate`），系统会提取 tag 并从 query 中移除前缀
2. **字段备选**: 如果 query 没有前缀，使用请求体中的 `tag` 字段值
3. **大小写不敏感**: `[sct]`, `[SCT]`, `"tag": "sct"` 都等价
4. **无效 tag 处理**: 无效 tag 会被忽略，等同于未指定 tag

### 请求示例

#### 示例 1: 最简请求（仅必填参数）
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "test_feng",
    "query": "allocate"
  }'
```

#### 示例 2: 使用 tag 字段检索 SCT 测试用例
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "test_feng",
    "query": "allocate",
    "tag": "SCT"
  }'
```

#### 示例 3: 使用 query 前缀检索编译方法
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "test_feng",
    "query": "[BUILD] cmake编译",
    "tag": "CODE"
  }'
# 实际使用: tag=BUILD, query="cmake编译", index=test_build_method
```

#### 示例 4: 混合检索（完整参数）
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "test_feng",
    "query": "SrVariablePeriodicityMgt allocate函数实现",
    "search_type": "hybrid",
    "vector_model": "bge-large",
    "top_k": 10,
    "vector_weight": 0.8,
    "enable_relation_search": true,
    "filter_mode": "none"
  }'
```

#### 示例 5: AI 增强检索
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "index_name": "test_feng",
    "query": "allocate函数的实现逻辑",
    "top_k": 5,
    "ai_enable": true,
    "ai_model": "gpt-5-mini"
  }'
# 实际检索 15 条(5×3)，AI 筛选出最佳 5 条
```

### 成功响应 (200)

#### 代码检索响应（tag=null/CODE）
```json
{
  "success": true,
  "results": {
    "code": [
      {
        "relative_code_header_file": "sr_variable_periodicity_mgt.h",
        "relative_code_source_file": "sr_variable_periodicity_mgt.cc",
        "relative_ut_file": "test_sr_variable_periodicity_mgt.cc",
        "relative_function_list": [
          "## 函数签名\n\n**函数签名**: `void allocate(...)`\n\n## 用途\n\n分配SR资源...\n\n## 逻辑描述\n\n该函数负责...",
          "## 函数签名\n\n**函数签名**: `void release(...)`\n\n## 用途\n\n释放SR资源..."
        ]
      }
    ]
  },
  "total": 1
}
```

**code 数组中单个结果字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `relative_code_header_file` | string | 头文件路径 |
| `relative_code_source_file` | string | 源文件路径 |
| `relative_ut_file` | string | 单元测试文件路径（可为空） |
| `relative_function_list` | array | 该文件中的函数内容列表，每个内容为 Markdown 格式 |

#### 其他知识库检索响应

**SCT 测试用例**（tag=SCT）:
```json
{
  "success": true,
  "results": {
    "sct": [
      {
        "section_title": "SR资源分配测试",
        "content": "## 测试场景\n\n验证SR资源分配...\n\n## 测试步骤\n\n1. 初始化..."
      }
    ]
  },
  "total": 1
}
```

**章节格式结果字段**（非代码检索）:
| 字段 | 类型 | 说明 |
|------|------|------|
| `section_title` | string | 章节标题 |
| `content` | string | 章节内容（Markdown 格式） |

**results 对象结构**:
| Tag | 返回字段 | 说明 |
|-----|----------|------|
| `null`/`CODE` | `code` | 代码相关检索结果（按文件分组） |
| `SCT` | `sct` | SCT 测试用例结果（章节格式） |
| `BUILD` | `build_method` | 编译方法结果（章节格式） |
| `SYNTAX` | `coding_standards` | 编码规范结果（章节格式） |
| `SPEC` | `requirement` | 需求规格结果（章节格式） |
| `ALG` | `algorithm` | 算法库结果（章节格式） |
| `DESIGN` | `design` | 设计文档结果（章节格式） |
| `FLOW` | `flow` | 流程文档结果（章节格式） |

### 错误响应

#### 400 Bad Request - 缺少必填参数
```json
{
  "error": "Missing required field: query"
}
```

#### 400 Bad Request - 参数无效
```json
{
  "error": "Invalid search_type: invalid_type. Must be one of: keyword, title, text, vector, hybrid"
}
```

#### 400 Bad Request - 参数值超出范围
```json
{
  "error": "top_k must be between 1 and 100"
}
```

#### 500 Internal Server Error
```json
{
  "error": "Internal server error: [详细错误信息]"
}
```

---

## 3. 检索类型说明

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `keyword` | 关键字精确匹配 | 查找特定术语、函数名 |
| `title` | 标题检索 | 根据章节标题查找 |
| `text` | 文本模糊匹配 | 全文搜索 |
| `vector` | 语义向量检索 | 语义理解、相似内容 |
| `hybrid` | 向量+文本混合 | 综合语义和关键字（推荐） |

---

## 4. 向量模型说明

| 模型 | 维度 | 说明 |
|------|------|------|
| `mini` | 384 | 轻量快速，适合实时查询 |
| `mpnet` | 768 | 平衡性好，速度和效果兼顾 |
| `bge-base` | 768 | 中文优化基础版 |
| `bge-large` | 1024 | 中文优化高精度（默认，推荐） |
| `bge-m3` | 1024 | 多语言长文本支持 |
| `e5-large` | 1024 | 多语言高质量 |

---

## 5. 上传与导入 API

### 5.1 单文件上传（常规文档）

#### 基本信息
- **端点**: `POST /api/v1/upload`
- **功能**: 上传单个文件并导入到 ES 索引
- **Content-Type**: `multipart/form-data`
- **适用类型**: CODE, SCT, BUILD, SYNTAX, SPEC, ALG, DESIGN, FLOW 等

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | 上传的文件 |
| `index_name` | string | ✅ | 目标索引名称 |
| `doc_type` | string | ✅ | 文档类型：CODE, SCT, BUILD 等 |
| `use_vector` | boolean | ❌ | 是否生成向量（默认 true） |
| `vector_model` | string | ❌ | 向量模型（默认 bge-large） |
| `chunk_size` | integer | ❌ | 分块大小（默认 500） |

#### 请求示例
```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@manual.pdf" \
  -F "index_name=test_feng" \
  -F "doc_type=SPEC" \
  -F "use_vector=true" \
  -F "vector_model=bge-large"
```

#### 成功响应 (202 Accepted)
```json
{
  "success": true,
  "task_id": "abc123-456def-789ghi",
  "status": "processing",
  "message": "File uploaded and import task started"
}
```

#### 查询任务状态
- **端点**: `GET /api/v1/tasks/{task_id}`
- **响应**:
```json
{
  "task_id": "abc123-456def-789ghi",
  "status": "completed",
  "progress": 100,
  "result": {
    "documents_imported": 1234,
    "vectors_generated": 1234,
    "duration": "3m 45s"
  }
}
```

---

### 5.2 批量上传（Session/Skill 专用）

#### 基本信息
- **端点**: `POST /api/v1/sessions/upload` 或 `POST /api/v1/skills/upload`
- **功能**: 一次性上传完整的 session/skill（包含多个文件）
- **Content-Type**: `multipart/form-data`
- **适用场景**: session、skill 等需要多文件支持的文档类型

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | file[] | ✅ | 多个文件（支持不同类型） |
| `title` | string | ✅ | Session/Skill 标题 |
| `description` | string | ❌ | 描述信息 |
| `files_config` | JSON string | ✅ | 每个文件的处理配置（JSON字符串） |
| `use_vector` | boolean | ❌ | 是否生成向量（默认 true） |
| `vector_model` | string | ❌ | 向量模型（默认 bge-large） |
| `chunk_size` | integer | ❌ | 分块大小（默认 1000） |

#### files_config 格式说明

```json
[
  {
    "file_index": 0,
    "role": "main_document",
    "process_type": "parse_and_index",
    "description": "主文档"
  },
  {
    "file_index": 1,
    "role": "attachment",
    "process_type": "store_only",
    "description": "附件"
  },
  {
    "file_index": 2,
    "role": "reference_material",
    "process_type": "parse_and_index",
    "description": "参考资料"
  }
]
```

**字段说明**:
- `file_index`: 文件在 files 数组中的索引（从0开始）
- `role`: 文件角色
  - `main_document`: 主文档（必须有一个）
  - `attachment`: 附件（仅存储，不索引）
  - `reference_material`: 参考资料（需要索引）
  - `code_example`: 代码示例
- `process_type`: 处理方式
  - `parse_and_index`: 解析并索引（生成向量、分块存储）
  - `store_only`: 仅存储（不解析、不索引）
- `description`: 文件描述（可选）

#### 请求示例

```bash
curl -X POST http://localhost:8000/api/v1/sessions/upload \
  -F "files=@session_main.md" \
  -F "files=@attachment.pdf" \
  -F "files=@code_example.py" \
  -F "title=Session 标题" \
  -F "description=这是一个完整的 session" \
  -F 'files_config=[
    {"file_index": 0, "role": "main_document", "process_type": "parse_and_index"},
    {"file_index": 1, "role": "attachment", "process_type": "store_only"},
    {"file_index": 2, "role": "code_example", "process_type": "parse_and_index"}
  ]' \
  -F "use_vector=true" \
  -F "chunk_size=1000"
```

#### 成功响应 (202 Accepted)
```json
{
  "success": true,
  "session_id": "session-abc123",
  "task_id": "task-456def",
  "status": "processing",
  "files_uploaded": 3,
  "message": "Session uploaded and processing started"
}
```

#### 任务完成响应
```json
{
  "task_id": "task-456def",
  "status": "completed",
  "progress": 100,
  "result": {
    "session_id": "session-abc123",
    "files_processed": [
      {
        "filename": "session_main.md",
        "role": "main_document",
        "process_type": "parse_and_index",
        "status": "success",
        "chunks_created": 45,
        "vectors_generated": 45
      },
      {
        "filename": "attachment.pdf",
        "role": "attachment",
        "process_type": "store_only",
        "status": "success",
        "storage_path": "/app/uploads/session/2026-04-01/session-abc123/attachment.pdf"
      },
      {
        "filename": "code_example.py",
        "role": "code_example",
        "process_type": "parse_and_index",
        "status": "success",
        "chunks_created": 12,
        "vectors_generated": 12
      }
    ],
    "total_chunks": 57,
    "total_vectors": 57,
    "duration": "4m 23s"
  }
}
```

---

### 5.3 两阶段上传（Session/Skill 管理）

#### 第一阶段：创建 Session/Skill

**端点**: `POST /api/v1/sessions` 或 `POST /api/v1/skills`

**请求体**:
```json
{
  "title": "Session 标题",
  "description": "这是一个 session 的描述",
  "metadata": {
    "author": "user123",
    "tags": ["python", "tutorial"]
  }
}
```

**成功响应 (201 Created)**:
```json
{
  "success": true,
  "session_id": "session-abc123",
  "title": "Session 标题",
  "created_at": "2026-04-01T10:30:45.123Z",
  "files": []
}
```

#### 第二阶段：上传文件

**端点**: `POST /api/v1/sessions/{session_id}/files`

**请求参数** (multipart/form-data):
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | ✅ | 上传的文件 |
| `role` | string | ✅ | 文件角色：main_document, attachment, reference_material, code_example |
| `process_type` | string | ✅ | 处理方式：parse_and_index, store_only |
| `description` | string | ❌ | 文件描述 |

**请求示例**:
```bash
# 上传主文档
curl -X POST http://localhost:8000/api/v1/sessions/session-abc123/files \
  -F "file=@main.md" \
  -F "role=main_document" \
  -F "process_type=parse_and_index" \
  -F "description=主要内容"

# 上传附件
curl -X POST http://localhost:8000/api/v1/sessions/session-abc123/files \
  -F "file=@attachment.pdf" \
  -F "role=attachment" \
  -F "process_type=store_only"
```

**成功响应 (202 Accepted)**:
```json
{
  "success": true,
  "file_id": "file-def456",
  "task_id": "task-789ghi",
  "status": "processing",
  "message": "File uploaded and processing started"
}
```

#### 查询 Session/Skill 详情

**端点**: `GET /api/v1/sessions/{session_id}`

**响应**:
```json
{
  "session_id": "session-abc123",
  "title": "Session 标题",
  "description": "描述信息",
  "doc_type": "SESSION",
  "created_at": "2026-04-01T10:30:45.123Z",
  "updated_at": "2026-04-01T10:35:20.456Z",
  "files": [
    {
      "file_id": "file-001",
      "filename": "main.md",
      "role": "main_document",
      "process_type": "parse_and_index",
      "storage_path": "/app/uploads/session/2026-04-01/session-abc123/main.md",
      "indexed": true,
      "chunks_count": 45,
      "size_bytes": 12345,
      "uploaded_at": "2026-04-01T10:31:00.000Z"
    },
    {
      "file_id": "file-002",
      "filename": "attachment.pdf",
      "role": "attachment",
      "process_type": "store_only",
      "storage_path": "/app/uploads/session/2026-04-01/session-abc123/attachment.pdf",
      "indexed": false,
      "size_bytes": 54321,
      "uploaded_at": "2026-04-01T10:32:00.000Z"
    }
  ],
  "total_files": 2,
  "total_chunks": 45,
  "metadata": {
    "author": "user123",
    "tags": ["python", "tutorial"]
  }
}
```

#### 删除 Session/Skill 中的文件

**端点**: `DELETE /api/v1/sessions/{session_id}/files/{file_id}`

**响应**:
```json
{
  "success": true,
  "message": "File deleted successfully",
  "file_id": "file-002"
}
```

---

### 5.4 查询任务状态

**端点**: `GET /api/v1/tasks/{task_id}`

**适用于**: 所有异步上传任务

**响应示例**:
```json
{
  "task_id": "task-456def",
  "status": "completed",
  "progress": 100,
  "result": {
    "documents_imported": 1234,
    "vectors_generated": 1234,
    "chunks_created": 45,
    "duration": "3m 45s"
  }
}
```

**status 可能的值**:
- `pending`: 等待处理
- `processing`: 处理中
- `completed`: 完成
- `failed`: 失败

---

## 6. 索引管理 API

### 6.1 列出所有索引
- **端点**: `GET /api/v1/indices`
- **参数**: `pattern` (可选，默认 `*`)

```bash
curl "http://localhost:8000/api/v1/indices?pattern=test_*"
```

**响应**:
```json
{
  "indices": [
    {
      "name": "test_feng",
      "health": "green",
      "status": "open",
      "docs_count": 1234,
      "docs_deleted": 0,
      "store_size": "15.2mb",
      "store_size_bytes": 15925248
    }
  ],
  "total": 1
}
```

### 6.2 获取索引详情
- **端点**: `GET /api/v1/indices/{index_name}`

```bash
curl http://localhost:8000/api/v1/indices/test_feng
```

**响应**:
```json
{
  "name": "test_feng",
  "health": "green",
  "status": "open",
  "docs_count": 1234,
  "docs_deleted": 0,
  "store_size": "15.2mb",
  "store_size_bytes": 15925248,
  "shards": 3,
  "replicas": 1,
  "created_at": "2026-03-01T10:00:00",
  "field_count": 15,
  "has_vector": true,
  "vector_dimension": 1024
}
```

---

## 7. 文档管理 API

### 7.1 获取单个文档
- **端点**: `GET /api/v1/docs/{doc_id}`

```bash
curl http://localhost:8000/api/v1/docs/abc123
```

**响应**:
```json
{
  "id": "abc123",
  "index": "test_feng",
  "content": "文档内容...",
  "metadata": {
    "file_path": "src/main.cc",
    "language": "cpp"
  },
  "created_at": "2026-03-30T10:00:00"
}
```

### 7.2 更新文档
- **端点**: `PUT /api/v1/docs/{doc_id}`

```bash
curl -X PUT http://localhost:8000/api/v1/docs/abc123 \
  -H "Content-Type: application/json" \
  -d '{
    "content": "更新后的内容",
    "metadata": {
      "updated_by": "admin"
    }
  }'
```

### 7.3 删除文档
- **端点**: `DELETE /api/v1/docs/{doc_id}`

```bash
curl -X DELETE http://localhost:8000/api/v1/docs/abc123
```

**响应**:
```json
{
  "success": true,
  "message": "Document deleted successfully"
}
```

---

## 8. 文档下载 API

### 基本信息
- **功能**: 用于下载 session/skill 类型的大文档及其关联文件
- **适用场景**: session、skill 等可能包含多个文件（md、python、shell等）的文档类型

### 8.1 下载单个文档

#### 基本信息
- **端点**: `GET /api/v1/download/{document_id}`
- **功能**: 下载指定文档的原始文件

#### 路径参数
| 参数 | 类型 | 说明 |
|------|------|------|
| `document_id` | string | 文档ID（UUID格式） |

#### 请求示例
```bash
curl -O http://localhost:8000/api/v1/download/abc123-456def-789ghi
```

#### 成功响应 (200)
- **Content-Type**: `application/octet-stream` 或文件实际类型
- **Headers**:
  - `Content-Disposition: attachment; filename="session-xxx.md"`
  - `Content-Length: 12345`
  - `X-File-Hash: sha256_hash_value`

#### 错误响应

**404 Not Found - 文档不存在**:
```json
{
  "error": "Document not found",
  "document_id": "abc123-456def-789ghi"
}
```

**404 Not Found - 文件已丢失**:
```json
{
  "error": "File not found on storage",
  "document_id": "abc123-456def-789ghi",
  "file_path": "/data/documents/session/ab/abc123.md"
}
```

---

### 8.2 批量下载文档（ZIP打包）

#### 基本信息
- **端点**: `POST /api/v1/download/batch`
- **功能**: 一次性下载多个文档，自动打包为ZIP文件
- **适用场景**: 一个skill包含多个文件（md、python、shell等）

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `document_ids` | array[string] | ✅ | 文档ID列表（最多50个） |
| `package_name` | string | ❌ | ZIP文件名（默认：documents.zip） |
| `include_metadata` | boolean | ❌ | 是否包含元数据文件（默认：false） |

#### 请求示例

**示例 1: 基本批量下载**
```bash
curl -X POST http://localhost:8000/api/v1/download/batch \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": [
      "abc123-456def-789ghi",
      "def456-789abc-012jkl",
      "ghi789-012def-345mno"
    ]
  }' \
  -o documents.zip
```

**示例 2: 自定义文件名并包含元数据**
```bash
curl -X POST http://localhost:8000/api/v1/download/batch \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": [
      "abc123-456def-789ghi",
      "def456-789abc-012jkl"
    ],
    "package_name": "my_skill_package.zip",
    "include_metadata": true
  }' \
  -o my_skill_package.zip
```

#### 成功响应 (200)
- **Content-Type**: `application/zip`
- **Headers**:
  - `Content-Disposition: attachment; filename="my_skill_package.zip"`
  - `Content-Length: 12345678`
  - `X-Files-Count: 3`
  - `X-Zip-Method: deflate`

**ZIP文件结构示例**:
```
my_skill_package.zip/
├── session-xxx.md              # 主文档
├── helper_script.py            # Python辅助脚本
├── test_script.sh              # Shell脚本
├── config.json                 # 配置文件
└── metadata.json               # 元数据（可选）
```

**metadata.json 内容示例**（当 `include_metadata: true` 时）:
```json
{
  "package_name": "my_skill_package",
  "created_at": "2026-03-31T10:30:45.123Z",
  "files": [
    {
      "document_id": "abc123-456def-789ghi",
      "filename": "session-xxx.md",
      "doc_type": "session",
      "file_size": 45678,
      "file_hash": "sha256_hash_1",
      "created_at": "2026-03-20T08:15:30.000Z"
    },
    {
      "document_id": "def456-789abc-012jkl",
      "filename": "helper_script.py",
      "doc_type": "skill",
      "file_size": 12345,
      "file_hash": "sha256_hash_2",
      "created_at": "2026-03-21T10:20:15.000Z"
    }
  ],
  "total_files": 2,
  "total_size": 58023
}
```

#### 错误响应

**400 Bad Request - 参数错误**:
```json
{
  "error": "document_ids must be a non-empty array",
  "max_limit": 50
}
```

**400 Bad Request - 超出数量限制**:
```json
{
  "error": "Too many documents requested",
  "requested": 60,
  "max_limit": 50
}
```

**404 Not Found - 部分文档不存在**:
```json
{
  "error": "Some documents not found",
  "missing_ids": [
    "xyz999-invalid-000xxx"
  ],
  "found_count": 2,
  "missing_count": 1
}
```

**500 Internal Server Error - ZIP创建失败**:
```json
{
  "error": "Failed to create ZIP archive",
  "details": "Disk space insufficient"
}
```

---

### 8.3 按查询结果批量下载

#### 基本信息
- **端点**: `POST /api/v1/download/by-search`
- **功能**: 根据检索条件批量下载匹配的文档
- **适用场景**: 需要下载某一类或满足特定条件的所有文档

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_type` | string | ✅ | 文档类型（session、skill） |
| `query` | string | ❌ | 搜索关键词（支持文本检索） |
| `max_files` | integer | ❌ | 最大下载数量（默认：20，最大：100） |
| `package_name` | string | ❌ | ZIP文件名 |
| `include_metadata` | boolean | ❌ | 是否包含元数据（默认：true） |

#### 请求示例

**示例 1: 下载所有session类型文档（前20个）**
```bash
curl -X POST http://localhost:8000/api/v1/download/by-search \
  -H "Content-Type: application/json" \
  -d '{
    "doc_type": "session"
  }' \
  -o all_sessions.zip
```

**示例 2: 按关键词搜索并下载**
```bash
curl -X POST http://localhost:8000/api/v1/download/by-search \
  -H "Content-Type: application/json" \
  -d '{
    "doc_type": "skill",
    "query": "数据处理",
    "max_files": 10,
    "package_name": "data_processing_skills.zip"
  }' \
  -o data_processing_skills.zip
```

#### 成功响应 (200)
- **Content-Type**: `application/zip`
- **Headers**:
  - `Content-Disposition: attachment; filename="data_processing_skills.zip"`
  - `X-Files-Count: 10`
  - `X-Query-Total: 45` （匹配总数）
  - `X-Downloaded: 10` （实际下载数）

#### 错误响应

**400 Bad Request - 必填参数缺失**:
```json
{
  "error": "Missing required field: doc_type"
}
```

**400 Bad Request - 无匹配结果**:
```json
{
  "error": "No documents found matching the criteria",
  "doc_type": "skill",
  "query": "不存在的关键词"
}
```

---

### 8.4 文档下载状态查询

#### 基本信息
- **端点**: `GET /api/v1/download/status/{document_id}`
- **功能**: 查询文档是否可下载及文件状态

#### 请求示例
```bash
curl http://localhost:8000/api/v1/download/status/abc123-456def-789ghi
```

#### 成功响应 (200)
```json
{
  "document_id": "abc123-456def-789ghi",
  "available": true,
  "document": {
    "title": "会话配置说明",
    "doc_type": "session",
    "file_path": "/data/documents/session/ab/abc123.md",
    "file_size": 45678,
    "file_hash": "7a8b9c0d1e2f3456789...",
    "created_at": "2026-03-20T08:15:30.000Z",
    "updated_at": "2026-03-25T14:20:10.000Z"
  },
  "file_exists": true,
  "storage_type": "local",
  "download_url": "/api/v1/download/abc123-456def-789ghi"
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `available` | boolean | 文档是否可下载 |
| `file_exists` | boolean | 文件在存储中是否存在 |
| `storage_type` | string | 存储类型：local、minio、s3 |
| `download_url` | string | 下载链接 |

#### 错误响应

**404 Not Found**:
```json
{
  "document_id": "xyz999-invalid-000xxx",
  "available": false,
  "error": "Document not found"
}
```

**文件丢失但记录存在**:
```json
{
  "document_id": "abc123-456def-789ghi",
  "available": false,
  "document": {
    "title": "会话配置说明",
    "doc_type": "session"
  },
  "file_exists": false,
  "error": "File missing from storage",
  "file_path": "/data/documents/session/ab/abc123.md"
}
```

---

## 9. 配置管理 API

### 9.1 重载配置
- **端点**: `POST /api/v1/admin/config/reload`
- **权限**: 需要 Admin Key

```bash
curl -X POST http://localhost:8000/api/v1/admin/config/reload \
  -H "X-Admin-Key: your-admin-key"
```

**响应**:
```json
{
  "success": true,
  "message": "Configuration reloaded successfully"
}
```

### 9.2 查看当前配置
- **端点**: `GET /api/v1/admin/config`

```bash
curl http://localhost:8000/api/v1/admin/config \
  -H "X-Admin-Key: your-admin-key"
```

**响应**:
```json
{
  "vector_models": {
    "default": "bge-large",
    "models": {
      "mini": {...},
      "bge-large": {...}
    }
  },
  "search": {
    "default_top_k": 10,
    "max_top_k": 100
  }
}
```

### 9.3 获取向量模型列表
- **端点**: `GET /api/v1/admin/config/vector-models`

```bash
curl http://localhost:8000/api/v1/admin/config/vector-models
```

**响应**:
```json
{
  "models": [
    {
      "key": "bge-large",
      "name": "BAAI/bge-large-zh-v1.5",
      "dimension": 1024,
      "description": "中文优化高精度（推荐）",
      "is_loaded": true
    }
  ],
  "default": "bge-large",
  "total": 6
}
```

---

## 10. 使用示例

### Python
```python
import requests

# 1. 健康检查
response = requests.get('http://localhost:8000/api/v1/health')
print(response.json())

# 2. 检索
response = requests.post(
    'http://localhost:8000/api/v1/search',
    json={
        'index_name': 'test_feng',
        'query': 'allocate函数',
        'search_type': 'hybrid',
        'top_k': 10
    }
)
results = response.json()
print(f"找到 {results['total']} 个文件组")

# 遍历代码结果
code_results = results['results'].get('code', [])
for file_group in code_results:
    header = file_group['relative_code_header_file']
    source = file_group['relative_code_source_file']
    ut = file_group['relative_ut_file']
    
    print(f"文件: {source or header}")
    if ut:
        print(f"  单元测试: {ut}")
    print(f"包含 {len(file_group['relative_function_list'])} 个函数")

# 3. 上传文件
with open('manual.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/v1/upload',
        files={'file': f},
        data={
            'index_name': 'test_feng',
            'doc_type': 'SPEC',
            'use_vector': True
        }
    )
print(f"Task ID: {response.json()['task_id']}")

# 4. 下载单个文档
document_id = 'abc123-456def-789ghi'
response = requests.get(f'http://localhost:8000/api/v1/download/{document_id}')
if response.status_code == 200:
    with open('downloaded_file.md', 'wb') as f:
        f.write(response.content)
    print(f"文件已下载，大小: {len(response.content)} 字节")

# 5. 批量下载文档（ZIP）
response = requests.post(
    'http://localhost:8000/api/v1/download/batch',
    json={
        'document_ids': [
            'abc123-456def-789ghi',
            'def456-789abc-012jkl'
        ],
        'package_name': 'my_documents.zip',
        'include_metadata': True
    }
)
if response.status_code == 200:
    with open('my_documents.zip', 'wb') as f:
        f.write(response.content)
    print(f"ZIP文件已下载")

# 6. 按条件批量下载
response = requests.post(
    'http://localhost:8000/api/v1/download/by-search',
    json={
        'doc_type': 'skill',
        'query': '数据处理',
        'max_files': 10
    }
)
if response.status_code == 200:
    with open('skill_documents.zip', 'wb') as f:
        f.write(response.content)
```

### JavaScript
```javascript
// 1. 健康检查
fetch('http://localhost:8000/api/v1/health')
  .then(res => res.json())
  .then(data => console.log(data));

// 2. 检索
fetch('http://localhost:8000/api/v1/search', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    index_name: 'test_feng',
    query: 'allocate函数',
    search_type: 'hybrid',
    top_k: 10
  })
})
  .then(res => res.json())
  .then(data => {
    console.log(`找到 ${data.total} 个文件组`);
    
    // 处理 code 分类结果
    const codeResults = data.results.code || [];
    codeResults.forEach(fileGroup => {
      const source = fileGroup.relative_code_source_file;
      const header = fileGroup.relative_code_header_file;
      const ut = fileGroup.relative_ut_file;
      
      console.log(`文件: ${source || header}`);
      if (ut) {
        console.log(`  单元测试: ${ut}`);
      }
      console.log(`包含 ${fileGroup.relative_function_list.length} 个函数`);
    });
  });

// 3. 上传文件
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('index_name', 'test_feng');
formData.append('doc_type', 'SPEC');
formData.append('use_vector', true);

fetch('http://localhost:8000/api/v1/upload', {
  method: 'POST',
  body: formData
})
  .then(res => res.json())
  .then(data => console.log(`Task ID: ${data.task_id}`));

// 4. 下载单个文档
const documentId = 'abc123-456def-789ghi';
fetch(`http://localhost:8000/api/v1/download/${documentId}`)
  .then(res => res.blob())
  .then(blob => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'document.md';
    a.click();
    console.log('文件已下载');
  });

// 5. 批量下载文档（ZIP）
fetch('http://localhost:8000/api/v1/download/batch', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    document_ids: ['abc123-456def-789ghi', 'def456-789abc-012jkl'],
    package_name: 'my_documents.zip',
    include_metadata: true
  })
})
  .then(res => res.blob())
  .then(blob => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'my_documents.zip';
    a.click();
    console.log('ZIP文件已下载');
  });
```

---

## 11. 注意事项

### 检索 API
1. **默认参数**: 仅提供 `index_name` 和 `query` 即可使用，其他参数都有合理默认值
2. **关联查询**: 默认启用，会额外耗时 100-500ms，关联结果会自动合并到 `results` 中，可通过 `enable_relation_search: false` 关闭
3. **向量权重**: 仅在 `search_type: "hybrid"` 时生效，范围 0.1-0.9，默认 0.8
4. **超时时间**: 建议设置 30 秒超时；启用 AI 增强检索时建议设置 60-120 秒超时
5. **结果格式**: 
   - 代码检索（`tag=null/CODE`）：结果按文件分组，同一文件的多个函数会合并到 `relative_function_list` 中
   - 其他知识库：结果为章节格式，包含 `section_title` 和 `content`

### 上传 API
1. **异步处理**: 上传立即返回 task_id，实际导入在后台 Celery 任务中完成
2. **文件大小限制**: 默认 50MB，可在配置中修改
3. **支持的文件类型**: `.pdf`, `.md`, `.txt`, `.py`, `.js`, `.java`, `.cpp`, `.json`, `.yaml`
4. **向量生成**: 默认启用，可通过 `use_vector: false` 关闭

### 下载 API
1. **适用类型**: 主要用于 session 和 skill 类型的大文档下载
2. **批量下载限制**: 单次最多下载 50 个文档（`/batch` 端点）
3. **按条件下载**: `/by-search` 端点默认下载前 20 个匹配文档，最多 100 个
4. **文件完整性**: 响应头中包含 `X-File-Hash` 用于校验文件完整性
5. **ZIP压缩**: 批量下载自动压缩为 ZIP 格式，使用 deflate 压缩算法
6. **元数据**: 可选择在 ZIP 包中包含 `metadata.json`，记录所有文件的详细信息
7. **并发下载**: 建议使用连接池，避免同时发起过多下载请求
8. **超时设置**: 下载大文件时建议设置较长超时（60-300秒），取决于文件大小
9. **存储一致性**: 下载前可调用 `/download/status/{doc_id}` 检查文件是否存在

### 配置管理
1. **热更新**: 修改 `config/dynamic_config.yaml` 后调用 `/admin/config/reload` 即可生效
2. **不可热更新**: ES/Redis/Celery 连接配置需要重启应用
3. **权限控制**: 配置管理 API 需要 Admin Key（通过 `X-Admin-Key` header 传递）

---

**完整 API 列表**:

```
健康检查:
  GET  /health                                # 兼容探针
  GET  /api/v1/system/status                  # 丰富探针
  GET  /api/v1/system/info                    # 系统信息（envelope）

检索:
  POST /api/v1/search

上传:
  POST /api/v1/upload                           # 单文件上传（常规文档）
  POST /api/v1/sessions/upload                  # Session 批量上传
  POST /api/v1/skills/upload                    # Skill 批量上传
  GET  /api/v1/tasks/{task_id}                  # 查询任务状态

Session/Skill 管理:
  POST   /api/v1/sessions                       # 创建 session
  GET    /api/v1/sessions/{session_id}          # 查询 session 详情
  POST   /api/v1/sessions/{session_id}/files    # 上传文件到 session
  DELETE /api/v1/sessions/{session_id}/files/{file_id}  # 删除文件
  POST   /api/v1/skills                         # 创建 skill
  GET    /api/v1/skills/{skill_id}              # 查询 skill 详情
  POST   /api/v1/skills/{skill_id}/files        # 上传文件到 skill
  DELETE /api/v1/skills/{skill_id}/files/{file_id}      # 删除文件

索引管理:
  GET  /api/v1/indices
  GET  /api/v1/indices/{index_name}

文档管理:
  GET    /api/v1/docs/{doc_id}
  PUT    /api/v1/docs/{doc_id}
  DELETE /api/v1/docs/{doc_id}

文档下载:
  GET  /api/v1/download/{document_id}
  POST /api/v1/download/batch
  POST /api/v1/download/by-search
  GET  /api/v1/download/status/{document_id}

配置管理:
  POST /api/v1/admin/config/reload
  GET  /api/v1/admin/config
  GET  /api/v1/admin/config/vector-models
```
