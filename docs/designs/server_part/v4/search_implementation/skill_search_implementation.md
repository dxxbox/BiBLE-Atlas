# SKILL Search 详细开发指南（v4）

本文档给出 `POST /api/search/skill` 的落地实现方案，覆盖：

- API 入参约束
- 服务层编排
- `search_profile -> DSL` 编译规则
- `keyword/text/vector/hybrid` 四类检索策略
- 检索结果组装与错误码

---

## 1. 适用范围

- 仅覆盖 `POST /api/search/skill`。
- 请求体字段沿用 `02_API接口文档.md`（`query/tag/kb_index/search_type/top_k/vector_model/vector_weight`）。
- `tag` 固定为 `skill`，检索目标数据来自 SKILL 导入产物（`SKILL.md` 解析出的 `name/description/body/content`）。
- `kb_index` 可选；提供时按 `domain=SKILL + kb_index` 精确查找绑定，未提供时按 `domain=SKILL + tag=skill` 查找 active binding。

---

## 2. 组件清单（建议）

1. `app/api/search/skill_search_api.py`（`SkillSearchAPI`）
2. `app/features/search/skill_search/skill_search_service.py`（`SkillSearchService`）
3. `app/features/search/skill_search/searcher/search_skill.py`（`SkillSearcher`）
4. `app/features/search/common/query_profile_compiler.py`（`QueryProfileCompiler`，通用组件）
5. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
6. `app/infrastructure/database/base.py`（绑定读取与查询执行网关接口）
7. `app/infrastructure/database/opensearch/*`（默认后端实现）
8. `app/infrastructure/vector/vector_tool.py`（向量模型就绪与查询向量生成）

---

## 3. 数据与字段约定（SKILL）

导入阶段（见 `import_implementations/skill_import_implementation.md`）已写入以下核心字段：

- 语义字段：`name`、`description`、`body`、`content`
- 展示字段：`title`（建议等于 `name`）
- 关联字段：`metadata.related_storage_paths`（来自本地存储计划回填）

检索侧的最小返回建议：

- `doc_id`
- `name`
- `description`
- `body`
- `content`
- `metadata.related_storage_paths`
- `score`（由 `_score` 映射）

约束：

- 不返回 `chunk_id`
- 不返回 `took_ms`

---

## 4. 搜索类型映射（SKILL 专项）

结合已确认规则，SKILL 域固定映射如下：

1. `keyword`
   - 主匹配字段：`name.keyword`
2. `text`
   - 匹配字段：`name/description/body`（可附带 `content` 兜底）
3. `vector`
   - 向量源模板：`name + description + body`
4. `hybrid`
   - 文本与向量混合打分

兼容约定：

- `search_type=title` 时，SKILL 域按 `name` 等价处理（避免额外分叉字段）。

---

## 5. `search_profile` 约定（SKILL）

导入阶段绑定到索引的 `search_profile` 至少包含：

```json
{
  "keyword": {
    "fields": ["name.keyword^5"]
  },
  "text": {
    "fields": ["name^4", "description^2", "body^1.5", "content^1"]
  },
  "vector": {
    "vector_field": "content_vector",
    "source_template": "{name}\n{description}\n{body}",
    "num_candidates": 100
  },
  "hybrid": {
    "default_vector_weight": 0.5
  },
  "response_fields": [
    "doc_id",
    "name",
    "description",
    "body",
    "content",
    "metadata.related_storage_paths",
    "score"
  ]
}
```

说明：

- 具体结构可由域内编译器做兼容（例如支持 `search_type_profile` 包裹层），但落地时建议保持稳定格式，便于 `search_profile_sha256` 一致性校验。

---

## 6. 服务层实现（`SkillSearchService`）

建议接口：

```python
def search(
    self,
    query: str,
    tag: str,
    search_type: str | None,
    top_k: int | None,
    vector_model: str | None,
    vector_weight: float | None,
    kb_index: str | None = None,
) -> dict[str, Any]: ...
```

建议流程：

1. 参数校验（`query/tag` 必填，`tag == "skill"`）。
2. 读取绑定记录（至少拿到 `kb_index/search_profile/vector_model`）：
   - 若请求显式携带 `kb_index`，调用 `get_binding_by_domain_index(SKILL, kb_index)` 精确查找。
   - 否则调用 `get_binding_by_domain_tag(SKILL, tag)`，保持旧客户端兼容。
3. 解析并标准化 `search_type/top_k/vector_weight`。
4. 做向量模型一致性校验：
   - 请求显式带 `vector_model` 时，必须与绑定模型一致。
5. 调用 `SkillSearcher.search(...)` 执行检索。
6. 组装统一响应结构返回。

---

## 7. Searcher 与 DSL 编译

## 7.1 `SkillSearcher` 建议接口

```python
def search(
    self,
    kb_index: str,
    query: str,
    search_type: str,
    top_k: int,
    search_profile: dict[str, Any],
    vector_model: str | None,
    vector_weight: float | None,
) -> list[dict[str, Any]]: ...
```

## 7.2 `QueryProfileCompiler` 输入输出

输入：

- `search_type`
- `query`
- `top_k`
- `search_profile`
- `vector_weight`（hybrid 时可覆盖默认值）
- `query_vector`（vector/hybrid 场景）

输出：

- OpenSearch DSL（`dict[str, Any]`）

---

## 8. DSL 规则（SKILL）

### 8.1 `keyword`

- 使用 `term` 查询 `name.keyword`
- boost 来自 `keyword.fields`

### 8.2 `text`

- 使用 `multi_match`
- fields 来源 `text.fields`

### 8.3 `vector`

- 使用 `knn` 查询（如 `content_vector`）
- `query_vector` 由 `VectorTool` 基于 `query` 生成

### 8.4 `hybrid`

- 文本查询（`multi_match`）+ `knn` 同次请求混合
- 权重：
  - `vector_weight` 优先使用请求值
  - 缺省回退 `search_profile.hybrid.default_vector_weight`
  - 文本权重为 `1 - vector_weight`

---

## 9. 向量模型处理（检索时）

仅在 `search_type` 为 `vector/hybrid` 时生效：

1. 确认绑定模型存在（或请求模型与绑定模型一致）。
2. `VectorTool.ensure_model_ready(model)`。
3. `VectorTool.embed_query(query, model)` 得到 `query_vector`。
4. 传给 DSL 编译器构造 `knn`。

---

## 10. 结果组装规则

命中项映射建议：

- `_source.doc_id -> doc_id`
- `_source.name -> name`
- `_source.description -> description`
- `_source.body -> body`
- `_source.content -> content`
- `_source.metadata.related_storage_paths -> related_storage_paths`
- `_score -> score`

响应骨架（示例）：

```json
{
  "success": true,
  "domain": "SKILL",
  "kb_index": "kb_skill_main",
  "tag": "skill",
  "total": 3,
  "results": {
    "skill": [
      {
        "doc_id": "skill_3b8f4b8d9e6d",
        "name": "k8s-log-cleaner",
        "description": "Clean stale k8s logs safely.",
        "content": "...",
        "related_storage_paths": ["/mnt/skill/2026/05/demo.png"],
        "score": 0.82
      }
    ]
  }
}
```

---

## 11. 错误码建议（检索侧）

- `INVALID_ARGUMENT`：参数格式错误（如 `top_k<=0`）
- `TAG_INVALID`：`tag != "skill"`
- `INDEX_NOT_BOUND`：未找到 SKILL 绑定
- `VECTOR_MODEL_CONFLICT`：请求模型与绑定模型不一致
- `SEARCH_TYPE_INVALID`：不支持的 `search_type`
- `SEARCH_PROFILE_INVALID`：绑定的 `search_profile` 不可编译
- `INTERNAL_ERROR`：数据库或未知内部异常

---

## 12. 测试清单（建议）

1. `tag=skill` 的 `keyword` 检索命中 `name`
2. `text` 检索命中 `name/description/body`
3. `vector` 检索使用 `name/description/body` 模板向量
4. `hybrid` 检索按文本+向量混合打分
5. `title` 检索按 `name` 等价处理
6. `vector_model` 冲突时返回 `VECTOR_MODEL_CONFLICT`
7. 无绑定返回 `INDEX_NOT_BOUND`
8. 返回结果包含 `related_storage_paths`
9. 不返回 `chunk_id`、不返回 `took_ms`
10. 相同查询在固定配置下结果稳定（排序抖动在可接受阈值内）

