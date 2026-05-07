# MEMORY `parse_memory.py` 全量解析实现（v4）

本文档针对 MEMORY 导入给出完整实现规范，重点满足以下要求：

1. `parse_memory.py` 是上传内容解析总入口，负责区分 `meta.json` 与其他附件
2. `meta.json` 的 `abstract` 和 `overview` 必须完整保存，不允许分块截断
3. 解析结果除 `chunks/search_profile` 外，新增 `local_file_storage_plan`
4. 存储总入口为 `store_memory`，并严格执行“先本地存储，再数据库存储”

---

## 1. 总体流程

### 1.1 高层时序

1. API 收到 `files[]`
2. `MemoryImportService` 将上传文件先临时落地到任务目录
3. `MemoryImportService` 生成 `memory_request_manifest.json`
4. `SandboxRunner.run_parse(..., file_path=<manifest_path>, ...)`
5. `parse_memory.py` 解析 manifest，内部区分 `meta.json` 与附件，返回：
   - `chunks`
   - `search_profile`
   - `local_file_storage_plan`
6. `store_memory.store(...)`（总入口）执行：
   - 先执行本地存储计划
   - 回填 `related_storage_paths`
   - 再执行数据库入库（可选向量化）

---

## 2. manifest 字段定义与来源

文件名建议：`memory_request_manifest.json`

```json
{
  "request_id": "import_20260424_001",
  "kb_index": "kb_memory_main",
  "tag": "memory",
  "files": [
    {
      "file_ref": "f_0001",
      "filename": "meta.json",
      "abs_path": "/tmp/memory_import/import_20260424_001/staged/meta.json",
      "size_bytes": 1321,
      "content_type": "application/json"
    },
    {
      "file_ref": "f_0002",
      "filename": "message.json",
      "abs_path": "/tmp/memory_import/import_20260424_001/staged/message.json",
      "size_bytes": 18234,
      "content_type": "application/json"
    }
  ]
}
```

### 2.1 `file_ref` 是什么？怎么产生？有什么作用？

- **定义**：文件在本次请求内的稳定引用 ID（如 `f_0001` / `f_0002`）
- **生成方**：`MemoryImportService` 或 `StoreMemory.stage_upload_files(...)` 在遍历 `files[]` 时生成
- **推荐生成规则**：
  - `request_scope_file_ref = f"{task_id}#{index:04d}"`
  - 示例：`import_20260424_001#0002`
  - 若只在 manifest 内展示短 ID，可写 `f_0002`，但落库/映射时建议保留 `task_id + file_ref` 复合键
- **作用**：
  - 作为“解析结果”和“本地存储结果”的关联键（join key）
  - 避免仅依赖 `filename`（文件重名会冲突）
  - 后续回填 `related_storage_paths` 时使用 `file_ref -> storage_path` 映射
- **冲突规避**：
  - 同一请求：通过递增 index 或 UUID 保证 `file_ref` 唯一
  - 不同请求：通过 `task_id` 隔离命名空间，即使同名文件也不会冲突

### 2.2 `content_type` 是什么？为什么要有？

- **定义**：上传文件 MIME 类型（例如 `application/json`、`text/plain`）
- **来源**：通常来自 `UploadFile.content_type`，无值时可根据扩展名猜测
- **作用**：
  - 存储策略与校验策略分支（例如只允许某些类型走特定流程）
  - 下载时响应头构造
  - 审计与观测

### 2.3 `size_bytes` 为什么要有？

- **定义**：文件字节大小
- **来源**：文件临时落地后通过 `stat().st_size` 获取
- **作用**：
  - 大小校验与限流
  - 大文件策略选择（例如 copy/move、分层存储）
  - 日志审计与成本统计

### 2.4 `abs_path` 是什么？是不是上传机制临时路径？

- **定义**：当前任务工作目录中“临时落地文件”的绝对路径
- **来源**：由服务层主动落地生成（建议在任务目录 `staged/` 下）
- **结论**：它是“上传处理链路的临时保存路径”，但不建议直接依赖框架内部临时文件路径，而应使用服务层可控 staging 路径。

---

## 3. 解析输出契约（含新增字段）

```json
{
  "chunks": [
    {
      "doc_id": "mem_20260424_0001",
      "memory_id": "mem_20260424_0001",
      "title": "CNI allocator 并发问题排查结论",
      "content": "abstract + \\n + overview 的完整内容",
      "abstract": "完整 abstract",
      "overview": "完整 overview",
      "metadata": {
        "source_file": "meta.json",
        "related_file_refs": ["f_0002", "f_0003"],
        "related_storage_paths": []
      }
    }
  ],
  "search_profile": {},
  "local_file_storage_plan": {
    "files": [
      {
        "file_ref": "f_0002",
        "filename": "message.json",
        "source_path": "/tmp/memory_import/import_20260424_001/staged/message.json",
        "must_store_local": true,
        "storage_role": "memory_attachment"
      }
    ]
  }
}
```

说明：

- `chunks`：仅表达 memory 语义数据（来源 `meta.json`）
- `local_file_storage_plan`：表达“哪些附件要保存到本地文件系统”
- `related_storage_paths` 初始可为空，待 `store_memory` 执行本地存储后回填

---

## 4. 代码职责拆分建议

```text
app/features/import/memory_import/parsers/
├── parse_memory.py                           # 入口，仅编排
└── memory_parser/
    ├── schemas.py                            # 类型定义
    ├── manifest_loader.py                    # 读取与校验 manifest
    ├── file_classifier.py                    # 区分 meta 与附件
    ├── meta_parser.py                        # 解析/校验 meta.json
    ├── chunk_builder.py                      # 构建 chunk（不分块 abstract/overview）
    ├── storage_plan_builder.py               # 构建 local_file_storage_plan
    ├── search_profile_builder.py             # 构建完整 search_profile
    └── orchestrator.py                       # 聚合执行
```

---

## 5. 参考实现代码（按模块）

### 5.1 `parse_memory.py`

```python
from __future__ import annotations

from typing import Any

from .memory_parser.orchestrator import parse_manifest


def parse(file_path: str, parser_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return parse_manifest(file_path=file_path, parser_context=parser_context or {})
```

### 5.2 `memory_parser/schemas.py`

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UploadedFile:
    file_ref: str
    filename: str
    abs_path: str
    size_bytes: int
    content_type: str | None = None


@dataclass(slots=True)
class MemoryMeta:
    memory_id: str
    title: str
    abstract: str
    overview: str
    created_at: str | None
    updated_at: str | None
    task_ids: list[str]
    feature_tags: list[str]
    domain_tags: list[str]
    component_tags: list[str]
    source_client: str | None
    language: str | None
```

### 5.3 `memory_parser/manifest_loader.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from .schemas import UploadedFile


def load_manifest(manifest_path: str) -> list[UploadedFile]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest.files must be non-empty list")

    out: list[UploadedFile] = []
    seen_refs: set[str] = set()
    for item in files:
        file_ref = str(item.get("file_ref", "")).strip()
        filename = str(item.get("filename", "")).strip()
        abs_path = str(item.get("abs_path", "")).strip()
        if not file_ref or not filename or not abs_path:
            raise ValueError("manifest file item missing required field")
        if file_ref in seen_refs:
            raise ValueError(f"duplicated file_ref: {file_ref}")
        seen_refs.add(file_ref)
        out.append(
            UploadedFile(
                file_ref=file_ref,
                filename=filename,
                abs_path=abs_path,
                size_bytes=int(item.get("size_bytes", 0) or 0),
                content_type=item.get("content_type"),
            )
        )
    return out
```

### 5.4 `memory_parser/file_classifier.py`

```python
from __future__ import annotations

from .schemas import UploadedFile


def split_meta_and_attachments(files: list[UploadedFile]) -> tuple[UploadedFile, list[UploadedFile]]:
    metas = [f for f in files if f.filename.lower() == "meta.json"]
    if len(metas) != 1:
        raise ValueError("memory upload must contain exactly one meta.json")
    meta = metas[0]
    attachments = [f for f in files if f.file_ref != meta.file_ref]
    return meta, attachments
```

### 5.5 `memory_parser/meta_parser.py`

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import MemoryMeta


def parse_meta(path: str) -> MemoryMeta:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_required(data)
    _validate_lengths(data)
    _validate_iso8601(data, "created_at", required=False)
    _validate_iso8601(data, "updated_at", required=False)

    return MemoryMeta(
        memory_id=str(data["memory_id"]).strip(),
        title=str(data["title"]).strip(),
        abstract=str(data["abstract"]).strip(),
        overview=str(data.get("overview", "") or "").strip(),
        created_at=_opt(data.get("created_at")),
        updated_at=_opt(data.get("updated_at")),
        task_ids=_str_list(data.get("task_ids")),
        feature_tags=_str_list(data.get("feature_tags")),
        domain_tags=_str_list(data.get("domain_tags")),
        component_tags=_str_list(data.get("component_tags")),
        source_client=_opt(data.get("source_client")),
        language=_opt(data.get("language")) or "zh",
    )


def _validate_required(data: dict[str, Any]) -> None:
    for field in ("memory_id", "title", "abstract"):
        if not str(data.get(field, "")).strip():
            raise ValueError(f"meta.json missing required field: {field}")


def _validate_lengths(data: dict[str, Any]) -> None:
    if len(str(data.get("title", ""))) > 200:
        raise ValueError("title length exceeds 200")
    if len(str(data.get("abstract", ""))) > 500:
        raise ValueError("abstract length exceeds 500")
    if len(str(data.get("overview", ""))) > 2000:
        raise ValueError("overview length exceeds 2000")


def _validate_iso8601(data: dict[str, Any], key: str, required: bool) -> None:
    value = _opt(data.get(key))
    if not value:
        if required:
            raise ValueError(f"{key} is required")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} must be ISO8601 format") from exc


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list")
    return [str(v).strip() for v in value if str(v).strip()]


def _opt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
```

### 5.6 `memory_parser/chunk_builder.py`（不做 overview/abstract 分块）

```python
from __future__ import annotations

from .schemas import MemoryMeta, UploadedFile


def build_single_memory_chunk(meta: MemoryMeta, attachments: list[UploadedFile]) -> list[dict]:
    # 必须完整保存，不允许分块
    content = "\n".join([meta.abstract, meta.overview]).strip()
    if not content:
        content = meta.abstract

    return [
        {
            "doc_id": meta.memory_id,
            "memory_id": meta.memory_id,
            "title": meta.title,
            "content": content,
            "abstract": meta.abstract,
            "overview": meta.overview,
            "task_ids": meta.task_ids,
            "feature_tags": meta.feature_tags,
            "domain_tags": meta.domain_tags,
            "component_tags": meta.component_tags,
            "attributes": {
                "tag": "memory",
                "source_client": meta.source_client or "",
                "language": meta.language or "zh",
            },
            "metadata": {
                "source_file": "meta.json",
                "created_at": meta.created_at,
                "updated_at": meta.updated_at,
                "related_file_refs": [f.file_ref for f in attachments],
                "related_storage_paths": [],
            },
        }
    ]
```

### 5.7 `memory_parser/storage_plan_builder.py`

```python
from __future__ import annotations

from .schemas import UploadedFile


def build_local_storage_plan(attachments: list[UploadedFile]) -> dict:
    return {
        "files": [
            {
                "file_ref": f.file_ref,
                "filename": f.filename,
                "source_path": f.abs_path,
                "size_bytes": f.size_bytes,
                "content_type": f.content_type,
                "must_store_local": True,
                "storage_role": "memory_attachment",
            }
            for f in attachments
        ]
    }
```

### 5.8 `memory_parser/search_profile_builder.py`（完整示例）

```python
from __future__ import annotations


def build_search_profile() -> dict:
    return {
        "tag": "memory",
        "search_type_profile": {
            "keyword": {
                "enabled": True,
                "term_fields": [
                    {"field": "memory_id.keyword", "weight": 5.0},
                    {"field": "task_ids.keyword", "weight": 2.0},
                    {"field": "feature_tags.keyword", "weight": 1.5},
                    {"field": "domain_tags.keyword", "weight": 1.2},
                    {"field": "component_tags.keyword", "weight": 1.2},
                ],
            },
            "title": {
                "enabled": True,
                "match_fields": [
                    {"field": "title", "weight": 3.0}
                ],
            },
            "text": {
                "enabled": True,
                "multi_match_type": "most_fields",
                "fields": [
                    {"field": "title", "weight": 3.0},
                    {"field": "abstract", "weight": 3.0},
                    {"field": "overview", "weight": 2.5},
                    {"field": "content", "weight": 2.0},
                ],
            },
            "vector": {
                "enabled": True,
                "vector_field": "content_vector",
                # 对 abstract + overview 的整体做向量化，不分块
                "source_template": "{title}\n{abstract}\n{overview}",
                "num_candidates_min": 100,
                "num_candidates_multiplier": 3,
            },
            "hybrid": {
                "enabled": True,
                "default_vector_weight": 0.65,
            },
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
            "score",
        ],
    }
```

### 5.9 `memory_parser/orchestrator.py`

```python
from __future__ import annotations

from typing import Any

from .chunk_builder import build_single_memory_chunk
from .file_classifier import split_meta_and_attachments
from .manifest_loader import load_manifest
from .meta_parser import parse_meta
from .search_profile_builder import build_search_profile
from .storage_plan_builder import build_local_storage_plan


def parse_manifest(file_path: str, parser_context: dict[str, Any]) -> dict[str, Any]:
    del parser_context

    files = load_manifest(file_path)
    meta_file, attachments = split_meta_and_attachments(files)
    meta = parse_meta(meta_file.abs_path)

    chunks = build_single_memory_chunk(meta, attachments)
    search_profile = build_search_profile()
    local_file_storage_plan = build_local_storage_plan(attachments)

    return {
        "chunks": chunks,
        "search_profile": search_profile,
        "local_file_storage_plan": local_file_storage_plan,
    }
```

---

## 6. `store_memory` 总入口（先本地，后数据库）

`store_memory` 是存储总入口，负责本地与数据库两类存储编排。

```python
def store(
    self,
    kb_index: str,
    parse_result: dict[str, Any],
    vector_model: str | None,
) -> dict[str, Any]:
    # 1) 本地存储（必须先执行）
    ref_to_store = self.save_files_by_plan(
        kb_index=kb_index,
        tag="memory",
        local_file_storage_plan=parse_result["local_file_storage_plan"],
    )

    # 2) 回填路径
    hydrated_chunks = self.hydrate_chunks_with_storage_paths(
        chunks=parse_result["chunks"],
        ref_to_store_result=ref_to_store,
    )

    # 3) 可选向量化
    if vector_model:
        hydrated_chunks = self._embed_chunks(hydrated_chunks, vector_model, parse_result["search_profile"])

    # 4) 数据库存储（后执行）
    content_result = self.store_parsed_content(
        kb_index=kb_index,
        chunks=hydrated_chunks,
        vector_model=vector_model,
        search_profile=parse_result["search_profile"],
    )

    return {
        "local_store_count": len(ref_to_store),
        "content_store_result": content_result,
    }
```

---

## 7. `search_profile` 与查询示例（完整）

### 7.1 `search_profile` 完整示例

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

### 7.2 OpenSearch 查询示例（keyword/title/text/vector/hybrid）

输入：

- `kb_index = kb_memory_main`
- `query = "allocator 锁竞争"`
- `top_k = 10`
- `vector_weight = 0.65`

#### keyword

```json
POST /kb_memory_main/_search
{
  "size": 10,
  "_source": [
    "doc_id", "memory_id", "title", "abstract", "overview",
    "task_ids", "feature_tags", "domain_tags", "component_tags",
    "metadata.related_storage_paths"
  ],
  "query": {
    "bool": {
      "should": [
        {"term": {"memory_id.keyword": {"value": "mem_20260424_0001", "boost": 5.0}}},
        {"term": {"task_ids.keyword": {"value": "CNI-12345", "boost": 2.0}}},
        {"term": {"feature_tags.keyword": {"value": "memory-import", "boost": 1.5}}}
      ],
      "minimum_should_match": 1
    }
  }
}
```

#### title

```json
POST /kb_memory_main/_search
{
  "size": 10,
  "_source": [
    "doc_id", "memory_id", "title", "abstract", "overview",
    "task_ids", "feature_tags", "domain_tags", "component_tags",
    "metadata.related_storage_paths"
  ],
  "query": {
    "match": {
      "title": {
        "query": "allocator 锁竞争",
        "boost": 3.0
      }
    }
  }
}
```

#### text

```json
POST /kb_memory_main/_search
{
  "size": 10,
  "_source": [
    "doc_id", "memory_id", "title", "abstract", "overview",
    "task_ids", "feature_tags", "domain_tags", "component_tags",
    "metadata.related_storage_paths"
  ],
  "query": {
    "multi_match": {
      "query": "allocator 锁竞争",
      "type": "most_fields",
      "fields": [
        "title^3.0",
        "abstract^3.0",
        "overview^2.5",
        "content^2.0"
      ]
    }
  }
}
```

#### vector

```json
POST /kb_memory_main/_search
{
  "size": 10,
  "_source": [
    "doc_id", "memory_id", "title", "abstract", "overview",
    "task_ids", "feature_tags", "domain_tags", "component_tags",
    "metadata.related_storage_paths"
  ],
  "knn": {
    "field": "content_vector",
    "query_vector": [0.0123, -0.0301, 0.4421],
    "k": 10,
    "num_candidates": 100
  }
}
```

#### hybrid

```json
POST /kb_memory_main/_search
{
  "size": 10,
  "_source": [
    "doc_id", "memory_id", "title", "abstract", "overview",
    "task_ids", "feature_tags", "domain_tags", "component_tags",
    "metadata.related_storage_paths"
  ],
  "query": {
    "bool": {
      "should": [
        {
          "multi_match": {
            "query": "allocator 锁竞争",
            "type": "most_fields",
            "fields": [
              "title^3.0",
              "abstract^3.0",
              "overview^2.5",
              "content^2.0"
            ],
            "boost": 0.35
          }
        }
      ]
    }
  },
  "knn": {
    "field": "content_vector",
    "query_vector": [0.0123, -0.0301, 0.4421],
    "k": 10,
    "num_candidates": 100,
    "boost": 0.65
  }
}
```

### 7.3 Postgres + pgvector 查询示例（keyword/title/text/vector/hybrid）

假设表：`v4_content_docs_pgvector(index_name, row_id, payload, content_vector)`

#### keyword

```sql
SELECT
    row_id AS doc_id,
    payload->>'memory_id' AS memory_id,
    payload->>'title' AS title,
    payload->'metadata'->'related_storage_paths' AS related_storage_paths
FROM v4_content_docs_pgvector
WHERE index_name = $1
  AND (
      payload->>'memory_id' = $2
      OR EXISTS (
          SELECT 1 FROM jsonb_array_elements_text(coalesce(payload->'task_ids', '[]'::jsonb)) AS t(v)
          WHERE t.v = $3
      )
      OR EXISTS (
          SELECT 1 FROM jsonb_array_elements_text(coalesce(payload->'feature_tags', '[]'::jsonb)) AS t(v)
          WHERE t.v = $4
      )
  )
LIMIT $5;
```

#### title

```sql
SELECT
    row_id AS doc_id,
    payload->>'memory_id' AS memory_id,
    payload->>'title' AS title,
    payload->'metadata'->'related_storage_paths' AS related_storage_paths,
    ts_rank_cd(
        to_tsvector('simple', coalesce(payload->>'title', '')),
        websearch_to_tsquery('simple', $2)
    ) AS score
FROM v4_content_docs_pgvector
WHERE index_name = $1
  AND to_tsvector('simple', coalesce(payload->>'title', ''))
      @@ websearch_to_tsquery('simple', $2)
ORDER BY score DESC
LIMIT $3;
```

#### text

```sql
SELECT
    row_id AS doc_id,
    payload->>'memory_id' AS memory_id,
    payload->>'title' AS title,
    payload->'metadata'->'related_storage_paths' AS related_storage_paths,
    ts_rank_cd(
        to_tsvector(
            'simple',
            coalesce(payload->>'title', '') || ' ' ||
            coalesce(payload->>'abstract', '') || ' ' ||
            coalesce(payload->>'overview', '') || ' ' ||
            coalesce(payload->>'content', '')
        ),
        websearch_to_tsquery('simple', $2)
    ) AS score
FROM v4_content_docs_pgvector
WHERE index_name = $1
  AND to_tsvector(
        'simple',
        coalesce(payload->>'title', '') || ' ' ||
        coalesce(payload->>'abstract', '') || ' ' ||
        coalesce(payload->>'overview', '') || ' ' ||
        coalesce(payload->>'content', '')
      ) @@ websearch_to_tsquery('simple', $2)
ORDER BY score DESC
LIMIT $3;
```

#### vector

```sql
SELECT
    row_id AS doc_id,
    payload->>'memory_id' AS memory_id,
    payload->>'title' AS title,
    payload->'metadata'->'related_storage_paths' AS related_storage_paths,
    (1 - (content_vector <=> $2::vector)) AS score
FROM v4_content_docs_pgvector
WHERE index_name = $1
ORDER BY content_vector <=> $2::vector
LIMIT $3;
```

#### hybrid

```sql
WITH scored AS (
    SELECT
        row_id AS doc_id,
        payload->>'memory_id' AS memory_id,
        payload->>'title' AS title,
        payload->'metadata'->'related_storage_paths' AS related_storage_paths,
        ts_rank_cd(
            to_tsvector(
                'simple',
                coalesce(payload->>'title', '') || ' ' ||
                coalesce(payload->>'abstract', '') || ' ' ||
                coalesce(payload->>'overview', '') || ' ' ||
                coalesce(payload->>'content', '')
            ),
            websearch_to_tsquery('simple', $2)
        ) AS text_score,
        (1 - (content_vector <=> $4::vector)) AS vector_score
    FROM v4_content_docs_pgvector
    WHERE index_name = $1
)
SELECT
    doc_id,
    memory_id,
    title,
    related_storage_paths,
    (text_score * (1 - $5) + vector_score * $5) AS score
FROM scored
ORDER BY score DESC
LIMIT $3;
```

参数：

- `$1 = 'kb_memory_main'`
- `$2 = 'allocator 锁竞争'`
- `$3 = 10`
- `$4 = query_vector`
- `$5 = 0.65`

---

## 8. 测试建议

1. `manifest.files` 无 `meta.json` 时失败
2. 多个 `meta.json` 时失败
3. `meta.json` 必填字段缺失时失败
4. `abstract/overview` 全量入库，不发生分块
5. `local_file_storage_plan` 与附件集合一致
6. `store_memory` 先本地存储后数据库存储（顺序测试）
7. 回填后检索结果可返回 `metadata.related_storage_paths`
8. OpenSearch / pgvector 的 keyword/title/text/vector/hybrid 都可执行

---

样例文件：`meta.json.sample.json`
