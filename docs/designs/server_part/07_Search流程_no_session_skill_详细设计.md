# Search 流程详细设计（无 SESSION / SKILL 仓储切片）

本文档描述在 FastAPI 分层架构下，**检索 API** 与 **`app/features/search/`** 的实现型设计，范围**排除** `SessionSearchRepository`、`SkillSearchRepository` 及 SESSION、SKILL 专属编排逻辑。对外 HTTP 契约以 [04_API接口文档.md](./04_API接口文档.md) 为准；分层原则见 [02_分层职责详解.md](./02_分层职责详解.md)。

---

## 1. 范围与术语

### 1.1 包含

- `POST /api/v1/search` 的路由与 Pydantic 模型（与 04 字段一致）。
- `SearchService`：**编排**（解析 tag、`enable_hit` 任务列表、并行调度、**合并**多索引 `results`）；**不在此层**逐条调用 `RerankTool` / **Copilot CLI（AI）**。
- **Rerank** 与 **AI 增强** 为**两项独立能力**（cross-encoder 等 **重排序** vs **经 Copilot CLI 的筛选/理解**）；配置见 [03](./03_配置管理设计.md)；**默认在各自 `BaseSearchRepository` 实现内**、于 **底层检索（Elasticsearch / OpenSearch / PostgreSQL 等，见 §4.2）完成且 `map_backend_response_to_items` 之后** 按序执行，便于单索引 **一次性** 产出该索引的最终候选，再由 Service 合并。
- **Query 向量**：仍由 **Service** 调用 `VectorTool` 生成后 **传入** Repository（避免在仓储内重复加载向量模型）；Repository **不调用** `VectorTool`。
- 以下 index tag 的 **Repository 与工厂注册**：`CODE`, `SCT`, `BUILD`, `SYNTAX`, `SPEC`, `ALG`, `DESIGN`, `FLOW`。

### 1.2 不包含（本切片）

- SESSION、SKILL 的仓储类、索引侧特殊逻辑、多文件存储联动。
- **`hit_list` 不在上层裁剪**：`enable_hit` 展开时 **保留配置中的完整 `hit_list`（含 SESSION、SKILL）**；对本切片 **未实现的 tag**，由 **`SearchRepositoryFactory`** 返回 **空分桶占位仓储**（见 §4.3），使 **`index_search_tasks.py` / `SearchService` 不必随 Session/Skill 上线再改编排逻辑**。后续若 SESSION/SKILL 有真实仓储，只需在工厂注册实现类即可。

### 1.3 主 tag 为 SESSION 或 SKILL 时的 API 行为
- HTTP 仍允许客户端传入 `tag: "SESSION"` / `"SKILL"`（04 已列出）。**本切片不实现** SESSION/SKILL 真实仓储与索引检索；为避免客户端报错中断，**应返回 HTTP 200**：
  - `success: true`
  - `results`：返回与任务对应的**空分桶**，即 `SESSION -> {"session": []}`、`SKILL -> {"skill": []}`；若 `enable_hit=true` 展开到 SESSION/SKILL，也保留对应空桶，避免调用方区分“未执行该桶”与“执行了但本切片为空实现”
  - `total: 0`
- **实现路径（与「子任务」统一）**：**不在 `SearchService` 最前短路**。照常经 **`index_search_tasks` 构建 `IndexSearchTask`** → `asyncio.gather` → **`SearchRepositoryFactory.create`** 得到 **占位仓储** → `merge_results`，与 `enable_hit` 下 SESSION/SKILL 子任务 **同一路径**；占位仓储 **`search()` 不调检索后端**，便于后续 **只替换工厂注册** 即接入真实检索。
- 服务端可打 **INFO 级日志**（如「SESSION/SKILL 占位仓储，返回空分桶」），**不在响应体中**用 `error` 字段表示「未实现」（除非未来产品改为显式提示）。
- 待 Session/Skill 检索能力补齐后，再改为真实检索并更新本文档。

---

## 2. 与 04 API 的字段对照

### 2.1 请求体（`SearchRequest`，建议置于 `app/features/search/schemas.py`）

| JSON 字段 | Python 字段 | 必填 | 说明 |
|-----------|-------------|------|------|
| `index_name` | `index_name` | 是 | 主检索 `index_name`；`CODE` 或无前缀 tag 时使用 |
| `query` | `query` | 是 | 支持 `[TAG]` 前缀，规则见 04 |
| `tag` | `tag` | 否 | 与 query 前缀解析后的 `effective_tag` 合并逻辑见 §5；检索用文本为 **`query_for_search`**（§3.2） |
| `search_type` | `search_type` | 否，默认 `hybrid` | 枚举：`keyword`, `title`, `text`, `vector`, `hybrid` |
| `vector_model` | `vector_model` | 否，默认 `bge-large` | 须在动态配置 `vector_models.models` 中存在 |
| `top_k` | `top_k` | 否，默认 `10` | `1`～`search.max_top_k`（动态配置） |
| `vector_weight` | `vector_weight` | 否，默认 `0.8` | `0.1`～`0.9`，仅 `hybrid` 有意义 |
| `enable_relation_search` | `enable_relation_search` | 否，默认 `true` | 本切片：**预留**，默认透传至 Repository 查询构建（无实现时可忽略） |
| `enable_hit` | `enable_hit` | 否，默认 `false` | 为 `true` 时扩展索引，见 §5.3 |
| `filter_mode` | `filter_mode` | 否，默认 `none` | `none` / `elbow` / `gap_statistic`；本切片：**预留**，可在 Service 后处理或 Repository 分数过滤中接好接口 |
| `ai_enable` | `ai_enable` | 否，默认 `false` | 为 `true` 时启用 **AI 增强检索**（见 §5.5）；与 04 一致 |
| `ai_model` | `ai_model` | 否，默认 `"gpt-5-mini"` | `ai_enable=true` 时生效；允许值与 04 一致，并与动态配置 **`copilot_config.available_models`**（及 `default_model`）对齐，便于热更新 |

**Pydantic v2 校验**：**以 `app/features/search/schemas.py` 为主**——在 **`SearchRequest` / `SearchResponse`** 上使用 `Field`、`field_validator`、`model_validator` 完成类型、范围、枚举及「`ai_enable=true` 时 `ai_model` 合法」等规则；必要时用 **`Annotated` + 依赖 `ConfigManager` 的校验器**（构造后校验或工厂函数建模型）读取 `vector_models`、`copilot_config`。**`search_api.py` 只负责** `response_model=SearchResponse`、依赖注入与 **`HTTPException` 映射**；**不要**在路由函数里堆业务级校验逻辑，避免 API 层与 feature 模型重复。

**字段级规则补充**：`search_type`、`tag` 可与 `search_types` 配置对齐；`vector_model` 与 `ConfigManager` 允许列表对齐；**`ai_enable=true` 时** `ai_model` 须在 **`copilot_config.available_models`** 内（若无该键则回退 `search.ai.allowed_models` 或 04 枚举）。

**本切片固定语义**：

1. `vector_weight` **仅**在 `search_type="hybrid"` 时参与查询构建；其余 `search_type` 下**接受但忽略**，不报错。
2. `ai_model` **仅**在 `ai_enable=true` 时校验并生效；`ai_enable=false` 时即使传入也**接受但忽略**。
3. `enable_relation_search` 在本切片中为**兼容性开关**：允许透传给具体 Repository；若仓储暂不支持，**静默忽略并记录 debug/info 日志**，不改变响应结构。
4. `filter_mode` 在本切片中为**预留枚举参数**：先完成校验并透传；若当前 Service/Repository 未实现对应过滤算法，则视为 **no-op**。
5. 请求体验证失败统一按项目错误体映射为 **400**，不向客户端暴露 FastAPI 默认 `422` 结构。

### 2.2 响应体（`SearchResponse`）

与 04 一致：

- `success: bool`
- `results: SearchResultsBuckets` — 按 index 分桶，键名见 §4.1 与 §4.3
- `total: int` — **固定定义为** `results` 中**所有分桶列表长度之和**

错误响应：`{"error": "..."}`，HTTP 状态码 **400**（参数非法）、**500**（系统/模型调用失败等）。**AI 调用失败**在本切片**固定按降级成功处理**：返回非 AI 路径结果并记录日志，**不**因 AI 子步骤失败把整次请求改为 500。

#### `SearchResponse.results` 精确约定

`results` 建议建模为结构化对象（如 `SearchResultsBuckets`），而不是无约束 `dict[str, Any]`。键集合固定为：

- `code`
- `sct`
- `build_method`
- `coding_standards`
- `requirement`
- `algorithm`
- `design`
- `flow`
- `session`
- `skill`

约束：

1. **仅对本次实际执行的任务桶输出对应 key**；值恒为列表。
2. 某桶执行后即使没有命中，也返回空列表 `[]`，**不**返回 `null`。
3. `SESSION` / `SKILL` 在本切片中若出现在任务列表里，其桶值**固定为空列表**。
4. `_merge_results(...)` 不得丢弃已执行任务的空桶，否则会破坏 `total` 与分桶可观测性的一致性。

#### `SearchResponse.results` 的桶值类型

| `results_key` | 值类型 | 说明 |
|---------------|--------|------|
| `code` | `list[CodeSearchItem]` | 代码按文件聚合结果 |
| `sct` / `build_method` / `coding_standards` / `requirement` / `algorithm` / `design` / `flow` | `list[SectionSearchItem]` | 章节型结果 |
| `session` / `skill` | `list[dict]`，且本切片固定为 `[]` | 预留桶；待后续切片补真实 item 结构 |

### 2.3 对外模型接口设计

#### `SearchRequest`

`SearchRequest` 是 **`search_api.py`** 的输入模型，也是整个 Search 编排的**唯一外部入参载体**。建议接口设计如下：

| 接口点 | 约定 |
|--------|------|
| 构造来源 | FastAPI 自动将 HTTP JSON body 解析为 `SearchRequest` |
| 校验职责 | 字段范围、枚举、关联校验（如 `ai_enable=true` 时 `ai_model` 必须合法） |
| 对 Service 暴露 | 只暴露标准化后的字段值；非法请求不进入 `SearchService.search(...)` |

建议保留的模型级校验：

1. `top_k`、`vector_weight` 的范围校验。
2. `search_type`、`tag`、`vector_model`、`ai_model` 的合法性校验。
3. 若 `search_type` 为 `vector` / `hybrid`，则允许 `SearchService` 按需生成向量；`SearchRequest` 本身不直接依赖 `VectorTool`。

接口边界补充：

1. **Client -> API**：HTTP JSON body 由 FastAPI 解析为 `SearchRequest`。
2. **API -> Service**：`search_api.search_documents(request: SearchRequest)` 调用 `SearchService.search(req: SearchRequest)`。
3. **Service -> Repository**：Repository 的 `build_query(...)` / `search(...)` 可继续接收同一个 `SearchRequest`，用于读取 `search_type`、`top_k`、`ai_enable` 等请求参数。
4. **不作为输出 DTO**：`SearchRequest` 只承载请求，不出现在响应体。

#### `SearchResponse`

`SearchResponse` 是 **Search API 的统一成功返回模型**，建议接口设计如下：

| 字段 | 含义 |
|------|------|
| `success` | 请求是否成功完成业务流程 |
| `results` | 按 `results_key` 分桶后的结构化结果 |
| `total` | 统一口径的结果计数 |

设计约束：

1. 所有仓储返回的结果都必须能够被 `SearchService._merge_results(...)` 收敛为 `SearchResponse.results`。
2. `EmptySearchRepository` 也必须返回与该模型兼容的空分桶结构。
3. 对外错误响应仍走 04 中定义的错误体，不把异常状态塞进 `SearchResponse.success=false` 分支混用。

接口边界补充：

1. **Service -> API**：`SearchService.search(...)` 的返回类型为 `SearchResponse`。
2. **API -> Client**：`search_api.search_documents(...)` 以 `response_model=SearchResponse` 返回成功响应。
3. **不下沉到 Repository**：Repository 只返回各自分桶片段，由 Service 合并后统一封装成 `SearchResponse`。

### 2.4 DTO 分层接口归属总览

下表用于明确 **`SearchRequest` / `SearchResponse` / `IndexSearchTask` / `SearchMatchRow`** 分别在哪一层接口出现，以及它们的边界是否对外暴露：

| DTO | 定义位置 | 主要使用层间接口 | 边界说明 |
|-----|----------|------------------|----------|
| `SearchRequest` | `app/features/search/schemas.py` | `search_api.search_documents(request: SearchRequest)`；`SearchService.search(req: SearchRequest)`；`BaseSearchRepository.build_query(..., req: SearchRequest, ...)` / `search(..., req: SearchRequest, ...)` | **API 入参 DTO**。客户端通过 HTTP body 传入；进入 Service 后继续作为**请求上下文载体**传给 Repository，但**不**作为 Repository 对外暴露结果 |
| `SearchResponse` | `app/features/search/schemas.py` | `SearchService.search(...) -> SearchResponse`；`search_api.search_documents(...) -> SearchResponse` | **API 出参 DTO**。是 Service 对 API 的返回契约，也是 API 对客户端的成功响应模型 |
| `IndexSearchTask` | `app/features/search/schemas.py`（或与 `index_search_tasks.py` 紧邻定义） | `index_search_tasks` 输出 `list[IndexSearchTask]`；`SearchService._build_index_search_tasks(...)`；`SearchService._search_one_task(task: IndexSearchTask, ...)`；`BaseSearchRepository.build_query/search(..., task: IndexSearchTask, ...)` | **Service -> Repository 的内部任务 DTO**。只用于单 index 任务编排与调度，**不进入 API 层** |
| `SearchMatchRow` | `app/features/search/schemas.py` | `BaseSearchRepository.map_backend_response_to_items(...) -> list[SearchMatchRow]`；`RerankTool.rerank(...)`；`AiRankingRunner(...)` | **Repository 内部 / Repository -> 精炼组件 的中间 DTO**。用于统一底层检索命中，不直接暴露给 API 层，也**不作为** Service 合并接口 |

### 2.5 错误映射与降级矩阵

| 场景 | 处理方式 | HTTP |
|------|----------|------|
| 请求体缺字段、类型错误、枚举/范围校验失败 | 统一映射项目错误体 `{"error": "..."}` | **400** |
| `query` 中 tag 非法、body `tag` 非法 | 按 04 规则视为“未指定 tag”，继续走默认 `index_name` | **200** / 正常业务结果 |
| `tag_to_index_mapping` / `hit_list` / `results_key` 等内部配置缺失或不合法 | 视为服务端配置错误，记录 error 日志 | **500** |
| `SearchRepositoryFactory` 收到任务构造阶段产出的未知 `index_tag` | 视为内部一致性错误，不归因为客户端输入 | **500** |
| `SearchClient` 底层检索异常、超时、协议错误 | 记录 error 日志并返回统一错误体 | **500** |
| `RerankTool` 失败 | 视为本次检索失败，返回统一错误体（除非后续版本另行定义降级） | **500** |
| `AiRankingRunner` 解析失败、CLI 异常、超时 | **降级**到上一步结果并截断到 `top_k` | **200** |

### 2.6 本版本固定实现边界

以下约定用于保证后续 implementation 文档和代码实现不再出现分叉：

1. `SearchResponse.total` 口径固定为**所有分桶最终返回条目数之和**。
2. `SESSION` / `SKILL` 在本切片内是**已知但未实现的业务 tag**，因此返回 **200 + 空桶**，而不是 4xx/5xx。
3. `enable_relation_search`、`filter_mode` 是**兼容性参数**，本切片允许 no-op，但必须保留校验与透传边界。
4. AI 属于**可降级子步骤**；Rerank 属于**非降级主链路步骤**。

---

## 3. 模块与文件结构

```
app/
├── api/
│   └── v1/
│       └── search_api.py          # APIRouter，POST /search
├── infrastructure/
│   ├── search/                    # 推荐：统一检索后端适配层
│   │   └── client.py              # SearchClient 抽象/门面，封装 ES/OpenSearch/Postgres
│   └── vector/                    # 已有：RerankTool、VectorTool（见 01 架构总览）
│       └── rerank_tool.py
└── features/
    └── search/
        ├── __init__.py
        ├── search_service.py      # SearchService
        ├── schemas.py             # SearchRequest, SearchResponse, 内部 DTO
        ├── dependencies.py        # get_search_service
        ├── tag_query.py           # 仅协议级：解析 [TAG]、effective tag、query_for_search（§3.2）
        ├── index_search_tasks.py  # Index 搜索任务生成、enable_hit 展开、索引映射与去重
        ├── ai_ranking.py          # AI 增强：组 prompt、调 Copilot CLI、解析输出
        └── repositories/
            ├── __init__.py
            ├── base.py            # BaseSearchRepository（ABC）
            ├── factory.py         # SearchRepositoryFactory
            ├── empty.py           # EmptySearchRepository（SESSION/SKILL 占位）
            ├── code.py            # CodeSearchRepository
            ├── sct.py             # SctSearchRepository
            ├── build.py           # BuildSearchRepository
            ├── syntax.py          # SyntaxSearchRepository（SYNTAX → coding_standards）
            ├── spec.py            # SpecSearchRepository
            ├── alg.py             # AlgSearchRepository
            ├── design.py          # DesignSearchRepository
            └── flow.py            # FlowSearchRepository
```

| 文件 | 职责 |
|------|------|
| `search_api.py` | 路由入口：注册 `POST /search`、承接 **FastAPI + Pydantic** 参数校验、`Depends(get_search_service)`、统一 HTTP 异常映射；**不**承担检索编排、Rerank/AI 判断或查询改写等业务分支 |
| `search_service.py` | 编排入口：解析 tag、展开 `enable_hit` 任务、按 `search_type` 决定是否生成 query 向量、计算 `fetch_size`、并发调度各仓储、执行 `_merge_results` 与 `total` 口径收束；**无** SESSION/SKILL 专门短路，统一经任务列表 + 工厂占位（§1.4） |
| `schemas.py` | 统一定义 Search 相关 DTO 边界：`SearchRequest` / `SearchResponse` 是 **API <-> Service** 契约；`IndexSearchTask` 是 **Service <-> Repository** 内部任务契约；`SearchMatchRow` 是 **Repository <-> Rerank/AI** 中间契约 |
| `tag_query.py` | 见 **§3.2** |
| `index_search_tasks.py` | Index 搜索任务生成模块：负责主任务 + `enable_hit` 关联任务的生成、tag→`index_name` 映射、`results_key` 绑定与去重；输出 `list[IndexSearchTask]`；**不**在此处移除 SESSION/SKILL |
| `dependencies.py` | FastAPI 依赖装配：集中构造 `SearchService` 及其协作者（`SearchClient`、`VectorTool`、`RerankTool`、`AiRankingRunner`、`ConfigManager`）；避免在路由函数中手写对象构造 |
| `ai_ranking.py` | 封装 Copilot CLI 调用：组 prompt、执行 `subprocess`/`asyncio.create_subprocess_exec`、读取 `copilot_config`（`cli_path`、`workspace_root`、超时等）、解析 stdout、在失败/超时场景按 §5.5 降级 |
| `repositories/__init__.py` | 仓储导出/注册入口：集中暴露各 `*SearchRepository` 与 `SearchRepositoryFactory`，降低调用方 import 复杂度；若未来引入自动注册，也可作为单点落位 |
| `repositories/base.py` | 定义 `BaseSearchRepository` 共享检索流水线、抽象扩展点（`build_query`、`map_backend_response_to_items`）、公共依赖注入约定 |
| `repositories/factory.py` | 根据 `index_tag` 选择具体仓储类或 `EmptySearchRepository`；封装已知/未知 tag 分流与依赖透传规则 |
| `repositories/empty.py` | `EmptySearchRepository` 的落位文件；用于 `SESSION` / `SKILL` 在本切片中的空分桶占位实现 |
| `repositories/*` | 各 index 仓储：按部署选择 **Elasticsearch / OpenSearch / PostgreSQL** 等后端，负责 tag 专属查询构建、原始结果映射与最终分桶输出；共享流程仍遵循 **检索 → `map_backend_response_to_items` → Rerank → AI → top_k**（§4.2） |
| `infrastructure/search/client.py`（推荐抽象） | 统一检索后端门面：对上提供稳定的 `search(...)` 契约，对下适配 ES / OpenSearch / PostgreSQL 等不同客户端、查询协议与错误类型；必要时在此做连接复用、重试、超时与统一错误包装。**后端类型建议由静态 `settings.database_type` 选择**（见 [01_架构总览.md](./01_架构总览.md)），**不建议放到动态配置热切换** |

`dependencies.py` 的推荐注入边界：

1. 路由层只 `Depends(get_search_service)`。
2. `get_search_service()` 负责装配 **`SearchClient`、`VectorTool`、`RerankTool`、`AiRankingRunner`、`ConfigManager`**。
3. `SearchRepositoryFactory.create(...)` 再把 **`RerankTool`**（或 `None`）、**`AiRankingRunner`**、**`SearchContext`** 等透传给具体仓储。


可选：若 `search_api.py` 膨胀，可改为 `app/api/v1/search/router.py` 再在 `v1/__init__.py` 挂载；默认单文件即可。

### 3.1 FastAPI：`search_api.py` 要点

```python
# 结构示意（非完整实现）
router = APIRouter(tags=["Search"])

@router.post("/search", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    service: SearchService = Depends(get_search_service),
    # api_key: str | None = Depends(validate_api_key_optional),
) -> SearchResponse:
    ...
```

- 在 `app/api/v1` 聚合层使用 `prefix="/api/v1"` 包含该 router，使完整路径为 `/api/v1/search`。
- `tags=["Search"]` 便于 OpenAPI 分组。
- **`SearchRequest` / `SearchResponse` 从 `schemas` 导入**；Pydantic 在 **模型定义处**生效，路由层不重复校验。
- **`search_api` 里的参数校验**：**需要**，但 **不必手写**——FastAPI 将 body 解析为 `SearchRequest` 时，**Pydantic 自动完成校验**；本项目应通过统一异常处理将验证失败映射为 **400 + `{"error": "..."}`**。`search_api` 保持 **`response_model=SearchResponse`** 与业务异常映射即可。

### 3.2 `tag_query` 职责边界

- **仅做协议级处理**：解析 `query` 是否以 `[TAG]` 前缀开头、与 body `tag` 的优先级（与 [04](./04_API接口文档.md)「query 前缀优先」一致）、**规范化 `effective_tag`**。
- **输出 `query_for_search`**：去掉 **`[TAG]` 前缀及紧随空白** 后的字符串，**原样**作为后续检索用的查询文本；**不是**关键词抽取、同义扩展、LLM 查询改写或「从自然语言描述中提炼检索式」。此类能力 **默认在 Client 完成**；服务端只检索客户端提交的 `query`（经上述前缀剥离后的部分）。
- **读取 `tag_to_index_mapping`** 以解析目标 `index_name` 等行为，仍属本模块或与其紧邻的配置解析，**不**引入 NLP 依赖。

---

## 4. 核心类型与接口

### 4.1 内部 DTO（建议）

#### 基础枚举与结构化结果类型

建议先在 `schemas.py` 中固定以下基础类型，供 API、Service、Repository 共用：

- `IndexTag = Literal["CODE", "SCT", "BUILD", "SYNTAX", "SPEC", "ALG", "DESIGN", "FLOW", "SESSION", "SKILL"]`
- `SearchType = Literal["keyword", "title", "text", "vector", "hybrid"]`
- `FilterMode = Literal["none", "elbow", "gap_statistic"]`
- `ResultsKey = Literal["code", "sct", "build_method", "coding_standards", "requirement", "algorithm", "design", "flow", "session", "skill"]`

建议同步定义两类稳定的桶内 item：

| 类型 | 字段 | 说明 |
|------|------|------|
| `CodeSearchItem` | `relative_code_header_file`、`relative_code_source_file`、`relative_ut_file`、`relative_function_list` | 对应 04 的代码分组结果 |
| `SectionSearchItem` | `section_title`、`content` | 对应 04 的章节型结果 |

建议再定义两个聚合类型：

1. `RepositoryResult = dict[ResultsKey, list[CodeSearchItem] | list[SectionSearchItem] | list[dict]]`
2. `SearchResultsBuckets`：作为 `SearchResponse.results` 的结构化对象；字段集合固定为全部 `ResultsKey`，其中未执行的桶可省略，已执行但无命中的桶必须为 `[]`

#### `IndexSearchTask`

由 **`index_search_tasks.py`** 统一构造，建议定义为 **不可变 dataclass / Pydantic DTO**，确保 Service 并发调度过程中不会被仓储意外改写。

| 字段 | 含义 |
|------|------|
| `index_tag` | 当前任务归属的 index tag（如 `CODE` / `BUILD` / `SESSION`） |
| `index_name` | 当前任务的检索目标（ES/OpenSearch 索引名、Postgres 表/视图或逻辑标识） |
| `results_key` | 最终写入 `SearchResponse.results` 的桶键 |
| `query_for_search` | 去掉 `[TAG]` 前缀后的检索文本 |
| `original_query` | 原始请求 query；用于日志、AI prompt 或后续排障 |

设计约束：

1. **一个 `IndexSearchTask` 对应一次单 index 检索任务**。
2. `index_search_tasks` 在输出前完成 **去重**，避免同一 `(index_tag, index_name)` 重复调度。
3. Service 只消费该 DTO，**不**回写或追加运行态字段。

接口边界补充：

1. **Task Builder -> Service**：`index_search_tasks` 输出 `list[IndexSearchTask]` 给 `SearchService`。
2. **Service -> Repository**：`SearchService._search_one_task(task, ...)` 把单个 `IndexSearchTask` 传给 `BaseSearchRepository.build_query/search(...)`。
3. **不进入 API**：客户端既不会提交也不会收到 `IndexSearchTask`。

#### `SearchMatchRow`

**`SearchMatchRow`** 为仓储层与精炼层（Rerank / AI）之间的**最小共享中间结构**，用于屏蔽 ES/OpenSearch/Postgres 原始返回差异。

| 字段 | 含义 |
|------|------|
| `item_id` | 统一主键/文档标识 |
| `score` | 当前排序分数；允许在 Rerank 后被覆盖 |
| `title` | 可选标题（章节类仓储常用） |
| `content` | 主文本内容 |
| `metadata` | 结构化附加字段（路径、章节名、语言、来源等） |
| `raw_payload` | 可选；保留原始响应切片便于调试或兼容特殊映射 |

设计目的：

1. 避免让 **RerankTool / AiRankingRunner** 直接依赖某一种后端的返回格式。
2. 让最终格式化可在共享字段之上再映射到 04 的分桶响应结构。
3. 约束 Repository 精炼阶段的统一接口，避免同一条流水线里混入 `dict` / 后端原始 JSON。

接口边界补充：

1. **Repository 产出**：`map_backend_response_to_items(...)` 把底层原始响应映射为 `list[SearchMatchRow]`。
2. **Rerank / AI 消费并返回**：`RerankTool.rerank(...)`、`AiRankingRunner(...)` 的输入输出都应保持 `list[SearchMatchRow]`。
3. **不直接上浮给 Service**：Service 合并的是 Repository 已格式化的分桶结果，而不是 `SearchMatchRow` 列表。
4. **命名虽为 `map_backend_response_to_items`，但在本设计中其返回值固定为 `list[SearchMatchRow]`**；最终面向 `results_key` 的 item 组装由独立格式化步骤负责。

#### `SearchContext` / `request_ctx`

传给工厂与仓储的 **只读上下文**，建议至少包含：

- `effective_tag`
- `fetch_size`
- `backend_type`
- 便于日志追踪的请求标识（如 trace id / request id，若项目已有）

约束：仅承载**派生后的运行态元信息**，避免与 `req: SearchRequest`、`task: IndexSearchTask` 重复承载同一业务参数，更不要把整个 FastAPI `Request` 对象或不稳定的运行态对象直接透传进仓储。

字段责任固定如下：

1. **`req: SearchRequest`**：承载客户端原始业务参数，如 `search_type`、`top_k`、`vector_weight`、`enable_relation_search`、`filter_mode`、`ai_enable`、`ai_model`。
2. **`task: IndexSearchTask`**：承载单任务解析结果，如 `index_tag`、`index_name`、`results_key`、`query_for_search`。
3. **`request_ctx: SearchContext`**：承载本次调度派生出的运行态元信息，如 `fetch_size`、`backend_type`、`request_id`。

建议作为 dataclass / typed object 暴露的最小接口：

- `effective_tag: str | None`
- `fetch_size: int`
- `backend_type: str`
- `request_id: str | None`

#### `AiRankingRunner`

建议抽象为**异步可调用接口**（Protocol / callable object）：

- **输入**：`query_for_search`、`list[SearchMatchRow]`、`top_k`、`ai_model`、`SearchContext`
- **输出**：筛选/重排后的 `list[SearchMatchRow]`
- **失败语义**：解析失败、超时或 CLI 异常时，按 §5.5 **回退上一步结果并截断到 `top_k`**

#### `SearchClient`

建议抽象为统一接口，例如：

- `async search(target, query, size, *, backend, timeout=None, **kwargs) -> raw_response`

其职责不是做业务编排，而是：

1. 根据部署选择调用 **ES / OpenSearch / PostgreSQL** 客户端。
2. 统一超时、连接错误、协议错误的异常语义。
3. 把“底层检索成功但无结果”与“底层调用失败”区分清楚，供仓储层做不同处理。

**当前支持哪一种后端，如何识别**：

- 建议沿用 [01_架构总览.md](./01_架构总览.md) 的静态启动配置：**`settings.database_type`**，取值如 `elasticsearch` / `opensearch` / `postgres`。
- 应在应用启动时（lifespan / 容器初始化）**一次性确定**当前后端，并初始化对应 client / connection pool。
- **不建议增加动态配置来热切换后端类型**：这会影响连接生命周期、查询语法、索引/表结构、连接池与资源清理，属于**静态部署决策**而不是业务参数。
- 若确需支持“同一套代码可切换不同后端”，推荐：
  1. **静态配置**：`settings.database_type`
  2. **动态配置**：仅保留各后端内部的业务参数（如 `search.*`、`top_k`、模型开关等），**不**热切换后端种类

### 4.2 `BaseSearchRepository`（`repositories/base.py`）

**检索后端**：项目需同时支持 **Elasticsearch**、**OpenSearch**（与 ES 协议相近，可共用或分支 client）、**PostgreSQL**（关键词 / 向量字段 / `pgvector` 等，由部署与配置决定）。仓储实现通过 **`infrastructure`** 中的 **统一 `SearchClient` / adapter** 访问具体后端，**不在** feature 层硬编码单一引擎。**当前实例使用哪一种后端**，建议由静态 **`settings.database_type`** 在应用启动时确定，而**不是**由动态配置在运行时切换。

**类职责**：

1. 定义单索引检索的**共享骨架**。
2. 把“后端查询构建”和“结果映射”留给具体子类扩展。
3. 统一调用 `RerankTool`、`AiRankingRunner` 与失败降级逻辑。
4. 保证输出结构始终能被 `SearchService._merge_results` 消费。

**推荐构造注入项**：

| 依赖 | 用途 |
|------|------|
| `search_client: SearchClient` | 统一访问 ES/OpenSearch/Postgres |
| `rerank_tool: RerankTool | None` | 可选精排能力 |
| `ai_ranking_runner: AiRankingRunner | None` | 可选 AI 增强能力 |
| `config: ConfigManager` | 读取检索、Rerank、AI、索引映射等配置 |
| `request_ctx: SearchContext` | 透传 `fetch_size`、`backend_type`、`request_id` 等派生运行态上下文；**不重复承载** `req` / `task` 已有字段 |

**单索引流水线（推荐封装在一个入口内，例如 `search` 或 `search_and_refine`）**：

1. `build_query(...)` → 生成当前后端所需的 **查询载体**（ES/OpenSearch 的 body、或 Postgres 的 SQL/参数化查询等）；`fetch_size` 由 Service 按 **§4.4 `_initial_fetch_size`** 计算后传入。
2. 执行 **`SearchClient.search(...)`**（或等价）→ **原始响应**（JSON 或行集；引擎文档若称 `hits` 仅为底层术语）。
3. **`map_backend_response_to_items(raw_response)`** → `list[SearchMatchRow]`。
4. 若 **`search.rerank.enable`**：调用注入的 **`RerankTool.rerank`**，对当前列表重打分、重排序。
5. 若 **`req.ai_enable`**：调用 **`ai_ranking`（Copilot CLI）**，将列表筛到用户 **`top_k`**。
6. 若二者皆关：将列表截断到用户 **`top_k`**（按底层相关性分数即可）。
7. **`format_bucket_items(rows, *, task, req)`** → 映射成当前 `results_key` 对应的最终 bucket item 列表。
8. 返回 **本索引** 对应的结构化片段（供 Service 按 `results_key` 合并）。

| 方法 / 成员 | 说明 |
|-------------|------|
| `index_tag` / `results_key` | `ClassVar[str]`，与 04 分桶一致 |
| `build_query(...)` | 生成当前后端的查询；`vector` 由 **Service** 生成后传入，**不**调用 `VectorTool` |
| `map_backend_response_to_items(raw_response)` | 统一把 **各后端原始结果** 转为 **`list[SearchMatchRow]`** |
| `format_bucket_items(rows, *, task, req)` | 将最终 `SearchMatchRow` 列表映射为当前分桶的 item 列表（代码分组或章节项） |
| `async def search(...)`（或拆分步骤） | 完成上述 1～8；构造器或工厂注入 **`SearchClient`、RerankTool、AI 运行器（Copilot CLI）、`ConfigManager`、请求上下文** |

**禁止**：在 Repository 内 **`new` 向量模型 / Rerank 模型 / Copilot 子进程门面**；须 **依赖注入**。**允许**在 Repository 内调用 **`RerankTool` 与 `ai_ranking`（Copilot CLI）**（在 **首次检索** 完成之后），与「最初分层：精炼紧跟单次索引检索」一致。

`BaseSearchRepository.search(...)` 建议主流程：

1. 根据 `search_type`、`vector`、`index_name` 调 `build_query(...)`。
2. 通过 `SearchClient.search(...)` 发起底层检索。
3. `map_backend_response_to_items(...)` 映射为 `list[SearchMatchRow]`。
4. 若启用 Rerank，则调 `RerankTool.rerank(...)`。
5. 若启用 AI，则调 `AiRankingRunner(...)`；失败则按 §5.5 回退上一步结果。
6. 截断到 `top_k`。
7. 调 `format_bucket_items(...)` 映射成当前仓储对应的分桶结构并返回。

**统一接口约定**（供所有具体仓储继承/实现）：

```python
class BaseSearchRepository(ABC):
    index_tag: ClassVar[str]
    results_key: ClassVar[str]

    @abstractmethod
    def build_query(self, *, task: IndexSearchTask, req: SearchRequest, vector) -> object: ...

    @abstractmethod
    def map_backend_response_to_items(self, raw_response) -> list[SearchMatchRow]: ...

    @abstractmethod
    def format_bucket_items(
        self,
        rows: list[SearchMatchRow],
        *,
        task: IndexSearchTask,
        req: SearchRequest,
    ) -> list[dict]: ...

    async def search(self, *, task: IndexSearchTask, req: SearchRequest, fetch_size: int, vector=None) -> dict: ...
```

说明：

1. 具体仓储至少需要实现 **`build_query(...)`**、**`map_backend_response_to_items(...)`** 与 **`format_bucket_items(...)`**。
2. **`search(...)`** 建议由基类提供共享骨架，具体子类只覆写必要步骤。
3. 若某一 index 需要特殊聚合，也应保持最终返回值仍为 **`{results_key: [...]}`** 结构。

### 4.2.1 `search_type` 与 Repository / 向量化的关系

请求体 **`search_type`**（及 [03](./03_配置管理设计.md) / [04](./04_API接口文档.md) 中的 **`search_types`** 配置）决定 **查询如何构建**，**不是**所有方式都要对 `query` 做向量化。

| `search_type`（与 04 枚举一致） | 典型查询形态 | **是否需要** Service 侧 `VectorTool` 生成 query 向量 |
|--------------------------------|--------------|--------------------------------------------------------|
| `keyword` / `title` / `text` | 全文、标题、正文字段等 **关键词/BM25 类** DSL 或 SQL | **否**，`vector` 传 **`None`**（除非实现上把某类 `text` 扩展为稠密检索，需在项目内单独约定） |
| `vector` | **kNN / script_score** 等仅向量检索 | **是** |
| `hybrid` | 关键词 + 向量 **加权**（`vector_weight`） | **是** |

**Repository 差异**：各具体仓储（`code.py` 等）的 **`build_query(...)`** 根据 **`search_type` + `req`** 分支：拼接 **bool/match**、**knn**、或 **混合子句**；**公共流水线**（`SearchClient.search` → `map_backend_response_to_items` → Rerank → Copilot → `format_bucket_items`）不变。**占位仓储**（SESSION/SKILL 本切片）**不调** `build_query` 与后端，也 **不调** `VectorTool`。

### 4.3 `SearchRepositoryFactory`（`repositories/factory.py`）

`create(index_tag: str, *, search_client, rerank_tool, ai_ranking_runner, request_ctx, ...) -> BaseSearchRepository`（签名以实现为准；须把 **检索客户端 / Rerank / AI（Copilot CLI）/ 请求上下文** 传入具体仓储类）：

**类职责**：

1. 根据 `index_tag` 选择具体 `*SearchRepository`。
2. 为所有仓储提供一致的构造依赖（`SearchClient`、`RerankTool`、`AiRankingRunner`、`ConfigManager`、`SearchContext`）。
3. 对已知但本切片未实现的 tag（SESSION/SKILL）返回 **`EmptySearchRepository`**。
4. 对未知/非法 tag 抛出显式异常，而不是静默降级。

| `index_tag` | 实现类 | `results_key`（与 04 一致） |
|----------|--------|----------------------------|
| `CODE` | `CodeSearchRepository` | `code` |
| `SCT` | `SctSearchRepository` | `sct` |
| `BUILD` | `BuildSearchRepository` | `build_method` |
| `SYNTAX` | `SyntaxSearchRepository` | `coding_standards` |
| `SPEC` | `SpecSearchRepository` | `requirement` |
| `ALG` | `AlgSearchRepository` | `algorithm` |
| `DESIGN` | `DesignSearchRepository` | `design` |
| `FLOW` | `FlowSearchRepository` | `flow` |
| `SESSION` | **本切片**：`EmptySearchRepository`（或等价占位） | `session`（本切片固定返回 `[]`） |
| `SKILL` | **本切片**：同上 | `skill`（本切片固定返回 `[]`） |

**`SESSION` / `SKILL` 与任务列表**：**主 tag** 仅对应 **单主任务** 时，或 **`enable_hit` 展开** 时，均可映射到上述 tag；工厂返回 **占位仓储**，`search()` **不调后端**、立即返回空分桶，从而 **上层无需维护「要扣掉哪些 tag」列表**。待 Session/Skill 检索实现后，仅在工厂 **替换**为真实 `SessionSearchRepository` / `SkillSearchRepository` 即可。

**未知 / 非法 `index_tag`**（例如配置错误、非预期枚举）：建议抛出显式异常并由 Service 映射 **500**；与「占位」区分：**占位用于已知但未实现的业务 tag**，**异常用于不应出现的内部任务**，不应归因为客户端输入。

`SearchRepositoryFactory.create(...)` 建议主流程：

1. 校验 `index_tag` 是否在受支持集合内。
2. 若为 `SESSION` / `SKILL`，直接构造 `EmptySearchRepository`。
3. 否则选择具体仓储类，并注入共享依赖。
4. 返回与 `BaseSearchRepository` 兼容的实例，供 Service 透明调用。

#### 4.3.1 `EmptySearchRepository`

`EmptySearchRepository` 的设计目标是让“主 tag 未实现”和“`enable_hit` 子任务未实现”都走**同一套编排路径**。

建议约定：

1. 与真实仓储保持**同签名** `search(...)`，便于 Factory 对外返回统一类型。
2. **不调用** `SearchClient`、`RerankTool`、`AiRankingRunner`、`VectorTool`。
3. 直接返回当前 `results_key` 对应的**空分桶结构**，使 `SearchService._merge_results` 无需识别特例。
4. 该空分桶仍参与 `SearchResponse.total` 计算，但因长度为 `0` 不影响总数。

#### 4.3.2 各 index 仓储差异

**各具体仓储的共同接口设计**：

- 继承：`BaseSearchRepository`
- 必备类属性：`index_tag`、`results_key`
- 必备实现：`build_query(...)`、`map_backend_response_to_items(...)`、`format_bucket_items(...)`
- 默认复用：`search(...)` 共享流水线

若个别 index 需要特殊逻辑（如代码聚合、章节拼装），允许覆写 `search(...)` 的内部步骤，但**不应**改变统一输入/输出契约。

为避免与 **§3 模块文件结构** 脱节，各仓储类与文件名采用**一类一文件、文件名与 tag 小写对齐**的约定；占位仓储单独放在 `empty.py`。对应关系如下：

| 仓储类 | 文件 | `index_tag` | `results_key` |
|--------|------|-------------|---------------|
| `CodeSearchRepository` | `repositories/code.py` | `CODE` | `code` |
| `SctSearchRepository` | `repositories/sct.py` | `SCT` | `sct` |
| `BuildSearchRepository` | `repositories/build.py` | `BUILD` | `build_method` |
| `SyntaxSearchRepository` | `repositories/syntax.py` | `SYNTAX` | `coding_standards` |
| `SpecSearchRepository` | `repositories/spec.py` | `SPEC` | `requirement` |
| `AlgSearchRepository` | `repositories/alg.py` | `ALG` | `algorithm` |
| `DesignSearchRepository` | `repositories/design.py` | `DESIGN` | `design` |
| `FlowSearchRepository` | `repositories/flow.py` | `FLOW` | `flow` |
| `EmptySearchRepository` | `repositories/empty.py` | `SESSION` / `SKILL` | `session` / `skill` |

调用关系也固定为：

1. `SearchService` 不直接 import 具体仓储文件，只调用 `SearchRepositoryFactory.create(index_tag=...)`。
2. `SearchRepositoryFactory` 内部维护 `index_tag -> Repository class` 的映射，再实例化对应文件中的类。
3. 因此 **§3 的文件名**是“代码落位”，**§4.3.2 的仓储类名**是“类型名/实现名”，二者是一一对应关系，不是两套独立概念。

- `CodeSearchRepository`
  - 面向代码知识；通常需要把多个函数/文件片段聚合成“按文件分组”的输出。
  - `map_backend_response_to_items(...)` 更强调路径、函数列表、测试文件等元数据；`format_bucket_items(...)` 负责真正聚合成 `CodeSearchItem`。
  - `results_key = "code"`。
  - 接口实现重点：`build_query(...)` 更偏源码/头文件/函数级字段，`format_bucket_items(...)` 需聚合成代码分组结果。

- `SctSearchRepository`
  - 面向 SCT 测试用例与章节化测试内容。
  - 输出更偏 `section_title + content` 形式。
  - `results_key = "sct"`。
  - 接口实现重点：`format_bucket_items(...)` 返回章节型结构，而不是文件聚合结构。

- `BuildSearchRepository`
  - 面向编译方法/构建步骤。
  - 查询时通常会优先覆盖标题、步骤说明、命令片段等字段。
  - `results_key = "build_method"`。
  - 接口实现重点：命令片段、步骤标题和说明字段优先。

- `SyntaxSearchRepository`
  - 面向编码规范、语法规则、风格约束。
  - 更偏规范条目/章节映射，而非文件聚合。
  - `results_key = "coding_standards"`。
  - 接口实现重点：规范标题、规则正文和示例字段映射。

- `SpecSearchRepository`
  - 面向需求规格、功能定义、接口契约性描述。
  - 查询结果通常以需求章节/条目回包。
  - `results_key = "requirement"`。
  - 接口实现重点：规格章节/条目型映射。

- `AlgSearchRepository`
  - 面向算法说明、原理、策略和相关实现背景。
  - 可根据项目数据模型重点映射算法标题、公式说明、设计说明等字段。
  - `results_key = "algorithm"`。
  - 接口实现重点：算法标题、原理和策略说明的字段选择。

- `DesignSearchRepository`
  - 面向设计文档、模块设计、架构说明。
  - 与 `Spec`/`Flow` 的差异主要在字段来源与结果语义。
  - `results_key = "design"`。
  - 接口实现重点：模块/架构章节映射。

- `FlowSearchRepository`
  - 面向流程文档、时序步骤、业务流或技术流说明。
  - 更适合返回步骤化章节或流程片段。
  - `results_key = "flow"`。
  - 接口实现重点：步骤化、流程化内容的结构化回包。

上述仓储的**共享点**是：都复用同一检索/Rerank/AI 骨架；**主要差异**集中在 `build_query(...)` 的字段选择、`map_backend_response_to_items(...)` 的原始结果归一化，以及 `format_bucket_items(...)` 的最终分桶映射。

### 4.4 `SearchService`（`search_service.py`）

| 方法 | 说明 |
|------|------|
| `async def search(self, req: SearchRequest) -> SearchResponse` | 对外唯一入口 |
| `_resolve_effective_tag_and_query(req)` | 调 `tag_query` |
| `_resolve_index_name(...)` | `tag_to_index_mapping` |
| `_build_index_search_tasks(...)` | `index_search_tasks`；**不**在此处过滤 SESSION/SKILL |
| `_initial_fetch_size(user_top_k, req)` | **首次检索条数上限**（ES/OpenSearch 的 `size`、Postgres 的 `LIMIT` 等语义对齐），传入各 `Repository.search(..., fetch_size=...)`。记 `Mr = search.rerank.top_k_multiplier`（仅当 `search.rerank.enable`）、`Ma = search.ai.top_k_multiplier`（仅当 `req.ai_enable`）。**仅 Rerank**：`size = min(user_top_k × Mr, max_top_k)`。**仅 AI**：`size = min(user_top_k × Ma, max_top_k)`。**二者皆开**：**有效倍数取大** — `M = max(Mr, Ma)`，`size = min(user_top_k × M, max_top_k)`。**皆关**：`size = user_top_k`。 |
| `async def _search_one_task(self, task, req, fetch_size)` | 若 **`factory.create` 为占位仓储**（SESSION/SKILL 本切片等）：**跳过 `VectorTool`**，直接 **`await repository.search(...)`**（零后端）。否则：先 **`create`** 再按 **`search_type`（§4.2.1）** 决定是否调用 **`VectorTool`**（`keyword`/`title`/`text` 通常 **不调**）→ **`await repository.search(...)`**（**首次检索** → Rerank → Copilot AI → 本分桶）；**不再**在 Service 里调用 `_rerank_if_needed` / `_ai_filter_if_needed`。 |
| `_merge_results(task_results) -> SearchResultsBuckets` | 将各索引返回的分桶片段合并为 04 的 `results`（`enable_hit` 多 key 并存）；**保留已执行任务的空桶** |

**处理顺序（本切片约定）**：`asyncio.gather` 并行 **各索引的 `Repository` 完整流水线**（内序：**首次检索 → Rerank（若开）→ Copilot AI 筛选（若 `ai_enable`）→ 本索引 `top_k`**）→ Service **`_merge_results`** → `SearchResponse`。**Rerank 与 AI 仍是不同技术**；仅 **首次检索扩大倍数**在二者同开时用 **`max(Mr, Ma)`** 一次取够候选。

`SearchService.search(...)` 建议职责：

1. 调 `tag_query` 得到 `effective_tag` 与 `query_for_search`。
2. 调 `index_search_tasks` 构造 `IndexSearchTask` 列表。
3. 计算 `fetch_size`，并按 `search_type` 决定是否生成向量。
4. 借助 `SearchRepositoryFactory` 并发执行各任务。
5. 合并多分桶结果。
6. 按 **`sum(len(bucket) for bucket in results.values())`** 计算 `total`。
7. 返回 `SearchResponse`。

**类接口设计建议**：

```python
class SearchService:
    def __init__(
        self,
        *,
        search_client: SearchClient,
        vector_tool: VectorTool,
        rerank_tool: RerankTool | None,
        ai_ranking_runner: AiRankingRunner | None,
        config: ConfigManager,
    ) -> None: ...

    async def search(self, req: SearchRequest) -> SearchResponse: ...
    def _resolve_effective_tag_and_query(self, req: SearchRequest) -> tuple[str | None, str]: ...
    def _resolve_index_name(self, ...) -> str: ...
    def _build_index_search_tasks(self, req: SearchRequest, effective_tag: str | None) -> list[IndexSearchTask]: ...
    async def _search_one_task(self, task: IndexSearchTask, req: SearchRequest, fetch_size: int): ...
    def _merge_results(self, task_results: list[dict]) -> SearchResultsBuckets: ...
```

约束：

1. `SearchService` 只做编排，不直接实现后端查询。
2. 所有外部依赖均通过构造注入或 `dependencies.py` 装配。
3. `_search_one_task(...)` 是 Service 到 Repository 的唯一单任务桥接入口。

---

## 5. SearchService 时序说明

### 5.1 解析顺序

1. 若 `query` 匹配 `^\[(?P<tag>[A-Za-z_]+)\]\s*`：提取 `tag`，得到 **`query_for_search`**（已去掉前缀及紧随空白）；与 body `tag` 冲突时 **以 query 前缀为准**（与 04「query 前缀优先」一致）。
2. 将提取或传入的 tag 规范化为大写，映射到 `IndexTag`；无效则视为未指定（等同 CODE + `index_name`），与 04「无效 tag 忽略」一致。
3. **`SESSION` / `SKILL`（含主 tag）不触发 Service 短路**：继续 **`index_search_tasks` 构建任务列表** → `gather` → 工厂 **占位仓储** → `merge_results`，对外仍满足 §1.4 的 **200 与空分桶**。

### 5.2 `index_name` 解析

- 查 `search_types.tag_to_index_mapping`（见 [03_配置管理设计.md](./03_配置管理设计.md)）。
- 映射值为 `null` 或对应 `CODE`：当前任务的 `index_name` = 请求体 `index_name`。
- 否则：当前任务的 `index_name` = 配置中的逻辑名（部署层可再加前缀如 `test_`，与运维约定一致，不在本文档硬编码）。

### 5.3 `enable_hit`

1. 若为 `false`：仅主检索 `index_name` 对应的一个 `IndexSearchTask`。
2. 若为 `true`：读取 `search_types.hit_list`，**按配置原样展开**（**不**在 `index_search_tasks` / Service 中移除 SESSION、SKILL）。
3. 对 `hit_list` 中每个 tag：映射出 `index_name`；**跳过与主任务完全相同的 (tag, index_name)** 以免重复查询。
4. 主任务始终在列表中（即使也在 hit_list 中出现，去重仅保留一次）。
5. 任务中的 **SESSION / SKILL**（含 **仅主任务** 时的主 tag）在 **`SearchRepositoryFactory.create`** 中落到 **占位仓储**，检索阶段 **零后端调用**、合并时得到空列表；后续实现真实仓储时 **只改工厂注册**，不动 `index_search_tasks`。

### 5.4 并行调度与单索引流水线

- `asyncio.gather` 并发执行多个 `_search_one_task`。
- 每个任务：`fetch_size = _initial_fetch_size`（**Rerank 与 AI 同开时** `size = user_top_k × max(Mr, Ma)`，见 §4.4）→ **`factory.create` 得仓储**；若为 **占位仓储**则 **不调 `VectorTool`**，否则按 **§4.2.1** **`search_type`** 决定 **是否** `VectorTool` → **`await repository.search(...)`**（占位仓储可忽略 `fetch_size`）。
- **在 `Repository.search` 内部**（同一索引、一次调用内；占位仓储直接返回空分桶）：**首次检索 → `map_backend_response_to_items`（统一转 `SearchMatchRow`）→（若开）RerankTool →（若 `ai_enable`）ai_ranking（Copilot CLI）→ 截断到本索引 `top_k` → `format_bucket_items`**。
- 全部任务结束后，**仅在 Service** 执行 **`_merge_results`**，组装 `SearchResponse`；`total` 为各桶长度之和。

### 5.5 AI 增强在仓储内的要点（`ai_enable` / `ai_model`）

- 与 **Rerank** 独立：Rerank 为 **`RerankTool`**；AI 为 **`ai_ranking`（Copilot CLI）** + **`copilot_config`**。
- **默认**各索引在仓储流水线内 **Rerank（若开）之后** 再 **Copilot 筛选**至 `top_k`（与 §4.2 一致）。
- **解析失败、超时或 CLI 异常时的降级策略**：**直接回退到上一步结果**，并**取前 `top_k` 个**作为该索引最终结果。
  - 若开启了 Rerank，则“上一步结果”指 **Rerank 后结果**。
  - 若未开启 Rerank，则“上一步结果”指 **首次检索结果**。

时序图见：[pumls/search_flow_with_hit_and_rerank_sequence.puml](./pumls/search_flow_with_hit_and_rerank_sequence.puml)。

---

## 6. 配置依赖

| 配置路径 | 用途 |
|----------|------|
| `search_types.tag_to_index_mapping` | 主检索 `index_name` 与 **`enable_hit` 关联索引**解析（配置名 `hit_list`；非 thinking「hit」） |
| `search_types.hit_list` | `enable_hit` 扩展列表（**完整**展开；SESSION/SKILL 由工厂占位处理） |
| `search_types.available` | 校验 `search_type`（可选） |
| `search.max_top_k` / `search.default_top_k` | `top_k` 默认值与上限 |
| `search.rerank.enable` | 是否启用 **Rerank（重排序模型）**；与 `ai_enable` **独立** |
| `search.rerank.top_k_multiplier` | **仅** Rerank 路径：相对用户 `top_k` 的 **首次检索**扩大倍数（cross-encoder 输入规模） |
| `search.rerank.default_model` | Rerank 模型（如 bge-reranker-base） |
| `search.ai.enable` | 可选全局默认；与请求 `ai_enable` 关系由产品决定（通常请求优先） |
| `search.ai.top_k_multiplier` | **仅 AI 开**时用于 **首次检索条数**；**与 Rerank 同开**时参与 **`max(本值, rerank.top_k_multiplier)`**，再乘 `top_k` |
| `search.ai.default_model` | 与请求体 `ai_model` 默认值对齐时可引用（若与 `copilot_config.default_model` 重复，实现上择一为主或二者必须一致） |
| `search.ai.allowed_models` | **可选**；若未配置，则以 **`copilot_config.available_models`** 作为 `ai_model` 校验来源 |
| `copilot_config.cli_path` | Copilot 可执行文件路径（热更新） |
| `copilot_config.workspace_root` | CLI 工作目录 |
| `copilot_config.available_models` | `ai_model` 允许列表（热更新） |
| `copilot_config.default_model` | 未传 `ai_model` 时的回退 |
| `vector_models.models` | `vector_model` 合法性 |

热更新边界见 [README.md](./README.md) 配置表：业务参数可 reload。**Copilot CLI** 的登录态 / 令牌由 **CLI 与运行环境** 管理，**不写进**动态 YAML；**Elasticsearch / OpenSearch / PostgreSQL** 等连接串通常 **不可热更新**（与运维策略一致）。

**后端类型选择**：建议使用静态配置 **`settings.database_type`**（见 [01_架构总览.md](./01_架构总览.md) 的应用启动流程），在启动时决定当前实例绑定 **Elasticsearch / OpenSearch / PostgreSQL**。**不建议**在 `dynamic_config.yaml` 中增加“当前后端类型”并热切换。

---

## 7. 与 PlantUML 的对应关系

流程图文件：

- 主流程图：[pumls/search_flow_with_hit_and_rerank.puml](./pumls/search_flow_with_hit_and_rerank.puml)
- 时序图：[pumls/search_flow_with_hit_and_rerank_sequence.puml](./pumls/search_flow_with_hit_and_rerank_sequence.puml)

| 图中分区 / 步骤 | 代码归属 |
|-----------------|----------|
| 校验 `SearchRequest` | **`schemas.py`（Pydantic）**；`search_api` 仅 `response_model` 与异常映射（§2.1） |
| 解析 `[TAG]`、`tag_to_index_mapping` | `tag_query` + `ConfigManager` |
| `enable_hit` + **完整** `hit_list` | `index_search_tasks`；SESSION/SKILL（含 **主 tag 单任务**）均由 **工厂占位** → `merge_results` |
| 首次检索 `fetch_size` | `SearchService._initial_fetch_size`（§4.4；**Rerank+AI 同开** 时倍数 = **`max(Mr, Ma)`**） |
| 并行 | `asyncio.gather` + 多 `IndexSearchTask` |
| `SearchRepositoryFactory.create` | 注入 **`SearchClient`**、`RerankTool`、**AI 运行器（Copilot）**、`request_ctx`；未实现 tag → **占位仓储** |
| 仓储内检索 | `repository.search` 内 **`SearchClient` + `map_backend_response_to_items`**（统一产出 `SearchMatchRow`；ES / OpenSearch / Postgres 等；占位仓储跳过） |
| 仓储内 Rerank | `RerankTool.rerank`（`search.rerank.enable`） |
| 仓储内 AI | `ai_ranking` + **`copilot_config`**（`ai_enable`） |
| 仓储内结果格式化 | `format_bucket_items(...)`（`SearchMatchRow` → `CodeSearchItem` / `SectionSearchItem`） |
| SESSION/SKILL **空分桶（主 tag 与子任务）** | **统一**：`SearchRepositoryFactory` → **占位仓储** → `merge_results`（§1.4；**无** Service 级短路） |
| 合并与响应 | `SearchService._merge_results` + `search_api`；`total = sum(len(bucket) for bucket in results.values())` |

**可视化提示**：该活动图含多泳道与注释，在线渲染时建议使用 [PlantUML 服务](http://earth.benben.eecloud.dynamic.nsn-net.net:9400/uml/) 的 **SVG** 模式，避免 PNG 过长被截断。

---

## 8. 实现检查清单（本切片交付）

- [ ] `search_api.py` 仅依赖 `SearchService` 与 schemas，异常映射符合 04。
- [ ] Repository **通过注入** 调用 `RerankTool` / **AI 运行器（Copilot CLI）**；**不**在仓储内 `new` Rerank 模型或子进程封装；**不**调用 `VectorTool`（向量在 Service 生成）。
- [ ] `index_search_tasks` **不**裁剪 `hit_list`；**`SearchRepositoryFactory`** 对 SESSION/SKILL 返回 **占位仓储**（空分桶）。
- [ ] **主 tag** SESSION/SKILL：**无** `SearchService` 早期短路；走任务列表 + 占位 + `merge`，对外 **200 空结果**（§1.4）；占位路径 **跳过 `VectorTool`**。
- [ ] **Rerank** 与 **AI** 分路径、分配置；同开时 **首次检索**条数使用 **`top_k × max(rerank_top_k_multiplier, ai_top_k_multiplier)`**（§4.4）；流水线在 **Repository** 内 **检索 → `SearchMatchRow` 归一化 → Rerank → Copilot AI → `format_bucket_items`**；支持 **ES / OpenSearch / Postgres** 由 **`SearchClient`** 切换。
- [ ] `ai_enable` / `ai_model`：**Copilot CLI 筛选至 top_k**（§5.5），`ai_model` 与 **`copilot_config.available_models`** 对齐，与 04 示例一致。
- [ ] `SearchResponse.results` 使用固定桶键集合，已执行但空结果的桶返回 `[]`；`total` 为全部桶长度之和。
- [ ] OpenAPI 示例与 04 示例请求体对齐（含 AI 示例）。

---

## 9. 文档索引

- [04_API接口文档.md](./04_API接口文档.md)
- [02_分层职责详解.md](./02_分层职责详解.md)
- [03_配置管理设计.md](./03_配置管理设计.md)
- [pumls/search_flow_with_hit_and_rerank.puml](./pumls/search_flow_with_hit_and_rerank.puml)
