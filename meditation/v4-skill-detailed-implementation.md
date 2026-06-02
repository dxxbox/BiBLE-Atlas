# BiBLE v4 Skill 详细实现细节

> 基于 `docs/designs/server_part/v4/` 设计文档，针对当前 `bible/` 代码的 gap 分析
> 生成日期：2026-06-02

---

## 目录

1. [通用复用组件提取](#1-通用复用组件提取)
2. [Phase 1: Skill Search API](#2-phase-1-skill-search-api)
3. [Knowledge Base Import（不在本次范围）](#3-knowledge-base-import不在本次范围)
4. [Phase 2: Skill Import](#4-phase-2-skill-import)
5. [Phase 3: Download 功能](#5-phase-3-download-功能)
6. [Phase 4: Control 端点 + 收尾](#6-phase-4-control-端点--收尾)
7. [配置补全](#7-配置补全)
8. [测试策略](#8-测试策略)

---

## 1. 通用复用组件提取

### 1.1 QueryProfileCompiler 提取

**背景**：当前 `search_profile → DSL` 编译逻辑嵌入在 Searcher 中（`search_knowledge_base.py` / `search_memory.py`），需提取为通用组件供三域复用。

**文件**：`bible/features/search/common/query_profile_compiler.py`

**接口设计**：

```python
from typing import Any

class QueryProfileCompiler:
    """将 search_profile 编译为数据库查询 DSL。"""

    @staticmethod
    def compile(
        search_type: str,         # keyword | title | text | vector | hybrid
        query: str,
        top_k: int,
        search_profile: dict[str, Any],
        vector_weight: float | None = None,
        query_vector: list[float] | None = None,
    ) -> dict[str, Any]:
        """
        返回：数据库查询 DSL（dict）

        编译规则：
        - keyword:  term_fields  → term 查询 + boost
        - title:    match_fields → match 查询 + boost
        - text:     fields       → multi_match 查询
        - vector:   vector_field → knn 查询
        - hybrid:   text查询 + knn 同次请求混合（单次请求，非两次）
        """
        ...

    @staticmethod
    def _build_keyword_dsl(profile: dict, query: str, top_k: int) -> dict: ...
    @staticmethod
    def _build_title_dsl(profile: dict, query: str, top_k: int) -> dict: ...
    @staticmethod
    def _build_text_dsl(profile: dict, query: str, top_k: int) -> dict: ...
    @staticmethod
    def _build_vector_dsl(profile: dict, query_vector: list[float], top_k: int) -> dict: ...
    @staticmethod
    def _build_hybrid_dsl(profile: dict, query: str, query_vector: list[float],
                          top_k: int, vector_weight: float) -> dict: ...
    @staticmethod
    def _extract_response_fields(profile: dict) -> list[str]:
        """从 response_fields 提取 _source 字段列表（排除 score）。"""
        ...
```

**DSL 编译规则细节（与设计文档 03 一致）**：

1. `keyword.term_fields[].field/weight` → `term` 查询 + `boost`
2. `title.match_fields[].field/weight` → `match` 查询 + `boost`
3. `text.fields[].field/weight` → `multi_match.fields` 中的 `field^weight`
4. `vector.vector_field` → `knn.field`；`num_candidates_min/multiplier` → `knn.num_candidates`
5. `hybrid.default_vector_weight` → `knn.boost`（文本权重 = `1 - vector_weight`）
6. `response_fields` → `_source` 字段过滤（排除 `score`）

**注意点**：
- 只接受已知字段，拒绝未知字段（profile 白名单校验）
- hybrid 是单次请求（同一次 OpenSearch 请求中同时包含 query + knn），不是两次请求
- `vector` 和 `hybrid` 类型必须提供 `query_vector`，否则抛出 `VECTOR_MODEL_REQUIRED`

---

### 1.2 现有 Searcher 的修改

对 `search_knowledge_base.py` / `search_memory.py` / `search_skill.py` 中现有的 DSL 构建逻辑，替换为调用 `QueryProfileCompiler.compile()`，减少重复代码。

---

## 2. Phase 1: Skill Search API

### 2.1 Skill Search API 端点

**文件**：`bible/api/search/skill_search_api.py`

**参照模板**：`bible/api/search/memory_search_api.py`（结构相同，只改 domain 和 tag 固定值）

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/search/skill", tags=["search"])

class SkillSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    tag: str = Field(default="skill")   # 固定为 skill
    search_type: str | None = Field(default=None)  # keyword|title|text|vector|hybrid
    top_k: int | None = Field(default=None)
    vector_model: str | None = Field(default=None)
    vector_weight: float | None = Field(default=None, ge=0.0, le=1.0)

@router.post("")
async def search_skill(request: SkillSearchRequest, ...):
    """
    1. 校验 tag == "skill"（强校验）
    2. 校验 search_type 合法性
    3. 调用 SkillSearchService.search(...)
    4. 返回: {success, domain:"SKILL", kb_index, tag, total, results: {skill: [...]}}
    """
```

**关键差异 vs Memory Search API**：
- `tag` 固定为 `"skill"`
- `domain` 返回 `"SKILL"`
- 结果 key 为 `"skill"`

### 2.2 Skill Search Service

**文件**：`bible/features/search/skill_search/skill_search_service.py`

**参照模板**：`bible/features/search/memory_search/memory_search_service.py`

```python
class SkillSearchService:
    def __init__(self, db_factory: DatabaseFactory, vector_tool: VectorTool, config: Config):
        self._db = db_factory
        self._vector_tool = vector_tool
        self._config = config

    def search(self, query: str, tag: str, search_type: str | None,
               top_k: int | None, vector_model: str | None,
               vector_weight: float | None) -> dict:
        """
        1. 校验 query/tag 非空，tag 必须为 "skill"
        2. db.get_binding_by_domain_tag("SKILL", tag) 读取绑定
        3. 标准化 search_type/top_k/vector_weight（使用默认值）
        4. 校验 vector_model 一致性（请求显式提供时需与绑定一致）
        5. 调用 SkillSearcher.search(...)
        6. 组装响应: {success, domain, kb_index, tag, total, results}
        """
```

### 2.3 Skill Search Searcher

**文件**：`bible/features/search/skill_search/searcher/search_skill.py`

已有的 searcher 需确保接口与 KB/Memory 一致：

```python
class SkillSearcher:
    def search(self, kb_index: str, query: str, search_type: str, top_k: int,
               search_profile: dict, vector_model: str | None,
               vector_weight: float | None) -> list[dict]:
        """
        1. 若 search_type 为 vector/hybrid：
           - vector_tool.ensure_model_ready(vector_model)
           - query_vector = vector_tool.embed_query(query, vector_model)
        2. dsl = QueryProfileCompiler.compile(search_type, query, top_k,
                                               search_profile, vector_weight, query_vector)
        3. hits = db.search_content_docs(kb_index, dsl)
        4. 映射: _source 透传，score ← _score
        5. 返回 [{"doc_id": ..., "title": ..., "score": ...}, ...]
        """
```

**SKILL 检索字段映射（固定规则）**：
- `keyword`：匹配 `name`
- `text`：匹配 `name/description/body`
- `vector`：向量源模板为 `name+description+body`
- `hybrid`：文本与向量混合

### 2.4 路由注册

**文件**：`bible/api/search/__init__.py`

```python
from bible.api.search.knowledge_base_search_api import router as kb_search_router
from bible.api.search.memory_search_api import router as memory_search_router
from bible.api.search.skill_search_api import router as skill_search_router   # 新增

search_router = APIRouter()
search_router.include_router(kb_search_router)
search_router.include_router(memory_search_router)
search_router.include_router(skill_search_router)   # 新增
```

---

## 3. Knowledge Base Import（不在本次范围）

> **决策**：KNOWLEDGE_BASE Import 暂不在本次 Skill 开发计划内，延后到后续迭代。相关设计文档保留在 `docs/designs/server_part/v4/import_implementations/knowledge_base_import_implementation.md`，届时以 Memory Import 为模板实现即可。

---

## 4. Phase 2: Skill Import

### 4.1 Skill Import API

**文件**：`bible/api/import/skill_import_api.py`

**参照模板**：`bible/api/import/memory_import_api.py`

```python
router = APIRouter(prefix="/api/import/skill", tags=["import"])

@router.post("", status_code=202)
async def import_skill(
    files: list[UploadFile] = File(..., alias="files[]"),
    kb_index: str = Form(...),
    tag: str = Form(...),                        # 强校验: 必须 == "skill"
    parser_script: UploadFile | None = File(None),
    vector_model: str | None = Form(None),
    parser_context: str | None = Form(None),
):
    """
    1. ConfigManager.get_upload_constraints("import.skill.upload")
    2. 校验 files（至少一个 .skill 文件）
    3. 强校验 tag == "skill"
    4. parser_context JSON 解析
    5. 流式保存 files 到 session_dir
    6. AsyncTaskService.submit(task_type="import.skill", ...)
    7. 返回 202 + {task_id, domain:"SKILL", kb_index, tag, status:"queued"}
    """
```

### 4.2 Skill Import Service

**文件**：`bible/features/import/skill_import/skill_import_service.py`

```python
class SkillImportService:
    def execute_task(self, task_id: str, payload: SkillImportPayload, files: list) -> None:
        """
        try:
            1. 脚本选择链路:
               - 上传脚本 → parsers/parse_skill.py
               - 否则查 parsers/parse_skill.py
               - 否则回退 parsers/parse_default.py

            2. ASTGuard.validate(script_path)

            3. StoreSkill.stage_upload_files(files, task_id) — 临时落地

            4. StoreSkill.build_parse_manifest(staged_files, task_id, kb_index, tag)
               → 生成 skill_request_manifest.json

            5. SandboxRunner.run_parse(script_path, manifest_path, parser_context)
               - parse_skill.py 作为唯一解析总入口：
                 a. 读取 manifest 的全部上传文件
                 b. 校验 .skill 文件必须且仅有一个
                 c. 对 .skill 执行 ZIP 解压（防 Zip Slip、解压炸弹、软链接）
                 d. 定位 SKILL.md（必需文件）
                 e. 解析 name/description/正文
                 f. 非 .skill 文件分类，加入 local_file_storage_plan
                 g. 返回 {chunks, search_profile, local_file_storage_plan}

            6. validate_parse_result_schema(result)

            7. StoreSkill.store(kb_index, parse_result, vector_model, ...)
               - 按 local_file_storage_plan 执行文件存储
               - 回填 chunk.metadata.related_storage_paths
               - 查询/创建绑定
               - 可选向量化
               - 写内容索引 + 文件注册表

        finally:
            cleanup_staged_workspace(task_id)
        """
```

### 4.3 Skill Package Parser

**文件**：`bible/features/import/skill_import/skill_package_parser.py`

```python
class SkillPackageParser:
    """解析 .skill 包（本质 ZIP）和 SKILL.md 文件。"""

    @staticmethod
    def extract_and_parse(skill_file_path: str) -> SkillPackage:
        """
        1. 校验文件扩展名为 .skill
        2. ZIP 解压（防 Zip Slip: 拒绝 ../ 路径）
        3. 校验解压后文件大小（防解压炸弹）
        4. 拒绝软链接
        5. 定位 SKILL.md（必需文件，缺失抛错）
        6. 解析 SKILL.md:
           - name: 一级标题后的文本（# xxx）
           - description: name 后的第一段
           - body: 剩余正文
        7. 返回 SkillPackage(name, description, body, extra_files)
        """

@dataclass
class SkillPackage:
    name: str
    description: str
    body: str
    extra_files: list[dict]  # 非 SKILL.md 的其他文件
```

### 4.4 Skill Parser（parse_skill.py）

**文件**：`bible/features/import/skill_import/parsers/parse_skill.py`

```python
def parse(file_path: str, context: dict | None = None) -> dict:
    """
    file_path 指向 skill_request_manifest.json（而非单个文件）

    内部逻辑：
    1. 读取 manifest，获取全部上传文件列表
    2. 找到 .skill 文件（必须且仅一个）
    3. 调用 SkillPackageParser.extract_and_parse(skill_file_path)
    4. 其他文件分类到 local_file_storage_plan
    5. 构建 chunks（语义内容只来自 SKILL.md）：
       - title = name
       - content = name + description + body
       - metadata.related_storage_paths 回填
    6. 构建 search_profile（固定规则）：
       - keyword: 匹配 name
       - text: 匹配 name/description/body
       - vector: 向量源模板 = name+description+body
       - hybrid: 文本与向量混合
    7. 构建 local_file_storage_plan（覆盖全部上传文件）
    8. 返回 {chunks, search_profile, local_file_storage_plan}
    """
```

### 4.5 Skill Storage

**文件**：`bible/features/import/skill_import/storage/store_skill.py`

```python
class StoreSkill:
    def stage_upload_files(self, files: list, task_id: str) -> list[dict]:
        """临时保存上传文件到任务工作目录"""
        ...

    def build_parse_manifest(self, staged_files: list, task_id: str,
                              kb_index: str, tag: str) -> str:
        """生成 skill_request_manifest.json 并返回路径"""
        ...

    def store(self, kb_index: str, parse_result: ParseResult,
              vector_model: str | None, parser_script_source: str,
              parser_script_sha256: str) -> dict:
        """
        1. 按 local_file_storage_plan 执行文件存储：
           for plan_item in local_file_storage_plan:
               fs.store(file_stream, domain="SKILL", kb_index, filename, task_id)

        2. 回填 chunk.metadata.related_storage_paths

        3. 查询/创建绑定（db.get_binding_by_domain_index → create_binding）
           - 已存在则 assert_binding_consistency

        4. 可选向量化（vector_model 非空时）

        5. 写内容索引：db.bulk_upsert_content_docs(kb_index, chunks)

        6. 写文件注册表：db.bulk_upsert_file_registry(kb_index, file_records)

        7. 返回 {database_write_status, file_write_status}
        """
```

---

## 5. Phase 3: Download 功能

### 5.1 通用 Artifact Store

**文件**：`bible/features/download/common/artifact_store.py`

**决策**：artifact 物理文件使用 `infrastructure/file_system/` 统一管理，不独立部署存储路径。ArtifactStore 仅负责元信息（过期时间、content_type 等）的存取和 TTL 清理编排。

```python
@dataclass
class ArtifactMeta:
    artifact_id: str
    artifact_name: str
    content_type: str
    storage_path: str          # file_system 中的逻辑路径
    size_bytes: int
    expires_at: str            # ISO 8601
    domain: str                # "SKILL" | "MEMORY"
    task_id: str

class DownloadArtifactStore:
    def __init__(self, db_factory: DatabaseFactory, fs_factory: FileSystemFactory, config: Config): ...

    def create(self, meta: ArtifactMeta) -> None:
        """写入 artifact 元信息到数据库"""

    def get(self, artifact_id: str) -> ArtifactMeta | None:
        """读取 artifact 元信息，自动校验过期（过期返回 None）"""

    def delete(self, artifact_id: str) -> bool:
        """删除 artifact 元信息 + 通过 file_system 删除物理文件"""

    def sweep_expired(self, limit: int = 100) -> int:
        """清理过期 artifact：遍历过期记录 → fs.delete(storage_path) → 删除元信息"""
```

**与 file_system 的协作方式**：
- `create()` 之前：物理文件已由 DownloadService 通过 `fs.store()` 写入 file_system
- `storage_path` 即为 file_system 返回的逻辑路径
- `delete()` / `sweep_expired()` 通过 `fs.delete(storage_path)` 删除物理文件

### 5.2 通用 Zip Builder

**文件**：`bible/features/download/common/zip_builder.py`

```python
class DownloadZipBuilder:
    @staticmethod
    def build(
        files: list[dict],           # [{storage_path, download_name}, ...]
        output_path: str,
        include_metadata: bool = False,
    ) -> dict:
        """
        1. 创建 ZIP 文件
        2. 逐个添加文件（流式读取，避免内存峰值）
        3. 可选：添加 metadata.json（文件清单 + hash）
        4. 返回 {storage_path, size_bytes, file_count}
        """
```

### 5.3 Download Task Executor

**文件**：`bible/features/async_task/executors/download_task_executor.py`

```python
class DownloadTaskExecutor:
    task_type = "download"  # 前缀匹配 download.skill.* / download.memory.*

    def execute(self, task_id: str, task_type: str, payload: dict) -> dict:
        """
        路由：
        - download.skill.file  → SkillDownloadService.execute_single(...)
        - download.skill.batch → SkillDownloadService.execute_batch(...)
        - download.memory.file  → MemoryDownloadService.execute_single(...)
        - download.memory.batch → MemoryDownloadService.execute_batch(...)

        返回：
        {
            "artifact_id": "dl_xxx",
            "artifact_name": "xxx.zip",
            "content_type": "application/zip",
            "size_bytes": 12345,
            "expires_at": "2026-06-03T00:00:00Z",
            "item_count": 3
        }
        """
```

### 5.4 SKILL Download API + Service

**文件**：`bible/api/download/skill_download_api.py`

```python
router = APIRouter(prefix="/api/download/skill", tags=["download"])

class SkillSingleDownloadRequest(BaseModel):
    tag: str = Field(default="skill")
    storage_path: str
    download_name: str | None = None

class SkillBatchDownloadRequest(BaseModel):
    tag: str = Field(default="skill")
    storage_paths: list[str]
    package_name: str | None = None
    include_metadata: bool = False

@router.post("/file", status_code=202)
async def submit_skill_file_download(request: SkillSingleDownloadRequest):
    """
    1. 校验 tag == "skill"
    2. 校验 storage_path 格式（防目录穿越）
    3. AsyncTaskService.submit(task_type="download.skill.file", ...)
    4. 返回 202 + task_id
    """

@router.post("/batch", status_code=202)
async def submit_skill_batch_download(request: SkillBatchDownloadRequest):
    """同上，task_type="download.skill.batch" """

@router.get("/artifact/{artifact_id}")
async def fetch_skill_download_artifact(artifact_id: str):
    """
    1. DownloadArtifactStore.get(artifact_id)
    2. 校验 domain="SKILL" + 未过期
    3. fs.open_read(storage_path) → StreamingResponse
    4. 设置 Content-Type, Content-Disposition
    """
```

**文件**：`bible/features/download/skill_download/skill_download_service.py`

```python
class SkillDownloadService:
    def execute_single(self, task_id: str, payload: dict) -> dict:
        """
        1. resolve_binding(tag="skill") → kb_index
        2. 查询 file_registry 校验 storage_path 属于该 kb_index
        3. 校验物理文件存在
        4. 生成单文件 artifact（可选重命名）
        5. DownloadArtifactStore.create(meta)
        6. 返回 artifact 元信息
        """

    def execute_batch(self, task_id: str, payload: dict) -> dict:
        """
        1-3. 同上，校验每个 storage_path
        4. DownloadZipBuilder.build(files, output_path)
        5. DownloadArtifactStore.create(meta)
        6. 返回 artifact 元信息
        """
```

### 5.5 MEMORY Download API + Service

结构完全与 SKILL Download 一致，仅：
- 路径前缀：`/api/download/memory`
- domain：`"MEMORY"`
- tag：固定 `"memory"`
- task_type：`download.memory.file` / `download.memory.batch`

### 5.6 路由注册

**文件**：`bible/main.py`

```python
from bible.api.download.skill_download_api import router as skill_download_router
from bible.api.download.memory_download_api import router as memory_download_router

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.include_router(system_router)
    app.include_router(knowledge_router)
    app.include_router(import_router)
    app.include_router(search_router)
    app.include_router(skill_download_router)     # 新增
    app.include_router(memory_download_router)    # 新增
    return app
```

---

## 6. Phase 4: Control 端点 + 收尾

### 6.1 Tasks Admin API

**文件**：`bible/api/control/admin_api.py`

```python
router = APIRouter(prefix="/api/control/admin", tags=["control"])

@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """查询通用异步任务状态（含 download 任务）"""
    return AsyncTaskService.get(task_id)

@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消通用异步任务"""
    return AsyncTaskService.cancel(task_id)
```

### 6.2 Docs API

**文件**：`bible/api/control/docs_api.py`

```python
router = APIRouter(prefix="/api/control/docs", tags=["control"])

@router.get("/list")
async def list_docs(): ...
    # 返回已注册的 API 文档列表
```

### 6.3 Statistics API

**文件**：`bible/api/control/statistics_api.py`

```python
router = APIRouter(prefix="/api/control/statistics", tags=["control"])

@router.get("/overview")
async def get_statistics():
    """返回三域统计信息（索引数、文档数、任务数等）"""
```

### 6.4 Memory meta.json Parser（降级 P2）

**决策**：当前 Memory Import 复用默认解析器 `parse_default.py`，不单独开发专用 `parse_memory.py`。此项降级为 P2，待后续有明确的 meta.json 结构化解析需求时再补充。

如需后续实现，参照文件：`bible/features/import/memory_import/parsers/parse_memory.py`

---

## 7. 配置补全

**文件**：`bible/config/configure.py` 中的 `AppConfig` 需增加的配置项：

```python
@dataclass
class ImportKnowledgeBaseConfig:
    parsers_dir: str = "./workspace/knowledge_base/parsers"
    import_work_dir: str = "./workspace/knowledge_base/import_work"
    task_timeout_seconds: int = 300
    sandbox_timeout_seconds: int = 60
    workspace_ttl_hours: int = 24
    sweep_interval_seconds: int = 3600
    keep_failed_workspace: bool = False

@dataclass
class ImportSkillConfig:
    parsers_dir: str = "./workspace/skill/parsers"
    import_work_dir: str = "./workspace/skill/import_work"
    task_timeout_seconds: int = 300
    sandbox_timeout_seconds: int = 60
    workspace_ttl_hours: int = 24
    sweep_interval_seconds: int = 3600
    keep_failed_workspace: bool = False

@dataclass
class DownloadConfig:
    artifact_ttl_hours: int = 24
    sweep_interval_seconds: int = 3600
    max_batch_file_count: int = 100
    artifact_dir: str = "./workspace/downloads"

@dataclass
class UploadConstraintsConfig:
    supported_types: list[str]     # e.g. [".md", ".txt", ".py", ".skill", ".json"]
    max_file_size: int             # bytes
    max_total_size: int            # bytes
    max_file_count: int
```

在 `AppConfig` 中增加：
```python
import_knowledge_base: ImportKnowledgeBaseConfig
import_skill: ImportSkillConfig
download: DownloadConfig
# upload_constraints 按域拆分
import_kb_upload: UploadConstraintsConfig
import_skill_upload: UploadConstraintsConfig
import_memory_upload: UploadConstraintsConfig
```

---

## 8. 测试策略

### 8.1 单元测试

| 模块 | 测试内容 |
|------|---------|
| `QueryProfileCompiler` | 5种 search_type DSL 编译正确性，profile 白名单校验 |
| `SkillPackageParser` | .skill 解压正常/异常（Zip Slip、炸弹、缺SKILL.md） |
| `ASTGuard` | 安全/危险脚本检测，白名单导入/黑名单调用 |
| `StoreKnowledgeBase` | 绑定创建/冲突，内容写入 |
| `StoreSkill` | 文件落盘、绑定、向量化、内容+注册写库 |
| `StoreMemory` | 已有，补充 meta.json 解析测试 |
| `DownloadArtifactStore` | 创建/读取/过期清理 |
| `DownloadZipBuilder` | 单文件/批量打包 |

### 8.2 API 集成测试

| 端点 | 测试场景 |
|------|---------|
| `POST /api/search/skill` | keyword/title/text/vector/hybrid 五种检索 |
| `POST /api/import/knowledge-base` | 默认解析、自定义解析、tag=design/flow/alg |
| `POST /api/import/skill` | .skill 包导入、非 .skill 附件、向量化 |
| `POST /api/download/skill/file` | 单文件下载→轮询→拉取→过期 |
| `POST /api/download/skill/batch` | 批量下载→ZIP拉取 |
| `POST /api/download/memory/*` | 同 SKILL |
| `GET /api/control/admin/tasks/{id}` | 任务状态查询 |
| `DELETE /api/control/admin/tasks/{id}` | 任务取消 |

### 8.3 端到端测试

```
1. import KB (tag=design) → search KB (tag=design) → 验证命中
2. import Skill → search Skill → download Skill → 验证文件一致性
3. import Memory → search Memory → download Memory → 验证文件一致性
4. 绑定冲突: 同一 kb_index 用不同 vector_model 再次 import → 返回 CONFLICT
5. 自定义脚本安全: 上传含 eval() 脚本 → 被 ASTGuard 拒绝
```

---

## 附录：文件创建清单

以下是需要**新建**的所有文件（按 Phase 排列）：

```
Phase 1:
  bible/features/search/common/query_profile_compiler.py
  bible/api/search/skill_search_api.py
  bible/features/search/skill_search/skill_search_service.py

Phase 2:
  bible/api/import/skill_import_api.py
  bible/features/import/skill_import/__init__.py
  bible/features/import/skill_import/skill_import_service.py
  bible/features/import/skill_import/schemas.py
  bible/features/import/skill_import/skill_package_parser.py
  bible/features/import/skill_import/parsers/__init__.py
  bible/features/import/skill_import/parsers/parse_skill.py
  bible/features/import/skill_import/storage/__init__.py
  bible/features/import/skill_import/storage/store_skill.py

Phase 3:
  bible/features/download/__init__.py
  bible/features/download/common/__init__.py
  bible/features/download/common/artifact_store.py
  bible/features/download/common/zip_builder.py
  bible/features/async_task/executors/download_task_executor.py
  bible/api/download/__init__.py
  bible/api/download/skill_download_api.py
  bible/api/download/memory_download_api.py
  bible/features/download/skill_download/__init__.py
  bible/features/download/skill_download/skill_download_service.py
  bible/features/download/memory_download/__init__.py
  bible/features/download/memory_download/memory_download_service.py

Phase 4:
  bible/api/control/__init__.py
  bible/api/control/admin_api.py
  bible/api/control/docs_api.py
  bible/api/control/statistics_api.py
```

> **不在本次范围**（延后）：`bible/api/import/knowledge_base_import_api.py` 及 `bible/features/import/knowledge_base_import/` 下全部文件。

需要**修改**的现有文件：

```
  bible/api/search/__init__.py            — 注册 skill_search_router
  bible/api/import/__init__.py            — 注册 skill_import_router
  bible/main.py                           — 注册 download_router, control_router
  bible/features/__init__.py              — 增加新模块的 lazy import
  bible/features/import/import_task_executor.py  — 增加 import.skill 路由
  bible/config/configure.py               — 增加 import_skill / download 配置
  bible/features/search/*/searcher/*.py   — 替换为 QueryProfileCompiler
```
