# Import流程详细设计

## 1. 概述

### 1.1 设计目标

本文档描述Import（导入）功能的详细设计，主要特点：

1. **现代框架**：基于FastAPI构建
2. **Clean Architecture**：采用DDD（领域驱动设计）+ Clean Architecture模式
3. **新架构**：功能垂直聚合（features/）+ API水平聚合（api/v1/）
4. **OpenSearch数据库**：使用OpenSearch 2.x替代Elasticsearch
5. **简化流程**：合并文件上传和导入为单一端点
6. **智能流程**：
   - 文件上传和解析同步完成，立即返回解析结果
   - 向量化和OpenSearch导入异步执行（Celery）
   - 立即返回job_id供后续查询
7. **可扩展性**：支持用户自定义文档解析脚本（Python）
8. **精细状态**：区分parsing、vectorizing、importing、completed等状态

### 1.2 核心流程

```
┌──────────────────────────────────────────────────────────┐
│ 1. 提交导入任务（含文件上传）                              │
│    POST /api/v1/import/jobs                               │
│    - 上传文件                                              │
│    - 立即解析文件                                          │
│    - 生成向量（如需要）                                    │
│    - 写入 PostgreSQL（主存储）                             │
│    - 返回 job_id + document_ids                           │
│    - 异步执行 OpenSearch 同步                              │
└──────────────┬───────────────────────────────────────────┘
               │
               v
┌──────────────────────────────────────────────────────────┐
│ 2. 查询任务状态                                            │
│    GET /api/v1/import/jobs/{job_id}                       │
│    - 查询 OpenSearch 同步进度                              │
└──────────────────────────────────────────────────────────┘
```

### 1.3 术语定义

- **Import Job**：导入任务，由用户提交的一次完整导入操作
- **Document Parser**：文档解析器，将原始文件转换为标准JSON格式
- **Custom Parser**：用户上传的自定义解析脚本
- **Sandbox**：隔离的Python执行环境，用于安全执行自定义解析脚本
- **Vector Model**：向量模型，用于将文本转换为向量表示，支持语义检索
- **PostgreSQL**：主数据库，存储所有文档数据，保证数据完整性（Source of Truth）
- **OpenSearch**：搜索引擎，提供高性能全文检索和向量搜索
- **Sync Task**：同步任务，负责将 PostgreSQL 数据同步到 OpenSearch

### 1.4 向量模型概述

#### 1.4.1 什么是向量模型

向量模型用于将文本内容转换为高维向量（embeddings），使得系统能够：
- 支持**语义检索**：理解文本含义而非仅匹配关键词
- 支持**相似度搜索**：找到意义相近的文档
- 提升**检索精度**：更准确地匹配用户意图

#### 1.4.2 是否需要向量化

**需要向量化的场景**：
- ✅ 需要语义搜索（理解查询意图）
- ✅ 文档内容复杂，关键词检索不够精准
- ✅ 需要相似度排序
- ✅ 多语言文档混合

**不需要向量化的场景**：
- ✅ 简单的关键词检索已足够
- ✅ 文档量很大，资源受限
- ✅ 快速原型开发阶段
- ✅ 精确匹配的场景（如代码搜索）

#### 1.4.3 向量模型对比

| 维度 | mini (384) | mpnet (768) | bge-base (768) | bge-large (1024) |
|------|-----------|-------------|----------------|------------------|
| 生成速度 | 最快 | 快 | 快 | 较慢 |
| 检索精度 | 一般 | 良好 | 良好（中文优） | 优秀（中文优） |
| 内存占用 | 最小 | 中等 | 中等 | 较大 |
| 存储空间 | 最小 | 中等 | 中等 | 较大 |
| 推荐场景 | 快速测试 | **通用场景** | 中文文档 | 追求高精度 |

**选择建议**：
- 🌟 **默认推荐**：`mpnet` - 性能和效果最平衡
- 🇨🇳 **中文文档**：`bge-base` 或 `bge-large` - 针对中文优化
- 🌍 **多语言**：`bge-m3` - 支持超过100种语言
- ⚡ **快速原型**：`mini` - 速度优先
- 💾 **不需要语义搜索**：不传 `vector_model` 参数 - 节省资源

---

## 2. API层设计

### 2.1 完整流程时序图

```
客户端                    API层                      Service层                    Celery任务
  │                        │                           │                            │
  │  POST /api/v1/import/jobs                          │                            │
  │  (files + params)      │                           │                            │
  ├────────────────────────>│                           │                           │
  │                        │                           │                            │
  │                        │  create_import_job_with_files()                        │
  │                        ├───────────────────────────>│                           │
  │                        │                           │                            │
  │                        │                     1. 保存文件到临时目录                │
  │                        │                     2. 立即解析所有文件                  │
  │                        │                     3. 保存解析结果为.parsed.json        │
  │                        │                     4. 创建ImportJob实体              │
  │                        │                           │                            │
  │                        │                     5. 提交Celery任务                  │
  │                        │                           ├────────────────────────────>│
  │                        │                           │                            │
  │  返回job_id +          │                           │                       (异步执行)
  │  parse_results         │                           │                            │
  │<────────────────────────┤<──────────────────────────┤                            │
  │                        │                           │                            │
  │  {                     │                           │                     6. 读取.parsed.json
  │    "job_id": "xxx",    │                           │                     7. 生成向量(可选)
  │    "parse_results": {  │                           │                     8. 批量导入OpenSearch
  │      "parsed_files": 2,│                           │                     9. 更新Job状态
  │      "failed_files": 0 │                           │                     10. 清理临时文件
  │    }                   │                           │                            │
  │  }                     │                           │                            │
  │                        │                           │                            │
  │  轮询查询状态           │                           │                            │
  │  GET /api/v1/import/jobs/{job_id}                  │                            │
  ├────────────────────────>│                           │                            │
  │                        │  get_job_status()         │                            │
  │                        ├───────────────────────────>│                            │
  │                        │                           │                            │
  │  返回当前状态          │                           │                            │
  │  (parsing/vectorizing/ │                           │                            │
  │   importing/completed) │                           │                            │
  │<────────────────────────┤<──────────────────────────┤                            │
  │                        │                           │                            │
```

### 2.2 目录结构

```
app/
├── api/                            # API 路由层（水平聚合）
│   ├── __init__.py                 # 注册所有路由
│   ├── deps.py                     # 通用依赖（认证、限流）
│   └── v1/                         # API v1 版本
│       ├── __init__.py  
│       ├── import_api.py           # Import相关API端点
│       └── dependencies.py         # Import依赖注入
│
├── features/                       # 功能层（垂直聚合）
│   └── import/                     # 导入功能（垂直聚合）
│       ├── import_service.py       # 业务逻辑
│       ├── repositories/           # 多仓储设计
│       │   ├── __init__.py  
│       │   ├── base.py             # 基类
│       │   └── factory.py          # 工厂
│       ├── schemas.py              # API 数据模型
│       └── dependencies.py         # 依赖注入
│
├── infrastructure/                 # 基础设施层
│   ├── __init__.py
│   │
│   ├── postgres/                   # PostgreSQL（主存储）
│   │   ├── client.py               # asyncpg 客户端
│   │   ├── repositories/
│   │   │   ├── base.py             # 基础Repository
│   │   │   ├── document.py         # 文档主表操作
│   │   │   └── chunk.py            # 文档块操作
│   │   └── migrations/             # 数据库迁移脚本
│   │
│   ├── opensearch/                 # OpenSearch（搜索引擎）
│   │   ├── client.py               # OpenSearch 客户端
│   │   ├── query_builder.py        # 查询构建器（knn语法）
│   │   ├── index_manager.py        # 索引管理
│   │   └── mappings/  
│   │       ├── documents.json      # 文档主索引映射
│   │       └── chunks.json         # 文档块索引映射
│   │
│   ├── redis/                     # Redis
│   │   └── client.py             # Redis 客户端
│   │
│   ├── celery/                    # Celery
│   │   ├── app.py                # Celery 应用
│   │   └── tasks.py              # 任务定义
│   │
│   └── vector/                     # 向量工具
│       ├── vector_tool.py          # 向量生成和模型管理
│       └── rerank_tool.py          # 重排序和模型管理
│
└── config/                         # 配置管理
    ├── __init__.py
    ├── settings.py                 # 静态配置（环境变量）
    ├── logging.py                  # 日志配置
    ├── config_manager.py           # 动态配置管理器（统一）
    └── dynamic_config.yaml         # 动态配置文件（统一）
```

### 2.3 向量模型选择

#### 2.3.1 可选向量模型

用户可以在导入时选择是否使用向量化，以及使用哪种向量模型。系统支持以下向量模型：

| 模型ID | 模型名称 | 维度 | 特点 | 适用场景 |
|--------|---------|------|------|---------|
| `mini` | paraphrase-multilingual-MiniLM-L12-v2 | 384 | 轻量快速，多语言支持 | 快速原型、资源受限环境 |
| `mpnet` | paraphrase-multilingual-mpnet-base-v2 | 768 | 平衡性好，多语言支持 | **推荐**，通用场景 |
| `bge-base` | BAAI/bge-base-zh-v1.5 | 768 | 中文优化，基础版 | 中文文档 |
| `bge-large` | BAAI/bge-large-zh-v1.5 | 1024 | 中文优化，高精度 | 中文文档，追求精度 |
| `bge-m3` | BAAI/bge-m3 | 1024 | 多语言，支持长文本 | 多语言混合、长文档 |
| `e5-large` | intfloat/multilingual-e5-large | 1024 | 多语言，高性能 | 多语言文档，追求性能 |

#### 2.3.2 使用说明

**不使用向量化**：
```bash
# 不传 vector_model 参数，或传空值
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "files=@doc.md"
```

**使用向量化**：
```bash
# 指定 vector_model 参数
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=mpnet" \
  -F "files=@doc.md"
```

#### 2.3.3 选择建议

1. **通用场景**：推荐使用 `mpnet`，性能和效果平衡
2. **中文文档**：推荐使用 `bge-base` 或 `bge-large`
3. **多语言混合**：推荐使用 `bge-m3` 或 `e5-large`
4. **快速测试**：使用 `mini`，速度最快但精度较低
5. **不需要语义搜索**：不传 `vector_model`，节省资源

#### 2.3.4 性能对比

| 模型 | 向量生成速度 | 检索精度 | 内存占用 |
|------|------------|----------|---------|
| mini | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 低 |
| mpnet | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 中 |
| bge-base | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 中 |
| bge-large | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 高 |
| bge-m3 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 高 |
| e5-large | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 高 |

### 2.4 API端点定义

#### 2.4.1 提交导入任务（含文件上传）

**端点**: `POST /api/v1/import/jobs`

**请求类型**: `multipart/form-data`

**表单参数**:
```python
class ImportJobRequest(BaseModel):
    """导入任务请求"""
    library: str = Field(..., description="目标知识库名称", example="common")
    vector_model: Optional[str] = Field(None, description="向量模型", example="mpnet")
    import_mode: Literal["replace", "append"] = Field("replace", description="导入模式")
    custom_parser_id: Optional[str] = Field(None, description="自定义解析器ID")
    # files 通过 multipart/form-data 上传，不在 Pydantic 模型中定义
    
    @validator('library')
    def validate_library(cls, v):
        from app.config.settings import get_settings
        settings = get_settings()
        valid_libraries = settings.valid_libraries
        if v not in valid_libraries:
            raise ValueError(f"Invalid library. Must be one of: {valid_libraries}")
        return v
    
    @validator('vector_model')
    def validate_vector_model(cls, v):
        if v is not None:
            from app.config.config_manager import get_config_manager
            config = get_config_manager()
            vector_models = config.get("vector_models", {})
            valid_models = [k for k in vector_models.keys() if k != "default" and k != "load_on_startup" and k != "preload_models"]
            if v not in valid_models:
                raise ValueError(f"Invalid vector_model. Must be one of: {valid_models}")
        return v
```

**FastAPI 端点签名**:
```python
async def create_import_job(
    library: str = Form(...),
    vector_model: Optional[str] = Form(None),
    import_mode: str = Form("replace"),
    custom_parser_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    service: ImportService = Depends(get_import_service)
) -> ImportJobResponse:
```

**cURL 示例**:

```bash
# 示例1：不使用向量化
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "files=@document1.md" \
  -F "files=@document2.md"

# 示例2：使用推荐的 mpnet 模型（768维）
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=mpnet" \
  -F "files=@document1.md" \
  -F "files=@document2.md"

# 示例3：中文文档使用 bge-base 模型（768维）
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=bge-base" \
  -F "files=@chinese_doc.md"

# 示例4：追求高精度使用 bge-large 模型（1024维）
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=bge-large" \
  -F "files=@important_doc.md"

# 示例5：多语言混合文档使用 bge-m3（1024维）
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=bge-m3" \
  -F "files=@multilang_doc.md"

# 示例6：使用自定义解析器 + 向量化
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=mpnet" \
  -F "custom_parser_id=custom_abc123def456" \
  -F "files=@custom_format.txt"
```

**响应**:
```python
class ImportJobResponse(BaseModel):
    """导入任务响应"""
    success: bool
    job_id: str = Field(..., description="任务ID")
    message: str
    
    # 立即返回的文件解析结果
    parse_results: Dict[str, Any] = Field(..., description="文件解析结果")
    # {
    #     "total_files": 3,
    #     "parsed_files": 2,
    #     "failed_files": 1,
    #     "file_details": [
    #         {"filename": "doc1.md", "success": true, "sections": 10},
    #         {"filename": "doc2.md", "success": true, "sections": 5},
    #         {"filename": "doc3.md", "success": false, "error": "Invalid format"}
    #     ]
    # }
    
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

**成功响应示例**:

**1. 所有文件解析成功（HTTP 201）**:
```json
{
  "success": true,
  "job_id": "import_20260412_123456_abc123",
  "document_ids": [1001, 1002, 1003, 1004, 1005],
  "status": "syncing",
  "message": "文档已保存到数据库 (23 条)，正在后台同步到搜索引擎",
  "details": {
    "library": "common",
    "use_vector": true,
    "vector_model": "mpnet",
    "vector_dims": 768,
    "import_mode": "replace",
    "postgresql_docs": 23,
    "parse_results": {
      "total_files": 3,
      "parsed_files": 3,
      "failed_files": 0,
      "file_details": [
        {
          "filename": "doc1.md",
          "success": true,
          "sections": 10,
          "size_bytes": 15360
        },
        {
          "filename": "doc2.md",
          "success": true,
          "sections": 5,
          "size_bytes": 8192
        },
        {
          "filename": "doc3.json",
          "success": true,
          "sections": 8,
          "size_bytes": 4096
        }
      ]
    }
  }
}
```

**2. 部分文件解析失败（HTTP 201）**:
```json
{
  "success": true,
  "job_id": "import_20260412_123457_def456",
  "document_ids": [2001, 2002, 2003],
  "status": "syncing",
  "message": "文档已保存到数据库 (15 条)，正在后台同步到搜索引擎。1个文件解析失败。",
  "details": {
    "library": "common",
    "use_vector": false,
    "vector_model": null,
    "import_mode": "append",
    "postgresql_docs": 15,
    "parse_results": {
      "total_files": 3,
      "parsed_files": 2,
      "failed_files": 1,
      "file_details": [
        {
          "filename": "valid.md",
          "success": true,
          "sections": 10,
          "size_bytes": 15360
        },
        {
          "filename": "invalid.md",
          "success": false,
          "error": "解析失败: 文件格式不正确",
          "size_bytes": 2048
        },
        {
          "filename": "good.json",
          "success": true,
          "sections": 5,
          "size_bytes": 8192
        }
      ]
    }
  }
}
```

**异常响应示例**:

**1. 没有提供文件（HTTP 400）**:
```json
{
  "detail": "No files provided"
}
```

**2. 无效的向量模型（HTTP 400）**:
```json
{
  "detail": "Invalid vector_model: invalid_model. Available: mini, mpnet, bge-base, bge-large, bge-m3, e5-large"
}
```

**3. 无效的知识库名称（HTTP 400）**:
```json
{
  "detail": "Invalid library. Must be one of: ['common', 'test', 'private']"
}
```

**4. 文件过大（HTTP 413）**:
```json
{
  "detail": "File too large: document.md (15MB). Maximum size: 10MB"
}
```

**5. 文件数量超限（HTTP 400）**:
```json
{
  "detail": "Too many files. Maximum: 10 files per request"
}
```

**6. 不支持的文件类型（HTTP 400）**:
```json
{
  "detail": "Unsupported file type: document.pdf. Supported: .md, .json"
}
```

**7. 所有文件解析失败（HTTP 400）**:
```json
{
  "detail": "All files failed to parse. Cannot proceed with import.",
  "failed_files": [
    {
      "filename": "bad1.md",
      "error": "Invalid markdown format"
    },
    {
      "filename": "bad2.json",
      "error": "JSON decode error"
    }
  ]
}
```

**8. 自定义解析器不存在（HTTP 404）**:
```json
{
  "detail": "Custom parser not found: custom_abc123"
}
```

**9. 服务内部错误（HTTP 500）**:
```json
{
  "detail": "Internal server error occurred during file processing"
}
```

#### 2.4.2 查询任务状态

**端点**: `GET /api/v1/import/jobs/{job_id}`

**路径参数**:
- `job_id`: 任务ID

**响应**:
```python
class ImportJobStatus(BaseModel):
    """导入任务状态"""
    job_id: str
    status: Literal["parsing", "vectorizing", "saving", "syncing", "completed", "failed", "cancelled"]
    progress: float = Field(..., ge=0.0, le=1.0, description="进度 0.0-1.0")
    message: str
    
    # 解析结果（始终返回）
    parse_results: Optional[Dict[str, Any]] = Field(None, description="文件解析结果")
    
    # 最终结果（仅 completed 时有值）
    result: Optional[Dict[str, Any]] = None
    # {
    #     "index_name": "test_common",
    #     "imported_docs": 150,
    #     "total_docs": 150,
    #     "failed_docs": 0,
    #     "has_vector": true,
    #     "vector_dims": 768
    # }
    
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

**成功响应示例**:

**1. 任务正在解析（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "parsing",
  "progress": 0.0,
  "message": "正在解析文件...",
  "parse_results": null,
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": null,
  "completed_at": null
}
```

**2. 任务正在向量化（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "vectorizing",
  "progress": 0.35,
  "message": "正在生成向量 (35/100)...",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": null
}
```

**3. 任务正在导入ES（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "importing",
  "progress": 0.75,
  "message": "正在导入到OpenSearch (112/150)...",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": null
}
```

**4. 任务完成（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "completed",
  "progress": 1.0,
  "message": "导入完成",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": {
    "index_name": "test_common",
    "imported_docs": 150,
    "total_docs": 150,
    "failed_docs": 0,
    "has_vector": true,
    "vector_dims": 768
  },
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:36:30"
}
```

**5. 任务失败（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "failed",
  "progress": 0.45,
  "message": "同步失败",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": "OpenSearch connection timeout: Failed to connect to OpenSearch after 3 retries",
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:35:45"
}
```

**注意**：
- 数据已保存到 PostgreSQL（主存储），即使 OpenSearch 同步失败，数据也不会丢失
- 可以通过重新触发同步任务来修复 OpenSearch 索引

**6. 任务已取消（HTTP 200）**:
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "cancelled",
  "progress": 0.25,
  "message": "任务已取消",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": null,
  "error": null,
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:35:15"
}
```

**异常响应示例**:

**1. 任务不存在（HTTP 404）**:
```json
{
  "detail": "Job not found: import_20260412_999999_notexist"
}
```

**2. 无效的任务ID格式（HTTP 400）**:
```json
{
  "detail": "Invalid job_id format"
}
```

#### 2.4.3 取消任务

**端点**: `POST /api/v1/import/jobs/{job_id}/cancel`

**路径参数**:
- `job_id`: 任务ID

**响应**:
```python
class ImportJobCancelResponse(BaseModel):
    """取消任务响应"""
    success: bool
    job_id: str
    message: str
```

**成功响应示例**:

**1. 成功取消任务（HTTP 200）**:
```json
{
  "success": true,
  "job_id": "import_20260412_123456_abc123",
  "message": "任务取消请求已提交"
}
```

**异常响应示例**:

**1. 任务不存在（HTTP 404）**:
```json
{
  "detail": "Job not found: import_20260412_999999_notexist"
}
```

**2. 任务已完成无法取消（HTTP 400）**:
```json
{
  "detail": "Cannot cancel job in status: completed"
}
```

**3. 任务已失败无法取消（HTTP 400）**:
```json
{
  "detail": "Cannot cancel job in status: failed"
}
```

**4. 任务已取消（HTTP 400）**:
```json
{
  "detail": "Job is already cancelled"
}
```

**5. 取消失败（HTTP 500）**:
```json
{
  "detail": "Failed to cancel Celery task: Task revoke timeout"
}
```

#### 2.4.4 获取任务列表

**端点**: `GET /api/v1/import/jobs`

**查询参数**:
- `status`: 过滤状态 (可选, 可选值: parsing/vectorizing/importing/completed/failed/cancelled)
- `limit`: 返回数量限制 (默认20, 最大100)
- `offset`: 分页偏移 (默认0)

**cURL 示例**:
```bash
# 获取所有任务
curl http://localhost:9220/api/v1/import/jobs

# 获取正在运行的任务
curl "http://localhost:9220/api/v1/import/jobs?status=vectorizing"

# 分页获取
curl "http://localhost:9220/api/v1/import/jobs?limit=10&offset=20"
```

**响应**:
```python
class ImportJobListResponse(BaseModel):
    """任务列表响应"""
    total: int
    items: List[ImportJobStatus]
    limit: int
    offset: int
```

**成功响应示例**:

**1. 获取任务列表（HTTP 200）**:
```json
{
  "total": 15,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "job_id": "import_20260412_123456_abc123",
      "status": "completed",
      "progress": 1.0,
      "message": "导入完成",
      "parse_results": {
        "total_files": 2,
        "parsed_files": 2,
        "failed_files": 0
      },
      "result": {
        "index_name": "test_common",
        "imported_docs": 150,
        "total_docs": 150,
        "failed_docs": 0,
        "has_vector": true,
        "vector_dims": 768
      },
      "error": null,
      "created_at": "2026-04-12T12:34:56",
      "started_at": "2026-04-12T12:35:01",
      "completed_at": "2026-04-12T12:36:30"
    },
    {
      "job_id": "import_20260412_123500_def456",
      "status": "vectorizing",
      "progress": 0.45,
      "message": "正在生成向量 (45/100)...",
      "parse_results": {
        "total_files": 3,
        "parsed_files": 3,
        "failed_files": 0
      },
      "result": null,
      "error": null,
      "created_at": "2026-04-12T12:35:00",
      "started_at": "2026-04-12T12:35:05",
      "completed_at": null
    },
    {
      "job_id": "import_20260412_123400_ghi789",
      "status": "failed",
      "progress": 0.30,
      "message": "导入失败",
      "parse_results": {
        "total_files": 1,
        "parsed_files": 1,
        "failed_files": 0
      },
      "result": null,
      "error": "OpenSearch connection refused",
      "created_at": "2026-04-12T12:34:00",
      "started_at": "2026-04-12T12:34:05",
      "completed_at": "2026-04-12T12:34:20"
    }
  ]
}
```

**2. 按状态过滤（HTTP 200）**:
```json
{
  "total": 3,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "job_id": "import_20260412_123456_abc123",
      "status": "vectorizing",
      "progress": 0.65,
      "message": "正在生成向量 (65/100)...",
      "parse_results": {
        "total_files": 2,
        "parsed_files": 2,
        "failed_files": 0
      },
      "result": null,
      "error": null,
      "created_at": "2026-04-12T12:34:56",
      "started_at": "2026-04-12T12:35:01",
      "completed_at": null
    }
  ]
}
```

**3. 空结果（HTTP 200）**:
```json
{
  "total": 0,
  "limit": 20,
  "offset": 0,
  "items": []
}
```

**异常响应示例**:

**1. 无效的状态参数（HTTP 400）**:
```json
{
  "detail": "Invalid status: invalid_status. Must be one of: parsing, vectorizing, importing, completed, failed, cancelled"
}
```

**2. 无效的分页参数（HTTP 400）**:
```json
{
  "detail": "limit must be between 1 and 100"
}
```

**3. 偏移量超出范围（HTTP 400）**:
```json
{
  "detail": "offset must be non-negative"
}
```

### 2.5 API实现示例

```python
# app/api/v1/import_api.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from typing import List, Optional
from app.api.v1.schemas.import_schemas import (
    ImportJobResponse,
    ImportJobStatus,
    ImportJobCancelResponse,
    ImportJobListResponse
)
from app.features.import.application.import_service import ImportService
from app.api.v1.dependencies import get_import_service
from logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/import", tags=["Import"])


@router.post(
    "/jobs",
    response_model=ImportJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交导入任务（含文件上传）",
    description="上传文件并创建导入任务，立即返回解析结果和job_id"
)
async def create_import_job(
    library: str = Form(..., description="目标知识库名称"),
    files: List[UploadFile] = File(..., description="待导入的文件列表"),
    vector_model: Optional[str] = Form(None, description="向量模型名称"),
    import_mode: str = Form("replace", description="导入模式 replace/append"),
    custom_parser_id: Optional[str] = Form(None, description="自定义解析器ID"),
    service: ImportService = Depends(get_import_service)
) -> ImportJobResponse:
    """
    提交导入任务
    
    流程：
    1. 接收并保存文件到本地
    2. 立即解析文件为JSON格式
    3. 创建Celery异步任务（向量化 + OpenSearch导入）
    4. 返回job_id和解析结果
    
    参数说明：
    - **library**: 目标知识库名称（必填）
    - **files**: 文件列表（必填，支持.md和.json，最多10个文件，单个文件最大10MB）
    - **vector_model**: 向量模型名称（可选）
      - 不传或传空：不使用向量化
      - 可选值：mini, mpnet, bge-base, bge-large, bge-m3, e5-large
      - 推荐：mpnet（通用）、bge-base（中文）
    - **import_mode**: 导入模式 replace/append（默认replace）
    - **custom_parser_id**: 自定义解析器ID（可选）
    """
    try:
        # 1. 验证文件
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No files provided"
            )
        
        # 2. 验证文件数量
        from config import MAX_FILES_PER_UPLOAD
        if len(files) > MAX_FILES_PER_UPLOAD:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Too many files. Maximum: {MAX_FILES_PER_UPLOAD} files per request"
            )
        
        # 3. 验证文件大小和类型
        from config import MAX_FILE_SIZE
        SUPPORTED_EXTENSIONS = {'.md', '.json'}
        
        for file in files:
            # 检查文件大小
            file_size = 0
            if hasattr(file, 'size'):
                file_size = file.size
            elif hasattr(file.file, 'seek') and hasattr(file.file, 'tell'):
                # 计算文件大小
                file.file.seek(0, 2)  # 移动到文件末尾
                file_size = file.file.tell()
                file.file.seek(0)  # 重置到文件开头
            
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large: {file.filename} ({file_size / 1024 / 1024:.1f}MB). Maximum size: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
                )
            
            # 检查文件类型
            import os
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported file type: {file.filename}. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
                )
        
        # 4. 验证library参数
        from config import TEST_LIBRARIES
        if library not in TEST_LIBRARIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid library. Must be one of: {TEST_LIBRARIES}"
            )
        
        # 5. 验证向量模型
        if vector_model:
            from config import VECTOR_MODELS
            if vector_model not in VECTOR_MODELS:
                available_models = ', '.join(VECTOR_MODELS.keys())
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid vector_model: {vector_model}. Available: {available_models}"
                )
            logger.info(f"Using vector model: {vector_model} ({VECTOR_MODELS[vector_model]['dims']}D)")
        else:
            logger.info("Vector model not specified, will not generate embeddings")
        
        # 6. 验证自定义解析器（如果提供）
        if custom_parser_id:
            parser_exists = await service.check_parser_exists(custom_parser_id)
            if not parser_exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Custom parser not found: {custom_parser_id}"
                )
        
        logger.info(f"Received {len(files)} files for library: {library}")
        
        # 7. 调用服务层创建导入任务
        result = await service.create_import_job_with_files(
            library=library,
            files=files,
            vector_model=vector_model,
            import_mode=import_mode,
            custom_parser_id=custom_parser_id
        )
        
        # 8. 构造响应
        return ImportJobResponse(
            success=True,
            job_id=result['job_id'],
            message=result['message'],
            parse_results=result['parse_results'],
            details=result.get('details', {})
        )
    
    except HTTPException:
        # 重新抛出HTTPException（已经有正确的状态码）
        raise
    except ValueError as e:
        # 业务逻辑错误（如所有文件解析失败）
        logger.warning(f"Invalid request: {str(e)}")
        
        # 检查是否是所有文件解析失败的错误
        error_msg = str(e)
        if "All files failed to parse" in error_msg or "failed to parse" in error_msg.lower():
            # 尝试提取失败文件信息
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # 未预期的系统错误
        logger.error(f"Failed to create import job: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred during file processing"
        )


@router.get(
    "/jobs/{job_id}",
    response_model=ImportJobStatus,
    summary="查询任务状态",
    description="获取指定导入任务的当前状态"
)
async def get_import_job_status(
    job_id: str,
    service: ImportService = Depends(get_import_service)
) -> ImportJobStatus:
    """查询任务状态"""
    try:
        status_info = await service.get_job_status(job_id)
        
        if not status_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Import job not found: {job_id}"
            )
        
        return ImportJobStatus(**status_info)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job status: {str(e)}"
        )


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ImportJobCancelResponse,
    summary="取消任务",
    description="取消正在执行或等待中的导入任务"
)
async def cancel_import_job(
    job_id: str,
    service: ImportService = Depends(get_import_service)
) -> ImportJobCancelResponse:
    """取消任务"""
    try:
        # 检查任务是否存在
        job = await service.get_job_status(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        # 检查任务状态是否可以取消
        current_status = job.get('status')
        if current_status in ['completed', 'failed', 'cancelled']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel job in status: {current_status}"
            )
        
        # 执行取消操作
        success = await service.cancel_job(job_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cancel Celery task: Task revoke timeout"
            )
        
        return ImportJobCancelResponse(
            success=True,
            job_id=job_id,
            message="任务取消请求已提交"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel job: {str(e)}"
        )


@router.get(
    "/jobs",
    response_model=ImportJobListResponse,
    summary="获取任务列表",
    description="获取所有导入任务列表（支持过滤和分页）"
)
async def list_import_jobs(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    service: ImportService = Depends(get_import_service)
) -> ImportJobListResponse:
    """获取任务列表"""
    try:
        # 验证status参数
        valid_statuses = ['parsing', 'vectorizing', 'importing', 'completed', 'failed', 'cancelled']
        if status and status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}"
            )
        
        # 验证limit参数
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="limit must be between 1 and 100"
            )
        
        # 验证offset参数
        if offset < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="offset must be non-negative"
            )
        
        result = await service.list_jobs(
            status_filter=status,
            limit=limit,
            offset=offset
        )
        
        return ImportJobListResponse(**result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list jobs: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list jobs: {str(e)}"
        )
```

### 2.6 依赖注入

```python
# app/api/v1/dependencies.py
from functools import lru_cache
from app.features.import.application.import_service import ImportService
from app.features.import.infrastructure.repositories.job_repository_impl import JobRepositoryImpl
from app.features.import.infrastructure.repositories.file_repository_impl import FileRepositoryImpl
from app.features.import.infrastructure.repositories.parser_repository_impl import ParserRepositoryImpl
from app.features.import.infrastructure.parsers.parser_factory import ParserFactory
from app.features.import.infrastructure.task_executor.async_executor import AsyncTaskExecutor


@lru_cache()
def get_job_repository() -> JobRepositoryImpl:
    """获取Job仓储实例（单例）"""
    return JobRepositoryImpl()


@lru_cache()
def get_file_repository() -> FileRepositoryImpl:
    """获取File仓储实例（单例）"""
    return FileRepositoryImpl()


@lru_cache()
def get_parser_repository() -> ParserRepositoryImpl:
    """获取Parser仓储实例（单例）"""
    return ParserRepositoryImpl()


@lru_cache()
def get_parser_factory() -> ParserFactory:
    """获取Parser工厂实例（单例）"""
    return ParserFactory(get_parser_repository())


@lru_cache()
def get_task_executor() -> AsyncTaskExecutor:
    """获取任务执行器实例（单例）"""
    return AsyncTaskExecutor()


def get_import_service(
    job_repo: JobRepositoryImpl = Depends(get_job_repository),
    file_repo: FileRepositoryImpl = Depends(get_file_repository),
    parser_factory: ParserFactory = Depends(get_parser_factory),
    executor: AsyncTaskExecutor = Depends(get_task_executor)
) -> ImportService:
    """获取Import服务实例"""
    return ImportService(
        job_repository=job_repo,
        file_repository=file_repo,
        parser_factory=parser_factory,
        task_executor=executor
    )
```

---

## 3. Features层设计

### 3.1 目录结构

```
app/
└── features/
    └── import/                     # 导入功能（垂直聚合）
        ├── __init__.py
        ├── domain/                 # 领域层
        │   ├── __init__.py
        │   ├── entities/           # 实体
        │   │   ├── __init__.py
        │   │   ├── import_job.py   # 导入任务实体
        │   │   ├── parsed_document.py  # 解析后的文档实体
        │   │   └── import_result.py    # 导入结果实体
        │   ├── value_objects/      # 值对象
        │   │   ├── __init__.py
        │   │   ├── job_id.py
        │   │   ├── job_status.py
        │   │   ├── library_name.py
        │   │   └── vector_config.py
        │   └── repositories/       # 仓储接口
        │       ├── __init__.py
        │       ├── job_repository.py
        │       ├── file_repository.py
        │       └── parser_repository.py
        │
        ├── application/            # 应用层
        │   ├── __init__.py
        │   ├── import_service.py   # 导入服务（核心编排）
        │   └── dto/                # 数据传输对象
        │       ├── __init__.py
        │       ├── import_job_dto.py
        │       └── import_result_dto.py
        │
        └── infrastructure/         # 基础设施层
            ├── __init__.py
            ├── repositories/       # 仓储实现
            │   ├── __init__.py
            │   ├── job_repository_impl.py
            │   ├── file_repository_impl.py
            │   └── parser_repository_impl.py
            │
            ├── parsers/            # 文档解析器
            │   ├── __init__.py
            │   ├── base_parser.py  # 解析器基类
            │   ├── markdown_parser.py  # Markdown解析器
            │   ├── json_parser.py  # JSON解析器
            │   ├── custom_parser_executor.py  # 自定义解析器执行器
            │   └── parser_factory.py  # 解析器工厂
            │
            ├── task_executor/      # 任务执行器
            │   ├── __init__.py
            │   ├── celery_executor.py  # Celery任务执行器
            │   ├── celery_tasks.py # Celery任务定义
            │   └── progress_tracker.py # 进度跟踪器
            │
            └── opensearch_integration/  # OpenSearch集成
                ├── __init__.py
                ├── document_importer.py  # 文档导入器
                └── index_manager.py      # 索引管理器
```

### 3.1.1 分层架构说明

本项目采用DDD（领域驱动设计）+ Clean Architecture模式，基于新的架构原则：**功能垂直聚合 + API 水平聚合**。

#### 架构层次对比

| 层级 | 位置 | 职责 | 依赖方向 |
|------|------|------|---------|
| **API层** | `app/api/v1/` | HTTP端点、参数验证、调用Service | → Application层 |
| **Application层** | `app/features/import/application/` | 用例编排、业务流程协调 | → Domain层 |
| **Domain层** | `app/features/import/domain/` | 业务逻辑、实体、Repository接口 | 不依赖其他层 |
| **Infrastructure层（特性内）** | `app/features/import/infrastructure/` | Repository实现、Parser、Celery | 实现Domain接口 |
| **Infrastructure层（共享）** | `app/infrastructure/` | OpenSearch客户端、Redis、Celery应用 | 被特性Infrastructure使用 |

#### 三层架构对比

| 维度 | Domain层 | Application层 | Infrastructure层 |
|------|----------|--------------|-----------------|
| **核心职责** | 业务概念和规则 | 用例编排 | 技术实现 |
| **包含内容** | 实体、值对象、Repository接口 | Service、DTO | Repository实现、Parser、Celery |
| **依赖方向** | 不依赖其他层 | 依赖Domain层 | 实现Domain层接口 |
| **技术无关性** | 完全无关 | 部分相关 | 完全相关 |
| **变更频率** | 低（业务稳定） | 中（用例变化） | 高（技术演进） |
| **示例代码** | `ImportJob.start()` | `service.create_import_job()` | `JobRepositoryImpl.save()` |
| **测试方式** | 纯单元测试 | Mock依赖测试 | 集成测试 |

#### 依赖规则（依赖倒置原则）

```
┌─────────────────┐
│   API层         │  ← app/api/v1/import_api.py（FastAPI端点）
└────────┬────────┘
         ↓ 调用
┌─────────────────┐
│ Application层   │  ← app/features/import/application/import_service.py
│                 │     （编排用例）
└────────┬────────┘
         ↓ 使用
┌─────────────────┐
│   Domain层      │  ← app/features/import/domain/entities/import_job.py
│                 │     + Repository接口
└────────┬────────┘
         ↑ 实现接口
┌─────────────────┐
│Infrastructure层 │  ← app/features/import/infrastructure/repositories/
│（特性内）        │     + app/infrastructure/opensearch/client.py
└─────────────────┘

关键：Domain层定义接口，Infrastructure层实现接口
     这样Domain层不依赖Infrastructure层（依赖倒置）
```

#### 数据流转示例

**创建导入任务的完整流程**：

1. **API层**：接收HTTP请求
   ```python
   # app/api/v1/import_api.py
   async def create_import_job(
       files: List[UploadFile],
       service: ImportService = Depends(get_import_service)  # 依赖注入
   ):
   ```

2. **Application层**：编排业务流程
   ```python
   # app/features/import/application/import_service.py
   # ImportService.create_import_job_with_files()
   - 保存文件（Infrastructure）
   - 解析文件（Infrastructure）
   - 创建ImportJob实体（Domain）
   - 保存任务（Infrastructure实现的Repository）
   - 提交Celery任务（Infrastructure）
   ```

3. **Domain层**：业务逻辑
   ```python
   # app/features/import/domain/entities/import_job.py
   # ImportJob实体
   job = ImportJob(...)  # 创建实体
   job.start()           # 业务逻辑：状态转换
   ```

4. **Infrastructure层**：技术实现
   ```python
   # app/features/import/infrastructure/repositories/job_repository_impl.py
   # JobRepositoryImpl.save()
   - 将ImportJob序列化为JSON
   - 保存到Redis
   
   # app/features/import/infrastructure/task_executor/celery_executor.py
   # CeleryExecutor.submit_import_task()
   - 提交异步任务到Celery
   ```

#### 分层的优势

| 优势 | 说明 | 示例 |
|------|------|------|
| **业务逻辑复用** | Domain层可以在不同技术栈中复用 | 从Flask迁移到FastAPI，Domain层不变 |
| **独立测试** | 各层可以独立测试 | Domain层不需要数据库就能测试 |
| **技术演进** | 可以替换技术实现 | Redis → PostgreSQL，只改Infrastructure |
| **职责清晰** | 每层关注点分离 | 业务人员关注Domain，技术人员关注Infrastructure |
| **并行开发** | 团队可以并行开发 | 后端定义接口，前后端并行开发 |

### 3.2 Domain层设计

**概述**

Domain层（领域层）是整个业务逻辑的核心，体现了DDD（领域驱动设计）的核心思想。这一层完全独立于技术实现细节，只关注业务概念和规则。

#### 职责与作用

| 职责 | 说明 |
|------|------|
| **业务概念建模** | 定义领域实体、值对象，表达业务核心概念（如ImportJob、ParsedDocument） |
| **业务规则封装** | 将业务逻辑封装在实体方法中（如任务状态转换、进度更新） |
| **定义接口契约** | 通过Repository接口定义数据访问契约，不依赖具体实现 |
| **保持纯净性** | 不依赖任何框架、数据库、外部服务，只包含纯粹的业务逻辑 |

#### 核心组件

1. **Entities（实体）**
   - `ImportJob`：导入任务的完整生命周期管理
   - `ParsedDocument`：解析后的文档数据表示
   - 特点：有唯一标识（ID）、有生命周期、可变状态

2. **Value Objects（值对象）**
   - `JobStatus`：任务状态枚举
   - `ParseResult`：解析结果值对象
   - 特点：无标识、不可变、按值比较

3. **Repository Interfaces（仓储接口）**
   - `JobRepository`：定义任务持久化契约
   - `FileRepository`：定义文件访问契约
   - `ParserRepository`：定义解析器管理契约
   - 特点：只定义接口，不实现，由Infrastructure层实现

#### 设计原则

- ✅ **独立性**：不依赖Application层和Infrastructure层
- ✅ **纯粹性**：只包含业务逻辑，无技术实现
- ✅ **可测试性**：可以在没有数据库、框架的情况下单元测试
- ✅ **表达力**：代码即文档，清晰表达业务规则

#### 3.2.1 实体：ImportJob

```python
# app/features/import/domain/entities/import_job.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class JobStatus(str, Enum):
    """任务状态"""
    PARSING = "parsing"          # 正在解析文件
    VECTORIZING = "vectorizing"  # 正在生成向量
    SAVING = "saving"            # 正在保存到PostgreSQL
    SYNCING = "syncing"          # 正在同步到OpenSearch
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


@dataclass
class ParseResult:
    """文件解析结果"""
    total_files: int
    parsed_files: int
    failed_files: int
    file_details: List[Dict[str, Any]] = field(default_factory=list)
    # file_details: [
    #     {"filename": "doc1.md", "success": True, "sections": 10},
    #     {"filename": "doc2.md", "success": False, "error": "Invalid format"}
    # ]


@dataclass
class ImportJob:
    """导入任务实体"""
    
    # 标识
    job_id: str
    
    # 配置
    library: str
    vector_model: Optional[str] = None
    import_mode: str = "replace"
    custom_parser_id: Optional[str] = None
    
    # 状态
    status: JobStatus = JobStatus.PARSING
    progress: float = 0.0
    message: str = ""
    
    # 文件解析结果（在任务创建时就有）
    parse_result: Optional[ParseResult] = None
    
    # 最终结果（仅 completed 时有值）
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # 时间
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def start(self):
        """开始执行（从解析转到向量化或导入）"""
        if self.status != JobStatus.PARSING:
            raise ValueError(f"Cannot start job in status: {self.status}")
        # 如果有向量模型，先进入向量化阶段，否则直接导入
        self.status = JobStatus.VECTORIZING if self.vector_model else JobStatus.IMPORTING
        self.started_at = datetime.now()
        self.message = "任务开始执行"
    
    def update_progress(self, progress: float, message: str):
        """更新进度"""
        if self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            raise ValueError(f"Cannot update progress for job in status: {self.status}")
        self.progress = max(0.0, min(1.0, progress))
        self.message = message
    
    def set_vectorizing(self):
        """设置为向量化阶段"""
        self.status = JobStatus.VECTORIZING
        self.message = "正在生成向量..."
    
    def set_saving(self):
        """设置为保存阶段"""
        self.status = JobStatus.SAVING
        self.message = "正在保存到PostgreSQL..."
    
    def set_syncing(self):
        """设置为同步阶段"""
        self.status = JobStatus.SYNCING
        self.message = "正在同步到OpenSearch..."
    
    def complete(self, result: Dict[str, Any]):
        """完成任务"""
        if self.status not in [JobStatus.VECTORIZING, JobStatus.SAVING, JobStatus.SYNCING]:
            raise ValueError(f"Cannot complete job in status: {self.status}")
        self.status = JobStatus.COMPLETED
        self.progress = 1.0
        self.result = result
        self.completed_at = datetime.now()
        self.message = "任务执行成功"
    
    def fail(self, error: str):
        """任务失败"""
        self.status = JobStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()
        self.message = f"任务执行失败: {error}"
    
    def cancel(self):
        """取消任务"""
        if self.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            raise ValueError(f"Cannot cancel job in status: {self.status}")
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.now()
        self.message = "任务已取消"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            'job_id': self.job_id,
            'library': self.library,
            'vector_model': self.vector_model,
            'import_mode': self.import_mode,
            'custom_parser_id': self.custom_parser_id,
            'status': self.status.value,
            'progress': self.progress,
            'message': self.message,
            'result': self.result,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
        
        # 添加解析结果
        if self.parse_result:
            data['parse_results'] = {
                'total_files': self.parse_result.total_files,
                'parsed_files': self.parse_result.parsed_files,
                'failed_files': self.parse_result.failed_files,
                'file_details': self.parse_result.file_details
            }
        
        return data
```

#### 3.2.2 实体：ParsedDocument

```python
# app/features/import/domain/entities/parsed_document.py
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class DocumentSection:
    """文档章节"""
    section_id: str
    section_title: str
    content: str


@dataclass
class DocumentMetadata:
    """文档元数据"""
    filename: str
    header_file: str = ""
    source_file: str = ""
    ut_file: str = ""


@dataclass
class ParsedDocument:
    """解析后的文档实体"""
    
    metadata: DocumentMetadata
    sections: List[DocumentSection]
    
    def to_json_dict(self) -> Dict[str, Any]:
        """转换为JSON格式"""
        return {
            'document_info': {
                'filename': self.metadata.filename,
                'header_file': self.metadata.header_file,
                'source_file': self.metadata.source_file,
                'ut_file': self.metadata.ut_file
            },
            'sections': [
                {
                    'section_id': section.section_id,
                    'section_title': section.section_title,
                    'content': section.content
                }
                for section in self.sections
            ]
        }
    
    @classmethod
    def from_json_dict(cls, data: Dict[str, Any]) -> 'ParsedDocument':
        """从JSON格式创建"""
        doc_info = data.get('document_info', {})
        metadata = DocumentMetadata(
            filename=doc_info.get('filename', ''),
            header_file=doc_info.get('header_file', ''),
            source_file=doc_info.get('source_file', ''),
            ut_file=doc_info.get('ut_file', '')
        )
        
        sections = [
            DocumentSection(
                section_id=s.get('section_id', ''),
                section_title=s.get('section_title', ''),
                content=s.get('content', '')
            )
            for s in data.get('sections', [])
        ]
        
        return cls(metadata=metadata, sections=sections)
```

#### 3.2.3 仓储接口

```python
# app/features/import/domain/repositories/job_repository.py
from abc import ABC, abstractmethod
from typing import Optional, List
from app.features.import.domain.entities.import_job import ImportJob


class JobRepository(ABC):
    """导入任务仓储接口"""
    
    @abstractmethod
    def save(self, job: ImportJob) -> None:
        """保存任务"""
        pass
    
    @abstractmethod
    def find_by_id(self, job_id: str) -> Optional[ImportJob]:
        """根据ID查找任务"""
        pass
    
    @abstractmethod
    def find_all(
        self,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[ImportJob], int]:
        """查找所有任务（支持过滤和分页）
        
        Returns:
            (任务列表, 总数)
        """
        pass
    
    @abstractmethod
    def delete(self, job_id: str) -> bool:
        """删除任务"""
        pass
```

```python
# app/features/import/domain/repositories/file_repository.py
from abc import ABC, abstractmethod
from typing import Optional, List


class FileRepository(ABC):
    """文件仓储接口"""
    
    @abstractmethod
    def get_file_path(self, file_id: str) -> Optional[str]:
        """根据file_id获取文件路径"""
        pass
    
    @abstractmethod
    def get_file_paths(self, file_ids: List[str]) -> List[str]:
        """批量获取文件路径"""
        pass
    
    @abstractmethod
    def file_exists(self, file_id: str) -> bool:
        """检查文件是否存在"""
        pass
```

```python
# app/features/import/domain/repositories/parser_repository.py
from abc import ABC, abstractmethod
from typing import Optional


class ParserRepository(ABC):
    """解析器仓储接口"""
    
    @abstractmethod
    def get_custom_parser_path(self, parser_id: str) -> Optional[str]:
        """获取自定义解析器脚本路径"""
        pass
    
    @abstractmethod
    def save_custom_parser(self, parser_id: str, script_content: bytes) -> str:
        """保存自定义解析器脚本
        
        Returns:
            保存的文件路径
        """
        pass
    
    @abstractmethod
    def parser_exists(self, parser_id: str) -> bool:
        """检查解析器是否存在"""
        pass
```

### 3.3 Application层设计

**概述**

Application层（应用层）是业务用例的编排中心，负责协调Domain层的领域对象和Infrastructure层的技术组件，完成具体的业务流程。

#### 职责与作用

| 职责 | 说明 |
|------|------|
| **用例编排** | 实现具体的业务用例（如"创建导入任务"、"查询任务状态"） |
| **流程协调** | 协调多个领域对象、仓储、外部服务完成复杂业务流程 |
| **事务管理** | 定义事务边界，确保操作的原子性 |
| **数据转换** | 在领域对象和DTO（数据传输对象）之间转换 |
| **业务验证** | 执行跨实体的业务验证逻辑 |

#### 核心组件

1. **ImportService（导入服务）**
   - 导入流程的核心编排器
   - 协调文件保存、解析、任务创建、异步执行等步骤
   - 是API层和Domain层之间的桥梁

2. **DTOs（数据传输对象）**
   - 用于在不同层之间传递数据
   - 与领域对象解耦，避免暴露内部结构

#### 设计特点

**流程编排示例**（创建导入任务）：
```
1. 生成任务ID和临时目录          ← 基础设施操作
2. 保存上传的文件                ← 基础设施操作
3. 解析文件内容                  ← 调用Infrastructure层的Parser
4. 验证解析结果                  ← 应用层业务规则
5. 创建ImportJob实体             ← 调用Domain层
6. 保存任务到仓储                ← 调用Repository
7. 提交Celery异步任务            ← 调用Infrastructure层
8. 返回结果                      ← 数据转换为DTO
```

#### 依赖关系

- **依赖于Domain层**：使用领域实体和仓储接口
- **依赖于Infrastructure层**：通过依赖注入使用具体实现
- **被API层依赖**：API层调用Application层的Service

#### 设计原则

- ✅ **薄应用层**：只做编排，不包含核心业务逻辑（业务逻辑在Domain层）
- ✅ **无状态**：Service对象本身不保存状态
- ✅ **单一职责**：每个方法对应一个完整的用例
- ✅ **依赖倒置**：依赖接口而非实现（Repository接口在Domain层定义）

#### 与其他层的交互

```
API层 (FastAPI)
    ↓ 调用
Application层 (ImportService)
    ↓ 使用实体和接口
Domain层 (ImportJob, Repository接口)
    ↑ 实现接口
Infrastructure层 (Repository实现, Parser, Celery)
```

#### 3.3.1 ImportService

```python
# app/features/import/application/import_service.py
import uuid
import tempfile
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.config.logging import get_logger
from fastapi import UploadFile

from app.features.import.domain.entities.import_job import ImportJob, JobStatus, ParseResult
from app.features.import.domain.repositories.job_repository import JobRepository
from app.features.import.infrastructure.parsers.parser_factory import ParserFactory
from app.features.import.infrastructure.task_executor.celery_executor import CeleryExecutor

logger = get_logger(__name__)


class ImportService:
    """导入服务（应用层）
    
    职责：
    - 编排导入流程
    - 验证业务规则
    - 协调领域对象和基础设施
    """
    
    def __init__(
        self,
        job_repository: JobRepository,
        parser_factory: ParserFactory,
        celery_executor: CeleryExecutor
    ):
        self.job_repository = job_repository
        self.parser_factory = parser_factory
        self.celery_executor = celery_executor
        logger.info("ImportService initialized")
    
    async def create_import_job_with_files(
        self,
        library: str,
        files: List[UploadFile],
        vector_model: Optional[str] = None,
        import_mode: str = "replace",
        custom_parser_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建导入任务（含文件上传和解析）
        
        流程：
        1. 接收并保存文件到临时目录
        2. 立即解析所有文件
        3. 生成向量（如需要）
        4. 【主存储】写入PostgreSQL（同步，事务保证）
        5. 【异步同步】提交Celery任务同步到OpenSearch
        6. 返回job_id和document_ids
        
        Args:
            library: 知识库名称
            files: 上传的文件列表
            vector_model: 向量模型
            import_mode: 导入模式
            custom_parser_id: 自定义解析器ID
        
        Returns:
            {
                'job_id': str,
                'document_ids': List[int],
                'message': str,
                'status': 'syncing',
                'details': {...}
            }
        """
        # 1. 生成任务ID和临时目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        job_id = f"import_{timestamp}_{unique_id}"
        
        # 创建临时目录存储上传的文件
        temp_dir = os.path.join(tempfile.gettempdir(), 'import_jobs', job_id)
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f"Created temp dir: {temp_dir}")
        
        # 2. 保存文件到临时目录
        saved_files = []
        for file in files:
            file_path = os.path.join(temp_dir, file.filename)
            
            # 读取并保存文件
            content = await file.read()
            with open(file_path, 'wb') as f:
                f.write(content)
            
            saved_files.append({
                'filename': file.filename,
                'path': file_path,
                'size': len(content)
            })
            logger.info(f"Saved file: {file.filename} ({len(content)} bytes)")
        
        # 3. 立即解析所有文件
        parse_results = await self._parse_files(
            saved_files,
            custom_parser_id
        )
        
        logger.info(f"Parse completed: {parse_results['parsed_files']}/{parse_results['total_files']} succeeded")
        
        # 4. 检查是否有成功解析的文件
        if parse_results['parsed_files'] == 0:
            # 所有文件都解析失败，不创建任务
            # 清理临时目录
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            raise ValueError(
                f"All {parse_results['total_files']} files failed to parse. "
                f"Details: {parse_results['file_details']}"
            )
        
        # 5. 创建任务实体
        parse_result_obj = ParseResult(
            total_files=parse_results['total_files'],
            parsed_files=parse_results['parsed_files'],
            failed_files=parse_results['failed_files'],
            file_details=parse_results['file_details']
        )
        
        job = ImportJob(
            job_id=job_id,
            library=library,
            vector_model=vector_model,
            import_mode=import_mode,
            custom_parser_id=custom_parser_id,
            status=JobStatus.PARSING,
            parse_result=parse_result_obj
        )
        
        # 6. 生成向量（同步执行）
        vectorized_sections = []
        if vector_model:
            logger.info(f"Job {job_id}: Generating vectors with model {vector_model}...")
            job.set_vectorizing()
            self.job_repository.save(job)
            
            from app.infrastructure.vector.vector_tool import VectorTool
            vector_tool = VectorTool(vector_model)
            
            # 遍历所有解析成功的文档
            for file_info in saved_files:
                parsed_json_path = f"{file_info['path']}.parsed.json"
                if not os.path.exists(parsed_json_path):
                    continue
                
                import json
                with open(parsed_json_path, 'r', encoding='utf-8') as f:
                    parsed_data = json.load(f)
                
                for section in parsed_data.get('sections', []):
                    text = f"{section['section_title']}\n{section['content']}"
                    vector = vector_tool.generate_embedding(text)
                    
                    vectorized_sections.append({
                        'filename': parsed_data['document_info']['filename'],
                        'section_id': section['section_id'],
                        'section_title': section['section_title'],
                        'content': section['content'],
                        'content_vector': vector
                    })
            
            logger.info(f"Job {job_id}: Generated {len(vectorized_sections)} vectors")
        else:
            # 不使用向量化，直接准备数据
            for file_info in saved_files:
                parsed_json_path = f"{file_info['path']}.parsed.json"
                if not os.path.exists(parsed_json_path):
                    continue
                
                import json
                with open(parsed_json_path, 'r', encoding='utf-8') as f:
                    parsed_data = json.load(f)
                
                for section in parsed_data.get('sections', []):
                    vectorized_sections.append({
                        'filename': parsed_data['document_info']['filename'],
                        'section_id': section['section_id'],
                        'section_title': section['section_title'],
                        'content': section['content'],
                        'content_vector': None
                    })
        
        # 7. 【主存储】写入PostgreSQL（同步，事务保证）
        logger.info(f"Job {job_id}: Saving {len(vectorized_sections)} documents to PostgreSQL...")
        job.set_saving()
        self.job_repository.save(job)
        
        from app.infrastructure.postgres.repositories.document import DocumentRepository
        from app.infrastructure.postgres.client import get_pg_client
        
        pg_client = get_pg_client()
        doc_repo = DocumentRepository(pg_client)
        
        # 批量保存文档（事务保证）
        document_ids = await doc_repo.bulk_save_documents(
            library=library,
            documents=vectorized_sections,
            mode=import_mode
        )
        
        logger.info(f"Job {job_id}: Saved to PostgreSQL, document_ids: {document_ids[:5]}...")
        
        # 8. 保存任务
        self.job_repository.save(job)
        logger.info(f"Import job created: {job_id}")
        
        # 9. 【异步同步】提交Celery任务同步到OpenSearch
        celery_task = await self.celery_executor.submit_sync_task(
            job_id=job_id,
            library=library,
            document_ids=document_ids,
            temp_dir=temp_dir  # 用于任务完成后清理
        )
        
        logger.info(f"Celery sync task submitted: {celery_task.id} for job {job_id}")
        
        # 10. 返回结果
        message = (
            f"文档已保存到数据库 ({len(document_ids)} 条)，"
            f"正在后台同步到搜索引擎"
        )
        
        if parse_results['failed_files'] > 0:
            message += f"，{parse_results['failed_files']} 个文件解析失败"
        
        return {
            'job_id': job_id,
            'document_ids': document_ids,
            'status': 'syncing',
            'message': message,
            'details': {
                'library': library,
                'use_vector': bool(vector_model),
                'vector_model': vector_model,
                'import_mode': import_mode,
                'postgresql_docs': len(document_ids),
                'parse_results': parse_results
            }
        }
    
    async def _parse_files(
        self,
        saved_files: List[Dict[str, Any]],
        custom_parser_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """解析文件列表
        
        Args:
            saved_files: 保存的文件列表 [{'filename', 'path', 'size'}]
            custom_parser_id: 自定义解析器ID
        
        Returns:
            {
                'total_files': int,
                'parsed_files': int,
                'failed_files': int,
                'file_details': [...]
            }
        """
        total_files = len(saved_files)
        parsed_files = 0
        failed_files = 0
        file_details = []
        
        for file_info in saved_files:
            filename = file_info['filename']
            file_path = file_info['path']
            
            try:
                # 获取解析器
                parser = self.parser_factory.get_parser(
                    file_path=file_path,
                    custom_parser_id=custom_parser_id
                )
                
                # 解析文件
                parsed_doc = parser.parse(file_path)
                
                # 统计章节数
                section_count = len(parsed_doc.sections)
                
                file_details.append({
                    'filename': filename,
                    'success': True,
                    'sections': section_count,
                    'error': None
                })
                
                parsed_files += 1
                logger.info(f"✓ Parsed {filename}: {section_count} sections")
            
            except Exception as e:
                error_msg = str(e)
                file_details.append({
                    'filename': filename,
                    'success': False,
                    'sections': 0,
                    'error': error_msg
                })
                
                failed_files += 1
                logger.error(f"✗ Failed to parse {filename}: {error_msg}")
        
        return {
            'total_files': total_files,
            'parsed_files': parsed_files,
            'failed_files': failed_files,
            'file_details': file_details
        }
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        job = self.job_repository.find_by_id(job_id)
        if not job:
            return None
        return job.to_dict()
    
    async def cancel_job(self, job_id: str) -> bool:
        """取消任务"""
        job = self.job_repository.find_by_id(job_id)
        if not job:
            return False
        
        try:
            job.cancel()
            self.job_repository.save(job)
            await self.celery_executor.cancel_task(job_id)
            logger.info(f"Job cancelled: {job_id}")
            return True
        except ValueError as e:
            logger.warning(f"Cannot cancel job: {job_id} - {str(e)}")
            return False
    
    async def list_jobs(
        self,
        status_filter: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """获取任务列表"""
        jobs, total = self.job_repository.find_all(
            status=status_filter,
            limit=limit,
            offset=offset
        )
        
        return {
            'total': total,
            'items': [job.to_dict() for job in jobs],
            'limit': limit,
            'offset': offset
        }
```

### 3.4 Infrastructure层设计

**概述**

Infrastructure层（基础设施层）是技术实现的集中地，负责与外部系统、框架、数据库等技术细节打交道。这一层实现Domain层定义的接口契约，为Application层提供具体的技术支持。

#### 职责与作用

| 职责 | 说明 |
|------|------|
| **接口实现** | 实现Domain层定义的Repository接口（数据持久化） |
| **外部集成** | 与OpenSearch、Redis、Celery等外部系统集成 |
| **技术组件** | 提供文档解析器、任务执行器、向量生成器等技术组件 |
| **框架适配** | 处理框架特定的逻辑（如Celery任务定义） |
| **资源管理** | 管理文件系统、网络连接、数据库连接等资源 |

#### 核心组件

1. **Repositories（仓储实现）**
   - `JobRepositoryImpl`：使用Redis/文件系统存储任务状态
   - `FileRepositoryImpl`：管理临时文件的存储和访问
   - `ParserRepositoryImpl`：管理自定义解析器脚本
   - 特点：实现Domain层的Repository接口

2. **Parsers（文档解析器）**
   - `MarkdownParser`：解析Markdown文件
   - `JsonParser`：解析JSON文件
   - `CustomParserExecutor`：安全执行用户上传的Python解析脚本
   - `ParserFactory`：根据文件类型创建合适的解析器

3. **Task Executor（任务执行器）**
   - `CeleryExecutor`：封装Celery任务提交和管理
   - `celery_tasks.py`：定义Celery异步任务（向量化、OpenSearch导入）
   - `ProgressTracker`：跟踪和更新任务进度

4. **OpenSearch Integration（OpenSearch集成）**
   - `DocumentImporter`：批量导入文档到OpenSearch
   - `IndexManager`：管理OpenSearch索引的创建、更新、删除

#### 技术栈

```
Infrastructure层的技术依赖：
├── PostgreSQL 14+        ← 主数据库（事务保证、pgvector）
├── OpenSearch 2.x        ← 搜索引擎（全文检索、向量搜索）
├── Redis                 ← 任务状态存储、Celery消息队列
├── Celery 5.3+           ← 异步任务处理（数据同步）
├── sentence-transformers ← 向量生成
└── subprocess            ← 安全执行自定义解析器
```

#### 依赖关系

- **实现Domain层接口**：Repository接口的具体实现
- **被Application层使用**：通过依赖注入提供具体实现
- **独立可替换**：可以替换技术实现而不影响业务逻辑（如Redis→PostgreSQL）

#### 设计特点

**关键设计模式**：
1. **Repository模式**：统一的数据访问接口
2. **Factory模式**：ParserFactory根据文件类型创建解析器
3. **Strategy模式**：不同的文档解析策略（Markdown、JSON、自定义）
4. **Adapter模式**：CeleryExecutor适配Celery框架

**安全隔离**：
- 自定义解析器使用`subprocess`在独立进程中执行
- 超时控制、资源限制、输出大小限制
- 环境变量隔离，防止访问敏感信息

#### 与其他层的交互

```
Domain层定义接口
    ↓ 实现
Infrastructure层提供实现
    ↑ 通过依赖注入
Application层使用实现
    ↑ 通过API调用
API层触发操作
```

#### 可扩展性

- ✅ **新增解析器**：实现`BaseParser`接口，注册到`ParserFactory`
- ✅ **切换存储**：实现新的`JobRepository`，替换Redis
- ✅ **替换队列**：实现新的`TaskExecutor`，替换Celery
- ✅ **新增向量模型**：在配置中添加模型，无需修改代码

#### 设计原则

- ✅ **封装技术细节**：隐藏PostgreSQL、OpenSearch、Celery等复杂性
- ✅ **依赖倒置**：实现Domain层定义的接口，不让Domain依赖Infrastructure
- ✅ **可测试性**：可以用内存实现替换真实实现进行测试
- ✅ **可替换性**：技术栈可以独立演进，不影响业务逻辑
- ✅ **职责分离**：PostgreSQL负责持久化，OpenSearch负责搜索

#### 3.4.1 Celery任务执行器

```python
# app/features/import/infrastructure/task_executor/celery_executor.py
from celery.result import AsyncResult
from app.config.logging import get_logger

logger = get_logger(__name__)


class CeleryExecutor:
    """Celery任务执行器"""
    
    def __init__(self, celery_app):
        """
        Args:
            celery_app: Celery应用实例
        """
        self.celery_app = celery_app
        logger.info("CeleryExecutor initialized")
    
    async def submit_sync_task(
        self,
        job_id: str,
        library: str,
        document_ids: list,
        temp_dir: str = None
    ):
        """提交OpenSearch同步任务到Celery
        
        Args:
            job_id: 任务ID
            library: 知识库名称
            document_ids: PostgreSQL中的文档ID列表
            temp_dir: 临时目录（用于任务完成后清理）
        
        Returns:
            Celery AsyncResult
        """
        from app.features.import.infrastructure.task_executor.celery_tasks import sync_to_opensearch_task
        
        # 提交异步任务
        task = sync_to_opensearch_task.delay(
            job_id=job_id,
            library=library,
            document_ids=document_ids,
            temp_dir=temp_dir
        )
        
        logger.info(f"Celery sync task submitted: {task.id} for job {job_id}")
        return task
    
    async def cancel_task(self, job_id: str):
        """取消Celery任务
        
        Args:
            job_id: 任务ID
        """
        # 根据job_id查找对应的Celery task_id
        # 这里需要维护job_id到task_id的映射
        # 简化处理：直接使用job_id作为task_id
        task = AsyncResult(job_id, app=self.celery_app)
        task.revoke(terminate=True)
        logger.info(f"Celery task cancelled: {job_id}")


# app/features/import/infrastructure/task_executor/celery_tasks.py
from celery import shared_task
from app.config.logging import get_logger
import os
import shutil

logger = get_logger(__name__)


@shared_task(bind=True, name='import.sync_to_opensearch_task')
def sync_to_opensearch_task(
    self,
    job_id: str,
    library: str,
    document_ids: list,
    temp_dir: str = None
):
    """同步数据到OpenSearch（Celery异步任务）
    
    流程：
    1. 从PostgreSQL读取文档数据
    2. 构建OpenSearch索引文档
    3. 批量索引到OpenSearch
    4. 更新任务状态
    5. 清理临时文件
    
    Args:
        self: Celery task instance
        job_id: 任务ID
        library: 知识库名称
        document_ids: PostgreSQL中的文档ID列表
        temp_dir: 临时目录
    """
    try:
        # 更新任务状态：开始同步
        from app.features.import.domain.repositories.job_repository import JobRepository
        from app.features.import.infrastructure.repositories.job_repository_impl import JobRepositoryImpl
        
        job_repo = JobRepositoryImpl()
        job = job_repo.find_by_id(job_id)
        
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        # 1. 从PostgreSQL读取文档数据
        logger.info(f"Task {job_id}: Loading documents from PostgreSQL...")
        job.set_syncing()
        job.update_progress(0.0, f"开始从PostgreSQL读取数据 (0/{len(document_ids)})...")
        job_repo.save(job)
        
        from app.infrastructure.postgres.repositories.document import DocumentRepository
        from app.infrastructure.postgres.client import get_pg_client
        
        pg_client = get_pg_client()
        doc_repo = DocumentRepository(pg_client)
        
        # 批量读取文档
        documents = await doc_repo.get_documents_by_ids(document_ids)
        logger.info(f"Task {job_id}: Loaded {len(documents)} documents from PostgreSQL")
        
        # 2. 构建OpenSearch索引文档
        logger.info(f"Task {job_id}: Building OpenSearch documents...")
        opensearch_docs = []
        
        for doc in documents:
            opensearch_doc = {
                '_id': str(doc['id']),
                'doc_id': doc['id'],
                'document_fingerprint': doc['fingerprint'],
                'filename': doc['filename'],
                'library': library,
                'doc_type': doc.get('doc_type', 'CODE'),
                'section_id': doc.get('section_id', ''),
                'section_title': doc.get('section_title', ''),
                'content': doc['content'],
                'created_at': doc['created_at'].isoformat(),
                'updated_at': doc['updated_at'].isoformat()
            }
            
            # 添加向量（如果有）
            if 'content_vector' in doc and doc['content_vector']:
                opensearch_doc['content_vector'] = doc['content_vector']
            
            opensearch_docs.append(opensearch_doc)
        
        # 3. 批量索引到OpenSearch
        logger.info(f"Task {job_id}: Indexing to OpenSearch...")
        job.update_progress(0.3, f"正在同步到OpenSearch (0/{len(opensearch_docs)})...")
        job_repo.save(job)
        
        from app.infrastructure.opensearch.client import get_opensearch_client
        from app.infrastructure.opensearch.document_indexer import DocumentIndexer
        from app.infrastructure.opensearch.index_manager import IndexManager
        from app.config.config_manager import get_config_manager
        
        config = get_config_manager()
        opensearch_client = get_opensearch_client()
        doc_indexer = DocumentIndexer(opensearch_client)
        index_manager = IndexManager(opensearch_client)
        
        index_name = config.get(f"index_mappings.{library}.index_name", library)
        
        # 检查/创建索引
        if not index_manager.index_exists(index_name):
            # 检查是否有向量维度
            has_vector = any('content_vector' in doc for doc in opensearch_docs)
            vector_dims = None
            if has_vector and opensearch_docs[0].get('content_vector'):
                vector_dims = len(opensearch_docs[0]['content_vector'])
            
            index_manager.create_index(
                index_name,
                use_vector=has_vector,
                vector_dims=vector_dims
            )
            logger.info(f"Created OpenSearch index: {index_name}")
        
        # 批量索引
        bulk_result = doc_indexer.bulk_index(index_name, opensearch_docs)
        
        indexed_count = bulk_result['success_count']
        error_count = bulk_result['error_count']
        
        logger.info(f"Task {job_id}: OpenSearch indexing completed - {indexed_count} success, {error_count} errors")
        
        # 4. 更新任务状态为完成
        result = {
            'index_name': index_name,
            'postgresql_docs': len(documents),
            'opensearch_indexed': indexed_count,
            'opensearch_failed': error_count,
            'document_ids': document_ids
        }
        
        job.complete(result)
        job_repo.save(job)
        
        # 5. 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Task {job_id}: Cleaned up temp dir: {temp_dir}")
        
        return result
    
    except Exception as e:
        logger.error(f"Task {job_id} failed: {str(e)}", exc_info=True)
        
        # 更新任务状态为失败
        try:
            job = job_repo.find_by_id(job_id)
            if job:
                job.fail(str(e))
                job_repo.save(job)
        except Exception as update_error:
            logger.error(f"Failed to update job status: {str(update_error)}")
        
        # 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        raise
    
    Args:
        self: Celery task instance
        job_id: 任务ID
        library: 知识库名称
        parsed_file_paths: 已解析的文件路径列表
        vector_model: 向量模型
        import_mode: 导入模式
        temp_dir: 临时目录
    """
    try:
        # 更新任务状态：开始向量化或导入
        from app.features.import.domain.repositories.job_repository import JobRepository
        from app.features.import.infrastructure.repositories.job_repository_impl import JobRepositoryImpl
        
        job_repo = JobRepositoryImpl()
        job = job_repo.find_by_id(job_id)
        
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        # 1. 读取已解析的文件数据
        logger.info(f"Task {job_id}: Loading parsed files...")
        parsed_docs = []
        
        for file_path in parsed_file_paths:
            # 读取解析后的JSON数据（由前面解析步骤保存）
            # 这里假设解析器已经将结果保存为 {file_path}.parsed.json
            parsed_json_path = f"{file_path}.parsed.json"
            
            if os.path.exists(parsed_json_path):
                import json
                with open(parsed_json_path, 'r', encoding='utf-8') as f:
                    parsed_data = json.load(f)
                    parsed_docs.append(parsed_data)
            else:
                logger.warning(f"Parsed file not found: {parsed_json_path}")
        
        if not parsed_docs:
            raise ValueError("No parsed documents found")
        
        total_sections = sum(len(doc.get('sections', [])) for doc in parsed_docs)
        logger.info(f"Task {job_id}: Loaded {len(parsed_docs)} files, {total_sections} sections")
        
        # 2. 向量化阶段（如果需要）
        if vector_model:
            job.set_vectorizing()
            job.update_progress(0.0, f"开始生成向量 (0/{total_sections})...")
            job_repo.save(job)
            
            from app.infrastructure.vector.vector_tool import VectorTool
            vector_tool = VectorTool(vector_model)
            
            processed_sections = 0
            for doc in parsed_docs:
                for section in doc.get('sections', []):
                    # 生成向量
                    text = f"{section['section_title']}\n{section['content']}"
                    vector = vector_tool.generate_embedding(text)
                    section['content_vector'] = vector
                    
                    processed_sections += 1
                    progress = processed_sections / total_sections
                    
                    # 每10%更新一次进度
                    if processed_sections % max(1, total_sections // 10) == 0:
                        job.update_progress(
                            progress * 0.5,  # 向量化占50%
                            f"生成向量中 ({processed_sections}/{total_sections})..."
                        )
                        job_repo.save(job)
            
            logger.info(f"Task {job_id}: Vectorization completed")
        
        # 3. 导入OpenSearch阶段
        job.set_importing()
        job.update_progress(0.5 if vector_model else 0.0, "开始导入到OpenSearch...")
        job_repo.save(job)
        
        from app.infrastructure.opensearch.client import OpenSearchClient
        from app.infrastructure.opensearch.document_importer import DocumentImporter
        from app.infrastructure.opensearch.index_manager import IndexManager
        from app.config.config_manager import get_config_manager
        
        config = get_config_manager()
        opensearch_client = OpenSearchClient()
        doc_importer = DocumentImporter(opensearch_client)
        index_manager = IndexManager(opensearch_client)
        
        index_name = config.get(f"index_mappings.{library}.index_name", library)
        
        # 检查/创建索引
        if not index_manager.index_exists(index_name):
            vector_models_config = config.get("vector_models", {})
            vector_dims = vector_models_config.get(vector_model, {}).get('dimension') if vector_model else None
            index_manager.create_index(
                index_name,
                use_vector=bool(vector_model),
                vector_dims=vector_dims
            )
            logger.info(f"Created index: {index_name}")
        
        # 准备文档列表
        documents = []
        for doc_data in parsed_docs:
            doc_info = doc_data['document_info']
            filename = doc_info['filename']
            fingerprint = doc_importer.generate_fingerprint(filename)
            
            for section in doc_data['sections']:
                doc_id = doc_importer.generate_doc_id(fingerprint, section['section_id'])
                
                opensearch_doc = {
                    '_id': doc_id,
                    'doc_id': doc_id,
                    'document_fingerprint': fingerprint,
                    'filename': filename,
                    'header_file': doc_info.get('header_file', ''),
                    'source_file': doc_info.get('source_file', ''),
                    'ut_file': doc_info.get('ut_file', ''),
                    'section_id': section['section_id'],
                    'section_title': section['section_title'],
                    'content': section['content']
                }
                
                if 'content_vector' in section:
                    opensearch_doc['content_vector'] = section['content_vector']
                
                documents.append(opensearch_doc)
        
        # 批量导入
        logger.info(f"Task {job_id}: Importing {len(documents)} documents to OpenSearch...")
        bulk_result = doc_importer.bulk_import(index_name, documents)
        
        imported_count = bulk_result['success_count']
        error_count = bulk_result['error_count']
        
        logger.info(f"Task {job_id}: Import completed - {imported_count} success, {error_count} errors")
        
        # 4. 更新任务状态为完成
        vector_models_config = config.get("vector_models", {})
        result = {
            'index_name': index_name,
            'imported_docs': imported_count,
            'total_docs': len(documents),
            'failed_docs': error_count,
            'has_vector': bool(vector_model),
            'vector_dims': vector_models_config.get(vector_model, {}).get('dimension') if vector_model else None
        }
        
        job.complete(result)
        job_repo.save(job)
        
        # 5. 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Task {job_id}: Cleaned up temp dir: {temp_dir}")
        
        return result
    
    except Exception as e:
        logger.error(f"Task {job_id} failed: {str(e)}", exc_info=True)
        
        # 更新任务状态为失败
        try:
            job = job_repo.find_by_id(job_id)
            if job:
                job.fail(str(e))
                job_repo.save(job)
        except Exception as update_error:
            logger.error(f"Failed to update job status: {str(update_error)}")
        
        # 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        raise
```

#### 3.4.2 仓储实现

```python
# app/features/import/infrastructure/repositories/job_repository_impl.py
import threading
from typing import Optional, List, Dict
from app.features.import.domain.entities.import_job import ImportJob
from app.features.import.domain.repositories.job_repository import JobRepository
from app.config.logging import get_logger

logger = get_logger(__name__)


class JobRepositoryImpl(JobRepository):
    """导入任务仓储实现（内存版本）
    
    注意：生产环境应使用Redis或数据库实现
    """
    
    def __init__(self):
        self._jobs: Dict[str, ImportJob] = {}
        self._lock = threading.Lock()
        logger.info("JobRepositoryImpl initialized (in-memory)")
    
    def save(self, job: ImportJob) -> None:
        """保存任务"""
        with self._lock:
            self._jobs[job.job_id] = job
            logger.debug(f"Job saved: {job.job_id}")
    
    def find_by_id(self, job_id: str) -> Optional[ImportJob]:
        """根据ID查找任务"""
        with self._lock:
            return self._jobs.get(job_id)
    
    def find_all(
        self,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[ImportJob], int]:
        """查找所有任务"""
        with self._lock:
            jobs = list(self._jobs.values())
            
            # 状态过滤
            if status:
                jobs = [j for j in jobs if j.status.value == status]
            
            # 按创建时间倒序
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            
            total = len(jobs)
            
            # 分页
            jobs = jobs[offset:offset + limit]
            
            return jobs, total
    
    def delete(self, job_id: str) -> bool:
        """删除任务"""
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                logger.debug(f"Job deleted: {job_id}")
                return True
            return False
```

```python
# app/features/import/infrastructure/repositories/file_repository_impl.py
import os
from typing import Optional, List
from app.features.import.domain.repositories.file_repository import FileRepository
from app.config.logging import get_logger

logger = get_logger(__name__)


class FileRepositoryImpl(FileRepository):
    """文件仓储实现"""
    
    def __init__(self):
        logger.info("FileRepositoryImpl initialized")
    
    def get_file_path(self, file_id: str) -> Optional[str]:
        """根据file_id获取文件路径"""
        try:
            # 从存储系统获取文件路径
            # 这里需要根据实际存储方式实现
            # 例如：从 app/infrastructure/storage/ 获取
            return None
        except Exception as e:
            logger.error(f"Failed to get file path: {file_id} - {str(e)}")
            return None
    
    def get_file_paths(self, file_ids: List[str]) -> List[str]:
        """批量获取文件路径"""
        paths = []
        for file_id in file_ids:
            path = self.get_file_path(file_id)
            if path:
                paths.append(path)
        return paths
    
    def file_exists(self, file_id: str) -> bool:
        """检查文件是否存在"""
        path = self.get_file_path(file_id)
        return path is not None and os.path.exists(path)
```

```python
# app/features/import/infrastructure/repositories/parser_repository_impl.py
import os
from typing import Optional
from app.features.import.domain.repositories.parser_repository import ParserRepository
from app.config.settings import get_settings
from app.config.logging import get_logger

logger = get_logger(__name__)


class ParserRepositoryImpl(ParserRepository):
    """解析器仓储实现"""
    
    def __init__(self):
        settings = get_settings()
        self.parsers_dir = settings.custom_parsers_dir
        os.makedirs(self.parsers_dir, exist_ok=True)
        logger.info(f"ParserRepositoryImpl initialized: {self.parsers_dir}")
    
    def get_custom_parser_path(self, parser_id: str) -> Optional[str]:
        """获取自定义解析器脚本路径"""
        file_path = os.path.join(self.parsers_dir, f"{parser_id}.py")
        if os.path.exists(file_path):
            return file_path
        return None
    
    def save_custom_parser(self, parser_id: str, script_content: bytes) -> str:
        """保存自定义解析器脚本"""
        file_path = os.path.join(self.parsers_dir, f"{parser_id}.py")
        
        with open(file_path, 'wb') as f:
            f.write(script_content)
        
        logger.info(f"Custom parser saved: {parser_id}")
        return file_path
    
    def parser_exists(self, parser_id: str) -> bool:
        """检查解析器是否存在"""
        file_path = os.path.join(self.parsers_dir, f"{parser_id}.py")
        return os.path.exists(file_path)
```

#### 3.4.2 文档解析器

```python
# app/features/import/infrastructure/parsers/base_parser.py
from abc import ABC, abstractmethod
from app.features.import.domain.entities.parsed_document import ParsedDocument


class BaseParser(ABC):
    """文档解析器基类"""
    
    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        """解析文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            ParsedDocument实体
        
        Raises:
            ValueError: 文件格式错误或解析失败
        """
        pass
    
    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """检查是否支持该文件类型
        
        Args:
            file_path: 文件路径
        
        Returns:
            True if supported
        """
        pass
```

```python
# app/features/import/infrastructure/parsers/markdown_parser.py
import os
from app.features.import.infrastructure.parsers.base_parser import BaseParser
from app.features.import.domain.entities.parsed_document import (
    ParsedDocument,
    DocumentMetadata,
    DocumentSection
)
from app.infrastructure.parsers.markdown_converter import MarkdownConverter
from app.config.logging import get_logger

logger = get_logger(__name__)


class MarkdownParser(BaseParser):
    """Markdown文档解析器"""
    
    def parse(self, file_path: str) -> ParsedDocument:
        """解析Markdown文件
        
        注意：解析结果会同时保存为 {file_path}.parsed.json 供Celery任务使用
        """
        logger.debug(f"Parsing Markdown file: {file_path}")
        
        # 使用MarkdownConverter转换
        success, json_data, error_msg = MarkdownConverter.convert_to_json(file_path)
        
        if not success:
            raise ValueError(f"Failed to parse Markdown: {error_msg}")
        
        # 保存解析结果为JSON文件（供Celery任务使用）
        import json
        parsed_json_path = f"{file_path}.parsed.json"
        with open(parsed_json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved parsed result to: {parsed_json_path}")
        
        # 转换为ParsedDocument实体
        return ParsedDocument.from_json_dict(json_data)
    
    def supports(self, file_path: str) -> bool:
        """检查是否支持该文件"""
        return file_path.lower().endswith('.md')
```

```python
# app/features/import/infrastructure/parsers/json_parser.py
import json
from app.features.import.infrastructure.parsers.base_parser import BaseParser
from app.features.import.domain.entities.parsed_document import ParsedDocument
from app.infrastructure.parsers.file_validator import FileValidator
from app.config.logging import get_logger

logger = get_logger(__name__)


class JsonParser(BaseParser):
    """JSON文档解析器"""
    
    def parse(self, file_path: str) -> ParsedDocument:
        """解析JSON文件
        
        注意：解析结果会同时保存为 {file_path}.parsed.json 供Celery任务使用
        """
        logger.debug(f"Parsing JSON file: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # 验证JSON结构
        success, error_msg = FileValidator.validate_json_structure(json_data)
        if not success:
            raise ValueError(f"Invalid JSON structure: {error_msg}")
        
        # 保存解析结果为JSON文件（供Celery任务使用）
        # JSON文件本身已经是标准格式，直接复制
        parsed_json_path = f"{file_path}.parsed.json"
        with open(parsed_json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved parsed result to: {parsed_json_path}")
        
        # 转换为ParsedDocument实体
        return ParsedDocument.from_json_dict(json_data)
    
    def supports(self, file_path: str) -> bool:
        """检查是否支持该文件"""
        return file_path.lower().endswith('.json')
```

---

## 4. 自定义文档解析机制

### 4.1 设计原则

1. **安全性优先**：不能直接import/exec用户脚本
2. **隔离执行**：使用subprocess独立进程执行
3. **标准接口**：定义清晰的输入输出协议
4. **错误处理**：完善的错误捕获和日志记录
5. **资源限制**：超时控制、内存限制

### 4.2 自定义解析器协议

用户上传的Python脚本必须遵循以下接口规范：

```python
# 用户自定义解析器模板
"""
自定义文档解析器

必须实现 parse_document() 函数
"""

def parse_document(file_path: str) -> dict:
    """解析文档
    
    Args:
        file_path: 待解析的文件路径（绝对路径）
    
    Returns:
        解析结果，必须符合以下格式：
        {
            "document_info": {
                "filename": str,        # 必填
                "header_file": str,     # 可选
                "source_file": str,     # 可选
                "ut_file": str          # 可选
            },
            "sections": [
                {
                    "section_id": str,      # 必填
                    "section_title": str,   # 必填
                    "content": str          # 必填
                },
                ...
            ]
        }
    
    Raises:
        ValueError: 解析失败时抛出异常
    """
    # 用户自定义的解析逻辑
    pass


# 示例：解析纯文本文件
def parse_document(file_path: str) -> dict:
    import os
    
    filename = os.path.basename(file_path)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 按空行分割为多个章节
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    
    sections = []
    for i, para in enumerate(paragraphs, 1):
        # 取第一行作为标题
        lines = para.split('\n')
        title = lines[0][:50] if lines else f"Section {i}"
        
        sections.append({
            "section_id": f"sec_{i:03d}",
            "section_title": title,
            "content": para
        })
    
    return {
        "document_info": {
            "filename": filename,
            "header_file": "",
            "source_file": "",
            "ut_file": ""
        },
        "sections": sections
    }
```

### 4.3 自定义解析器执行器

```python
# app/features/import/infrastructure/parsers/custom_parser_executor.py
import os
import sys
import json
import subprocess
import tempfile
from typing import Dict, Any
from app.config.logging import get_logger

logger = get_logger(__name__)


class CustomParserExecutor:
    """自定义解析器执行器
    
    使用subprocess独立进程执行用户上传的Python解析脚本
    """
    
    # 安全配置
    TIMEOUT_SECONDS = 300  # 5分钟超时
    MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10MB输出限制
    
    def __init__(self, parser_script_path: str):
        """
        Args:
            parser_script_path: 用户自定义解析器脚本路径
        """
        self.parser_script_path = parser_script_path
        
        if not os.path.exists(parser_script_path):
            raise FileNotFoundError(f"Parser script not found: {parser_script_path}")
        
        logger.info(f"CustomParserExecutor initialized: {parser_script_path}")
    
    def execute(self, file_path: str) -> Dict[str, Any]:
        """执行自定义解析器
        
        Args:
            file_path: 待解析的文件路径
        
        Returns:
            解析结果（JSON dict）
        
        Raises:
            RuntimeError: 执行失败
            ValueError: 输出格式错误
            TimeoutError: 执行超时
        """
        logger.info(f"Executing custom parser for: {file_path}")
        
        # 1. 创建临时包装脚本
        wrapper_script = self._create_wrapper_script(file_path)
        
        try:
            # 2. 在子进程中执行
            result = subprocess.run(
                [sys.executable, wrapper_script],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                env=self._get_safe_env()
            )
            
            # 3. 检查执行结果
            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Custom parser failed: {error_msg}")
                raise RuntimeError(f"Custom parser execution failed: {error_msg}")
            
            # 4. 解析输出
            output = result.stdout
            
            if len(output) > self.MAX_OUTPUT_SIZE:
                raise ValueError(f"Parser output too large: {len(output)} bytes")
            
            try:
                parsed_result = json.loads(output)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON output: {output[:500]}")
                raise ValueError(f"Parser returned invalid JSON: {str(e)}")
            
            # 5. 验证输出格式
            self._validate_output_format(parsed_result)
            
            logger.info(f"Custom parser executed successfully: {len(parsed_result.get('sections', []))} sections")
            return parsed_result
        
        except subprocess.TimeoutExpired:
            logger.error(f"Custom parser timeout: {file_path}")
            raise TimeoutError(f"Parser execution timeout ({self.TIMEOUT_SECONDS}s)")
        
        finally:
            # 清理临时文件
            if os.path.exists(wrapper_script):
                os.remove(wrapper_script)
    
    def _create_wrapper_script(self, file_path: str) -> str:
        """创建包装脚本
        
        包装脚本负责：
        1. 加载用户的解析器脚本
        2. 调用parse_document函数
        3. 将结果以JSON格式输出到stdout
        """
        wrapper_code = f'''
import sys
import json
import os

# 禁用所有危险操作
import builtins
# 禁止import某些危险模块（可根据需要调整）
# builtins.__import__ = lambda *args, **kwargs: None  # 过于严格，会导致无法import基础库

# 加载用户解析器
user_parser_path = r"{self.parser_script_path}"
spec = __import__('importlib.util').util.spec_from_file_location("user_parser", user_parser_path)
user_parser = __import__('importlib.util').util.module_from_spec(spec)
spec.loader.exec_module(user_parser)

# 检查是否实现了parse_document函数
if not hasattr(user_parser, 'parse_document'):
    raise AttributeError("Parser script must implement parse_document() function")

# 执行解析
file_path = r"{file_path}"
try:
    result = user_parser.parse_document(file_path)
    
    # 输出JSON结果到stdout
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)
    
except Exception as e:
    # 错误信息输出到stderr
    sys.stderr.write(f"Parser error: {{type(e).__name__}}: {{str(e)}}\\n")
    sys.exit(1)
'''
        
        # 创建临时文件
        fd, temp_path = tempfile.mkstemp(suffix='.py', prefix='parser_wrapper_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(wrapper_code)
            return temp_path
        except Exception:
            os.close(fd)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
    
    def _get_safe_env(self) -> Dict[str, str]:
        """获取安全的环境变量
        
        移除可能包含敏感信息的环境变量
        """
        env = os.environ.copy()
        
        # 移除敏感环境变量
        sensitive_keys = [
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
            'DATABASE_PASSWORD',
            'API_KEY',
        ]
        
        for key in sensitive_keys:
            env.pop(key, None)
        
        return env
    
    def _validate_output_format(self, data: Dict[str, Any]):
        """验证输出格式
        
        Raises:
            ValueError: 格式错误
        """
        # 检查必填字段
        if 'document_info' not in data:
            raise ValueError("Missing 'document_info' field")
        
        if 'sections' not in data:
            raise ValueError("Missing 'sections' field")
        
        doc_info = data['document_info']
        if not isinstance(doc_info, dict):
            raise ValueError("'document_info' must be a dict")
        
        if 'filename' not in doc_info:
            raise ValueError("Missing 'document_info.filename' field")
        
        sections = data['sections']
        if not isinstance(sections, list):
            raise ValueError("'sections' must be a list")
        
        # 检查每个章节
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError(f"Section {i} must be a dict")
            
            required_fields = ['section_id', 'section_title', 'content']
            for field in required_fields:
                if field not in section:
                    raise ValueError(f"Section {i} missing required field: {field}")
        
        logger.debug("Output format validation passed")
```

```python
# app/features/import/infrastructure/parsers/custom_parser.py
from app.features.import.infrastructure.parsers.base_parser import BaseParser
from app.features.import.domain.entities.parsed_document import ParsedDocument
from app.features.import.infrastructure.parsers.custom_parser_executor import CustomParserExecutor
from app.config.logging import get_logger

logger = get_logger(__name__)


class CustomParser(BaseParser):
    """自定义解析器包装类"""
    
    def __init__(self, parser_script_path: str):
        """
        Args:
            parser_script_path: 自定义解析器脚本路径
        """
        self.executor = CustomParserExecutor(parser_script_path)
        logger.info(f"CustomParser initialized: {parser_script_path}")
    
    def parse(self, file_path: str) -> ParsedDocument:
        """解析文件"""
        logger.debug(f"Parsing file with custom parser: {file_path}")
        
        # 执行自定义解析器
        json_data = self.executor.execute(file_path)
        
        # 转换为ParsedDocument实体
        return ParsedDocument.from_json_dict(json_data)
    
    def supports(self, file_path: str) -> bool:
        """自定义解析器支持所有文件"""
        return True
```

### 4.4 解析器工厂

```python
# app/features/import/infrastructure/parsers/parser_factory.py
import os
from typing import Optional
from app.features.import.infrastructure.parsers.base_parser import BaseParser
from app.features.import.infrastructure.parsers.markdown_parser import MarkdownParser
from app.features.import.infrastructure.parsers.json_parser import JsonParser
from app.features.import.infrastructure.parsers.custom_parser import CustomParser
from app.features.import.domain.repositories.parser_repository import ParserRepository
from app.config.logging import get_logger

logger = get_logger(__name__)


class ParserFactory:
    """解析器工厂"""
    
    def __init__(self, parser_repository: ParserRepository):
        self.parser_repository = parser_repository
        
        # 内置解析器
        self.builtin_parsers = [
            MarkdownParser(),
            JsonParser()
        ]
        
        logger.info("ParserFactory initialized")
    
    def get_parser(
        self,
        file_path: str,
        custom_parser_id: Optional[str] = None
    ) -> BaseParser:
        """获取合适的解析器
        
        Args:
            file_path: 文件路径
            custom_parser_id: 自定义解析器ID（可选）
        
        Returns:
            解析器实例
        
        Raises:
            ValueError: 无法找到合适的解析器
        """
        # 1. 如果指定了自定义解析器，优先使用
        if custom_parser_id:
            parser_script_path = self.parser_repository.get_custom_parser_path(custom_parser_id)
            
            if not parser_script_path:
                raise ValueError(f"Custom parser not found: {custom_parser_id}")
            
            logger.info(f"Using custom parser: {custom_parser_id}")
            return CustomParser(parser_script_path)
        
        # 2. 使用内置解析器
        for parser in self.builtin_parsers:
            if parser.supports(file_path):
                logger.info(f"Using built-in parser: {parser.__class__.__name__}")
                return parser
        
        # 3. 无法找到合适的解析器
        ext = os.path.splitext(file_path)[1]
        raise ValueError(f"No parser available for file type: {ext}")
```

### 4.5 自定义解析器管理API

```python
# app/api/v1/parser_api.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from typing import List
from app.api.v1.schemas.parser_schemas import (
    CustomParserUploadResponse,
    CustomParserListResponse
)
from app.features.import.domain.repositories.parser_repository import ParserRepository
from app.api.v1.dependencies import get_parser_repository
from app.config.logging import get_logger
import uuid

logger = get_logger(__name__)
router = APIRouter(prefix="/parsers", tags=["Parsers"])


@router.post(
    "/custom",
    response_model=CustomParserUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传自定义解析器",
    description="上传用户自定义的Python解析脚本"
)
async def upload_custom_parser(
    file: UploadFile = File(..., description="解析器脚本文件（.py）"),
    parser_repo: ParserRepository = Depends(get_parser_repository)
) -> CustomParserUploadResponse:
    """上传自定义解析器"""
    
    # 验证文件类型
    if not file.filename.endswith('.py'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parser script must be a Python file (.py)"
        )
    
    try:
        # 生成parser_id
        parser_id = f"custom_{uuid.uuid4().hex[:12]}"
        
        # 读取文件内容
        content = await file.read()
        
        # 保存解析器脚本
        saved_path = parser_repo.save_custom_parser(parser_id, content)
        
        logger.info(f"Custom parser uploaded: {parser_id}")
        
        return CustomParserUploadResponse(
            success=True,
            parser_id=parser_id,
            filename=file.filename,
            message="自定义解析器上传成功"
        )
    
    except Exception as e:
        logger.error(f"Failed to upload parser: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload parser: {str(e)}"
        )


# Schema定义
from pydantic import BaseModel

class CustomParserUploadResponse(BaseModel):
    success: bool
    parser_id: str
    filename: str
    message: str
```

---

## 5. 配置和部署

### 5.1 配置项

本项目采用统一的动态配置系统，所有配置都在 `app/config/dynamic_config.yaml` 中定义。

```yaml
# app/config/dynamic_config.yaml

# PostgreSQL 配置（主数据库）
postgres:
  host: "localhost"
  port: 5432
  database: "bible_server"
  user: "postgres"
  password: "your_password"
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  enable_pgvector: true

# OpenSearch 配置（搜索引擎）
opensearch:
  host: "http://localhost:9200"
  timeout: 30
  max_retries: 3
  verify_certs: false

# Redis 配置（可选，用于任务状态存储和Celery消息队列）
redis:
  host: "localhost"
  port: 6379
  db: 0
  password: null

# Celery 配置
celery:
  broker_url: "redis://localhost:6379/0"  # 如果Redis不可用，会降级为Memory broker
  result_backend: "redis://localhost:6379/0"
  task_serializer: "json"
  result_serializer: "json"
  accept_content: ["json"]
  timezone: "Asia/Shanghai"
  enable_utc: true

# 向量模型配置
vector_models:
  mini:
    name: "paraphrase-multilingual-MiniLM-L12-v2"
    dimension: 384
  mpnet:
    name: "paraphrase-multilingual-mpnet-base-v2"
    dimension: 768
  bge-base:
    name: "BAAI/bge-base-zh-v1.5"
    dimension: 768
  bge-large:
    name: "BAAI/bge-large-zh-v1.5"
    dimension: 1024
  bge-m3:
    name: "BAAI/bge-m3"
    dimension: 1024
  e5-large:
    name: "intfloat/multilingual-e5-large"
    dimension: 1024
  default: "mpnet"
  load_on_startup: false  # 是否在启动时加载模型
  preload_models: []      # 预加载的模型列表

# 上传配置
upload:
  max_file_size: 52428800     # 50MB
  max_files_per_request: 10   # 每次请求最多上传文件数
  allowed_extensions: [".md", ".json"]
  temp_dir: "/tmp/import_jobs"

# 解析器配置
parsers:
  custom_parsers_dir: "/data/custom_parsers"
  execution_timeout: 300      # 解析器执行超时（秒）
  max_output_size: 10485760   # 解析器输出大小限制（10MB）

# 任务执行配置
tasks:
  worker_count: 3             # 任务执行工作线程数
  max_retention_hours: 24     # 任务结果保留时间（小时）
  job_cleanup_enabled: true   # 是否自动清理过期任务

# 索引配置（针对不同知识库）
index_mappings:
  common:
    index_name: "common_docs"
    mappings:
      properties:
        content:
          type: "text"
          analyzer: "standard"
        content_vector:
          type: "knn_vector"
          dimension: 768
          method:
            name: "hnsw"
            space_type: "cosinesimil"
            engine: "nmslib"
  test:
    index_name: "test_docs"
    mappings:
      properties:
        content:
          type: "text"
        content_vector:
          type: "knn_vector"
          dimension: 768
          method:
            name: "hnsw"
            space_type: "cosinesimil"
            engine: "nmslib"
```

### 5.2 目录初始化

```python
# app/config/init.py
import os
from app.config.settings import get_settings
from app.config.config_manager import get_config_manager
from app.config.logging import get_logger

logger = get_logger(__name__)


def initialize_directories():
    """初始化必要的目录"""
    config = get_config_manager()
    
    directories = [
        config.get("parsers.custom_parsers_dir", "/data/custom_parsers"),
        config.get("upload.temp_dir", "/tmp/import_jobs"),
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Directory initialized: {directory}")


async def initialize_app():
    """应用初始化"""
    logger.info("Initializing application...")
    
    # 1. 初始化目录
    initialize_directories()
    
    # 2. 初始化PostgreSQL客户端（主存储）
    from app.infrastructure.postgres.client import PostgreSQLClient
    pg_client = await PostgreSQLClient.create()
    logger.info("PostgreSQL client initialized (Primary storage)")
    
    # 3. 初始化OpenSearch客户端（搜索引擎）
    from app.infrastructure.opensearch.client import OpenSearchClient
    opensearch_client = await OpenSearchClient.create()
    logger.info("OpenSearch client initialized (Search engine)")
    
    # 4. 初始化Redis客户端（如果配置了）
    config = get_config_manager()
    if config.get("redis.host"):
        try:
            from app.infrastructure.redis.client import RedisClient
            redis_client = await RedisClient.create()
            logger.info("Redis client initialized")
        except Exception as e:
            logger.warning(f"Redis initialization failed, continuing without Redis: {e}")
    
    # 5. 初始化Celery应用
    from app.infrastructure.celery.app import get_celery_app
    celery_app = get_celery_app()
    logger.info("Celery app initialized")
    
    # 6. 加载向量模型（如果配置了预加载）
    if config.get("vector_models.load_on_startup"):
        preload_models = config.get("vector_models.preload_models", [])
        if preload_models:
            from app.infrastructure.celery.tasks import load_vector_models_task
            for model_id in preload_models:
                load_vector_models_task.delay(model_id)
                logger.info(f"Submitted vector model loading task: {model_id}")
    
    logger.info("Application initialized successfully")
```

---

## 6. 测试策略

### 6.1 单元测试

```python
# tests/unit/test_custom_parser_executor.py
import pytest
import tempfile
import os
from app.features.import.infrastructure.parsers.custom_parser_executor import CustomParserExecutor


def test_custom_parser_executor_success():
    """测试自定义解析器正常执行"""
    # 创建测试解析器脚本
    parser_script = '''
def parse_document(file_path):
    return {
        "document_info": {"filename": "test.txt"},
        "sections": [
            {
                "section_id": "sec_001",
                "section_title": "Test Section",
                "content": "Test content"
            }
        ]
    }
'''
    
    # 保存到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(parser_script)
        parser_path = f.name
    
    try:
        # 创建测试输入文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            input_path = f.name
        
        try:
            # 执行解析器
            executor = CustomParserExecutor(parser_path)
            result = executor.execute(input_path)
            
            # 验证结果
            assert 'document_info' in result
            assert 'sections' in result
            assert len(result['sections']) == 1
            assert result['sections'][0]['section_id'] == 'sec_001'
        
        finally:
            os.remove(input_path)
    
    finally:
        os.remove(parser_path)


def test_custom_parser_executor_timeout():
    """测试解析器超时"""
    # 创建会超时的解析器
    parser_script = '''
import time

def parse_document(file_path):
    time.sleep(1000)  # 睡眠很长时间
    return {"document_info": {}, "sections": []}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(parser_script)
        parser_path = f.name
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test")
            input_path = f.name
        
        try:
            executor = CustomParserExecutor(parser_path)
            executor.TIMEOUT_SECONDS = 2  # 设置短超时
            
            with pytest.raises(TimeoutError):
                executor.execute(input_path)
        
        finally:
            os.remove(input_path)
    
    finally:
        os.remove(parser_path)
```

### 6.2 集成测试

```python
# tests/integration/test_import_flow.py
import pytest
import time
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_complete_import_flow():
    """测试完整的导入流程（含文件上传）"""
    
    # 1. 提交导入任务（含文件上传）
    with open('test_data/sample1.md', 'rb') as f1, \
         open('test_data/sample2.md', 'rb') as f2:
        
        response = client.post(
            '/api/v1/import/jobs',
            data={
                'library': 'common',
                'vector_model': 'mpnet',
                'import_mode': 'replace'
            },
            files=[
                ('files', ('sample1.md', f1, 'text/markdown')),
                ('files', ('sample2.md', f2, 'text/markdown'))
            ]
        )
    
    # 验证响应
    assert response.status_code == 201
    result = response.json()
    
    assert result['success'] == True
    assert 'job_id' in result
    assert 'parse_results' in result
    
    job_id = result['job_id']
    parse_results = result['parse_results']
    
    # 验证解析结果
    assert parse_results['total_files'] == 2
    assert parse_results['parsed_files'] >= 1  # 至少有一个成功
    assert 'file_details' in parse_results
    
    print(f"Job created: {job_id}")
    print(f"Parse results: {parse_results}")
    
    # 2. 轮询任务状态
    max_wait = 120  # 最多等待2分钟
    waited = 0
    final_status = None
    
    while waited < max_wait:
        response = client.get(f'/api/v1/import/jobs/{job_id}')
        assert response.status_code == 200
        
        status = response.json()
        current_status = status['status']
        progress = status['progress']
        message = status['message']
        
        print(f"[{waited}s] Status: {current_status}, Progress: {progress:.2f}, Message: {message}")
        
        if current_status in ['completed', 'failed', 'cancelled']:
            final_status = status
            break
        
        time.sleep(3)
        waited += 3
    
    # 3. 验证最终状态
    assert final_status is not None, "Task did not complete within timeout"
    assert final_status['status'] == 'completed', f"Task failed: {final_status.get('error')}"
    
    # 验证结果
    result = final_status['result']
    assert result['imported_docs'] > 0
    assert result['index_name'] == 'test_common'
    assert result['has_vector'] == True
    assert result['vector_dims'] == 768  # MPNet维度
    
    print(f"Import completed successfully!")
    print(f"Imported {result['imported_docs']} documents to {result['index_name']}")


def test_import_with_parse_errors():
    """测试部分文件解析失败的情况"""
    
    # 创建一个无效的文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("Invalid markdown content without proper structure")
        invalid_file_path = f.name
    
    try:
        with open('test_data/sample.md', 'rb') as f1, \
             open(invalid_file_path, 'rb') as f2:
            
            response = client.post(
                '/api/v1/import/jobs',
                data={'library': 'common'},
                files=[
                    ('files', ('valid.md', f1, 'text/markdown')),
                    ('files', ('invalid.md', f2, 'text/markdown'))
                ]
            )
        
        result = response.json()
        
        # 应该至少有一个文件解析失败
        assert result['parse_results']['failed_files'] >= 1
        
        # 但只要有成功的文件，任务应该继续
        if result['parse_results']['parsed_files'] > 0:
            assert result['success'] == True
            assert 'job_id' in result
    
    finally:
        import os
        os.remove(invalid_file_path)


def test_import_all_files_failed():
    """测试所有文件都解析失败的情况"""
    
    # 创建完全无效的文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("invalid content")
        invalid_file_path = f.name
    
    try:
        with open(invalid_file_path, 'rb') as f1:
            response = client.post(
                '/api/v1/import/jobs',
                data={'library': 'common'},
                files=[('files', ('invalid.md', f1, 'text/markdown'))]
            )
        
        # 所有文件都失败，应该返回400错误
        assert response.status_code == 400
        assert 'failed to parse' in response.json()['detail'].lower()
    
    finally:
        import os
        os.remove(invalid_file_path)


def test_concurrent_imports():
    """测试并发导入"""
    
    import concurrent.futures
    
    def submit_import(file_index):
        with open(f'test_data/sample{file_index}.md', 'rb') as f:
            response = client.post(
                '/api/v1/import/jobs',
                data={'library': f'lib{file_index}'},
                files=[('files', (f'file{file_index}.md', f, 'text/markdown'))]
            )
            return response.json()
    
    # 并发提交3个导入任务
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(submit_import, i) for i in range(1, 4)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    # 验证所有任务都成功创建
    assert len(results) == 3
    for result in results:
        assert result['success'] == True
        assert 'job_id' in result


def test_different_vector_models():
    """测试不同的向量模型"""
    
    test_cases = [
        ('mini', 384),
        ('mpnet', 768),
        ('bge-base', 768),
        ('bge-large', 1024),
        ('bge-m3', 1024),
        ('e5-large', 1024)
    ]
    
    for model_name, expected_dims in test_cases:
        with open('test_data/sample.md', 'rb') as f:
            response = client.post(
                '/api/v1/import/jobs',
                data={
                    'library': 'common',
                    'vector_model': model_name
                },
                files=[('files', ('test.md', f, 'text/markdown'))]
            )
        
        assert response.status_code == 201
        result = response.json()
        
        assert result['success'] == True
        assert result['details']['use_vector'] == True
        assert result['details']['vector_model'] == model_name
        
        # 等待任务完成
        job_id = result['job_id']
        import time
        max_wait = 120
        waited = 0
        
        while waited < max_wait:
            status_resp = client.get(f'/api/v1/import/jobs/{job_id}')
            status = status_resp.json()
            
            if status['status'] == 'completed':
                # 验证向量维度
                assert status['result']['has_vector'] == True
                assert status['result']['vector_dims'] == expected_dims
                print(f"✓ Model {model_name} test passed, dims={expected_dims}")
                break
            
            time.sleep(3)
            waited += 3
        
        assert waited < max_wait, f"Task timeout for model {model_name}"


def test_no_vector_model():
    """测试不使用向量化"""
    
    with open('test_data/sample.md', 'rb') as f:
        response = client.post(
            '/api/v1/import/jobs',
            data={'library': 'common'},  # 不传 vector_model
            files=[('files', ('test.md', f, 'text/markdown'))]
        )
    
    assert response.status_code == 201
    result = response.json()
    
    assert result['success'] == True
    assert result['details']['use_vector'] == False
    assert result['details']['vector_model'] is None
    
    # 等待任务完成
    job_id = result['job_id']
    import time
    max_wait = 60
    waited = 0
    
    while waited < max_wait:
        status_resp = client.get(f'/api/v1/import/jobs/{job_id}')
        status = status_resp.json()
        
        if status['status'] == 'completed':
            # 验证没有向量
            assert status['result']['has_vector'] == False
            assert status['result']['vector_dims'] is None
            print("✓ No vector model test passed")
            break
        
        time.sleep(2)
        waited += 2
    
    assert waited < max_wait, "Task timeout"


def test_invalid_vector_model():
    """测试无效的向量模型"""
    
    with open('test_data/sample.md', 'rb') as f:
        response = client.post(
            '/api/v1/import/jobs',
            data={
                'library': 'common',
                'vector_model': 'invalid_model'  # 无效的模型
            },
            files=[('files', ('test.md', f, 'text/markdown'))]
        )
    
    # 应该返回400错误
    assert response.status_code == 400
    assert 'Invalid vector_model' in response.json()['detail']
```

---

## 7. 安全考虑

### 7.1 自定义解析器安全

1. **进程隔离**：使用subprocess独立进程执行，不污染主进程
2. **超时控制**：限制执行时间，防止无限循环
3. **输出限制**：限制输出大小，防止内存耗尽
4. **环境隔离**：移除敏感环境变量
5. **代码审查**：建议生产环境需要人工审查上传的脚本

### 7.2 进一步安全增强（可选）

1. **沙箱容器**：使用Docker容器运行自定义解析器
2. **资源限制**：限制CPU、内存使用
3. **网络隔离**：禁止解析器访问网络
4. **白名单机制**：只允许导入特定的Python标准库

```python
# 使用Docker运行自定义解析器（示例）
import docker

def execute_in_docker(parser_script_path: str, file_path: str) -> dict:
    """在Docker容器中执行解析器"""
    client = docker.from_env()
    
    container = client.containers.run(
        image='python:3.9-slim',
        command=['python', '/parser/wrapper.py'],
        volumes={
            parser_script_path: {'bind': '/parser/script.py', 'mode': 'ro'},
            file_path: {'bind': '/input/file', 'mode': 'ro'}
        },
        network_disabled=True,  # 禁用网络
        mem_limit='512m',  # 内存限制
        cpu_quota=50000,  # CPU限制
        remove=True,
        detach=False
    )
    
    return json.loads(container.decode('utf-8'))
```

---

## 8. 总结

本文档详细设计了Import（导入）功能的完整实现方案，主要特点：

### 8.1 核心优势

1. **✅ 简化的API设计**
   - 单一端点完成文件上传和导入
   - 立即返回解析结果和失败文件列表
   - 清晰的job_id用于后续查询

2. **✅ 灵活的向量模型选择**
   - 支持6种预置向量模型（mini/mpnet/bge-base/bge-large/bge-m3/e5-large）
   - 可选择不使用向量化（纯关键词检索）
   - 不同维度和精度的模型满足不同场景
   - 自动验证模型兼容性

3. **✅ 完善的错误处理**
   - 详细的参数验证（文件大小、类型、数量）
   - 明确的HTTP状态码和错误信息
   - 部分文件失败时任务仍可继续
   - 所有API都有异常响应示例

4. **✅ 现代化架构**
   - FastAPI提供高性能和类型安全
   - DDD分层设计，职责清晰
   - 领域驱动，易于理解和维护

5. **✅ 可靠的异步处理**
   - Celery处理耗时操作
   - 精细的状态跟踪（parsing/vectorizing/importing）
   - 完善的进度反馈机制

6. **✅ 安全的自定义解析**
   - subprocess进程隔离
   - 超时和资源限制
   - 标准化的解析器接口

7. **✅ 良好的扩展性**
   - 易于添加新的解析器类型
   - 支持自定义解析脚本
   - 预留Session和Skill扩展点

### 8.2 API使用示例

#### 8.2.1 基础导入（不使用向量）

```bash
# 只做关键词检索，不需要语义理解
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "files=@doc1.md" \
  -F "files=@doc2.md"
```

#### 8.2.2 使用向量化导入（推荐方式）

```bash
# 使用 mpnet 模型（推荐，通用场景）
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=mpnet" \
  -F "files=@doc1.md" \
  -F "files=@doc2.md"
```

**立即返回**（包含解析结果）：
```json
{
  "success": true,
  "job_id": "import_20260412_123456_abc123",
  "message": "文件解析完成 (2/2)，正在后台导入到ES",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0,
    "file_details": [
      {"filename": "doc1.md", "success": true, "sections": 10},
      {"filename": "doc2.md", "success": true, "sections": 5}
    ]
  },
  "details": {
    "library": "common",
    "use_vector": true,
    "vector_model": "mpnet",
    "estimated_docs": 15
  }
}
```

#### 8.2.3 中文文档导入

```bash
# 使用针对中文优化的 bge-base 模型
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=chinese_docs" \
  -F "vector_model=bge-base" \
  -F "files=@中文文档.md"
```

#### 8.2.4 高精度导入

```bash
# 使用 bge-large 获得更高的检索精度
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=important_docs" \
  -F "vector_model=bge-large" \
  -F "files=@critical_doc.md"
```

#### 8.2.5 查询任务状态

```bash
# 查询任务执行状态
curl http://localhost:9220/api/v1/import/jobs/{job_id}
```

**响应示例**（向量化阶段）：
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "vectorizing",
  "progress": 0.35,
  "message": "生成向量中 (35/100)...",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01"
}
```

**响应示例**（完成）：
```json
{
  "job_id": "import_20260412_123456_abc123",
  "status": "completed",
  "progress": 1.0,
  "message": "导入完成",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0
  },
  "result": {
    "index_name": "test_common",
    "imported_docs": 150,
    "total_docs": 150,
    "failed_docs": 0,
    "has_vector": true,
    "vector_dims": 768
  },
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": "2026-04-12T12:36:30"
}
```

#### 8.2.6 错误处理示例

**场景1：无效的向量模型**
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "vector_model=invalid_model" \
  -F "files=@doc.md"
```

响应（HTTP 400）：
```json
{
  "detail": "Invalid vector_model: invalid_model. Available: mini, mpnet, bge-base, bge-large, bge-m3, e5-large"
}
```

**场景2：文件过大**
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "files=@large_file.md"  # 文件大于10MB
```

响应（HTTP 413）：
```json
{
  "detail": "File too large: large_file.md (15.2MB). Maximum size: 10MB"
}
```

**场景3：任务不存在**
```bash
curl http://localhost:9220/api/v1/import/jobs/invalid_job_id
```

响应（HTTP 404）：
```json
{
  "detail": "Job not found: invalid_job_id"
}
```

**场景4：部分文件解析失败**

提交请求：
```bash
curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=common" \
  -F "files=@valid.md" \
  -F "files=@invalid.md"
```

响应（HTTP 201，任务继续）：
```json
{
  "success": true,
  "job_id": "import_20260412_123457_def456",
  "message": "文件解析完成 (1/2)，正在后台导入到OpenSearch。1个文件解析失败。",
  "parse_results": {
    "total_files": 2,
    "parsed_files": 1,
    "failed_files": 1,
    "file_details": [
      {"filename": "valid.md", "success": true, "sections": 10},
      {"filename": "invalid.md", "success": false, "error": "解析失败: 文件格式不正确"}
    ]
  }
}
```

### 8.3 实施建议

1. **阶段一：基础设施**
   - 搭建FastAPI应用框架
   - 配置Celery和Redis
   - 实现基础的Repository层

2. **阶段二：核心功能**
   - 实现Import API端点
   - 实现ImportService核心逻辑
   - 实现内置解析器（Markdown、JSON）

3. **阶段三：异步任务**
   - 实现Celery任务执行器
   - 实现向量化和OpenSearch导入逻辑
   - 完善进度跟踪机制

4. **阶段四：自定义解析**
   - 实现CustomParserExecutor
   - 实现Parser管理API
   - 安全测试和优化

5. **阶段五：测试和部署**
   - 单元测试和集成测试
   - 性能测试和优化
   - 生产环境部署

### 8.4 技术栈

- **Web框架**: FastAPI 0.110+
- **主数据库**: PostgreSQL 14+ (主存储、事务保证)
- **向量存储**: pgvector 0.5+
- **搜索引擎**: OpenSearch 2.x (全文检索、向量搜索)
- **异步任务**: Celery 5.3+
- **消息队列**: Redis 7.0+ (可选)
- **向量生成**: sentence-transformers 2.2+
- **配置管理**: PyYAML 6.0+
- **数据验证**: Pydantic 2.0+
- **Python版本**: 3.9+

### 8.5 架构特点

本设计遵循新的架构原则：
- ✅ **功能垂直聚合**：业务逻辑按功能（import）组织
- ✅ **API 水平聚合**：对外接口统一管理（app/api/v1/）
- ✅ **Clean Architecture**：Domain/Application/Infrastructure 三层分离
- ✅ **统一配置管理**：所有动态配置在 dynamic_config.yaml
- ✅ **双数据库架构**：PostgreSQL（主存储）+ OpenSearch（搜索引擎）
- ✅ **职责分离**：PostgreSQL 负责持久化，OpenSearch 负责搜索
- ✅ **数据安全**：PostgreSQL 事务保证数据完整性（Source of Truth）
- ✅ **后台任务**：使用 Celery 异步处理数据同步
- ✅ **组件可选**：Redis 为可选组件，不影响核心功能

---

> **注意**：本设计文档不包括Session管理和Skill功能，这些将在后续版本中完善。