# MEMORY Search 详细开发指南（v4）

本文档给出 `POST /api/search/memory` 的落地实现方案，覆盖：

- API 入参约束
- 服务层编排
- `search_profile -> DSL` 编译规则
- `keyword/title/text/vector/hybrid` 检索策略
- 检索结果组装与错误码

---

## 1. 适用范围

- 仅覆盖 `POST /api/search/memory`。
- 请求体字段沿用 `02_API接口文档.md`（`query/tag/search_type/top_k/vector_model/vector_weight`）。
- `tag` 固定为 `memory`。
- 检索目标数据来自 MEMORY 导入产物（`meta.json` 语义字段 + 附件存储路径回填）。

---

## 2. 组件清单（建议）

1. `app/api/search/memory_search_api.py`（`MemorySearchAPI`）
2. `app/features/search/memory_search/memory_search_service.py`（`MemorySearchService`）
3. `app/features/search/memory_search/searcher/search_memory.py`（`MemorySearcher`）
4. `app/features/search/common/query_profile_compiler.py`（`QueryProfileCompiler`，通用组件）
5. `app/infrastructure/database/factory.py`（`DatabaseFactory`）
6. `app/infrastructure/database/base.py`（绑定读取与查询执行网关接口）
7. `app/infrastructure/database/opensearch/*`（默认后端实现）
8. `app/infrastructure/vector/vector_tool.py`（向量模型就绪与查询向量生成）

---

## 3. 数据与字段约定（MEMORY）

导入阶段（见 `import_implementations/memory_meta_parser_implementation.md`）通常写入：

- 主键/标识：`doc_id`、`memory_id`
- 语义字段：`title`、`abstract`、`overview`、`content`
- 标签字段：`task_ids`、`feature_tags`、`domain_tags`、`component_tags`
- 关联字段：`metadata.related_storage_paths`

检索侧最小返回建议：

- `doc_id`
- `memory_id`
- `title`
- `abstract`
- `overview`
- `task_ids/feature_tags/domain_tags/component_tags`
- `metadata.related_storage_paths`
- `score`

约束：

- 不返回 `chunk_id`
- 不返回 `took_ms`

---

## 4. 搜索类型映射（MEMORY）

结合 MEMORY 解析文档的 profile 约定，固定映射如下：

1. `keyword`
   - 主匹配：`memory_id.keyword`、`task_ids.keyword`、`feature_tags.keyword`、`domain_tags.keyword`、`component_tags.keyword`
2. `title`
   - 匹配字段：`title`
3. `text`
   - 匹配字段：`title/abstract/overview/content`
4. `vector`
   - 向量源模板：`title + abstract + overview`
5. `hybrid`
   - 文本与向量混合打分

---

## 5. `search_profile` 约定（MEMORY）

建议与 `memory_meta_parser_implementation.md` 保持一致：

```json
{
  "tag": "memory",
  "search_type_profile": {
    "keyword": {
      "enabled": true,
      "term_fields": [
        {"field": "memory_id.keyword", "weight": 5.0},
        {"field": "task_ids.keyword", "weight": 2.0},
        {"field": "feature_tags.keyword", "weight": 1.5},
        {"field": "domain_tags.keyword", "weight": 1.2},
        {"field": "component_tags.keyword", "weight": 1.2}
      ]
    },
    "title": {
      "enabled": true,
      "match_fields": [
        {"field": "title", "weight": 3.0}
      ]
    },
    "text": {
      "enabled": true,
      "multi_match_type": "most_fields",
      "fields": [
        {"field": "title", "weight": 3.0},
        {"field": "abstract", "weight": 3.0},
        {"field": "overview", "weight": 2.5},
        {"field": "content", "weight": 2.0}
      ]
    },
    "vector": {
      "enabled": true,
      "vector_field": "content_vector",
      "source_template": "{title}\n{abstract}\n{overview}",
      "num_candidates_min": 100,
      "num_candidates_multiplier": 3
    },
    "hybrid": {
      "enabled": true,
      "default_vector_weight": 0.65
    }
  },
  "response_fields": [
    "doc_id",
    "memory_id",
    "title",
    "abstract",
    "overview",
    "task_ids",
    "feature_tags",
    "domain_tags",
    "component_tags",
    "metadata.related_storage_paths",
    "score"
  ]
}
```

---

## 6. 服务层实现（`MemorySearchService`）

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
) -> dict[str, Any]: ...
```

建议流程：

1. 参数校验（`query/tag` 必填，`tag == "memory"`）。
2. 读取绑定记录（`kb_index/search_profile/vector_model`）。
3. 标准化 `search_type/top_k/vector_weight`。
4. 向量模型一致性校验。
5. 调用 `MemorySearcher.search(...)` 执行检索。
6. 组装统一响应返回。

---

## 7. Searcher 与 DSL 编译

## 7.1 `MemorySearcher` 建议接口

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

## 8. DSL 规则（MEMORY）

- `keyword`：`term_fields` -> `bool.should + term`
- `title`：`match_fields` -> `match`
- `text`：`fields` -> `multi_match`
- `vector`：`vector_field` -> `knn`
- `hybrid`：`multi_match + knn` 同次请求混合

---

## 9. 向量模型处理（检索时）

仅在 `search_type` 为 `vector/hybrid` 时生效：

1. 绑定模型存在且一致。
2. `VectorTool.ensure_model_ready(model)`。
3. `VectorTool.embed_query(query, model)` 生成 `query_vector`。
4. 编译 `knn` 并执行查询。

---

## 10. 结果组装规则

命中项映射建议：

- `_source.doc_id -> doc_id`
- `_source.memory_id -> memory_id`
- `_source.title/abstract/overview/content -> 对应字段`
- `_source.*_tags -> 对应标签字段`
- `_source.metadata.related_storage_paths -> related_storage_paths`
- `_score -> score`

响应骨架（示例）：

```json
{
  "success": true,
  "domain": "MEMORY",
  "kb_index": "kb_memory_main",
  "tag": "memory",
  "total": 2,
  "results": {
    "memory": [
      {
        "doc_id": "mem_20260424_0001",
        "memory_id": "mem_20260424_0001",
        "title": "CNI allocator 并发问题排查结论",
        "abstract": "...",
        "related_storage_paths": ["/mnt/memory/2026/05/message.json"],
        "score": 0.91
      }
    ]
  }
}
```

---

## 11. 错误码建议（检索侧）

- `INVALID_ARGUMENT`：参数格式错误
- `TAG_INVALID`：`tag != "memory"`
- `INDEX_NOT_BOUND`：未找到 MEMORY 绑定
- `VECTOR_MODEL_CONFLICT`：请求模型与绑定模型不一致
- `SEARCH_TYPE_INVALID`：不支持的 `search_type`
- `SEARCH_PROFILE_INVALID`：绑定 profile 不可编译
- `INTERNAL_ERROR`：数据库或未知内部异常

---

## 12. 测试清单（建议）

1. `keyword` 检索命中 `memory_id/task_ids/tags`
2. `title` 检索命中 `title`
3. `text` 检索命中 `title/abstract/overview/content`
4. `vector` 检索使用 `title+abstract+overview` 模板向量
5. `hybrid` 检索按文本+向量混合打分
6. `tag != memory` 返回 `TAG_INVALID`
7. 无绑定返回 `INDEX_NOT_BOUND`
8. `vector_model` 冲突返回 `VECTOR_MODEL_CONFLICT`
9. 返回结果包含 `related_storage_paths`
10. 不返回 `chunk_id`、不返回 `took_ms`
