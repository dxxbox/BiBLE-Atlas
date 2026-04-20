# Import 流程详细设计（无 SESSION / SKILL 仓储切片）

本文档描述在 FastAPI 分层架构下，**导入 API** 与 **`app/features/import/`** 的实现型设计，范围**排除** SESSION、SKILL 专属存储与编排逻辑。对外 HTTP 契约以 [IMPORT_API_REFERENCE.md](./IMPORT_API_REFERENCE.md) 为准；分层原则见 [02_分层职责详解.md](./02_分层职责详解.md)。

---

## 目录

### 📋 文档概览
- [1. 范围与术语](#1-范围与术语)
  - [1.1 包含](#11-包含)
  - [1.2 不包含（本切片）](#12-不包含本切片)
  - [1.3 主 library 为 SESSION 或 SKILL 时的 API 行为](#13-主-library-为-session-或-skill-时的-api-行为)
  - [1.4 数据库方案说明](#14-数据库方案说明)

### 🌐 API 层（app/api/v1/）
- [2. 与 IMPORT_API_REFERENCE.md 的字段对照](#2-与-import_api_referencemd-的字段对照)
  - [2.1 请求体（ImportJobRequest）](#21-请求体importjobrequest建议置于-appfeaturesimport_schemaspy)
  - [2.2 响应体（ImportJobResponse）](#22-响应体importjobresponse)
  - [2.3 对外模型接口设计](#23-对外模型接口设计)
  - [2.4 DTO 分层接口归属总览](#24-dto-分层接口归属总览)
  - [2.5 错误映射与降级矩阵](#25-错误映射与降级矩阵)
  - [2.6 本版本固定实现边界](#26-本版本固定实现边界)
- [3.1 FastAPI：import_api.py 要点](#31-fastapiimport_apipy-要点)
- [3.1.1 FastAPI：GET /api/v1/import/jobs/{job_id} 查询任务状态](#311-fastapiget-apiv1importjobsjob_id-查询任务状态)

### 🎯 Feature 层（app/features/import_/）

**模块结构与职责**
- [3. 模块与文件结构](#3-模块与文件结构)
- [3.2 import_service 职责边界](#32-import_service-职责边界)
- [4. 核心类型与接口](#4-核心类型与接口)

**Schemas 层（数据模型）**
- [4.1 内部 DTO（建议）](#41-内部-dto建议)

**Service 层（业务编排）**
- [4.4 ImportService 接口定义](#44-importserviceimport_servicepy)
- [5. ImportService 时序说明](#5-importservice-时序说明)
- [5.1 完整流程](#51-完整流程)
- [5.2 文件解析流程](#52-文件解析流程)

**Repository 层（数据访问）**
- [4.2 BaseImportRepository 接口定义](#42-baseimportrepositoryrepositoriesbasepy)
- [4.3 ImportRepositoryFactory 工厂模式](#43-importrepositoryfactoryrepositoriesfactorypy)
- [4.3.1 各 library 仓储差异](#431-各-library-仓储差异)

**Parsers 层（文件解析）**
- [5.3 Parsers 详细设计](#53-parsers-详细设计)
- [5.3.1 设计思路](#531-设计思路)
- [5.3.2 BaseDocumentParser（抽象接口）](#532-basedocumentparser抽象接口)
- [5.3.3 MarkdownParser（Markdown 解析器）](#533-markdownparsermarkdown-解析器)
- [5.3.4 JsonParser（JSON 解析器）](#534-jsonparserjson-解析器)
- [5.3.5 CustomParser（自定义解析器 - 预留）](#535-customparser自定义解析器---预留)
- [5.3.6 ParserFactory（解析器工厂）](#536-parserfactory解析器工厂)
- [5.3.7 Parsers 与 Repository 的协作流程](#537-parsers-与-repository-的协作流程)
- [5.3.8 错误处理流程](#538-错误处理流程)

### 🏗️ Infrastructure 层（app/infrastructure/）

**向量服务（vector/）**
- [6.1 VectorTool（向量生成工具）](#61-vectortool向量生成工具)

**OpenSearch 服务（opensearch/）**
- [6.2 OpenSearch 客户端与索引管理](#62-opensearch-客户端与索引管理)
  - [6.2.1 OpenSearchClient（客户端）](#621-opensearchclient客户端)
  - [6.2.2 IndexManager（索引管理）](#622-indexmanager索引管理)
  - [6.2.3 BulkImporter（批量导入）](#623-bulkimporter批量导入)

**异步任务服务（celery/）**
- [5.4 Celery 异步批量导入流程](#54-celery-异步批量导入流程)
- [6.3 Celery 任务定义](#63-celery-任务定义)

**依赖注入**
- [6.4 Infrastructure 层依赖注入](#64-infrastructure-层依赖注入)

### ⚙️ 配置与检查清单
- [7. 配置依赖](#7-配置依赖)
- [8. 实现检查清单（本切片交付）](#8-实现检查清单本切片交付)
- [9. 文档索引](#9-文档索引)

---

## 1. 范围与术语

### 1.1 包含

- `POST /api/v1/import/jobs` 的路由与 Pydantic 模型（与 IMPORT_API_REFERENCE 字段一致）。
- `GET /api/v1/import/jobs/{job_id}` 的路由与状态查询逻辑（查询 Celery 任务状态和元数据）。
- `ImportService`：**编排**（解析文件、向量生成、OpenSearch 批量写入、任务状态查询）。
- **Celery 异步任务**：后台执行耗时的向量化与 OpenSearch 批量导入，支持进度回调。
- **向量生成**：Service 调用 `VectorTool` 生成 embeddings 后传入 Repository。
- **OpenSearch 写入**：作为主存储和搜索引擎，直接批量写入文档。
- **数据库方案**：当前使用 **OpenSearch** 作为主存储；**PostgreSQL** 为备选方案（并行选择，不协作）。
- 以下 library tag 的 **Repository 与工厂注册**：`CODE`, `SCT`, `BUILD`, `SYNTAX`, `SPEC`, `ALG`, `DESIGN`, `FLOW`。

### 1.2 不包含（本切片）

- SESSION、SKILL 的特殊存储逻辑（大文档分块、外部文件存储、多文件关联）。
- **自定义解析器**的沙箱执行机制（预留接口，本切片不实现）。
- **`import_mode=append`** 的复杂冲突检测（本切片实现基础 replace 和 append）。

### 1.3 主 library 为 SESSION 或 SKILL 时的 API 行为

- HTTP 仍允许客户端传入 `library: "SESSION"` / `"SKILL"`（IMPORT_API_REFERENCE 已列出）。**本切片不实现** SESSION/SKILL 真实仓储与特殊存储；为避免客户端报错中断，**应返回 HTTP 400**：
  - `detail: "SESSION/SKILL import not supported in current version"`
- **实现路径**：在 `ImportService` 最前校验 `library` 参数，若为 SESSION/SKILL 则直接短路返回。
- 待 Session/Skill 导入能力补齐后，再改为真实存储并更新本文档。

### 1.4 数据库方案说明

**当前方案（本切片实现）**：
- **OpenSearch** 作为主存储和搜索引擎
- 文档直接写入 OpenSearch 索引
- 向量化与批量导入通过 Celery 异步执行

**备选方案（并行选择，本切片不实现）**：
- **PostgreSQL + pgvector** 作为主存储和向量搜索
- 文档写入 PostgreSQL 表
- 向量存储在 pgvector 扩展字段

---

## 2. 与 IMPORT_API_REFERENCE.md 的字段对照

### 2.1 请求体（`ImportJobRequest`，建议置于 `app/features/import_/schemas.py`）

| 表单字段 | Python 字段 | 必填 | 说明 |
|---------|-------------|------|------|
| `library` | `library` | 是 | 目标知识库名称，如 `CODE`、`DESIGN` 等 |
| `files` | `files` | 是 | 上传的文件列表（至少1个），通过 FastAPI `File(...)` 处理 |
| `vector_model` | `vector_model` | 否 | 向量模型：`mini`, `mpnet`, `bge-base`, `bge-large`, `bge-m3`, `e5-large`。不传则不使用向量化 |
| `import_mode` | `import_mode` | 否，默认 `replace` | 导入模式：`replace`（替换），`append`（追加） |
| `custom_parser` | `custom_parser` | 否 | 自定义解析器Python脚本文件（.py）|

**Pydantic v2 校验**：**以 `app/features/import_/schemas.py` 为主**——在 **`ImportJobRequest`** 上使用 `Field`、`field_validator` 完成类型、范围、枚举及关联校验。**`import_api.py` 只负责** `response_model=ImportJobResponse`、依赖注入与 **`HTTPException` 映射**；**不要**在路由函数里堆业务级校验逻辑。

**字段级规则补充**：
1. `library` 必须在动态配置的有效知识库列表中，与 `import_.valid_libraries` 对齐。
2. `vector_model` 若提供，必须在 `vector_models.models` 配置中存在。
3. `import_mode` 必须为 `replace` 或 `append`。
4. `files` 至少包含1个文件，最多 `import_.max_files_per_request`（动态配置）。
5. 单文件最大 `import_.max_file_size`（动态配置）。
6. 支持的文件类型：`.md`, `.json`（可通过自定义解析器扩展）。

**本切片固定语义**：

1. `library` 若为 `SESSION` / `SKILL`，在 Service 最前短路返回 **400 + "not supported"**。
2. `vector_model` 不传或传 `null` 时，不生成向量，文档的 `content_vector` 字段为 `null`。
3. `import_mode=replace` 时，先删除 OpenSearch 中该 library 对应索引的所有文档，再批量插入新文档；`append` 时直接批量插入。
4. `custom_parser` 本切片仅接收但不执行，记录 warning 日志。
5. 请求体验证失败统一按项目错误体映射为 **400**。

### 2.2 响应体（`ImportJobResponse`）

与 IMPORT_API_REFERENCE.md 一致：

- `success: bool`
- `job_id: str` — Celery 任务ID或自定义任务ID
- `status: str` — 任务状态：`parsing`, `saving`, `syncing`, `completed`, `failed`
- `message: str` — 操作结果描述
- `details: dict` — 详细信息

错误响应：`{"detail": "..."}`，HTTP 状态码 **400**（参数非法）、**413**（文件过大）、**500**（系统/模型调用失败等）。

#### `ImportJobResponse.details` 精确约定

`details` 包含导入详情：

| 字段 | 类型 | 说明 |
|------|------|------|
| `library` | str | 知识库名称 |
| `use_vector` | bool | 是否使用向量化 |
| `vector_model` | str \| None | 向量模型名称 |
| `vector_dims` | int \| None | 向量维度 |
| `import_mode` | str | 导入模式 |
| `total_documents` | int | 解析出的文档总数 |
| `parse_results` | dict | 文件解析结果 |

`parse_results` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_files` | int | 总文件数 |
| `parsed_files` | int | 解析成功的文件数 |
| `failed_files` | int | 解析失败的文件数 |
| `failed_file_details` | list[dict] | 失败文件详情（仅失败文件） |

约束：
1. 成功文件不返回详情以减少响应体积。
2. `failed_file_details` 仅包含失败文件的 `filename`、`error`、`size_bytes`。
3. 若所有文件解析失败，返回 **400** 错误，不创建任务。

### 2.3 对外模型接口设计

#### `ImportJobRequest`

```python
# app/features/import_/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal

class ImportJobRequest(BaseModel):
    """
    导入任务请求模型
    
    注意：files 和 custom_parser 通过 FastAPI File(...) 处理，不在 Pydantic 模型中定义
    """
    library: str = Field(..., description="目标知识库名称", example="CODE")
    vector_model: Optional[str] = Field(None, description="向量模型", example="mpnet")
    import_mode: Literal["replace", "append"] = Field("replace", description="导入模式")
    
    @field_validator('library')
    @classmethod
    def validate_library(cls, v):
        """验证知识库名称"""
        from app.config.config_manager import get_config_manager
        config = get_config_manager()
        valid_libraries = config.get("import_.valid_libraries", [])
        
        if v not in valid_libraries:
            raise ValueError(
                f"Invalid library. Must be one of: {valid_libraries}"
            )
        
        # SESSION/SKILL 校验
        if v in ["SESSION", "SKILL"]:
            raise ValueError(
                f"{v} import not supported in current version"
            )
        
        return v
    
    @field_validator('vector_model')
    @classmethod
    def validate_vector_model(cls, v):
        """验证向量模型"""
        if v is not None:
            from app.config.config_manager import get_config_manager
            config = get_config_manager()
            vector_models = config.get("vector_models.models", {})
            valid_models = list(vector_models.keys())
            
            if v not in valid_models:
                raise ValueError(
                    f"Invalid vector_model. Must be one of: {valid_models}"
                )
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "library": "CODE",
                "vector_model": "mpnet",
                "import_mode": "replace"
            }
        }
```

#### `ImportJobResponse`

```python
# app/features/import_/schemas.py
class ParseResult(BaseModel):
    """文件解析结果"""
    total_files: int
    parsed_files: int
    failed_files: int
    failed_file_details: List[dict] = Field(default_factory=list)

class ImportJobResponse(BaseModel):
    """导入任务响应"""
    success: bool
    job_id: str = Field(..., description="任务ID")
    status: str = Field(..., description="任务状态")
    message: str
    details: dict = Field(default_factory=dict)
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "job_id": "import_20260412_123456_abc123",
                "status": "importing",
                "message": "文档已解析完成，正在后台导入到OpenSearch",
                "details": {
                    "library": "CODE",
                    "use_vector": True,
                    "vector_model": "mpnet",
                    "vector_dims": 768,
                    "import_mode": "replace",
                    "total_documents": 23,
                    "parse_results": {
                        "total_files": 3,
                        "parsed_files": 3,
                        "failed_files": 0
                    }
                }
            }
        }
```

### 2.4 DTO 分层接口归属总览

| DTO | 定义位置 | 主要使用层间接口 | 边界说明 |
|-----|----------|------------------|----------|
| `ImportJobRequest` | `app/features/import_/schemas.py` | `import_api.create_import_job(...)`；`ImportService.create_import_job_with_files(...)` | **API 入参 DTO**。客户端通过 HTTP multipart/form-data 传入；进入 Service 后继续作为**请求上下文载体** |
| `ImportJobResponse` | `app/features/import_/schemas.py` | `ImportService.create_import_job_with_files(...) -> ImportJobResponse`；`import_api.create_import_job(...) -> ImportJobResponse` | **API 出参 DTO**。是 Service 对 API 的返回契约，也是 API 对客户端的成功响应模型 |
| `DocumentChunk` | `app/features/import_/schemas.py` | `BaseImportRepository.parse_document(...) -> List[DocumentChunk]`；`ImportService._batch_import_to_opensearch(...)` | **Service -> Repository 的文档分块 DTO**。用于统一文档解析输出格式 |

### 2.5 错误映射与降级矩阵

| 场景 | 处理方式 | HTTP |
|------|----------|------|
| 请求体缺字段、类型错误、枚举/范围校验失败 | 统一映射项目错误体 `{"detail": "..."}` | **400** |
| `library` 为 SESSION 或 SKILL | 返回 `{"detail": "not supported"}` | **400** |
| 文件数量超限 | 返回 `{"detail": "Too many files..."}` | **400** |
| 文件过大 | 返回 `{"detail": "File too large..."}` | **413** |
| 不支持的文件类型 | 返回 `{"detail": "Unsupported file type..."}` | **400** |
| 所有文件解析失败 | 返回 `{"detail": "All files failed to parse..."}`，包含失败详情 | **400** |
| OpenSearch 连接失败、写入异常 | 记录 error 日志并返回统一错误体 | **500** |
| `VectorTool` 加载模型失败 | 返回 `{"detail": "Vector model loading failed..."}` | **500** |
| Celery 任务提交失败 | 返回 `{"detail": "Task submission failed..."}` | **500** |

### 2.6 本版本固定实现边界

以下约定用于保证后续 implementation 文档和代码实现不再出现分叉：

1. `details.total_documents` 口径固定为**所有成功解析文件的章节数之和**。
2. `SESSION` / `SKILL` 在本切片内是**已知但未实现的业务 library**，因此在 Service 最前短路返回 **400**。
3. `custom_parser` 是**兼容性参数**，本切片允许接收但不执行，记录 warning 日志。
4. 向量生成属于**可选主链路步骤**；OpenSearch 批量写入失败属于**非降级主链路步骤**（必须成功）。
5. 文件解析与向量化在 API 请求同步完成，OpenSearch 批量导入通过 Celery 异步执行。

---

## 3. 模块与文件结构

```
app/
├── api/                           # API 路由层（水平聚合）
│   ├── __init__.py                # 注册所有路由
│   ├── deps.py                    # 通用依赖（认证、限流）
│   └── v1/                        # API v1 版本
│       ├── __init__.py  
│       └── import_api.py          # Import相关API端点
│
├── features/                      # 功能层（垂直聚合）
│   └── import_/                   # 导入功能（下划线避免与关键字冲突）
│       ├── __init__.py  
│       ├── import_service.py      # ImportService：业务逻辑编排
│       ├── repositories/          # 多仓储设计
│       │   ├── __init__.py  
│       │   ├── base.py            # BaseImportRepository
│       │   ├── factory.py         # ImportRepositoryFactory
│       │   ├── empty.py           # EmptyImportRepository（SESSION/SKILL占位）
│       │   ├── code.py            # CodeImportRepository
│       │   ├── sct.py             # SctImportRepository
│       │   ├── build.py           # BuildImportRepository
│       │   ├── syntax.py          # SyntaxImportRepository
│       │   ├── spec.py            # SpecImportRepository
│       │   ├── alg.py             # AlgImportRepository
│       │   ├── design.py          # DesignImportRepository
│       │   └── flow.py            # FlowImportRepository
│       ├── parsers/               # 文档解析器
│       │   ├── __init__.py
│       │   ├── base.py            # BaseDocumentParser
│       │   ├── markdown_parser.py # MarkdownParser
│       │   ├── json_parser.py     # JsonParser
│       │   └── custom_parser.py   # CustomParser（沙箱执行，预留）
│       ├── schemas.py             # API 数据模型
│       └── dependencies.py        # 依赖注入
│
└── infrastructure/                # 基础设施层
    ├── opensearch/                # OpenSearch（当前方案：主存储 + 搜索引擎）
    │   ├── client.py              # OpenSearch 客户端
    │   ├── index_manager.py       # 索引管理
    │   └── bulk_importer.py       # 批量导入工具
    │
    ├── postgres/                  # PostgreSQL（备选方案：主存储 + pgvector）
    │   ├── client.py              # asyncpg 客户端（本切片不实现）
    │   ├── repositories/
    │   │   ├── base.py            # 基础Repository（本切片不实现）
    │   │   ├── document.py        # 文档主表操作（本切片不实现）
    │   │   └── chunk.py           # 文档块操作（本切片不实现）
    │   └── migrations/            # 数据库迁移脚本（本切片不实现）
    │
    ├── celery/                    # Celery
    │   ├── app.py                 # Celery 应用
    │   └── tasks.py               # 任务定义
    │       # import_documents_task: 异步导入文档到OpenSearch
    │       # cleanup_old_jobs: 清理过期任务
    │
    └── vector/                    # 向量工具
        └── vector_tool.py         # VectorTool（向量生成）
```

| 文件 | 职责 |
|------|------|
| `import_api.py` | 路由入口：注册 `POST /api/v1/import/jobs`（创建导入任务）、`GET /api/v1/import/jobs/{job_id}`（查询任务状态）、承接 **FastAPI + Pydantic** 参数校验、`Depends(get_import_service)`、统一 HTTP 异常映射；**不**承担文件解析、向量生成或数据库导入等业务分支 |
| `import_service.py` | 业务编排入口：`create_import_job_with_files`（保存文件、解析文件、生成向量、提交 Celery 任务）、`get_job_status`（查询任务状态和进度）；在最前检查 SESSION/SKILL 并短路返回 400 |
| `schemas.py` | 统一定义 Import 相关 DTO 边界：`ImportJobRequest` / `ImportJobResponse` 是 **API <-> Service** 契约；`DocumentChunk` 是 **Service <-> Repository** 内部 DTO |
| `dependencies.py` | FastAPI 依赖装配：集中构造 `ImportService` 及其协作者（`OpenSearchClient`、`VectorTool`、`CeleryApp`、`ConfigManager`）；避免在路由函数中手写对象构造 |
| `repositories/base.py` | 定义 `BaseImportRepository` 共享导入流水线、抽象扩展点（`parse_document`、`format_for_opensearch`） |
| `repositories/factory.py` | 根据 `library` tag 选择具体仓储类或 `EmptyImportRepository`；封装已知/未知 tag 分流与依赖透传规则 |
| `repositories/empty.py` | `EmptyImportRepository` 的落位文件；用于 `SESSION` / `SKILL` 在本切片中的空实现占位（但本切片在 Service 最前短路，不走工厂） |
| `repositories/*.py` | 各 library 仓储：负责 tag 专属解析逻辑、OpenSearch 文档结构、字段映射 |
| `parsers/base.py` | 定义 `BaseDocumentParser` 接口，统一文档解析输入输出 |
| `parsers/markdown_parser.py` | Markdown 文件解析器：将 `.md` 文件转换为标准章节列表 |
| `parsers/json_parser.py` | JSON 文件解析器：验证 `.json` 文件结构并提取章节 |
| `parsers/custom_parser.py` | 自定义解析器执行器：沙箱执行用户上传的 Python 脚本（本切片预留接口） |
| `infrastructure/opensearch/` | OpenSearch 客户端与索引管理：创建索引、批量导入数据（当前方案） |
| `infrastructure/postgres/` | PostgreSQL 客户端与仓储：asyncpg 连接、文档表操作（备选方案，本切片不实现） |
| `infrastructure/celery/tasks.py` | Celery 任务定义：`import_documents_task`（异步批量导入到 OpenSearch）、`cleanup_old_jobs`（清理过期任务） |
| `infrastructure/vector/vector_tool.py` | 向量生成工具：加载模型、生成 embeddings、模型缓存 |

`dependencies.py` 的推荐注入边界：

1. 路由层只 `Depends(get_import_service)`。
2. `get_import_service()` 负责装配 **`OpenSearchClient`、`VectorTool`、`CeleryApp`、`ConfigManager`**。
3. `ImportRepositoryFactory.create(...)` 再把依赖透传给具体仓储。

**注意**：本切片使用 **OpenSearch** 作为主存储，不注入 `PostgresClient`。

### 3.1 FastAPI：`import_api.py` 要点

```python
# app/api/v1/import_api.py
"""导入 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile
from typing import List, Optional

from app.features.import_.import_service import ImportService
from app.features.import_.schemas import ImportJobResponse
from app.features.import_.dependencies import get_import_service
from app.api.deps import validate_api_key
from app.common.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Import"])


@router.post("/import/jobs", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
async def create_import_job(
    library: str = Form(...),
    files: List[UploadFile] = File(...),
    vector_model: Optional[str] = Form(None),
    import_mode: str = Form("replace"),
    custom_parser: Optional[UploadFile] = File(None),
    service: ImportService = Depends(get_import_service),
    # api_key: str | None = Depends(validate_api_key_optional),
):
    """
    创建导入任务（含文件上传）
    
    参数：
    - library: 目标知识库名称
    - files: 上传的文件列表
    - vector_model: 向量模型（可选）
    - import_mode: 导入模式（replace/append）
    - custom_parser: 自定义解析器Python文件（.py，可选，本切片不执行）
    
    示例：
    ```bash
    curl -X POST http://localhost:9220/api/v1/import/jobs \
      -F "library=CODE" \
      -F "vector_model=mpnet" \
      -F "files=@doc1.md" \
      -F "files=@doc2.md" \
      -F "custom_parser=@my_parser.py"
    ```
    """
    try:
        logger.info(
            f"Import request: library={library}, "
            f"files={len(files)}, vector_model={vector_model}"
        )
        
        # ✅ 只调用 Service，不包含业务逻辑
        result = await service.create_import_job_with_files(
            library=library,
            files=files,
            vector_model=vector_model,
            import_mode=import_mode,
            custom_parser=custom_parser
        )
        
        logger.info(f"Import job created: job_id={result.job_id}")
        return result
        
    except ValueError as e:
        # 业务错误（如无效参数）
        logger.warning(f"Import validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # 系统错误
        logger.error(f"Import failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Import operation failed"
        )
```

- 在 `app/api/v1/__init__.py` 中使用 `app.include_router(import_api.router, prefix="/api/v1")` 注册路由。
- **`import_api.py` 里的参数校验**：**需要**，但 **不必手写**——FastAPI 将 multipart/form-data 解析为参数时，**Pydantic 自动完成校验**（在 Service 内部或通过 `field_validator`）；本项目应通过统一异常处理将验证失败映射为 **400 + `{"detail": "..."}`**。`import_api` 保持 **`response_model=ImportJobResponse`** 与业务异常映射即可。

---

### 3.1.1 FastAPI：`GET /api/v1/import/jobs/{job_id}` 查询任务状态

#### API 端点定义

```python
# app/api/v1/import_api.py (续)

@router.get("/import/jobs/{job_id}", response_model=ImportJobStatusResponse, status_code=status.HTTP_200_OK)
async def get_import_job_status(
    job_id: str,
    service: ImportService = Depends(get_import_service),
):
    """
    查询导入任务状态
    
    参数：
    - job_id: 任务ID（由创建任务时返回）
    
    返回：
    - 任务状态信息（状态、进度、结果等）
    
    示例：
    ```bash
    curl http://localhost:9220/api/v1/import/jobs/import_20260412_123456_abc123
    ```
    """
    try:
        logger.info(f"Query job status: job_id={job_id}")
        
        # ✅ 调用 Service 获取任务状态
        status_info = await service.get_job_status(job_id)
        
        if not status_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        logger.debug(f"Job status retrieved: job_id={job_id}, status={status_info.status}")
        return status_info
        
    except FileNotFoundError as e:
        # 任务不存在
        logger.warning(f"Job not found: job_id={job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        # 系统错误
        logger.error(f"Failed to get job status: job_id={job_id}, error={e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve job status"
        )
```

#### 响应模型定义

在 `app/features/import_/schemas.py` 中添加任务状态响应模型：

```python
# app/features/import_/schemas.py (续)

from datetime import datetime
from typing import Optional, Literal

JobStatus = Literal["parsing", "vectorizing", "importing", "completed", "failed", "cancelled"]


class ParseResults(BaseModel):
    """文件解析结果"""
    total_files: int = Field(..., description="总文件数")
    parsed_files: int = Field(..., description="成功解析的文件数")
    failed_files: int = Field(..., description="解析失败的文件数")
    failed_file_details: list[dict] = Field(default_factory=list, description="失败文件详情")


class ImportResult(BaseModel):
    """导入结果"""
    index_name: str = Field(..., description="OpenSearch索引名称")
    imported_docs: int = Field(..., description="成功导入的文档数")
    total_docs: int = Field(..., description="总文档数")
    failed_docs: int = Field(default=0, description="失败的文档数")
    has_vector: bool = Field(..., description="是否包含向量")
    vector_dims: Optional[int] = Field(None, description="向量维度")


class ImportJobStatusResponse(BaseModel):
    """导入任务状态响应"""
    job_id: str = Field(..., description="任务ID")
    status: JobStatus = Field(..., description="任务状态")
    progress: float = Field(..., ge=0.0, le=1.0, description="任务进度 (0.0-1.0)")
    message: str = Field(..., description="当前状态描述")
    parse_results: Optional[ParseResults] = Field(None, description="文件解析结果")
    result: Optional[ImportResult] = Field(None, description="最终结果（仅completed时有值）")
    error: Optional[str] = Field(None, description="错误信息（仅failed时有值）")
    created_at: datetime = Field(..., description="任务创建时间")
    started_at: Optional[datetime] = Field(None, description="任务开始时间")
    completed_at: Optional[datetime] = Field(None, description="任务完成时间")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "job_id": "import_20260412_123456_abc123",
            "status": "importing",
            "progress": 0.75,
            "message": "正在导入到OpenSearch (112/150)...",
            "parse_results": {
                "total_files": 2,
                "parsed_files": 2,
                "failed_files": 0,
                "failed_file_details": []
            },
            "result": None,
            "error": None,
            "created_at": "2026-04-12T12:34:56",
            "started_at": "2026-04-12T12:35:01",
            "completed_at": None
        }
    })
```

#### Service 层实现

`ImportService.get_job_status()` 方法负责：

1. 从任务元数据文件（`metadata.json`）读取任务基础信息
2. 查询 Celery 任务状态并获取当前进度
3. 映射 Celery 技术状态到业务状态（parsing、vectorizing、importing、completed、failed、cancelled）
4. 合并信息并返回统一的 `ImportJobStatusResponse`

**详细实现请参考 [4.4 ImportService 实现](#44-importserviceimport_servicepy)**，包括：
- 完整的方法实现代码
- 任务元数据结构（`metadata.json`）
- Celery 状态到业务状态的映射规则
- 错误处理和异常场景

---

### 3.2 `import_service` 职责边界

- **仅做业务级处理**：保存文件到临时目录、解析文件、生成向量、提交 Celery 任务（异步批量导入到 OpenSearch）、查询任务状态、清理临时文件。
- **输出**：
  - `ImportJobResponse`：包含 `job_id`、`status`、`parse_results`、`details`（创建任务时）。
  - `ImportJobStatusResponse`：包含 `job_id`、`status`、`progress`、`message`、`result`、`error` 等（查询状态时）。
- **不包含**：HTTP 相关处理、直接的 OpenSearch 操作（委托给 Celery 任务）、文件上传细节（委托给 Infrastructure）。
- **元数据管理**：
  - 创建任务时生成 `metadata.json` 记录任务信息。
  - 任务执行过程中更新元数据（celery_task_id、started_at、parse_results）。
  - 任务完成时更新元数据（completed_at、result、error）。
  - 查询状态时读取元数据并结合 Celery 任务状态返回。

---

### 3.3 临时文件管理设计

> **可视化参考**：完整的文件生命周期管理流程请参考 [import_file_lifecycle.puml](./import_file_lifecycle.puml)

#### 3.3.1 文件存储路径设计

**临时目录结构**：

```
/tmp/bible_import/
├── jobs/
│   ├── import_20260415_123456_abc123/      # 任务目录（以 job_id 命名）
│   │   ├── files/                          # 上传的原始文件
│   │   │   ├── doc1.md
│   │   │   ├── doc2.json
│   │   │   └── custom_parser.py
│   │   └── metadata.json                   # 任务元数据
│   └── import_20260415_234567_def456/
│       └── ...
└── .cleanup_marker                          # 清理标记文件
```

**路径规则**：
- 根目录：`/tmp/bible_import/` 或通过配置指定 `import_.temp_dir`
- 任务目录：`{temp_dir}/jobs/{job_id}/`
- 文件存储：`{temp_dir}/jobs/{job_id}/files/{filename}`
- 元数据：`{temp_dir}/jobs/{job_id}/metadata.json`

#### 3.3.2 文件生命周期

```
1. 上传阶段
   └─ FastAPI 接收 UploadFile → 保存到临时目录

2. 解析阶段
   └─ 从临时目录读取文件 → 解析内容 → 生成 DocumentChunk

3. 向量化阶段（可选）
   └─ 为 DocumentChunk 生成向量

4. 任务提交阶段
   └─ 将解析结果和向量提交给 Celery 任务

5. 导入阶段（异步）
   └─ Celery 任务批量写入 OpenSearch

6. 清理阶段
   └─ 任务完成后删除临时文件（成功或失败）
   └─ 定期清理过期任务目录（7天）
```

#### 3.3.3 清理策略

**立即清理**（任务完成时）：
- 触发时机：Celery 任务 `import_documents_task` 执行完成（成功或失败）
- 清理内容：删除该任务的所有临时文件
- 保留内容：任务元数据保留（用于查询任务状态）

**延迟清理**（定期任务）：
- 触发时机：Celery 定期任务 `cleanup_old_jobs`（每天执行一次）
- 清理内容：删除超过 7 天的任务目录（包括元数据）
- 保留内容：最近 7 天的任务记录

**异常清理**（错误恢复）：
- 触发时机：服务启动时检查孤儿任务目录
- 清理内容：删除超过 1 天但没有对应任务记录的目录

---

## 4. 核心类型与接口

### 4.1 内部 DTO（建议）

#### 基础枚举与结构化结果类型

建议先在 `schemas.py` 中固定以下基础类型，供 API、Service、Repository 共用：

- `LibraryTag = Literal["CODE", "SCT", "BUILD", "SYNTAX", "SPEC", "ALG", "DESIGN", "FLOW", "SESSION", "SKILL"]`
- `ImportMode = Literal["replace", "append"]`
- `VectorModel = Literal["mini", "mpnet", "bge-base", "bge-large", "bge-m3", "e5-large"]`

建议同步定义文档分块结构：

| 类型 | 字段 | 说明 |
|------|------|------|
| `DocumentChunk` | `section_id`, `section_title`, `content`, `metadata` | 统一的文档分块结构，Repository 解析输出 |

#### `DocumentChunk`

```python
# app/features/import_/schemas.py
class DocumentChunk(BaseModel):
    """文档分块"""
    section_id: str = Field(..., description="章节ID")
    section_title: str = Field(..., description="章节标题")
    content: str = Field(..., description="章节内容")
    metadata: dict = Field(default_factory=dict, description="元数据")
```

### 4.2 `BaseImportRepository`（`repositories/base.py`）

**类职责**：

1. 定义单文件导入的**共享骨架**。
2. 把"文档解析"和"格式化"留给具体子类扩展。
3. 统一调用 `VectorTool` 生成向量（可选）。
4. 保证输出结构始终能被 `ImportService` 消费。

**推荐构造注入项**：

| 依赖 | 用途 |
|------|------|
| `opensearch_client: OpenSearchClient` | 统一访问 OpenSearch（当前方案） |
| `vector_tool: VectorTool | None` | 可选向量生成能力 |
| `config: ConfigManager` | 读取导入、向量等配置 |

**单文件处理流水线（推荐封装在 `process_file` 方法）**：

1. `parse_document(file)` → 生成 **`List[DocumentChunk]`**（具体子类实现）。
2. 若 `use_vector`：调用 **`VectorTool.generate_vector`** 生成每个 chunk 的向量。
3. `format_for_opensearch(chunks, *, library, use_vector)` → 映射成 OpenSearch 文档格式（具体子类实现）。
4. 返回 **文档列表**（供 Celery 任务批量写入 OpenSearch）。

| 方法 / 成员 | 说明 |
|-------------|------|
| `library_tag: ClassVar[str]` | 当前仓储对应的 library tag |
| `parse_document(file: UploadFile, custom_parser: UploadFile | None) -> List[DocumentChunk]` | 解析文件，返回章节列表 |
| `format_for_opensearch(chunks: List[DocumentChunk], *, library: str, use_vector: bool) -> List[dict]` | 格式化为 OpenSearch 文档格式 |
| `async def process_file(file: UploadFile, *, library: str, use_vector: bool, vector_model: str | None, custom_parser: UploadFile | None) -> List[dict]` | 完成上述 1～4 |

**统一接口约定**（供所有具体仓储继承/实现）：

```python
class BaseImportRepository(ABC):
    library_tag: ClassVar[str]
    
    @abstractmethod
    def parse_document(self, file: UploadFile) -> List[DocumentChunk]:
        """解析文档，返回章节列表"""
        pass
    
    @abstractmethod
    def format_for_opensearch(
        self,
        chunks: List[DocumentChunk],
        *,
        library: str,
        use_vector: bool
    ) -> List[dict]:
        """格式化为 OpenSearch 文档格式"""
        pass
    
    async def process_file(
        self,
        file: UploadFile,
        *,
        library: str,
        use_vector: bool,
        vector_model: str | None,
        custom_parser: UploadFile | None = None
    ) -> List[dict]:
        """处理单个文件"""
        # 1. 解析文档
        chunks = self.parse_document(file, custom_parser)
        
        # 2. 生成向量（可选）
        if use_vector and self.vector_tool:
            for chunk in chunks:
                text = f"{chunk.section_title}\n{chunk.content}"
                vector = await self.vector_tool.generate_vector(
                    text=text,
                    model=vector_model
                )
                chunk.metadata['vector'] = vector
        
        # 3. 格式化为 OpenSearch 文档
        documents = self.format_for_opensearch(
            chunks,
            library=library,
            use_vector=use_vector
        )
        
        return documents
```

### 4.3 `ImportRepositoryFactory`（`repositories/factory.py`）

`create(library: str, *, opensearch_client, vector_tool, config) -> BaseImportRepository`：

**类职责**：

1. 根据 `library` tag 选择具体 `*ImportRepository`。
2. 为所有仓储提供一致的构造依赖（`OpenSearchClient`、`VectorTool`、`ConfigManager`）。
3. 对已知但本切片未实现的 tag（SESSION/SKILL）返回 **`EmptyImportRepository`**（但本切片在 Service 最前短路，不走工厂）。
4. 对未知/非法 tag 抛出显式异常。

| `library` tag | 实现类 | 说明 |
|--------------|--------|------|
| `CODE` | `CodeImportRepository` | 代码文档导入 |
| `SCT` | `SctImportRepository` | 测试用例导入 |
| `BUILD` | `BuildImportRepository` | 构建配置导入 |
| `SYNTAX` | `SyntaxImportRepository` | 语法定义导入 |
| `SPEC` | `SpecImportRepository` | 规格说明导入 |
| `ALG` | `AlgImportRepository` | 算法文档导入 |
| `DESIGN` | `DesignImportRepository` | 设计文档导入 |
| `FLOW` | `FlowImportRepository` | 流程文档导入 |
| `SESSION` | **本切片**：在 Service 最前短路返回 400 | - |
| `SKILL` | **本切片**：在 Service 最前短路返回 400 | - |

`ImportRepositoryFactory.create(...)` 建议主流程：

1. 校验 `library` 是否在受支持集合内。
2. 若为 `SESSION` / `SKILL`，抛出异常（但本切片在 Service 最前已短路，不会走到这里）。
3. 否则选择具体仓储类，并注入共享依赖。
4. 返回与 `BaseImportRepository` 兼容的实例。

#### 4.3.1 各 library 仓储差异

**各具体仓储的共同接口设计**：

- 继承：`BaseImportRepository`
- 必备类属性：`library_tag`
- 必备实现：`parse_document(...)`、`format_for_opensearch(...)`
- 默认复用：`process_file(...)` 共享流水线

若个别 library 需要特殊逻辑（如代码聚合、章节拼装），允许覆写 `process_file(...)` 的内部步骤，但**不应**改变统一输入/输出契约。

- `CodeImportRepository`
  - 面向代码知识；通常需要解析函数签名、文件路径等元数据。
  - `parse_document(...)` 提取函数级章节；`format_for_opensearch(...)` 添加代码特定字段。
  - 接口实现重点：解析函数签名、文件路径、语言类型等元数据。

- `SctImportRepository`
  - 面向 SCT 测试用例。
  - `parse_document(...)` 提取测试步骤、预期结果等。
  - 接口实现重点：测试用例结构化字段。

- `BuildImportRepository`
  - 面向编译方法/构建步骤。
  - `parse_document(...)` 提取构建命令、步骤说明等。
  - 接口实现重点：命令片段、步骤标题映射。

- `SyntaxImportRepository`
  - 面向编码规范、语法规则。
  - `parse_document(...)` 提取规范条目、示例代码等。
  - 接口实现重点：规范标题、规则正文映射。

- `SpecImportRepository`
  - 面向需求规格、功能定义。
  - `parse_document(...)` 提取需求章节、接口定义等。
  - 接口实现重点：规格章节/条目型映射。

- `AlgImportRepository`
  - 面向算法说明、原理。
  - `parse_document(...)` 提取算法标题、公式、策略说明等。
  - 接口实现重点：算法标题、原理映射。

- `DesignImportRepository`
  - 面向设计文档、模块设计。
  - `parse_document(...)` 提取模块设计、架构说明等。
  - 接口实现重点：模块/架构章节映射。

- `FlowImportRepository`
  - 面向流程文档、时序步骤。
  - `parse_document(...)` 提取流程步骤、时序说明等。
  - 接口实现重点：步骤化、流程化内容映射。

### 4.4 `ImportService`（`import_service.py`）

| 方法 | 说明 |
|------|------|
| `async def create_import_job_with_files(self, *, library, files, vector_model, import_mode, custom_parser) -> ImportJobResponse` | 对外唯一入口：创建导入任务 |
| `async def get_job_status(self, job_id: str) -> ImportJobStatusResponse` | 查询导入任务状态（从元数据和 Celery 获取） |
| `_validate_library(library)` | 校验 library，SESSION/SKILL 短路返回 400 |
| `_create_job_metadata(job_id, metadata)` | 创建任务元数据文件 |
| `_update_job_metadata(job_id, updates)` | 更新任务元数据文件 |
| `_save_uploaded_files(job_id, files, custom_parser)` | 保存上传的文件到临时目录，返回文件路径映射 |
| `_parse_files(job_id, file_paths, library, use_vector, vector_model, custom_parser_path)` | 从临时目录读取文件并解析，生成向量（可选），调用 Repository 工厂 |
| `_submit_import_task(job_id, documents, library, import_mode)` | 提交 Celery 异步批量导入任务到 OpenSearch，返回 AsyncResult |
| `_cleanup_job_files(job_id, keep_metadata=False)` | 清理任务的临时文件（可选择保留元数据） |

`ImportService.create_import_job_with_files(...)` 建议职责：

1. 生成唯一的 `job_id`（格式：`import_{timestamp}_{random}`）。
2. 调 `_validate_library` 校验 library，SESSION/SKILL 短路返回 400。
3. 调 `_create_job_metadata` 创建初始任务元数据文件（记录任务基本信息）。
4. 调 `_save_uploaded_files` 保存上传的文件到临时目录，返回文件路径映射。
5. 调 `_parse_files` 从临时目录读取文件并解析，生成向量（可选），返回文档列表与解析结果。
6. 调 `_submit_import_task` 提交 Celery 异步批量导入任务到 OpenSearch（传入 documents 和 job_id），获取任务对象。
7. 调 `_update_job_metadata` 更新元数据文件（添加 celery_task_id、parse_results 和 started_at）。
8. 构造 `ImportJobResponse` 返回（包含 job_id 和解析结果）。
9. **注意**：文件解析完成后**不立即删除**临时文件，由 Celery 任务完成后调用 `_cleanup_job_files` 清理。

**类接口设计建议**：

```python
import os
import uuid
import shutil
import json
from datetime import datetime
from pathlib import Path

class ImportService:
    def __init__(
        self,
        *,
        opensearch_client: OpenSearchClient,
        vector_tool: VectorTool | None,
        celery_app,
        config: ConfigManager,
    ) -> None:
        self.opensearch_client = opensearch_client
        self.vector_tool = vector_tool
        self.celery_app = celery_app
        self.config = config
        
        # 临时目录配置
        self.temp_dir = Path(config.get("import_.temp_dir", "/tmp/bible_import"))
        self.jobs_dir = self.temp_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_job_id(self) -> str:
        """生成唯一的任务ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = uuid.uuid4().hex[:8]
        return f"import_{timestamp}_{random_suffix}"
    
    def _get_job_dir(self, job_id: str) -> Path:
        """获取任务目录路径"""
        return self.jobs_dir / job_id
    
    def _get_files_dir(self, job_id: str) -> Path:
        """获取任务文件目录路径"""
        return self._get_job_dir(job_id) / "files"
    
    async def _save_uploaded_files(
        self,
        job_id: str,
        files: List[UploadFile],
        custom_parser: UploadFile | None
    ) -> Dict[str, str]:
        """
        保存上传的文件到临时目录
        
        Args:
            job_id: 任务ID
            files: 上传的文件列表
            custom_parser: 自定义解析器文件（可选）
        
        Returns:
            Dict[str, str]: 文件名 -> 临时文件路径的映射
        
        Raises:
            IOError: 文件保存失败
        """
        # 创建任务目录
        job_dir = self._get_job_dir(job_id)
        files_dir = self._get_files_dir(job_id)
        files_dir.mkdir(parents=True, exist_ok=True)
        
        file_paths = {}
        
        try:
            # 保存主文件
            for file in files:
                file_path = files_dir / file.filename
                
                # 写入文件
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)
                
                file_paths[file.filename] = str(file_path)
                logger.debug(f"Saved file: {file.filename} -> {file_path}")
            
            # 保存自定义解析器（如果有）
            if custom_parser:
                parser_path = files_dir / custom_parser.filename
                with open(parser_path, "wb") as f:
                    content = await custom_parser.read()
                    f.write(content)
                file_paths["_custom_parser"] = str(parser_path)
                logger.debug(f"Saved custom parser: {custom_parser.filename}")
            
            # 保存任务元数据
            metadata = {
                "job_id": job_id,
                "created_at": datetime.now().isoformat(),
                "files": list(file_paths.keys()),
                "status": "files_saved"
            }
            metadata_path = job_dir / "metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            logger.info(
                f"Saved {len(files)} files for job {job_id} to {files_dir}"
            )
            
            return file_paths
            
        except Exception as e:
            # 保存失败时清理已创建的目录
            logger.error(f"Failed to save files for job {job_id}: {e}")
            self._cleanup_job_files(job_id, keep_metadata=False)
            raise IOError(f"Failed to save uploaded files: {e}")
    
    async def _parse_files(
        self,
        job_id: str,
        file_paths: Dict[str, str],
        library: str,
        use_vector: bool,
        vector_model: str | None,
        custom_parser_path: str | None
    ) -> tuple[List[dict], dict]:
        """
        从临时目录读取文件并解析
        
        Args:
            job_id: 任务ID
            file_paths: 文件名 -> 临时文件路径的映射
            library: 知识库名称
            use_vector: 是否使用向量
            vector_model: 向量模型
            custom_parser_path: 自定义解析器路径（可选）
        
        Returns:
            tuple[List[dict], dict]: (所有文档列表, 解析结果统计)
        """
        all_documents = []
        failed_files = []
        parsed_count = 0
        
        # 获取 Repository
        repo = ImportRepositoryFactory.create(
            library,
            opensearch_client=self.opensearch_client,
            vector_tool=self.vector_tool,
            config=self.config
        )
        
        # 处理每个文件（排除自定义解析器）
        for filename, file_path in file_paths.items():
            if filename == "_custom_parser":
                continue
            
            try:
                # 读取文件内容
                with open(file_path, "rb") as f:
                    content = f.read()
                
                # 创建 UploadFile 对象用于解析
                from fastapi import UploadFile
                from io import BytesIO
                
                file = UploadFile(
                    file=BytesIO(content),
                    filename=filename
                )
                
                # 处理文件
                documents, error = await repo.process_file(
                    file,
                    library=library,
                    use_vector=use_vector,
                    vector_model=vector_model,
                    custom_parser=None  # 本切片不支持自定义解析器
                )
                
                if error:
                    # 解析失败
                    failed_files.append({
                        'filename': filename,
                        'error': error,
                        'size_bytes': len(content)
                    })
                else:
                    # 解析成功
                    all_documents.extend(documents)
                    parsed_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process file {filename}: {e}")
                failed_files.append({
                    'filename': filename,
                    'error': str(e),
                    'size_bytes': 0
                })
        
        # 构建解析结果
        parse_results = {
            'total_files': len(file_paths) - (1 if "_custom_parser" in file_paths else 0),
            'parsed_files': parsed_count,
            'failed_files': len(failed_files),
            'failed_file_details': failed_files
        }
        
        # 如果所有文件都失败，抛出异常
        if parsed_count == 0:
            raise ValueError(
                f"All {len(file_paths)} files failed to parse. "
                f"See details: {failed_files}"
            )
        
        # 更新任务元数据
        self._update_job_metadata(job_id, {
            "status": "files_parsed",
            "parse_results": parse_results,
            "total_documents": len(all_documents)
        })
        
        return all_documents, parse_results
    
    def _update_job_metadata(self, job_id: str, updates: dict):
        """更新任务元数据"""
        metadata_path = self._get_job_dir(job_id) / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata.update(updates)
            metadata["updated_at"] = datetime.now().isoformat()
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    async def create_import_job_with_files(
        self,
        *,
        library: str,
        files: List[UploadFile],
        vector_model: str | None,
        import_mode: str,
        custom_parser: UploadFile | None
    ) -> ImportJobResponse:
        """
        创建导入任务
        
        完整流程：
        1. 生成 job_id
        2. 校验 library
        3. 创建任务元数据文件
        4. 保存上传文件到临时目录
        5. 解析文件并生成向量
        6. 更新元数据（添加 celery_task_id 和 started_at）
        7. 提交 Celery 异步导入任务
        8. 返回响应（临时文件由 Celery 任务完成后清理）
        """
        # 1. 生成任务ID
        job_id = self._generate_job_id()
        created_at = datetime.now()
        
        # 2. 校验 library
        self._validate_library(library)
        
        # 3. 创建任务元数据文件（初始状态）
        use_vector = vector_model is not None
        metadata = {
            "job_id": job_id,
            "library": library,
            "created_at": created_at.isoformat(),
            "started_at": None,
            "completed_at": None,
            "celery_task_id": None,
            "use_vector": use_vector,
            "vector_model": vector_model,
            "vector_dims": self.vector_tool.get_vector_dims(vector_model) if use_vector else None,
            "import_mode": import_mode,
            "total_files": len(files),
            "parse_results": None,
            "progress": 0.0
        }
        self._create_job_metadata(job_id, metadata)
        
        # 4. 保存文件到临时目录
        file_paths = await self._save_uploaded_files(
            job_id, files, custom_parser
        )
        
        # 5. 解析文件并生成向量
        custom_parser_path = file_paths.get("_custom_parser")
        
        documents, parse_results = await self._parse_files(
            job_id=job_id,
            file_paths=file_paths,
            library=library,
            use_vector=use_vector,
            vector_model=vector_model,
            custom_parser_path=custom_parser_path
        )
        
        # 6. 提交 Celery 异步导入任务
        celery_task = self._submit_import_task(
            job_id=job_id,
            documents=documents,
            library=library,
            import_mode=import_mode
        )
        
        # 7. 更新元数据（添加 celery_task_id、parse_results 和 started_at）
        self._update_job_metadata(job_id, {
            "celery_task_id": celery_task.id,
            "parse_results": parse_results,
            "total_documents": len(documents),
            "started_at": datetime.now().isoformat()
        })
        
        # 8. 构造响应
        response = ImportJobResponse(
            success=True,
            job_id=job_id,
            status="importing",
            message="文档已解析完成，正在后台导入到OpenSearch",
            details={
                "library": library,
                "use_vector": use_vector,
                "vector_model": vector_model,
                "vector_dims": self.vector_tool.get_vector_dims(vector_model) if use_vector else None,
                "import_mode": import_mode,
                "total_documents": len(documents),
                "parse_results": parse_results
            }
        )
        
        return response
    
    def _create_job_metadata(self, job_id: str, metadata: dict):
        """创建任务元数据文件"""
        job_dir = self._get_job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        
        metadata_path = job_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Created job metadata: {job_id}")
    
    def _validate_library(self, library: str):
        """校验 library，SESSION/SKILL 短路"""
        if library in ["SESSION", "SKILL"]:
            raise ValueError(f"{library} import not supported in current version")
    
    def _submit_import_task(
        self, 
        job_id: str, 
        documents: List[dict], 
        library: str, 
        import_mode: str
    ) -> AsyncResult:
        """
        提交 Celery 异步批量导入任务
        
        Returns:
            AsyncResult: Celery 任务对象（包含 task_id）
        """
        from app.infrastructure.celery.tasks import import_documents_task
        
        # 提交任务时传入 job_id，用于任务完成后清理文件
        celery_task = import_documents_task.delay(
            job_id=job_id,
            documents=documents,
            library=library,
            import_mode=import_mode
        )
        
        self.logger.info(f"Submitted Celery task: task_id={celery_task.id}, job_id={job_id}")
        return celery_task
    
    def _cleanup_job_files(self, job_id: str, keep_metadata: bool = False):
        """
        清理任务的临时文件
        
        Args:
            job_id: 任务ID
            keep_metadata: 是否保留元数据文件
        """
        job_dir = self._get_job_dir(job_id)
        
        if not job_dir.exists():
            logger.warning(f"Job directory not found: {job_dir}")
            return
        
        try:
            if keep_metadata:
                # 只删除 files 目录
                files_dir = self._get_files_dir(job_id)
                if files_dir.exists():
                    shutil.rmtree(files_dir)
                    logger.info(f"Cleaned up files for job {job_id}")
            else:
                # 删除整个任务目录
                shutil.rmtree(job_dir)
                logger.info(f"Cleaned up job directory: {job_id}")
        
        except Exception as e:
            logger.error(
                f"Failed to cleanup job {job_id}: {e}",
                exc_info=True
            )
    
    async def get_job_status(self, job_id: str) -> ImportJobStatusResponse:
        """
        查询导入任务状态
        
        Args:
            job_id: 任务ID
            
        Returns:
            ImportJobStatusResponse: 任务状态信息
            
        Raises:
            FileNotFoundError: 任务不存在
            
        工作流程：
        1. 检查任务元数据文件是否存在
        2. 读取任务基础信息（library、created_at、parse_results等）
        3. 从 Celery 获取任务执行状态（进度、当前阶段）
        4. 合并信息并返回统一的状态响应
        """
        # 1. 检查任务目录是否存在
        job_dir = self.temp_dir / "jobs" / job_id
        metadata_path = job_dir / "metadata.json"
        
        if not metadata_path.exists():
            self.logger.warning(f"Job metadata not found: {job_id}")
            raise FileNotFoundError(f"Job not found: {job_id}")
        
        # 2. 读取任务元数据
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to read job metadata: {job_id}, error={e}")
            raise ValueError(f"Invalid job metadata: {e}")
        
        # 3. 从元数据提取基础信息
        created_at = datetime.fromisoformat(metadata.get("created_at"))
        parse_results = metadata.get("parse_results")
        library = metadata.get("library")
        celery_task_id = metadata.get("celery_task_id")
        
        # 4. 从 Celery 获取任务执行状态
        if not celery_task_id:
            # 没有 Celery 任务ID，说明任务尚未提交到 Celery
            return ImportJobStatusResponse(
                job_id=job_id,
                status="parsing",
                progress=0.0,
                message="正在解析文件...",
                parse_results=None,
                result=None,
                error=None,
                created_at=created_at,
                started_at=None,
                completed_at=None
            )
        
        # 5. 查询 Celery 任务状态
        celery_task = AsyncResult(celery_task_id, app=self.celery_app)
        
        # 6. 映射 Celery 状态到业务状态
        if celery_task.state == 'PENDING':
            # 任务等待执行
            return ImportJobStatusResponse(
                job_id=job_id,
                status="parsing",
                progress=0.0,
                message="等待执行...",
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=None,
                error=None,
                created_at=created_at,
                started_at=None,
                completed_at=None
            )
        
        elif celery_task.state == 'PROGRESS':
            # 任务执行中
            task_info = celery_task.info or {}
            stage = task_info.get('stage', '')
            current = task_info.get('current', 0)
            total = task_info.get('total', 100)
            status_msg = task_info.get('status', '')
            
            # 根据执行阶段判断业务状态
            if stage == 'preparing':
                business_status = "parsing"
            elif stage == 'processing_files':
                business_status = "parsing"
            elif stage in ['files_processed', 'importing_es']:
                # 判断是否有向量化阶段
                use_vector = metadata.get("use_vector", False)
                if use_vector and current < 20:  # 前20%视为向量化阶段
                    business_status = "vectorizing"
                else:
                    business_status = "importing"
            elif stage == 'cleanup':
                business_status = "importing"
            else:
                business_status = "importing"
            
            progress = float(current) / 100.0 if total > 0 else 0.0
            
            return ImportJobStatusResponse(
                job_id=job_id,
                status=business_status,
                progress=progress,
                message=status_msg,
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=None,
                error=None,
                created_at=created_at,
                started_at=datetime.fromisoformat(metadata.get("started_at")) if metadata.get("started_at") else None,
                completed_at=None
            )
        
        elif celery_task.state == 'SUCCESS':
            # 任务成功完成
            task_result = celery_task.result or {}
            
            # 从 Celery 结果构建导入结果
            import_result = ImportResult(
                index_name=task_result.get('index_name', ''),
                imported_docs=task_result.get('imported_docs', 0),
                total_docs=task_result.get('total_docs', 0),
                failed_docs=task_result.get('failed_docs', 0),
                has_vector=task_result.get('has_vector', False),
                vector_dims=task_result.get('vector_dims')
            )
            
            completed_at = metadata.get("completed_at")
            if not completed_at:
                # 如果元数据中没有完成时间，使用当前时间
                completed_at = datetime.now().isoformat()
                metadata["completed_at"] = completed_at
                # 更新元数据文件
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            return ImportJobStatusResponse(
                job_id=job_id,
                status="completed",
                progress=1.0,
                message="导入完成",
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=import_result,
                error=None,
                created_at=created_at,
                started_at=datetime.fromisoformat(metadata.get("started_at")) if metadata.get("started_at") else None,
                completed_at=datetime.fromisoformat(completed_at)
            )
        
        elif celery_task.state == 'FAILURE':
            # 任务失败
            error_msg = str(celery_task.info) if celery_task.info else "Unknown error"
            
            # 从 Celery 任务信息获取进度（如果有）
            progress = 0.0
            if isinstance(celery_task.info, dict):
                current = celery_task.info.get('current', 0)
                total = celery_task.info.get('total', 100)
                progress = float(current) / 100.0 if total > 0 else 0.0
            
            completed_at = metadata.get("completed_at")
            if not completed_at:
                completed_at = datetime.now().isoformat()
                metadata["completed_at"] = completed_at
                metadata["error"] = error_msg
                # 更新元数据文件
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            return ImportJobStatusResponse(
                job_id=job_id,
                status="failed",
                progress=progress,
                message="同步失败",
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=None,
                error=error_msg,
                created_at=created_at,
                started_at=datetime.fromisoformat(metadata.get("started_at")) if metadata.get("started_at") else None,
                completed_at=datetime.fromisoformat(completed_at)
            )
        
        elif celery_task.state == 'REVOKED':
            # 任务被取消
            return ImportJobStatusResponse(
                job_id=job_id,
                status="cancelled",
                progress=metadata.get("progress", 0.0),
                message="任务已取消",
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=None,
                error=None,
                created_at=created_at,
                started_at=datetime.fromisoformat(metadata.get("started_at")) if metadata.get("started_at") else None,
                completed_at=datetime.fromisoformat(metadata.get("completed_at")) if metadata.get("completed_at") else None
            )
        
        else:
            # 其他未知状态（RETRY等）
            self.logger.warning(f"Unknown Celery task state: {celery_task.state} for job {job_id}")
            return ImportJobStatusResponse(
                job_id=job_id,
                status="importing",
                progress=metadata.get("progress", 0.0),
                message=f"任务状态: {celery_task.state}",
                parse_results=ParseResults(**parse_results) if parse_results else None,
                result=None,
                error=None,
                created_at=created_at,
                started_at=datetime.fromisoformat(metadata.get("started_at")) if metadata.get("started_at") else None,
                completed_at=None
            )
```

#### 任务元数据结构

`metadata.json` 文件结构示例：

```json
{
  "job_id": "import_20260412_123456_abc123",
  "library": "CODE",
  "created_at": "2026-04-12T12:34:56",
  "started_at": "2026-04-12T12:35:01",
  "completed_at": null,
  "celery_task_id": "abc-123-def-456",
  "use_vector": true,
  "vector_model": "mpnet",
  "vector_dims": 768,
  "import_mode": "replace",
  "total_files": 2,
  "parse_results": {
    "total_files": 2,
    "parsed_files": 2,
    "failed_files": 0,
    "failed_file_details": []
  },
  "progress": 0.0
}
```

#### 状态映射逻辑

| Celery 状态 | Celery Stage | 业务状态 | 进度范围 | 说明 |
|------------|-------------|---------|---------|------|
| `PENDING` | - | `parsing` | 0% | 任务等待执行 |
| `PROGRESS` | `preparing` | `parsing` | 0-5% | 准备阶段 |
| `PROGRESS` | `processing_files` | `parsing` | 5-10% | 文件解析中 |
| `PROGRESS` | `files_processed` | `vectorizing` (if use_vector) | 10-30% | 向量生成中 |
| `PROGRESS` | `importing_es` | `importing` | 30-95% | 导入OpenSearch |
| `PROGRESS` | `cleanup` | `importing` | 95-98% | 清理临时文件 |
| `SUCCESS` | - | `completed` | 100% | 任务成功完成 |
| `FAILURE` | - | `failed` | 当前进度 | 任务失败 |
| `REVOKED` | - | `cancelled` | 当前进度 | 任务被取消 |

约束：

1. `ImportService` 只做编排，不直接实现文档解析或数据库操作。
2. 所有外部依赖均通过构造注入或 `dependencies.py` 装配。
3. `_parse_files(...)` 是 Service 到 Repository 的唯一单文件桥接入口。
4. 临时文件在 Celery 任务完成后清理（保留元数据用于查询任务状态）。

---

## 5. ImportService 时序说明

### 5.1 完整流程

**重要设计变更**：Celery异步任务执行用户import的**完整任务**

新的设计将耗时操作（文件解析、向量生成）从API层移到Celery任务中，实现真正的异步处理。

```
ImportService.create_import_job_with_files
│
├── 1. 生成任务ID
│   └── job_id = import_{timestamp}_{random}
│
├── 2. 校验 library
│   └── SESSION/SKILL? 短路返回 400
│
├── 3. 创建任务元数据文件
│   ├── 创建任务目录: /tmp/bible_import/jobs/{job_id}/
│   └── 保存初始元数据: metadata.json
│       • job_id, library, created_at
│       • use_vector, vector_model, vector_dims
│       • import_mode, total_files
│       • celery_task_id: null, started_at: null
│       • parse_results: null, progress: 0.0
│
├── 4. 保存文件到临时目录
│   ├── 创建文件目录: /tmp/bible_import/jobs/{job_id}/files/
│   └── 保存上传的文件
│
├── 5. 解析文件并生成向量
│   ├── 遍历文件，调用 Repository 解析
│   │   ├── parse_document(file) -> List[DocumentChunk]
│   │   ├── 生成向量（可选）: VectorTool.generate_vector
│   │   └── format_for_opensearch(chunks, ...) -> List[dict]
│   └── 汇总解析结果: parse_results
│
├── 6. 提交 Celery 异步任务
│   ├── 调用: import_documents_task.delay(job_id, documents, library, import_mode)
│   └── 获取: celery_task (包含 task_id)
│
├── 7. 更新任务元数据
│   └── 更新 metadata.json:
│       • celery_task_id: celery_task.id
│       • parse_results: {...}
│       • total_documents: len(documents)
│       • started_at: datetime.now()
│
└── 8. 构造并返回响应（API请求快速返回）
    └── ImportJobResponse: {
          success: true,
          job_id: job_id,
          status: "importing",
          message: "文档已解析完成，正在后台导入到OpenSearch",
          details: { library, use_vector, total_documents, parse_results, ... }
        }

========================================
Celery 异步任务执行（后台）
========================================

import_documents_task(job_id, documents, library, import_mode)
│
├── 1. 更新任务状态（PROGRESS - 准备阶段）
│   └── self.update_state(state='PROGRESS', meta={stage: 'preparing', current: 0, total: 100})
│
├── 2. 导入到 OpenSearch (5-95%)
│   ├── IndexManager.ensure_index_exists(library)
│   ├── import_mode == "replace" → 删除旧文档
│   ├── BulkImporter.bulk_insert(documents)
│   │   └── 定期更新进度: self.update_state(stage='importing_es', current=X, total=100)
│   └── 更新状态: progress=95%
│
├── 3. 清理临时文件 (95-98%)
│   ├── 删除: /tmp/bible_import/jobs/{job_id}/files/
│   ├── 保留: /tmp/bible_import/jobs/{job_id}/metadata.json
│   └── 更新状态: stage='cleanup', progress=98%
│
├── 4. 更新任务元数据（完成状态）
│   └── 更新 metadata.json:
│       • completed_at: datetime.now()
│       • status: "completed"
│
└── 5. 返回任务结果（SUCCESS）
    └── {
          status: 'success',
          index_name: index_name,
          imported_docs: imported_docs,
          total_docs: total_docs,
          failed_docs: failed_docs,
          has_vector: use_vector,
          vector_dims: vector_dims,
          message: "成功导入 X 个文档到 Y"
        }

========================================
查询任务状态流程
========================================

GET /api/v1/import/jobs/{job_id}
│
ImportService.get_job_status(job_id)
│
├── 1. 检查元数据文件是否存在
│   └── /tmp/bible_import/jobs/{job_id}/metadata.json
│
├── 2. 读取任务元数据
│   ├── job_id, library, created_at
│   ├── celery_task_id
│   ├── parse_results
│   └── started_at, completed_at
│
├── 3. 查询 Celery 任务状态（如果有 celery_task_id）
│   └── AsyncResult(celery_task_id, app=celery_app)
│       ├── state: PENDING/PROGRESS/SUCCESS/FAILURE/REVOKED
│       └── info: {stage, current, total, status, ...}
│
├── 4. 映射状态到业务状态
│   ├── PENDING → parsing (等待执行)
│   ├── PROGRESS + stage='preparing' → parsing
│   ├── PROGRESS + stage='files_processed' → vectorizing (if use_vector)
│   ├── PROGRESS + stage='importing_es' → importing
│   ├── SUCCESS → completed
│   ├── FAILURE → failed
│   └── REVOKED → cancelled
│
└── 5. 返回统一的状态响应
    └── ImportJobStatusResponse: {
          job_id, status, progress, message,
          parse_results, result, error,
          created_at, started_at, completed_at
        }
```

**关键职责划分**：

| 层次 | 职责 | 执行时间 |
|------|------|---------|
| **API层（同步）** | 1. 接收POST请求<br>2. 校验参数<br>3. 创建元数据文件<br>4. 保存文件到临时目录<br>5. 解析文件并生成向量<br>6. 提交Celery任务<br>7. 立即返回job_id | 秒级（快速返回） |
| **Celery任务（异步）** | 1. 导入OpenSearch<br>2. 更新进度状态<br>3. 清理临时文件<br>4. 更新元数据（完成状态） | 分钟级（后台执行） |
| **API查询（同步）** | 1. 读取元数据文件<br>2. 查询Celery任务状态<br>3. 映射状态到业务状态<br>4. 返回统一状态响应 | 毫秒级（快速返回） |

**优点**：
- API请求快速返回，解析和向量生成在API层完成，确保数据质量
- Celery任务只负责批量导入，降低复杂度
- 用户可以立即获得job_id，然后轮询任务状态
- 元数据文件保留任务历史，支持状态查询和故障排查
- 状态映射清晰，用户可以了解任务的详细执行进度
- Celery worker可以并行处理多个导入任务
- 失败重试机制更健壮（Celery内置重试）
│
└── 6. 构造 ImportJobResponse 返回
    └── 临时文件保留，由 Celery 任务完成后清理
```

### 5.2 文件解析流程

```
Repository.process_file
│
├── 1. parse_document(file)
│   ├── 判断文件类型
│   │   ├── .md: MarkdownParser.parse
│   │   └── .json: JsonParser.parse
│   └── 返回 List[DocumentChunk]
│
├── 2. 生成向量（可选）
│   ├── use_vector=True?
│   │   ├── 遍历 chunks
│   │   │   ├── text = f"{title}\n{content}"
│   │   │   ├── vector = VectorTool.generate_vector(text, model)
│   │   │   └── chunk.metadata['vector'] = vector
│   │   └── 更新 chunks
│   └── 否则跳过
│
├── 3. format_for_opensearch(chunks, ...)
│   ├── 遍历 chunks
│   │   ├── 生成文档ID: generate_doc_id(library, filename, section_id)
│   │   ├── 构建文档: {doc_id, library, section_title, content, vector, ...}
│   │   └── documents.append(doc)
│   └── 返回 List[dict]
│
└── 4. 返回文档列表
```

---

### 5.3 Parsers 详细设计

#### 5.3.1 设计思路

**Parsers 的职责**：
- 将不同格式的原始文件（`.md`, `.json` 等）转换为统一的 `DocumentChunk` 列表
- 与 `BaseImportRepository` 解耦，通过标准接口协作
- 支持策略模式，便于扩展新文件类型

**与 Repository 的协作关系**：
```
ImportService._parse_files
    ↓
ImportRepositoryFactory.create(library)
    ↓
Repository.process_file(file)
    ↓
Repository.parse_document(file)  ← 选择合适的 Parser
    ↓
Parser.parse(file) → List[DocumentChunk]
```

**设计原则**：
1. **单一职责**：每个 Parser 只负责一种文件格式
2. **依赖倒置**：Repository 依赖 Parser 抽象接口，不依赖具体实现
3. **可扩展性**：新增文件格式只需实现 BaseDocumentParser
4. **错误处理**：Parser 内部捕获解析错误，返回友好错误信息

#### 5.3.2 BaseDocumentParser（抽象接口）

**文件位置**：`app/features/import_/parsers/base.py`

**接口定义**：

```python
# app/features/import_/parsers/base.py
from abc import ABC, abstractmethod
from typing import List, ClassVar
from fastapi import UploadFile

from app.features.import_.schemas import DocumentChunk


class ParserError(Exception):
    """解析错误基类"""
    pass


class FileFormatError(ParserError):
    """文件格式错误"""
    pass


class ContentValidationError(ParserError):
    """内容验证错误"""
    pass


class BaseDocumentParser(ABC):
    """
    文档解析器基类
    
    所有具体解析器必须继承此类并实现 parse 方法
    """
    
    # 支持的文件扩展名（含点号），如 ['.md', '.markdown']
    supported_extensions: ClassVar[List[str]] = []
    
    # 解析器名称
    parser_name: ClassVar[str] = "BaseParser"
    
    @abstractmethod
    async def parse(self, file: UploadFile, filename: str) -> List[DocumentChunk]:
        """
        解析上传文件，返回文档分块列表
        
        Args:
            file: FastAPI UploadFile 对象
            filename: 文件名（用于错误提示和元数据）
        
        Returns:
            List[DocumentChunk]: 文档分块列表
        
        Raises:
            FileFormatError: 文件格式不正确
            ContentValidationError: 内容验证失败
            ParserError: 其他解析错误
        """
        pass
    
    def supports_file(self, filename: str) -> bool:
        """
        检查是否支持该文件类型
        
        Args:
            filename: 文件名
        
        Returns:
            bool: 是否支持
        """
        import os
        _, ext = os.path.splitext(filename.lower())
        return ext in self.supported_extensions
    
    @staticmethod
    def generate_section_id(filename: str, index: int, title: str = "") -> str:
        """
        生成章节ID（统一格式）
        
        Args:
            filename: 文件名（不含路径）
            index: 章节索引（从1开始）
            title: 章节标题（可选，用于生成更友好的ID）
        
        Returns:
            str: 章节ID，如 "file_section_1" 或 "file_intro"
        """
        import re
        from pathlib import Path
        
        # 移除文件扩展名
        base_name = Path(filename).stem
        # 清理文件名，只保留字母数字和下划线
        clean_name = re.sub(r'[^\w\s-]', '', base_name)
        clean_name = re.sub(r'[-\s]+', '_', clean_name).lower()
        
        if title:
            # 清理标题，生成友好ID
            clean_title = re.sub(r'[^\w\s-]', '', title)
            clean_title = re.sub(r'[-\s]+', '_', clean_title).lower()
            clean_title = clean_title[:50]  # 限制长度
            return f"{clean_name}_{clean_title}_{index}"
        else:
            return f"{clean_name}_section_{index}"
```

**关键设计点**：
1. **类变量 `supported_extensions`**：声明支持的文件扩展名，便于工厂选择
2. **异常体系**：定义 `ParserError` 系列异常，便于上层统一处理
3. **异步接口**：`parse` 方法为 async，支持大文件异步读取
4. **辅助方法**：`generate_section_id` 提供统一的章节ID生成规则

#### 5.3.3 MarkdownParser（Markdown 解析器）

**文件位置**：`app/features/import_/parsers/markdown_parser.py`

**实现思路**：
1. 按照 Markdown 标题层级（`#`, `##`, `###` 等）分割章节
2. 提取标题文本作为 `section_title`
3. 提取标题下的内容作为 `content`
4. 保留元数据（文件名、标题层级、行号等）

**接口定义**：

```python
# app/features/import_/parsers/markdown_parser.py
import re
from typing import List, ClassVar
from fastapi import UploadFile

from app.features.import_.parsers.base import (
    BaseDocumentParser,
    FileFormatError,
    DocumentChunk
)
from app.common.logging import get_logger

logger = get_logger(__name__)


class MarkdownParser(BaseDocumentParser):
    """Markdown 文件解析器"""
    
    supported_extensions: ClassVar[List[str]] = ['.md', '.markdown']
    parser_name: ClassVar[str] = "MarkdownParser"
    
    # Markdown 标题正则（支持 # 到 ###### ）
    HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    
    async def parse(self, file: UploadFile, filename: str) -> List[DocumentChunk]:
        """
        解析 Markdown 文件
        
        按标题层级分割章节：
        - 每个标题（# ~ ######）作为一个章节的开始
        - 标题下的所有内容作为章节内容
        - 如果文件开头有内容（无标题），作为第一个章节（标题为文件名）
        
        Args:
            file: FastAPI UploadFile 对象
            filename: 文件名
        
        Returns:
            List[DocumentChunk]: 章节列表
        
        Raises:
            FileFormatError: 文件读取失败或编码错误
        """
        try:
            # 读取文件内容
            content_bytes = await file.read()
            
            # 尝试多种编码
            content = None
            for encoding in ['utf-8', 'gbk', 'gb2312']:
                try:
                    content = content_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                raise FileFormatError(
                    f"Cannot decode file {filename} with supported encodings"
                )
            
            # 解析章节
            chunks = self._split_by_headings(content, filename)
            
            if not chunks:
                # 如果没有找到任何标题，将整个文件作为一个章节
                chunks = [
                    DocumentChunk(
                        section_id=self.generate_section_id(filename, 1),
                        section_title=filename,
                        content=content.strip(),
                        metadata={
                            'filename': filename,
                            'parser': self.parser_name,
                            'heading_level': 0,
                            'has_heading': False
                        }
                    )
                ]
            
            logger.info(
                f"Parsed {filename}: {len(chunks)} sections, "
                f"{len(content)} chars"
            )
            
            return chunks
            
        except FileFormatError:
            raise
        except Exception as e:
            logger.error(f"Failed to parse {filename}: {e}", exc_info=True)
            raise FileFormatError(f"Failed to parse markdown file: {str(e)}")
    
    def _split_by_headings(
        self, 
        content: str, 
        filename: str
    ) -> List[DocumentChunk]:
        """
        按标题分割内容
        
        Args:
            content: 文件内容
            filename: 文件名
        
        Returns:
            List[DocumentChunk]: 章节列表
        """
        chunks = []
        
        # 查找所有标题位置
        headings = []
        for match in self.HEADING_PATTERN.finditer(content):
            level = len(match.group(1))  # # 的数量
            title = match.group(2).strip()
            start_pos = match.start()
            headings.append({
                'level': level,
                'title': title,
                'start': start_pos,
                'end': match.end()
            })
        
        if not headings:
            return []
        
        # 处理文件开头到第一个标题之前的内容
        first_heading = headings[0]
        preamble = content[:first_heading['start']].strip()
        if preamble:
            chunks.append(
                DocumentChunk(
                    section_id=self.generate_section_id(filename, 0, 'preamble'),
                    section_title=f"{filename} (Preamble)",
                    content=preamble,
                    metadata={
                        'filename': filename,
                        'parser': self.parser_name,
                        'heading_level': 0,
                        'is_preamble': True
                    }
                )
            )
        
        # 提取每个章节内容
        for i, heading in enumerate(headings):
            # 确定章节内容范围
            content_start = heading['end']
            content_end = (
                headings[i + 1]['start'] if i + 1 < len(headings)
                else len(content)
            )
            
            # 提取章节内容
            section_content = content[content_start:content_end].strip()
            
            # 创建 DocumentChunk
            chunk = DocumentChunk(
                section_id=self.generate_section_id(
                    filename, 
                    i + 1, 
                    heading['title']
                ),
                section_title=heading['title'],
                content=section_content,
                metadata={
                    'filename': filename,
                    'parser': self.parser_name,
                    'heading_level': heading['level'],
                    'heading_index': i + 1,
                    'content_length': len(section_content)
                }
            )
            
            chunks.append(chunk)
        
        return chunks
```

**输入**：
- `file: UploadFile` - FastAPI 上传的文件对象
- `filename: str` - 文件名

**输出**：
- `List[DocumentChunk]` - 解析后的章节列表，每个章节包含：
  - `section_id`: 唯一标识符（如 `design_doc_architecture_1`）
  - `section_title`: 章节标题（Markdown 标题文本）
  - `content`: 章节内容（标题下的所有文本）
  - `metadata`: 元数据（文件名、标题层级、索引等）

**特殊处理**：
1. **文件开头无标题内容**：作为 "Preamble" 章节
2. **整个文件无标题**：将整个文件作为一个章节，标题为文件名
3. **编码自动检测**：尝试 UTF-8, GBK, GB2312

#### 5.3.4 JsonParser（JSON 解析器）

**文件位置**：`app/features/import_/parsers/json_parser.py`

**实现思路**：
1. 验证 JSON 格式合法性
2. 期望 JSON 结构：`{"sections": [{"title": "...", "content": "..."}, ...]}`
3. 也支持顶层数组：`[{"title": "...", "content": "..."}, ...]`
4. 提取每个 section 作为 `DocumentChunk`

**接口定义**：

```python
# app/features/import_/parsers/json_parser.py
import json
from typing import List, ClassVar, Any, Dict
from fastapi import UploadFile

from app.features.import_.parsers.base import (
    BaseDocumentParser,
    FileFormatError,
    ContentValidationError,
    DocumentChunk
)
from app.common.logging import get_logger

logger = get_logger(__name__)


class JsonParser(BaseDocumentParser):
    """JSON 文件解析器"""
    
    supported_extensions: ClassVar[List[str]] = ['.json']
    parser_name: ClassVar[str] = "JsonParser"
    
    async def parse(self, file: UploadFile, filename: str) -> List[DocumentChunk]:
        """
        解析 JSON 文件
        
        支持两种格式：
        1. 带 sections 键：
           {
               "sections": [
                   {"title": "标题1", "content": "内容1"},
                   {"title": "标题2", "content": "内容2"}
               ]
           }
        
        2. 顶层数组：
           [
               {"title": "标题1", "content": "内容1"},
               {"title": "标题2", "content": "内容2"}
           ]
        
        Args:
            file: FastAPI UploadFile 对象
            filename: 文件名
        
        Returns:
            List[DocumentChunk]: 章节列表
        
        Raises:
            FileFormatError: JSON 格式错误
            ContentValidationError: JSON 结构不符合预期
        """
        try:
            # 读取文件内容
            content_bytes = await file.read()
            
            # 尝试解码
            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError as e:
                raise FileFormatError(
                    f"Cannot decode JSON file {filename} as UTF-8: {e}"
                )
            
            # 解析 JSON
            try:
                data = json.loads(content_str)
            except json.JSONDecodeError as e:
                raise FileFormatError(
                    f"Invalid JSON format in {filename}: {e}"
                )
            
            # 提取 sections
            sections = self._extract_sections(data, filename)
            
            # 转换为 DocumentChunk
            chunks = self._sections_to_chunks(sections, filename)
            
            logger.info(
                f"Parsed {filename}: {len(chunks)} sections, "
                f"{len(content_str)} chars"
            )
            
            return chunks
            
        except (FileFormatError, ContentValidationError):
            raise
        except Exception as e:
            logger.error(f"Failed to parse {filename}: {e}", exc_info=True)
            raise FileFormatError(f"Failed to parse JSON file: {str(e)}")
    
    def _extract_sections(
        self, 
        data: Any, 
        filename: str
    ) -> List[Dict[str, Any]]:
        """
        从 JSON 数据中提取 sections
        
        Args:
            data: 解析后的 JSON 数据
            filename: 文件名（用于错误提示）
        
        Returns:
            List[Dict]: sections 列表
        
        Raises:
            ContentValidationError: 数据结构不符合预期
        """
        # 格式1：{"sections": [...]}
        if isinstance(data, dict) and 'sections' in data:
            sections = data['sections']
            if not isinstance(sections, list):
                raise ContentValidationError(
                    f"'sections' must be a list in {filename}"
                )
            return sections
        
        # 格式2：[...]
        elif isinstance(data, list):
            return data
        
        # 不支持的格式
        else:
            raise ContentValidationError(
                f"JSON must be either {{'sections': [...]}} or [...] "
                f"in {filename}"
            )
    
    def _sections_to_chunks(
        self,
        sections: List[Dict[str, Any]],
        filename: str
    ) -> List[DocumentChunk]:
        """
        将 sections 转换为 DocumentChunk
        
        Args:
            sections: sections 列表
            filename: 文件名
        
        Returns:
            List[DocumentChunk]: 章节列表
        
        Raises:
            ContentValidationError: section 结构不符合预期
        """
        chunks = []
        
        for i, section in enumerate(sections, start=1):
            # 验证 section 结构
            if not isinstance(section, dict):
                logger.warning(
                    f"Section {i} in {filename} is not a dict, skipping"
                )
                continue
            
            # 提取字段
            title = section.get('title', f'Section {i}')
            content = section.get('content', '')
            
            if not isinstance(title, str):
                title = str(title)
            
            if not isinstance(content, str):
                # 如果 content 不是字符串，尝试序列化
                try:
                    content = json.dumps(content, ensure_ascii=False, indent=2)
                except Exception:
                    content = str(content)
            
            # 提取额外元数据
            metadata = {
                'filename': filename,
                'parser': self.parser_name,
                'section_index': i
            }
            
            # 保留原始 section 中的其他字段作为元数据
            for key, value in section.items():
                if key not in ['title', 'content']:
                    metadata[f'custom_{key}'] = value
            
            # 创建 DocumentChunk
            chunk = DocumentChunk(
                section_id=self.generate_section_id(filename, i, title),
                section_title=title,
                content=content,
                metadata=metadata
            )
            
            chunks.append(chunk)
        
        if not chunks:
            raise ContentValidationError(
                f"No valid sections found in {filename}"
            )
        
        return chunks
```

**输入**：
- `file: UploadFile` - FastAPI 上传的文件对象
- `filename: str` - 文件名

**输出**：
- `List[DocumentChunk]` - 解析后的章节列表

**支持的 JSON 格式**：

格式1（推荐）：
```json
{
  "sections": [
    {
      "title": "Introduction",
      "content": "This is the introduction..."
    },
    {
      "title": "Implementation",
      "content": "Implementation details..."
    }
  ]
}
```

格式2（简化）：
```json
[
  {
    "title": "Introduction",
    "content": "This is the introduction..."
  },
  {
    "title": "Implementation",
    "content": "Implementation details..."
  }
]
```

**特殊处理**：
1. **content 非字符串**：自动序列化为 JSON 字符串
2. **title 缺失**：使用 "Section {index}" 作为默认标题
3. **额外字段**：保留为元数据（加 `custom_` 前缀）

#### 5.3.5 CustomParser（自定义解析器 - 预留）

**文件位置**：`app/features/import_/parsers/custom_parser.py`

**实现思路**：
1. 用户上传 `.py` 文件作为自定义解析器
2. 该 Python 文件需要定义一个 `parse(filename: str) -> List[dict]` 函数
3. 解析器接收文件路径，需要自行读取文件内容
4. 返回格式：`[{"title": "...", "content": "...", "metadata": {...}}, ...]`
5. 必须包含异常处理，抛出的异常会被记录到任务日志中
6. 本切片仅预留接口，不实现沙箱执行
7. 未来实现时需要考虑安全性（沙箱、超时、资源限制）

**使用示例（未来实现）**：

用户可以通过上传自定义解析器来处理特殊格式的文件：

```bash
# 1. 准备自定义解析器文件 my_parser.py
# 2. 准备需要导入的文档文件 data.txt
# 3. 调用 Import API，同时上传两个文件

curl -X POST http://localhost:9220/api/v1/import/jobs \
  -F "library=CODE" \
  -F "vector_model=mpnet" \
  -F "files=@data.txt" \
  -F "custom_parser=@my_parser.py"
```

**用户自定义解析器的预期格式**：

```python
# 用户上传的 my_parser.py 示例
def parse(filename: str) -> list:
    """
    自定义解析函数
    
    Args:
        filename: 文件路径（绝对路径）
    
    Returns:
        list: 文档列表，每个元素为 {"title": "...", "content": "...", "metadata": {...}}
        
    Raises:
        Exception: 当解析失败时抛出异常，异常信息将被记录到任务日志中
        
    注意：
        - 必须定义名为 parse 的函数
        - 函数接收文件路径，需要自行读取文件内容
        - 返回格式必须为 list[dict]，每个 dict 至少包含 title 和 content
        - metadata 字段可选，用于存储额外的元数据信息
        - 必须包含异常处理，捕获文件读取、编码、格式解析等错误
    """
    documents = []
    
    try:
        # 读取文件内容
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 用户自己的解析逻辑
        # 示例：简单按空行分割
        parts = content.split('\n\n')
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
                
            documents.append({
                "title": f"Section {i+1}",
                "content": part,
                "metadata": {
                    "section_index": i + 1
                }
            })
        
        if not documents:
            raise ValueError("No valid documents found in file")
            
    except FileNotFoundError:
        raise Exception(f"File not found: {filename}")
    except UnicodeDecodeError:
        raise Exception(f"Failed to decode file {filename}, please ensure it's UTF-8 encoded")
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
    
    return documents
```

**更复杂的示例（解析特殊格式）**：

```python
# 解析 XML 格式的自定义解析器
import xml.etree.ElementTree as ET
import os

def parse(filename: str) -> list:
    """解析 XML 格式文件"""
    documents = []
    
    try:
        # 解析 XML 文件
        tree = ET.parse(filename)
        root = tree.getroot()
        
        # 遍历所有 section 节点
        for i, section in enumerate(root.findall('.//section'), start=1):
            title = section.get('title', f'Section {i}')
            content = section.text or ''
            
            if not content.strip():
                # 跳过没有内容的节点
                continue
            
            # 提取属性作为元数据
            metadata = {
                'section_index': i,
                'section_type': section.get('type'),
                'priority': section.get('priority'),
                'source_file': os.path.basename(filename)
            }
            # 移除值为 None 的元数据
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            documents.append({
                "title": title,
                "content": content.strip(),
                "metadata": metadata
            })
        
        if not documents:
            raise ValueError("No valid documents found in XML file")
        
        return documents
        
    except FileNotFoundError:
        raise Exception(f"File not found: {filename}")
    except ET.ParseError as e:
        raise Exception(f"XML parsing failed: {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to parse {filename}: {str(e)}")
```

**接口定义**：

```python
# app/features/import_/parsers/custom_parser.py
from typing import List, ClassVar
from fastapi import UploadFile

from app.features.import_.parsers.base import (
    BaseDocumentParser,
    ParserError,
    DocumentChunk
)
from app.common.logging import get_logger

logger = get_logger(__name__)


class CustomParser(BaseDocumentParser):
    """
    自定义解析器（执行用户上传的 Python 脚本）
    
    本切片仅预留接口，不实现沙箱执行机制
    """
    
    supported_extensions: ClassVar[List[str]] = []  # 支持所有扩展名
    parser_name: ClassVar[str] = "CustomParser"
    
    def __init__(self, parser_file: UploadFile):
        """
        Args:
            parser_file: 用户上传的解析器 Python 脚本文件
        """
        self.parser_file = parser_file
    
    async def parse(self, file: UploadFile, filename: str) -> List[DocumentChunk]:
        """
        执行自定义解析器脚本
        
        本切片不实现，直接抛出异常
        
        未来实现逻辑：
        1. 保存上传的文件到临时目录
        2. 读取 parser_file 内容（用户的自定义解析器脚本）
        3. 在沙箱环境中执行该 Python 脚本
        4. 调用脚本中的 parse(filename) 函数，传入临时文件路径
        5. 将返回的 dict 列表转换为 DocumentChunk 列表
        6. 清理临时文件
        
        Args:
            file: FastAPI UploadFile 对象
            filename: 文件名
        
        Returns:
            List[DocumentChunk]: 章节列表
        
        Raises:
            ParserError: 自定义解析器未实现
        """
        logger.warning(
            f"Custom parser requested for {filename}, "
            f"but not implemented in current version"
        )
        raise ParserError(
            "Custom parser is not supported in current version. "
            "Please use standard Markdown or JSON format."
        )
```
```

#### 5.3.6 ParserFactory（解析器工厂）

**文件位置**：`app/features/import_/parsers/__init__.py`

**实现思路**：
- 根据文件扩展名选择合适的解析器
- 如果提供了自定义解析器文件，使用 CustomParser
- 支持解析器注册（扩展点）

**接口定义**：

```python
# app/features/import_/parsers/__init__.py
from typing import Optional
from fastapi import UploadFile
from app.features.import_.parsers.base import BaseDocumentParser, ParserError
from app.features.import_.parsers.markdown_parser import MarkdownParser
from app.features.import_.parsers.json_parser import JsonParser
from app.features.import_.parsers.custom_parser import CustomParser
from app.common.logging import get_logger

logger = get_logger(__name__)


class ParserFactory:
    """解析器工厂"""
    
    # 内置解析器注册表
    _parsers = [
        MarkdownParser(),
        JsonParser()
    ]
    
    @classmethod
    def get_parser(
        cls,
        filename: str,
        custom_parser: Optional[UploadFile] = None
    ) -> BaseDocumentParser:
        """
        根据文件名和可选的自定义解析器文件获取解析器
        
        Args:
            filename: 文件名（用于判断扩展名）
            custom_parser: 自定义解析器 Python 文件（可选）
        
        Returns:
            BaseDocumentParser: 解析器实例
        
        Raises:
            ParserError: 找不到合适的解析器
        """
        # 如果提供了自定义解析器
        if custom_parser:
            logger.warning(
                f"Custom parser provided for {filename}, "
                f"but not implemented in current version"
            )
            raise ParserError(
                "Custom parser is not supported in current version"
            )
        
        # 查找支持该文件的内置解析器
        for parser in cls._parsers:
            if parser.supports_file(filename):
                logger.debug(
                    f"Selected {parser.parser_name} for {filename}"
                )
                return parser
        
        # 找不到合适的解析器
        import os
        _, ext = os.path.splitext(filename)
        supported_exts = []
        for p in cls._parsers:
            supported_exts.extend(p.supported_extensions)
        
        raise ParserError(
            f"Unsupported file type '{ext}'. "
            f"Supported types: {', '.join(supported_exts)}"
        )
    
    @classmethod
    def register_parser(cls, parser: BaseDocumentParser):
        """
        注册自定义解析器（扩展点）
        
        Args:
            parser: 解析器实例
        """
        cls._parsers.append(parser)
        logger.info(f"Registered parser: {parser.parser_name}")


__all__ = [
    'BaseDocumentParser',
    'MarkdownParser',
    'JsonParser',
    'CustomParser',
    'ParserFactory',
    'ParserError'
]
```

#### 5.3.7 Parsers 与 Repository 的协作流程

**完整调用链**：

```
1. ImportService.create_import_job_with_files(...)
   ├─ 校验参数
   └─ 调用 _parse_files(files, library, use_vector, vector_model, custom_parser)

2. ImportService._parse_files(...)
   ├─ for file in files:
   │   ├─ 获取 Repository
   │   │   └─ repo = ImportRepositoryFactory.create(library, ...)
   │   │
   │   └─ 处理文件
   │       └─ documents = await repo.process_file(file, ..., custom_parser)
   │
   └─ 返回 (all_documents, parse_results)

3. Repository.process_file(file, ..., custom_parser)
   ├─ 调用 parse_document(file, custom_parser)
   │   └─ 委托给 Parser
   │
   ├─ 生成向量（可选）
   │   └─ VectorTool.generate_vector(...)
   │
   └─ 格式化为 OpenSearch 文档
       └─ format_for_opensearch(chunks, ...)

4. Repository.parse_document(file, custom_parser)
   ├─ 获取文件名
   ├─ 选择解析器
   │   └─ parser = ParserFactory.get_parser(filename, custom_parser)
   │       ├─ 如果提供了 custom_parser：返回 CustomParser（本切片抛出异常）
   │       └─ 否则：根据文件扩展名选择 MarkdownParser 或 JsonParser
   │
   └─ 执行解析
       └─ chunks = await parser.parse(file, filename)
```

**BaseImportRepository.parse_document 实现示例**：

```python
# app/features/import_/repositories/base.py (补充)
from app.features.import_.parsers import ParserFactory, ParserError

class BaseImportRepository(ABC):
    # ... 其他方法 ...
    
    async def parse_document(
        self, 
        file: UploadFile,
        custom_parser: UploadFile | None = None
    ) -> List[DocumentChunk]:
        """
        解析文档（默认实现：通过 ParserFactory 选择解析器）
        
        子类可以覆写此方法以实现特殊解析逻辑
        
        Args:
            file: 上传的文件
            custom_parser: 自定义解析器 Python 文件（可选）
        
        Returns:
            List[DocumentChunk]: 文档分块列表
        
        Raises:
            ParserError: 解析失败
        """
        filename = file.filename
        
        try:
            # 获取解析器
            parser = ParserFactory.get_parser(filename, custom_parser)
            
            # 执行解析
            chunks = await parser.parse(file, filename)
            
            logger.info(
                f"[{self.library_tag}] Parsed {filename}: "
                f"{len(chunks)} chunks"
            )
            
            return chunks
            
        except ParserError as e:
            logger.error(
                f"[{self.library_tag}] Failed to parse {filename}: {e}"
            )
            raise
```

**特定 Repository 可以覆写解析逻辑**：

```python
# app/features/import_/repositories/code.py
class CodeImportRepository(BaseImportRepository):
    library_tag: ClassVar[str] = "CODE"
    
    async def parse_document(
        self, 
        file: UploadFile,
        custom_parser: UploadFile | None = None
    ) -> List[DocumentChunk]:
        """
        代码仓储的特殊解析逻辑
        
        可以在这里添加代码特定的处理：
        - 提取函数签名
        - 识别编程语言
        - 解析文件路径结构
        """
        # 先使用默认解析器
        chunks = await super().parse_document(file, custom_parser)
        
        # 添加代码特定的元数据处理
        for chunk in chunks:
            # 尝试识别代码语言
            if '```' in chunk.content:
                # 提取代码块语言标识
                import re
                lang_match = re.search(r'```(\w+)', chunk.content)
                if lang_match:
                    chunk.metadata['code_language'] = lang_match.group(1)
            
            # 添加其他代码特定处理...
        
        return chunks
```

#### 5.3.8 错误处理流程

**Parsers 的错误处理**：

```
Parser.parse(file, filename)
│
├─ try:
│   ├─ 读取文件
│   ├─ 解析内容
│   └─ 返回 DocumentChunk 列表
│
└─ except:
    ├─ FileFormatError       → 文件格式错误（编码、JSON格式等）
    ├─ ContentValidationError → 内容结构不符合预期
    └─ ParserError           → 其他解析错误
```

**Repository 层的错误处理**：

```python
# app/features/import_/repositories/base.py
async def process_file(
    self,
    file: UploadFile,
    *,
    library: str,
    use_vector: bool,
    vector_model: str | None,
    custom_parser: UploadFile | None = None
) -> tuple[List[dict], Optional[str]]:
    """
    处理单个文件
    
    Returns:
        tuple[List[dict], Optional[str]]: (文档列表, 错误信息)
    """
    try:
        # 1. 解析文档
        chunks = await self.parse_document(file, custom_parser)
        
        # 2. 生成向量（可选）
        if use_vector and self.vector_tool:
            for chunk in chunks:
                text = f"{chunk.section_title}\n{chunk.content}"
                vector = await self.vector_tool.generate_vector(
                    text=text,
                    model=vector_model
                )
                chunk.metadata['vector'] = vector
        
        # 3. 格式化为 OpenSearch 文档
        documents = self.format_for_opensearch(
            chunks,
            library=library,
            use_vector=use_vector
        )
        
        return documents, None  # 成功，无错误
        
    except ParserError as e:
        # 解析错误
        logger.error(f"Parse error for {file.filename}: {e}")
        return [], str(e)
        
    except Exception as e:
        # 其他错误
        logger.error(
            f"Unexpected error processing {file.filename}: {e}",
            exc_info=True
        )
        return [], f"Unexpected error: {str(e)}"
```

**ImportService 层的错误聚合**：

```python
# app/features/import_/import_service.py
async def _parse_files(
    self,
    files: List[UploadFile],
    library: str,
    use_vector: bool,
    vector_model: str | None,
    custom_parser: UploadFile | None
) -> tuple[List[dict], dict]:
    """
    解析文件列表
    
    Returns:
        tuple[List[dict], dict]: (所有文档列表, 解析结果统计)
    """
    all_documents = []
    failed_files = []
    parsed_count = 0
    
    # 获取 Repository
    repo = ImportRepositoryFactory.create(
        library,
        opensearch_client=self.opensearch_client,
        vector_tool=self.vector_tool,
        config=self.config
    )
    
    # 处理每个文件
    for file in files:
        documents, error = await repo.process_file(
            file,
            library=library,
            use_vector=use_vector,
            vector_model=vector_model,
            custom_parser=custom_parser
        )
        
        if error:
            # 解析失败
            failed_files.append({
                'filename': file.filename,
                'error': error,
                'size_bytes': file.size
            })
        else:
            # 解析成功
            all_documents.extend(documents)
            parsed_count += 1
    
    # 构建解析结果
    parse_results = {
        'total_files': len(files),
        'parsed_files': parsed_count,
        'failed_files': len(failed_files),
        'failed_file_details': failed_files
    }
    
    # 如果所有文件都失败，抛出异常
    if parsed_count == 0:
        raise ValueError(
            f"All {len(files)} files failed to parse. "
            f"See details: {failed_files}"
        )
    
    return all_documents, parse_results
```

---

### 5.4 Celery 异步批量导入流程

**设计原则**：

Celery任务执行用户import的**完整任务**，包括：
1. 从临时目录读取文件
2. 解析文件
3. 生成向量（如果需要）
4. 导入到OpenSearch
5. 清理临时文件

这样设计的优点：
- API请求可以快速返回（只保存文件）
- 耗时的解析、向量化、导入都在后台异步执行
- 用户体验更好（不会因为大文件导致请求超时）

```
import_documents_task
│
├── 1. 更新任务状态
│   └── state='PROGRESS', meta={'job_id', 'status': 'reading_files', 'progress': 0}
│
├── 2. 从临时目录读取文件
│   ├── 读取 /tmp/bible_import/jobs/{job_id}/files/ 目录
│   ├── 读取 metadata.json 获取文件列表
│   └── 获取 library, vector_model, import_mode 等参数
│
├── 3. 解析文件
│   ├── 遍历每个文件
│   ├── 根据文件扩展名选择解析器（MarkdownParser / JsonParser）
│   ├── 解析为 DocumentChunk 列表
│   └── 更新进度: state='PROGRESS', status='parsing_files'
│
├── 4. 生成向量（如果 vector_model 不为空）
│   ├── 遍历每个 DocumentChunk
│   ├── 调用 VectorTool.generate_vector(text)
│   ├── 将向量存入 chunk.content_vector
│   └── 更新进度: state='PROGRESS', status='generating_vectors'
│
├── 5. 创建/更新 OpenSearch 索引
│   ├── IndexManager.ensure_index_exists(library)
│   └── 检测向量配置是否匹配
│
├── 6. import_mode 处理
│   ├── replace: 删除索引中该 library 所有文档
│   │   └── DELETE FROM index WHERE library = ?
│   └── append: 跳过删除
│
├── 7. 批量导入到 OpenSearch
│   ├── BulkImporter.bulk_insert(documents)
│   ├── 更新进度: 每批100个文档
│   │   └── state='PROGRESS', status='importing_to_es', progress=X%
│   └── 记录成功/失败统计
│
├── 8. 更新任务状态
│   └── Job 状态: importing -> completed
│
└── 9. 清理临时文件
    ├── ImportService._cleanup_job_files(job_id, keep_metadata=True)
    │   └── 删除 /tmp/bible_import/jobs/{job_id}/files/ 目录
    └── 保留 metadata.json 用于查询任务状态
```

**API层与Celery任务的职责划分**：

| 层次 | 职责 | 是否异步 |
|------|------|---------|
| **API层** | 1. 接收POST请求<br>2. 校验参数<br>3. 保存文件到临时目录<br>4. 提交Celery任务<br>5. 立即返回job_id | 同步（快速返回） |
| **Celery任务** | 1. 从临时目录读取文件<br>2. 解析文件<br>3. 生成向量<br>4. 导入OpenSearch<br>5. 清理临时文件 | 异步（后台执行） |

**清理流程说明**：

1. **立即清理**：任务完成时（成功或失败）清理上传的文件，保留元数据
2. **延迟清理**：定期任务 `cleanup_old_jobs` 清理超过 7 天的任务目录（包括元数据）
3. **异常恢复**：服务启动时检查并清理孤儿任务目录（超过1天且无任务记录）

---

## 6. Infrastructure 层接口设计

本章节详细说明基础设施层（infrastructure）各模块提供的 API 接口，供上层（Service 层、Repository 层）调用。

### 6.1 VectorTool（向量生成工具）

**文件位置**：`app/infrastructure/vector/vector_tool.py`

**职责**：
- 加载和管理向量模型
- 为文本内容生成向量 embeddings
- 模型缓存与生命周期管理

**类定义**：

```python
# app/infrastructure/vector/vector_tool.py
from typing import List, Optional, Dict, Any
from sentence_transformers import SentenceTransformer
from app.common.logging import get_logger
from app.config.config_manager import ConfigManager

logger = get_logger(__name__)


class VectorTool:
    """
    向量生成工具
    
    负责加载向量模型并生成文本 embeddings
    """
    
    def __init__(self, config: ConfigManager):
        """
        Args:
            config: 配置管理器，用于读取向量模型配置
        """
        self.config = config
        self._models: Dict[str, SentenceTransformer] = {}  # 模型缓存
        self._model_configs: Dict[str, Dict[str, Any]] = {}  # 模型配置缓存
        
        # 加载模型配置
        self._load_model_configs()
    
    def _load_model_configs(self):
        """从配置中加载模型配置"""
        models_config = self.config.get("vector_models.models", {})
        for model_name, model_info in models_config.items():
            self._model_configs[model_name] = model_info
            logger.info(
                f"Registered vector model: {model_name} "
                f"(dims={model_info.get('dims')})"
            )
    
    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        获取模型配置信息
        
        Args:
            model_name: 模型名称（如 "mpnet", "bge-large"）
        
        Returns:
            Dict: 模型配置信息，包含 model (模型路径) 和 dims (向量维度)
        
        Raises:
            ValueError: 模型不存在
        
        示例：
            >>> tool.get_model_info("mpnet")
            {
                "model": "paraphrase-multilingual-mpnet-base-v2",
                "dims": 768
            }
        """
        if model_name not in self._model_configs:
            available = list(self._model_configs.keys())
            raise ValueError(
                f"Unknown vector model '{model_name}'. "
                f"Available models: {available}"
            )
        return self._model_configs[model_name]
    
    def _load_model(self, model_name: str) -> SentenceTransformer:
        """
        加载向量模型（内部方法，带缓存）
        
        Args:
            model_name: 模型名称
        
        Returns:
            SentenceTransformer: 加载的模型实例
        
        Raises:
            ValueError: 模型不存在
            RuntimeError: 模型加载失败
        """
        # 检查缓存
        if model_name in self._models:
            return self._models[model_name]
        
        # 获取模型配置
        model_info = self.get_model_info(model_name)
        model_path = model_info["model"]
        
        try:
            logger.info(f"Loading vector model: {model_path}")
            model = SentenceTransformer(model_path)
            self._models[model_name] = model
            logger.info(f"Vector model loaded: {model_name}")
            return model
            
        except Exception as e:
            logger.error(f"Failed to load vector model {model_name}: {e}")
            raise RuntimeError(
                f"Failed to load vector model '{model_name}': {e}"
            )
    
    async def generate_vector(
        self, 
        text: str, 
        model: str
    ) -> List[float]:
        """
        为文本生成向量 embedding
        
        Args:
            text: 输入文本
            model: 模型名称（如 "mpnet", "bge-large"）
        
        Returns:
            List[float]: 向量列表，长度由模型决定（如 mpnet 为 768 维）
        
        Raises:
            ValueError: 模型不存在或文本为空
            RuntimeError: 向量生成失败
        
        示例：
            >>> vector = await tool.generate_vector("Hello world", "mpnet")
            >>> len(vector)
            768
            >>> isinstance(vector[0], float)
            True
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        if not model:
            raise ValueError("Model name is required")
        
        try:
            # 加载模型
            model_instance = self._load_model(model)
            
            # 生成向量
            embedding = model_instance.encode(
                text,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            
            # 转换为列表
            vector = embedding.tolist()
            
            logger.debug(
                f"Generated vector for text (len={len(text)}): "
                f"dims={len(vector)}"
            )
            
            return vector
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to generate vector: {e}", exc_info=True)
            raise RuntimeError(f"Vector generation failed: {e}")
    
    async def generate_vectors_batch(
        self,
        texts: List[str],
        model: str,
        batch_size: int = 32
    ) -> List[List[float]]:
        """
        批量生成向量（性能优化）
        
        Args:
            texts: 文本列表
            model: 模型名称
            batch_size: 批次大小
        
        Returns:
            List[List[float]]: 向量列表，顺序与输入文本对应
        
        Raises:
            ValueError: 模型不存在或文本列表为空
            RuntimeError: 向量生成失败
        
        示例：
            >>> texts = ["Text 1", "Text 2", "Text 3"]
            >>> vectors = await tool.generate_vectors_batch(texts, "mpnet")
            >>> len(vectors)
            3
            >>> len(vectors[0])
            768
        """
        if not texts:
            raise ValueError("Text list cannot be empty")
        
        try:
            # 加载模型
            model_instance = self._load_model(model)
            
            # 批量生成向量
            embeddings = model_instance.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            
            # 转换为列表
            vectors = [emb.tolist() for emb in embeddings]
            
            logger.info(
                f"Generated {len(vectors)} vectors using {model} "
                f"(batch_size={batch_size})"
            )
            
            return vectors
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to generate batch vectors: {e}", exc_info=True)
            raise RuntimeError(f"Batch vector generation failed: {e}")
    
    def get_vector_dims(self, model: str) -> int:
        """
        获取模型的向量维度
        
        Args:
            model: 模型名称
        
        Returns:
            int: 向量维度
        
        Raises:
            ValueError: 模型不存在
        
        示例：
            >>> tool.get_vector_dims("mpnet")
            768
            >>> tool.get_vector_dims("bge-m3")
            1024
        """
        model_info = self.get_model_info(model)
        return model_info["dims"]
    
    def unload_model(self, model_name: str):
        """
        卸载已加载的模型（释放内存）
        
        Args:
            model_name: 模型名称
        """
        if model_name in self._models:
            del self._models[model_name]
            logger.info(f"Unloaded vector model: {model_name}")
    
    def unload_all_models(self):
        """卸载所有已加载的模型"""
        self._models.clear()
        logger.info("Unloaded all vector models")
```

**API 总结**：

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `get_model_info(model_name)` | `str` | `Dict[str, Any]` | 获取模型配置信息（model 路径和 dims 维度） |
| `generate_vector(text, model)` | `str, str` | `List[float]` | 为单个文本生成向量 embedding |
| `generate_vectors_batch(texts, model, batch_size)` | `List[str], str, int` | `List[List[float]]` | 批量生成向量（性能优化） |
| `get_vector_dims(model)` | `str` | `int` | 获取模型的向量维度 |
| `unload_model(model_name)` | `str` | `None` | 卸载指定模型（释放内存） |
| `unload_all_models()` | - | `None` | 卸载所有模型 |

**Repository 层调用示例**：

```python
# app/features/import_/repositories/base.py
class BaseImportRepository:
    def __init__(self, vector_tool: VectorTool, ...):
        self.vector_tool = vector_tool
    
    async def process_file(self, file, *, use_vector, vector_model, ...):
        if use_vector and self.vector_tool:
            # 单个文本生成向量
            vector = await self.vector_tool.generate_vector(
                text="Some content",
                model=vector_model
            )
            # vector 是 List[float]，如 [0.123, -0.456, ...]
            
            # 批量生成向量（性能更好）
            texts = ["Text 1", "Text 2", "Text 3"]
            vectors = await self.vector_tool.generate_vectors_batch(
                texts=texts,
                model=vector_model,
                batch_size=32
            )
            # vectors 是 List[List[float]]
```

---

### 6.2 OpenSearch 客户端与索引管理

**文件位置**：
- `app/infrastructure/opensearch/client.py` - OpenSearch 客户端
- `app/infrastructure/opensearch/index_manager.py` - 索引管理
- `app/infrastructure/opensearch/bulk_importer.py` - 批量导入工具

#### 6.2.1 OpenSearchClient（客户端）

**职责**：
- 管理 OpenSearch 连接
- 提供基础的 CRUD 操作
- 健康检查与连接池管理

**类定义**：

```python
# app/infrastructure/opensearch/client.py
from opensearchpy import OpenSearch, AsyncOpenSearch
from typing import Dict, List, Any, Optional
from app.common.logging import get_logger
from app.config.config_manager import ConfigManager

logger = get_logger(__name__)


class OpenSearchClient:
    """
    OpenSearch 客户端
    
    负责管理 OpenSearch 连接和基础操作
    """
    
    def __init__(self, config: ConfigManager):
        """
        Args:
            config: 配置管理器
        """
        self.config = config
        self._client: Optional[AsyncOpenSearch] = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化 OpenSearch 客户端"""
        hosts = self.config.get("opensearch.hosts", ["http://localhost:9200"])
        timeout = self.config.get("opensearch.timeout", 30)
        max_retries = self.config.get("opensearch.max_retries", 3)
        
        self._client = AsyncOpenSearch(
            hosts=hosts,
            timeout=timeout,
            max_retries=max_retries,
            retry_on_timeout=True
        )
        
        logger.info(f"OpenSearch client initialized: {hosts}")
    
    @property
    def client(self) -> AsyncOpenSearch:
        """获取底层 OpenSearch 客户端实例"""
        return self._client
    
    async def ping(self) -> bool:
        """
        检查 OpenSearch 连接是否正常
        
        Returns:
            bool: 连接正常返回 True，否则返回 False
        
        示例：
            >>> is_healthy = await client.ping()
            >>> print(is_healthy)
            True
        """
        try:
            return await self._client.ping()
        except Exception as e:
            logger.error(f"OpenSearch ping failed: {e}")
            return False
    
    async def get_cluster_health(self) -> Dict[str, Any]:
        """
        获取集群健康状态
        
        Returns:
            Dict: 集群健康信息
        
        示例：
            >>> health = await client.get_cluster_health()
            >>> print(health["status"])
            "green"
        """
        return await self._client.cluster.health()
    
    async def index_exists(self, index_name: str) -> bool:
        """
        检查索引是否存在
        
        Args:
            index_name: 索引名称
        
        Returns:
            bool: 索引存在返回 True
        
        示例:
            >>> exists = await client.index_exists("bible_code")
            >>> print(exists)
            True
        """
        return await self._client.indices.exists(index=index_name)
    
    async def create_index(
        self,
        index_name: str,
        mappings: Dict[str, Any],
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        创建索引
        
        Args:
            index_name: 索引名称
            mappings: 字段映射定义
            settings: 索引设置（可选）
        
        Returns:
            Dict: 创建结果
        
        Raises:
            RuntimeError: 索引创建失败
        
        示例：
            >>> mappings = {
            ...     "properties": {
            ...         "content": {"type": "text"},
            ...         "content_vector": {
            ...             "type": "knn_vector",
            ...             "dimension": 768
            ...         }
            ...     }
            ... }
            >>> result = await client.create_index("bible_code", mappings)
        """
        try:
            body = {"mappings": mappings}
            if settings:
                body["settings"] = settings
            
            result = await self._client.indices.create(
                index=index_name,
                body=body
            )
            
            logger.info(f"Created index: {index_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            raise RuntimeError(f"Index creation failed: {e}")
    
    async def delete_index(self, index_name: str) -> Dict[str, Any]:
        """
        删除索引
        
        Args:
            index_name: 索引名称
        
        Returns:
            Dict: 删除结果
        
        示例：
            >>> result = await client.delete_index("bible_code")
        """
        return await self._client.indices.delete(index=index_name)
    
    async def get_index_mapping(self, index_name: str) -> Dict[str, Any]:
        """
        获取索引映射
        
        Args:
            index_name: 索引名称
        
        Returns:
            Dict: 索引映射定义
        """
        return await self._client.indices.get_mapping(index=index_name)
    
    async def close(self):
        """关闭客户端连接"""
        if self._client:
            await self._client.close()
            logger.info("OpenSearch client closed")
```

#### 6.2.2 IndexManager（索引管理）

**职责**：
- 管理不同 library 的索引创建
- 定义索引的 mappings 和 settings
- 索引存在性检查与自动创建

**类定义**：

```python
# app/infrastructure/opensearch/index_manager.py
from typing import Dict, Any
from app.infrastructure.opensearch.client import OpenSearchClient
from app.common.logging import get_logger

logger = get_logger(__name__)


class IndexManager:
    """
    OpenSearch 索引管理器
    
    负责创建和管理不同 library 的索引
    """
    
    # 索引名称模板
    INDEX_PREFIX = "bible"
    
    def __init__(self, client: OpenSearchClient):
        """
        Args:
            client: OpenSearch 客户端
        """
        self.client = client
    
    @staticmethod
    def get_index_name(library: str) -> str:
        """
        获取 library 对应的索引名称
        
        Args:
            library: 知识库名称（如 "CODE", "DESIGN"）
        
        Returns:
            str: 索引名称（如 "bible_code", "bible_design"）
        
        示例：
            >>> IndexManager.get_index_name("CODE")
            "bible_code"
        """
        return f"{IndexManager.INDEX_PREFIX}_{library.lower()}"
    
    def get_default_mappings(
        self,
        use_vector: bool = False,
        vector_dims: int = 768
    ) -> Dict[str, Any]:
        """
        获取默认的索引映射
        
        Args:
            use_vector: 是否包含向量字段
            vector_dims: 向量维度
        
        Returns:
            Dict: mappings 定义
        
        示例：
            >>> mappings = manager.get_default_mappings(use_vector=True, vector_dims=768)
        """
        properties = {
            "doc_id": {"type": "keyword"},
            "library": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "section_id": {"type": "keyword"},
            "section_title": {"type": "text"},
            "content": {
                "type": "text",
                "analyzer": "standard"
            },
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False}
        }
        
        # 如果使用向量，添加向量字段
        if use_vector:
            properties["content_vector"] = {
                "type": "knn_vector",
                "dimension": vector_dims,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib"
                }
            }
        
        return {"properties": properties}
    
    def get_default_settings(self) -> Dict[str, Any]:
        """
        获取默认的索引设置
        
        Returns:
            Dict: settings 定义
        """
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "knn": True  # 启用 k-NN 搜索
            }
        }
    
    async def ensure_index_exists(
        self,
        library: str,
        use_vector: bool = False,
        vector_dims: int = 768
    ) -> str:
        """
        确保索引存在，如果不存在则创建
        
        Args:
            library: 知识库名称
            use_vector: 是否使用向量
            vector_dims: 向量维度
        
        Returns:
            str: 索引名称
        
        Raises:
            RuntimeError: 索引创建失败
        
        示例：
            >>> index_name = await manager.ensure_index_exists(
            ...     library="CODE",
            ...     use_vector=True,
            ...     vector_dims=768
            ... )
            >>> print(index_name)
            "bible_code"
        """
        index_name = self.get_index_name(library)
        
        # 检查索引是否存在
        exists = await self.client.index_exists(index_name)
        
        if exists:
            logger.info(f"Index already exists: {index_name}")
            return index_name
        
        # 创建索引
        logger.info(f"Creating index: {index_name}")
        mappings = self.get_default_mappings(use_vector, vector_dims)
        settings = self.get_default_settings()
        
        await self.client.create_index(
            index_name=index_name,
            mappings=mappings,
            settings=settings
        )
        
        logger.info(f"Index created: {index_name}")
        return index_name
    
    async def delete_library_documents(
        self,
        library: str
    ) -> Dict[str, Any]:
        """
        删除指定 library 的所有文档（用于 replace 模式）
        
        Args:
            library: 知识库名称
        
        Returns:
            Dict: 删除结果统计
        
        示例：
            >>> result = await manager.delete_library_documents("CODE")
            >>> print(result["deleted"])
            23
        """
        index_name = self.get_index_name(library)
        
        # 使用 delete_by_query 删除所有匹配的文档
        result = await self.client.client.delete_by_query(
            index=index_name,
            body={
                "query": {
                    "match_all": {}
                }
            }
        )
        
        deleted_count = result.get("deleted", 0)
        logger.info(
            f"Deleted {deleted_count} documents from {index_name}"
        )
        
        return result
```

#### 6.2.3 BulkImporter（批量导入）

**职责**：
- 批量插入文档到 OpenSearch
- 处理批量操作的错误
- 进度追踪与统计

**类定义**：

```python
# app/infrastructure/opensearch/bulk_importer.py
from typing import List, Dict, Any, Callable, Optional
from opensearchpy import helpers
from app.infrastructure.opensearch.client import OpenSearchClient
from app.common.logging import get_logger

logger = get_logger(__name__)


class BulkImporter:
    """
    OpenSearch 批量导入工具
    
    负责高效地批量插入文档
    """
    
    def __init__(
        self,
        client: OpenSearchClient,
        batch_size: int = 100,
        max_retries: int = 3
    ):
        """
        Args:
            client: OpenSearch 客户端
            batch_size: 每批文档数量
            max_retries: 失败重试次数
        """
        self.client = client
        self.batch_size = batch_size
        self.max_retries = max_retries
    
    async def bulk_insert(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        批量插入文档
        
        Args:
            index_name: 索引名称
            documents: 文档列表，每个文档包含 doc_id 和其他字段
            progress_callback: 进度回调函数 (已处理数, 总数)
        
        Returns:
            Dict: 导入统计信息
            {
                "total": 总文档数,
                "successful": 成功数,
                "failed": 失败数,
                "errors": 错误详情列表
            }
        
        Raises:
            RuntimeError: 批量导入失败
        
        示例：
            >>> documents = [
            ...     {"doc_id": "1", "content": "Text 1", ...},
            ...     {"doc_id": "2", "content": "Text 2", ...}
            ... ]
            >>> result = await importer.bulk_insert(
            ...     index_name="bible_code",
            ...     documents=documents,
            ...     progress_callback=lambda done, total: print(f"{done}/{total}")
            ... )
            >>> print(result["successful"])
            2
        """
        if not documents:
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "errors": []
            }
        
        total = len(documents)
        successful = 0
        failed = 0
        errors = []
        
        logger.info(
            f"Starting bulk insert: {total} documents to {index_name}"
        )
        
        try:
            # 准备批量操作
            actions = []
            for doc in documents:
                action = {
                    "_index": index_name,
                    "_id": doc.get("doc_id"),
                    "_source": doc
                }
                actions.append(action)
            
            # 执行批量插入
            success_count, errors_list = await helpers.async_bulk(
                client=self.client.client,
                actions=actions,
                chunk_size=self.batch_size,
                max_retries=self.max_retries,
                raise_on_error=False,  # 不因单个错误停止
                stats_only=False  # 返回错误详情
            )
            
            successful = success_count
            failed = total - successful
            
            # 解析错误
            if errors_list:
                for error in errors_list:
                    errors.append({
                        "doc_id": error.get("index", {}).get("_id"),
                        "error": str(error.get("index", {}).get("error"))
                    })
            
            # 进度回调
            if progress_callback:
                progress_callback(successful, total)
            
            logger.info(
                f"Bulk insert completed: "
                f"{successful} successful, {failed} failed"
            )
            
            return {
                "total": total,
                "successful": successful,
                "failed": failed,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Bulk insert failed: {e}", exc_info=True)
            raise RuntimeError(f"Bulk insert operation failed: {e}")
    
    async def bulk_update(
        self,
        index_name: str,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        批量更新文档
        
        Args:
            index_name: 索引名称
            updates: 更新列表，每个包含 doc_id 和要更新的字段
        
        Returns:
            Dict: 更新统计信息
        
        示例：
            >>> updates = [
            ...     {"doc_id": "1", "updated_at": "2026-04-14T10:00:00"},
            ...     {"doc_id": "2", "updated_at": "2026-04-14T10:00:00"}
            ... ]
            >>> result = await importer.bulk_update("bible_code", updates)
        """
        if not updates:
            return {"total": 0, "successful": 0, "failed": 0}
        
        actions = []
        for update in updates:
            doc_id = update.pop("doc_id")
            action = {
                "_op_type": "update",
                "_index": index_name,
                "_id": doc_id,
                "doc": update
            }
            actions.append(action)
        
        success_count, errors = await helpers.async_bulk(
            client=self.client.client,
            actions=actions,
            chunk_size=self.batch_size,
            raise_on_error=False
        )
        
        return {
            "total": len(updates),
            "successful": success_count,
            "failed": len(updates) - success_count
        }
```

**API 总结**：

| 类 | 方法 | 参数 | 返回值 | 说明 |
|----|------|------|--------|------|
| **OpenSearchClient** | `ping()` | - | `bool` | 检查连接健康状态 |
| | `index_exists(index_name)` | `str` | `bool` | 检查索引是否存在 |
| | `create_index(index_name, mappings, settings)` | `str, Dict, Dict` | `Dict` | 创建索引 |
| | `delete_index(index_name)` | `str` | `Dict` | 删除索引 |
| **IndexManager** | `get_index_name(library)` | `str` | `str` | 获取索引名称 |
| | `ensure_index_exists(library, use_vector, vector_dims)` | `str, bool, int` | `str` | 确保索引存在 |
| | `delete_library_documents(library)` | `str` | `Dict` | 删除 library 所有文档 |
| **BulkImporter** | `bulk_insert(index_name, documents, progress_callback)` | `str, List[Dict], Callable` | `Dict` | 批量插入文档 |
| | `bulk_update(index_name, updates)` | `str, List[Dict]` | `Dict` | 批量更新文档 |

---

### 6.3 Celery 任务定义

**文件位置**：`app/infrastructure/celery/tasks.py`

**职责**：
- 定义异步任务
- 执行批量导入到 OpenSearch
- 任务进度追踪与错误处理

**任务定义**：

```python
# app/infrastructure/celery/tasks.py
from celery import Task
from typing import List, Dict, Any
from app.infrastructure.celery.app import celery_app
from app.infrastructure.opensearch.client import OpenSearchClient
from app.infrastructure.opensearch.index_manager import IndexManager
from app.infrastructure.opensearch.bulk_importer import BulkImporter
from app.config.config_manager import get_config_manager
from app.common.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="import_documents_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def import_documents_task(
    self: Task,
    job_id: str,
    library: str,
    vector_model: str | None,
    import_mode: str
) -> Dict[str, Any]:
    """
    异步导入文档任务 - 执行完整的导入流程
    
    这个任务执行用户import的**完整任务**，包括：
    1. 从临时目录读取文件
    2. 解析文件为文档
    3. 生成向量（如果需要）
    4. 导入到OpenSearch
    5. 清理临时文件
    
    Args:
        self: Celery Task 实例（bind=True自动注入）
        job_id: 任务ID（用于定位临时目录）
        library: 知识库名称（CODE/SCT/BUILD等）
        vector_model: 向量模型名称（mini/mpnet/bge-base等），None表示不使用向量
        import_mode: 导入模式（"replace" 或 "append"）
    
    Returns:
        Dict: 导入结果
        {
            "job_id": 任务ID,
            "status": 状态（"completed" 或 "failed"）,
            "total_documents": 总文档数,
            "successful": 成功数,
            "failed": 失败数,
            "parse_results": 解析结果,
            "errors": 错误详情（如果有）
        }
    
    Raises:
        Exception: 导入失败时重试
    
    使用示例：
        >>> # 在 ImportService 中调用（API层保存完文件后）
        >>> from app.infrastructure.celery.tasks import import_documents_task
        >>> task = import_documents_task.delay(
        ...     job_id="import_20260415_001",
        ...     library="CODE",
        ...     vector_model="mpnet",
        ...     import_mode="replace"
        ... )
        >>> # 获取任务状态
        >>> task.state  # 'PENDING', 'STARTED', 'SUCCESS', 'FAILURE'
        >>> # 获取结果
        >>> result = task.get(timeout=300)
    
    临时目录结构：
        /tmp/bible_import/jobs/{job_id}/
        ├── files/
        │   ├── doc1.md
        │   ├── doc2.json
        │   └── custom_parser.py
        └── metadata.json
    """
    logger.info(
        f"Starting import task: job_id={job_id}, "
        f"library={library}, vector_model={vector_model}, "
        f"mode={import_mode}"
    )
    
    # 导入依赖
    from app.features.import_.import_service import ImportService
    from app.features.import_.dependencies import get_import_service
    from pathlib import Path
    import json
    
    try:
        # ========== 步骤1: 读取任务元数据 (0-5%) ==========
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id,
                'status': 'reading_files',
                'progress': 0,
                'stage': 'reading_metadata'
            }
        )
        
        # 读取临时目录
        config = get_config_manager()
        temp_dir = Path(config.get("import_.temp_dir", "/tmp/bible_import"))
        job_dir = temp_dir / "jobs" / job_id
        metadata_file = job_dir / "metadata.json"
        
        if not metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {metadata_file}")
        
        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        file_names = metadata.get("files", [])
        logger.info(f"Task {job_id}: Found {len(file_names)} files in metadata")
        
        # ========== 步骤2: 解析文件 (5-30%) ==========
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id,
                'status': 'parsing_files',
                'progress': 5,
                'stage': 'parsing',
                'total_files': len(file_names)
            }
        )
        
        # 获取ImportService实例（通过工厂函数）
        import_service = get_import_service()
        
        # 解析文件（从临时目录读取）
        files_dir = job_dir / "files"
        file_paths = {
            name: str(files_dir / name) 
            for name in file_names 
            if not name.startswith("_")  # 排除 _custom_parser
        }
        
        # 调用Service的解析方法
        documents, parse_results = await import_service._parse_files_from_disk(
            job_id=job_id,
            file_paths=file_paths,
            library=library,
            vector_model=vector_model
        )
        
        total_documents = len(documents)
        logger.info(
            f"Task {job_id}: Parsed {total_documents} documents, "
            f"success={parse_results['parsed_files']}, "
            f"failed={parse_results['failed_files']}"
        )
        
        # ========== 步骤3: 生成向量 (30-60%) ==========
        if vector_model and vector_model != 'none':
            self.update_state(
                state='PROGRESS',
                meta={
                    'job_id': job_id,
                    'status': 'generating_vectors',
                    'progress': 30,
                    'stage': 'vectorizing',
                    'total_documents': total_documents
                }
            )
            
            # 向量生成在解析阶段已经完成（在Repository中）
            # 这里只是更新进度
            logger.info(f"Task {job_id}: Vectors already generated during parsing")
        
        # ========== 步骤4: 导入OpenSearch (60-95%) ==========
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id,
                'status': 'importing_to_es',
                'progress': 60,
                'stage': 'importing'
            }
        )
        
        # 初始化基础设施
        config = get_config_manager()
        opensearch_client = OpenSearchClient(config)
        index_manager = IndexManager(opensearch_client)
        bulk_importer = BulkImporter(
            opensearch_client,
            batch_size=config.get("opensearch.bulk_size", 100)
        )
        
        # 检测向量配置
        use_vector = False
        vector_dims = 768
        if documents and "content_vector" in documents[0]:
            use_vector = True
            vector_dims = len(documents[0]["content_vector"])
        
        # 确保索引存在
        index_name = await index_manager.ensure_index_exists(
            library=library,
            use_vector=use_vector,
            vector_dims=vector_dims
        )
        
        # 处理 replace 模式
        if import_mode == "replace":
            logger.info(f"Deleting existing documents for {library}")
            await index_manager.delete_library_documents(library)
        
        # 批量导入
        def progress_callback(done, total):
            self.update_state(
                state='PROGRESS',
                meta={
                    'job_id': job_id,
                    'status': 'importing',
                    'progress': done,
                    'total': total
                }
            )
        
        result = await bulk_importer.bulk_insert(
            index_name=index_name,
            documents=documents,
            progress_callback=progress_callback
        )
        
        # 关闭连接
        await opensearch_client.close()
        
        # 清理临时文件（保留元数据）
        service = get_import_service()
        service._cleanup_job_files(job_id, keep_metadata=True)
        logger.info(f"Cleaned up temporary files for job {job_id}")
        
        # 构造返回结果
        import_result = {
            "job_id": job_id,
            "status": "completed" if result["failed"] == 0 else "partial",
            "total_documents": result["total"],
            "successful": result["successful"],
            "failed": result["failed"],
            "errors": result["errors"][:10] if result["errors"] else []  # 最多返回10个错误
        }
        
        logger.info(
            f"Import task completed: job_id={job_id}, "
            f"successful={result['successful']}, failed={result['failed']}"
        )
        
        return import_result
        
    except Exception as e:
        logger.error(
            f"Import task failed: job_id={job_id}, error={e}",
            exc_info=True
        )
        
        # 清理临时文件（即使失败也清理，保留元数据）
        try:
            service = get_import_service()
            service._cleanup_job_files(job_id, keep_metadata=True)
            logger.info(f"Cleaned up temporary files for failed job {job_id}")
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup job {job_id}: {cleanup_error}")
        
        # 重试逻辑
        if self.request.retries < self.max_retries:
            logger.info(
                f"Retrying import task: job_id={job_id}, "
                f"attempt={self.request.retries + 1}"
            )
            raise self.retry(exc=e)
        
        # 最终失败
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(e),
            "total_documents": len(documents),
            "successful": 0,
            "failed": len(documents)
        }


@celery_app.task(name="cleanup_old_jobs")
def cleanup_old_jobs(days: int = 7) -> Dict[str, Any]:
    """
    清理过期的任务记录
    
    Args:
        days: 保留天数，默认7天
    
    Returns:
        Dict: 清理统计
        {
            "deleted_count": 删除的任务数,
            "deleted_jobs": 删除的任务ID列表
        }
    
    使用示例：
        >>> # 在定时任务中调用
        >>> from app.infrastructure.celery.tasks import cleanup_old_jobs
        >>> cleanup_old_jobs.delay(days=7)
    """
    from datetime import datetime, timedelta
    from pathlib import Path
    import shutil
    import json
    
    logger.info(f"Starting cleanup: removing jobs older than {days} days")
    
    config = get_config_manager()
    temp_dir = Path(config.get("import_.temp_dir", "/tmp/bible_import"))
    jobs_dir = temp_dir / "jobs"
    
    if not jobs_dir.exists():
        logger.info("Jobs directory not found, nothing to cleanup")
        return {"deleted_count": 0, "deleted_jobs": []}
    
    deleted_count = 0
    deleted_jobs = []
    cutoff_time = datetime.now() - timedelta(days=days)
    
    try:
        # 遍历所有任务目录
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            
            job_id = job_dir.name
            metadata_file = job_dir / "metadata.json"
            
            # 检查是否过期
            should_delete = False
            
            if metadata_file.exists():
                # 读取元数据检查创建时间
                try:
                    with open(metadata_file, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                    
                    created_at_str = metadata.get("created_at")
                    if created_at_str:
                        created_at = datetime.fromisoformat(created_at_str)
                        if created_at < cutoff_time:
                            should_delete = True
                except Exception as e:
                    logger.warning(
                        f"Failed to read metadata for {job_id}: {e}"
                    )
                    # 元数据损坏，检查目录修改时间
                    if datetime.fromtimestamp(job_dir.stat().st_mtime) < cutoff_time:
                        should_delete = True
            else:
                # 无元数据的孤儿目录，检查是否超过1天
                one_day_ago = datetime.now() - timedelta(days=1)
                if datetime.fromtimestamp(job_dir.stat().st_mtime) < one_day_ago:
                    should_delete = True
                    logger.warning(
                        f"Found orphan job directory: {job_id}"
                    )
            
            # 删除过期任务目录
            if should_delete:
                try:
                    shutil.rmtree(job_dir)
                    deleted_count += 1
                    deleted_jobs.append(job_id)
                    logger.info(f"Deleted expired job: {job_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to delete job {job_id}: {e}",
                        exc_info=True
                    )
        
        logger.info(
            f"Cleanup completed: deleted {deleted_count} jobs"
        )
        
        return {
            "deleted_count": deleted_count,
            "deleted_jobs": deleted_jobs
        }
    
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        return {
            "deleted_count": deleted_count,
            "deleted_jobs": deleted_jobs,
            "error": str(e)
        }
```

**Celery 任务 API 总结**：

| 任务名称 | 参数 | 返回值 | 说明 |
|---------|------|--------|------|
| `import_documents_task` | `job_id: str`<br>`documents: List[Dict]`<br>`library: str`<br>`import_mode: str` | `Dict[str, Any]` | 异步批量导入文档到 OpenSearch |
| `cleanup_old_jobs` | `days: int` | `Dict[str, Any]` | 清理过期任务记录 |

**Service 层调用示例**：

```python
# app/features/import_/import_service.py
class ImportService:
    def _submit_import_task(
        self,
        job_id: str,
        documents: List[dict],
        library: str,
        import_mode: str
    ):
        """提交 Celery 异步导入任务"""
        from app.infrastructure.celery.tasks import import_documents_task
        
        # 提交任务
        task = import_documents_task.delay(
            job_id=job_id,
            documents=documents,
            library=library,
            import_mode=import_mode
        )
        
        logger.info(
            f"Submitted import task: job_id={job_id}, "
            f"celery_task_id={task.id}"
        )
        
        return task.id
```

---

### 6.4 Infrastructure 层依赖注入

**文件位置**：`app/features/import_/dependencies.py`

**推荐的依赖装配**：

```python
# app/features/import_/dependencies.py
from app.infrastructure.opensearch.client import OpenSearchClient
from app.infrastructure.opensearch.index_manager import IndexManager
from app.infrastructure.opensearch.bulk_importer import BulkImporter
from app.infrastructure.vector.vector_tool import VectorTool
from app.infrastructure.celery.app import celery_app
from app.config.config_manager import get_config_manager
from app.features.import_.import_service import ImportService


def get_import_service() -> ImportService:
    """
    获取 ImportService 实例（依赖注入）
    
    装配顺序：
    1. ConfigManager
    2. OpenSearchClient
    3. VectorTool
    4. CeleryApp
    5. ImportService
    """
    # 1. 配置管理器
    config = get_config_manager()
    
    # 2. OpenSearch 客户端
    opensearch_client = OpenSearchClient(config)
    
    # 3. 向量工具（可选）
    vector_model = config.get("vector_models.default")
    vector_tool = VectorTool(config) if vector_model else None
    
    # 4. Celery 应用
    celery = celery_app
    
    # 5. ImportService
    service = ImportService(
        opensearch_client=opensearch_client,
        vector_tool=vector_tool,
        celery_app=celery,
        config=config
    )
    
    return service
```

---

## 7. 配置依赖

| 配置路径 | 用途 |
|----------|------|
| `import_.valid_libraries` | 有效知识库列表，验证 `library` 参数 |
| `import_.max_files_per_request` | 单次请求最大文件数 |
| `import_.max_file_size` | 单文件最大大小（字节） |
| `import_.supported_file_types` | 支持的文件类型列表，如 `['.md', '.json']` |
| `import_.temp_dir` | 临时文件存储目录，默认 `/tmp/bible_import` |
| `import_.cleanup_days` | 任务记录保留天数，默认 7 天 |
| `vector_models.models` | 向量模型配置，包含模型名称、维度等信息 |
| `vector_models.default` | 默认向量模型 |
| `opensearch.hosts` | OpenSearch 连接地址（当前方案） |
| `opensearch.timeout` | OpenSearch 连接超时 |
| `opensearch.bulk_size` | 批量导入每批文档数 |
| `postgres.connection_string` | PostgreSQL 连接字符串（备选方案，本切片不用） |
| `celery.broker_url` | Celery broker 地址 |
| `celery.result_backend` | Celery result backend 地址 |

**配置示例**（`config/dynamic_config.yaml`）：

```yaml
# 导入配置
import_:
  valid_libraries:
    - CODE
    - SCT
    - BUILD
    - SYNTAX
    - SPEC
    - ALG
    - DESIGN
    - FLOW
    # SESSION 和 SKILL 暂不支持
  max_files_per_request: 10
  max_file_size: 10485760  # 10MB
  supported_file_types:
    - .md
    - .json
  temp_dir: /tmp/bible_import  # 临时文件存储目录
  cleanup_days: 7              # 任务记录保留天数

# 向量模型配置
vector_models:
  models:
    mini:
      model: "paraphrase-multilingual-MiniLM-L12-v2"
      dims: 384
    mpnet:
      model: "paraphrase-multilingual-mpnet-base-v2"
      dims: 768
    bge-base:
      model: "BAAI/bge-base-zh-v1.5"
      dims: 768
    bge-large:
      model: "BAAI/bge-large-zh-v1.5"
      dims: 1024
    bge-m3:
      model: "BAAI/bge-m3"
      dims: 1024
    e5-large:
      model: "intfloat/multilingual-e5-large"
      dims: 1024
  default: mpnet

# OpenSearch 配置（当前方案）
opensearch:
  hosts:
    - http://localhost:9200
  timeout: 30
  max_retries: 3
  bulk_size: 100  # 批量导入每批文档数

# PostgreSQL 配置（备选方案，本切片不使用）
# postgres:
#   connection_string: "postgresql://user:pass@localhost:5432/bible_db"
#   pool_size: 10

# Celery 配置
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/1"
```

---

## 8. 实现检查清单（本切片交付）

**API 层**：
- [ ] `import_api.py` 实现 `POST /api/v1/import/jobs`（创建导入任务）。
- [ ] `import_api.py` 实现 `GET /api/v1/import/jobs/{job_id}`（查询任务状态）。
- [ ] API 层仅依赖 `ImportService` 和 schemas，异常映射符合 API 参考文档。
- [ ] 实现 `ImportJobStatusResponse` 模型（包含所有必需字段）。

**Service 层**：
- [ ] `ImportService` **通过依赖注入** 使用 `OpenSearchClient`、`VectorTool`、`CeleryApp`；**不**在 Service 层 `new` 数据库客户端或向量模型。
- [ ] `create_import_job_with_files` 在最前校验 library，SESSION/SKILL 短路返回 400。
- [ ] `create_import_job_with_files` 创建任务元数据文件（包含所有必需字段）。
- [ ] `create_import_job_with_files` 在提交 Celery 任务后更新元数据（celery_task_id、started_at）。
- [ ] `get_job_status` 从元数据文件读取任务信息。
- [ ] `get_job_status` 查询 Celery 任务状态并映射到业务状态。
- [ ] `get_job_status` 返回统一的 `ImportJobStatusResponse`。
- [ ] `_create_job_metadata` 创建初始任务元数据文件。
- [ ] `_update_job_metadata` 支持部分更新元数据字段。
- [ ] `_save_uploaded_files` 保存文件到临时目录（`/tmp/bible_import/jobs/{job_id}/files/`）。
- [ ] `_parse_files` 从临时目录读取文件并解析，支持 `.md` 和 `.json` 格式，记录失败文件详情。
- [ ] `_submit_import_task` 返回 Celery 任务对象（包含 task_id）。
- [ ] `_cleanup_job_files` 清理任务临时文件，支持保留元数据选项。

**向量与解析**：
- [ ] 向量生成为**可选步骤**；文件解析与向量化在 API 请求中同步完成。
- [ ] Repository 工厂支持所有 library tag（CODE/SCT/BUILD/SYNTAX/SPEC/ALG/DESIGN/FLOW）。
- [ ] `process_file` 支持 `.md` 和 `.json` 格式，记录失败文件详情。

**Celery 异步任务**：
- [ ] Celery 任务 `import_documents_task` 负责批量导入到 OpenSearch，支持 `replace` 和 `append` 模式。
- [ ] Celery 任务支持进度更新（使用 `self.update_state` 更新 stage、current、total、status）。
- [ ] Celery 任务错误处理，失败时更新元数据（completed_at、error）。
- [ ] Celery 任务成功时更新元数据（completed_at、result）。
- [ ] Celery 任务完成后清理临时文件（调用 `ImportService._cleanup_job_files(job_id, keep_metadata=True)`）。
- [ ] `cleanup_old_jobs` 定期任务清理超过 7 天的任务目录（包括元数据）。

**临时文件与元数据管理**：
- [ ] 临时文件目录结构：`/tmp/bible_import/jobs/{job_id}/files/`。
- [ ] 任务元数据保存：`/tmp/bible_import/jobs/{job_id}/metadata.json`。
- [ ] 元数据包含所有必需字段：job_id、library、created_at、celery_task_id、parse_results 等。
- [ ] 立即清理：任务完成时删除文件，保留元数据。
- [ ] 延迟清理：定期任务清理超过 7 天的任务目录。
- [ ] 异常恢复：服务启动时清理孤儿任务目录（超过 1 天且无任务记录）。

**状态映射**：
- [ ] 实现 Celery 状态到业务状态的映射（PENDING→parsing、PROGRESS→parsing/vectorizing/importing、SUCCESS→completed、FAILURE→failed、REVOKED→cancelled）。
- [ ] 根据 Celery stage 字段判断当前处于哪个业务阶段。
- [ ] 支持向量化阶段识别（仅当 use_vector=true 时）。

**错误处理**：
- [ ] 任务不存在时返回 404 错误。
- [ ] 元数据文件损坏时返回 500 错误。
- [ ] Celery 连接失败时返回 500 错误。
- [ ] 所有错误都有适当的日志记录。

**配置管理**：
- [ ] 配置项 `import_.temp_dir` 用于指定临时目录路径。
- [ ] 配置项 `import_.cleanup_days` 用于指定任务记录保留天数。

---

## 9. 文档索引

### API 接口文档
- [IMPORT_API_REFERENCE.md](./IMPORT_API_REFERENCE.md) - Import API 接口文档

### 架构设计文档
- [01_架构总览.md](./01_架构总览.md) - 系统整体架构说明
- [02_分层职责详解.md](./02_分层职责详解.md) - 分层职责详细说明
- [03_配置管理设计.md](./03_配置管理设计.md) - 配置管理设计

### 流程图与泳道图
- [import_flow_swimlane.puml](./import_flow_swimlane.puml) - **Import 流程泳道图（详细版）** ⭐
- [import_flow_swimlane_simple.puml](./import_flow_swimlane_simple.puml) - Import 流程泳道图（简化版）
- [import_file_lifecycle.puml](./import_file_lifecycle.puml) - **Import 临时文件生命周期管理** ⭐
- [SWIMLANE_DIAGRAM_README.md](./SWIMLANE_DIAGRAM_README.md) - 泳道图使用说明

### 参考设计文档
- [07_Search流程_no_session_skill_详细设计.md](./07_Search流程_no_session_skill_详细设计.md) - Search 流程详细设计（参考）

---

**完成！** 本文档描述了 Import 流程的详细设计，专注于实现层面的类、方法与调用关系，遵循 FastAPI + DDD + Clean Architecture 架构。
