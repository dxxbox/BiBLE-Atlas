# KNOWLEDGE_BASE Search 详细开发指南（v4）

本文档给出 `POST /api/search/knowledge-base` 的落地实现方案，覆盖：

- API 入参约束
- 服务层编排
- `search_profile -> DSL` 编译规则
- `keyword/title/text/vector/hybrid` 检索策略
- 检索结果组装与错误码

---

## 1. 适用范围

- 仅覆盖 `POST /api/search/knowledge-base`。
- 请求体字段沿用 `02_API接口文档.md`（`query/tag/kb_index/search_type/top_k/vector_model/vector_weight`）。
- `tag` 为 KNOWLEDGE_BASE 子类型标识（如 `design/flow/alg`），通过绑定记录映射到实际 `kb_index` 与 `search_profile`。
- `kb_index` 可选；提供时按 `domain=KNOWLEDGE_BASE + kb_index` 精确查找绑定，未提供时按 `domain=KNOWLEDGE_BASE + tag` 查找 active binding。

---

## 2. 组件清单（建议）

1. `app/api/search/knowledge_base_search_api.py`（`KnowledgeBaseSearchAPI`）
2. `app/features/search/knowledge_base_search/knowledge_base_search_service.py`（`KnowledgeBaseSearchService`）
3. `app/features/search/knowledge_base_search/searcher/search_knowledge_base.py`（`KnowledgeBaseSearcher`）
4. `app/features/search/common/query_profile_compiler.py`（`QueryProfileCompiler`，通用组件）
5. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
6. `app/infrastructure/database/base.py`（绑定读取与查询执行网关接口）
7. `app/infrastructure/database/opensearch/*`（默认后端实现）
8. `app/infrastructure/vector/vector_tool.py`（向量模型就绪与查询向量生成）

---

## 3. 数据与字段约定（KNOWLEDGE_BASE）

导入阶段（见 `03_KNOWLEDGE_BASE解析与安全执行设计.md`）通常写入：

- 语义字段：`title`、`content`
- 元数据字段：`source_file`、`header_file`、`ut_file`（按 parser 产物而定）
- 可选属性：`attributes.*`

检索侧返回字段原则：

- 优先使用绑定中的 `search_profile.response_fields`
- `score` 由 `_score` 映射

约束：

- 不返回 `chunk_id`
- 不返回 `took_ms`

---

## 4. 搜索类型映射（KNOWLEDGE_BASE）

KNOWLEDGE_BASE 不固定字段组合，检索策略由绑定 `search_profile` 决定：

1. `keyword`
2. `title`
3. `text`
4. `vector`
5. `hybrid`

说明：

- 与 SKILL/MEMORY 相比，KNOWLEDGE_BASE 的字段集合按 `tag` 差异化，由导入脚本产出并绑定。

---

## 5. `search_profile` 约定（KNOWLEDGE_BASE）

推荐与 `03_KNOWLEDGE_BASE解析与安全执行设计.md` 保持一致，至少包含：

```json
{
  "tag": "design",
  "search_type_profile": {
    "keyword": {"enabled": true, "term_fields": [{"field": "title.keyword", "weight": 1.0}]},
    "title": {"enabled": true, "match_fields": [{"field": "title", "weight": 2.0}]},
    "text": {
      "enabled": true,
      "multi_match_type": "most_fields",
      "fields": [
        {"field": "content", "weight": 3.0},
        {"field": "content.english", "weight": 2.0},
        {"field": "title", "weight": 2.0}
      ]
    },
    "vector": {
      "enabled": true,
      "vector_field": "content_vector",
      "source_template": "{title}\n{content}",
      "num_candidates_min": 100,
      "num_candidates_multiplier": 3
    },
    "hybrid": {"enabled": true, "default_vector_weight": 0.6}
  },
  "response_fields": ["doc_id", "title", "content", "source_file", "header_file", "ut_file", "score"]
}
```

说明：

- 编译器可兼容“扁平结构”和 `search_type_profile` 包裹结构，但建议统一，避免绑定不一致。

---

## 6. 服务层实现（`KnowledgeBaseSearchService`）

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

1. 参数校验（`query/tag` 必填）。
2. 读取绑定记录：
   - 若请求显式携带 `kb_index`，根据 `domain=KNOWLEDGE_BASE + kb_index` 精确查找绑定。
   - 否则根据 `domain=KNOWLEDGE_BASE + tag` 查找 active binding。
3. 标准化 `search_type/top_k/vector_weight`。
4. 向量模型一致性校验（请求显式带模型时必须与绑定一致）。
5. 调用 `KnowledgeBaseSearcher.search(...)`。
6. 组装统一响应结构。

---

## 7. Searcher 与 DSL 编译

## 7.1 `KnowledgeBaseSearcher` 建议接口

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
- `vector_weight`
- `query_vector`（vector/hybrid 场景）

输出：

- OpenSearch DSL（`dict[str, Any]`）

---

## 8. DSL 规则（KNOWLEDGE_BASE）

按照绑定 `search_profile` 进行逐类编译：

- `keyword`：`term_fields` -> `term` + `boost`
- `title`：`match_fields` -> `match` + `boost`
- `text`：`fields` -> `multi_match`
- `vector`：`vector_field` -> `knn`
- `hybrid`：文本查询 + `knn` 同次请求混合

---

## 9. 向量模型处理（检索时）

仅在 `search_type` 为 `vector/hybrid` 时生效：

1. 绑定必须存在 `vector_model`（否则返回 `VECTOR_MODEL_CONFLICT` 或 `SEARCH_PROFILE_INVALID`）。
2. `VectorTool.ensure_model_ready(model)`。
3. `VectorTool.embed_query(query, model)` 得到 `query_vector`。
4. 编译 `knn` 查询并执行。

---

## 10. 结果组装规则

命中项映射：

- `_source` 按 `response_fields` 透传
- `score <- _score`

响应骨架（示例）：

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
        "title": "周期分配入口",
        "content": "...",
        "source_file": "src/scheduler/SrVariablePeriodicityMgt.cpp",
        "score": 0.87
      }
    ]
  }
}
```

---

## 11. 错误码建议（检索侧）

- `INVALID_ARGUMENT`：参数格式错误
- `TAG_REQUIRED`：缺少 `tag`
- `INDEX_NOT_BOUND`：未找到绑定
- `VECTOR_MODEL_CONFLICT`：请求模型与绑定模型不一致
- `SEARCH_TYPE_INVALID`：不支持的 `search_type`
- `SEARCH_PROFILE_INVALID`：绑定 profile 不可编译
- `INTERNAL_ERROR`：数据库或未知内部异常

---

## 12. 测试清单（建议）

1. `keyword/title/text/vector/hybrid` 五类检索均可执行
2. `tag` 缺失时返回 `TAG_REQUIRED`
3. `tag` 未绑定返回 `INDEX_NOT_BOUND`
4. `vector_model` 冲突返回 `VECTOR_MODEL_CONFLICT`
5. `response_fields` 生效（字段裁剪正确）
6. 不返回 `chunk_id`、不返回 `took_ms`
7. 固定查询在固定配置下结果稳定
