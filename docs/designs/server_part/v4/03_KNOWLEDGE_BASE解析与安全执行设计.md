# KNOWLEDGE_BASE 解析与安全执行设计（v4）

本文档定义 v4 的原生解析体系。  
v4 的目标不是“兼容当前工程实现”，而是建立统一、可扩展、可审计、可安全执行的解析与检索契约。

---

## 1. 设计目标

1. 所有域（`KNOWLEDGE_BASE/SKILL/MEMORY`）统一解析脚本规范
2. 默认解析脚本与自定义解析脚本完全同构
3. 导入时从解析结果直接产出检索策略（`search_profile`）
4. 索引与 `parser/search_profile/vector_model` 一次绑定，不可修改
5. 自定义脚本执行具备可验证安全边界

---

## 2. 统一解析脚本契约

### 2.1 适用范围

以下解析器都必须遵循同一契约：

- 默认解析脚本（系统内置）
- `KNOWLEDGE_BASE` 自定义脚本（上传或目录发现）
- `skill_import/parsers/` 下解析器
- `memory_import/parsers/` 下解析器

### 2.2 统一函数签名

所有解析器统一对外函数名：`parse`

```python
def parse(file_path: str, context: dict | None = None) -> dict:
    ...
```

### 2.3 统一返回格式

返回必须包含两部分：`chunks` 与 `search_profile`。

```json
{
  "chunks": [
    {
      "title": "周期分配入口",
      "content": "......",
      "attributes": {
        "component": "L2PS",
        "domain": "scheduler",
        "section_id": "1.2"
      },
      "metadata": {
        "source_file": "src/scheduler/SrVariablePeriodicityMgt.cpp",
        "header_file": "include/scheduler/SrVariablePeriodicityMgt.hpp",
        "ut_file": "test/scheduler/TestSrVariablePeriodicityMgt.cpp"
      }
    }
  ],
  "search_profile": {
    "tag": "design",
    "search_type_profile": {
      "keyword": {
        "enabled": true,
        "term_fields": [
          {"field": "title.keyword", "weight": 1.0}
        ]
      },
      "title": {
        "enabled": true,
        "match_fields": [
          {"field": "title", "weight": 2.0}
        ]
      },
      "text": {
        "enabled": true,
        "multi_match_type": "most_fields",
        "fields": [
          {"field": "content", "weight": 3.0},
          {"field": "content.english", "weight": 2.0},
          {"field": "content.standard", "weight": 1.0},
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
      "hybrid": {
        "enabled": true,
        "default_vector_weight": 0.6
      }
    },
    "response_fields": [
      "doc_id",
      "title",
      "content",
      "score",
      "source_file",
      "header_file",
      "ut_file"
    ]
  }
}
```

约束：

- 不允许返回空 `chunks`
- `search_profile` 必须完整声明 `keyword/title/text/vector/hybrid` 五类策略（可通过 `enabled=false` 关闭）

### 2.4 `search_profile` 转 OpenSearch 查询语句示例

本节给出可直接执行的 OpenSearch DSL（Dev Tools 风格），覆盖 `keyword/title/text/vector/hybrid` 五种检索。  
其中 `vector` 与 `hybrid` 的写法与当前工程 `x_data/search_manager.py` 已实现语句一致（单次请求，不是两次查询）。

输入（示例）：

- `query = "allocate 函数"`
- `top_k = 10`
- `vector_weight = 0.6`
- 使用 2.3 中的 `search_profile`

#### 2.4.1 映射规则（核心）

1. `keyword.term_fields[].field/weight` -> `term` 查询 + `boost`
2. `title.match_fields[].field/weight` -> `match` 查询 + `boost`
3. `text.fields[].field/weight` -> `multi_match.fields` 中的 `field^weight`
4. `vector.vector_field` -> `knn.field`
5. `vector.num_candidates_*` -> `knn.num_candidates`
6. `hybrid.default_vector_weight` -> `knn.boost`（文本权重用 `1 - vector_weight`）
7. `response_fields` -> `_source` 字段过滤；`score` 字段来自 `_score`

输出字段映射（示例）：

- `response_fields = ["doc_id","title","content","score","source_file","header_file","ut_file"]`
- `_source = ["doc_id","title","content","source_file","header_file","ut_file"]`
- `score` 不在 `_source`，由命中项 `_score` 提供

#### 2.4.2 `keyword` 检索 DSL（OpenSearch）

```json
POST /kb_design_main/_search
{
  "size": 10,
  "_source": [
    "doc_id",
    "title",
    "content",
    "source_file",
    "header_file",
    "ut_file"
  ],
  "query": {
    "term": {
      "title.keyword": {
        "value": "周期分配入口",
        "boost": 1.0
      }
    }
  }
}
```

#### 2.4.3 `title` 检索 DSL（OpenSearch）

```json
POST /kb_design_main/_search
{
  "size": 10,
  "_source": [
    "doc_id",
    "title",
    "content",
    "source_file",
    "header_file",
    "ut_file"
  ],
  "query": {
    "match": {
      "title": {
        "query": "周期分配入口",
        "boost": 2.0
      }
    }
  }
}
```

#### 2.4.4 `text` 检索 DSL（OpenSearch）

```json
POST /kb_design_main/_search
{
  "size": 10,
  "_source": [
    "doc_id",
    "title",
    "content",
    "source_file",
    "header_file",
    "ut_file"
  ],
  "query": {
    "multi_match": {
      "query": "allocate 函数",
      "type": "most_fields",
      "fields": [
        "content^3.0",
        "content.english^2.0",
        "content.standard^1.0",
        "title^2.0"
      ]
    }
  }
}
```

#### 2.4.5 `vector` 检索 DSL（OpenSearch）

> `query_vector` 由请求 `query` 按绑定 `vector_model` 生成。

```json
POST /kb_design_main/_search
{
  "size": 10,
  "knn": {
    "field": "content_vector",
    "query_vector": [0.0123, -0.0301, 0.4421],
    "k": 10,
    "num_candidates": 100
  },
  "_source": [
    "doc_id",
    "title",
    "content",
    "source_file",
    "header_file",
    "ut_file"
  ]
}
```

#### 2.4.6 `hybrid` 检索 DSL（OpenSearch，单次请求）

```json
POST /kb_design_main/_search
{
  "size": 10,
  "query": {
    "bool": {
      "should": [
        {
          "multi_match": {
            "query": "allocate 函数",
            "type": "most_fields",
            "fields": [
              "content^3.0",
              "content.english^2.0",
              "content.standard^1.0",
              "title^2.0"
            ],
            "boost": 0.4
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
    "boost": 0.6
  },
  "_source": [
    "doc_id",
    "title",
    "content",
    "source_file",
    "header_file",
    "ut_file"
  ]
}
```

说明：

- 这是“一次请求内同时执行 text + vector”的混合检索
- `vector_weight` 映射到 `knn.boost`
- `text_weight = 1 - vector_weight` 映射到 `multi_match.boost`

---

## 3. 解析脚本选择规则

### 3.1 当前目录约定（v4 基线）

当前 v4 按域管理解析脚本目录：

- `app/features/import/knowledge_base_import/parsers/`
- `app/features/import/skill_import/parsers/`
- `app/features/import/memory_import/parsers/`

### 3.2 选择算法

导入请求到达后按以下顺序确定最终解析脚本：

1. 若请求上传 `parser_script`：
   - 在对应域 `*_import_service.py` 内通过 `save_uploaded_parser(...)` 保存脚本到域内 `parsers/`
   - 作为本次导入最终脚本（`KNOWLEDGE_BASE` 目标名 `parse_{tag}.py`，`SKILL/MEMORY` 分别为 `parse_skill.py` / `parse_memory.py`）
2. 若请求未上传 `parser_script`：
   - `KNOWLEDGE_BASE` 在域内 `parsers/` 查找 `parse_{tag}.py`
   - `SKILL/MEMORY` 在域内 `parsers/` 查找固定脚本 `parse_skill.py` / `parse_memory.py`
3. 若仍未命中：回退到域内 `parsers/parse_default.py`
4. 默认脚本也缺失：返回 `PARSER_SCRIPT_NOT_FOUND`

> 未来“统一脚本目录 + 配置化 `parser_dir`”方案见 `06_未来演进规划.md`，不影响当前 v4 基线。

---

## 4. 持久化方案（search_profile 与索引绑定）

本节采用“**外层统一 database 抽象，内层可替换具体数据库实现**”的方案。  
`infrastructure/database/` 对 features 暴露统一接口；默认实现可用 OpenSearch，后续可扩展 Elasticsearch 或 Postgres 备份实现。

### 4.1 设计原则

- 一个 `kb_index` 只允许一条有效绑定记录
- 一个绑定记录包含：
  - 最终解析脚本信息
  - `search_profile`
  - 向量模型
- features 层不感知底层数据库类型，只依赖 `database/` 接口
- 绑定后不可修改；若要变更必须删除索引并重建
- 不做版本策略，不支持在线修改既有 `search_profile`

### 4.2 `database/` 统一接口（建议）

建议目录分层如下：

```text
app/infrastructure/database/
├── base.py                  # 统一抽象接口
├── factory.py               # 根据配置选择后端
├── opensearch/              # OpenSearch 适配实现
│   ├── client.py
│   ├── reader.py
│   └── writer.py
├── elasticsearch/           # 可选：Elasticsearch 适配实现
│   ├── client.py
│   ├── reader.py
│   └── writer.py
└── postgres/                # 可选：Postgres 适配实现（如备份/审计）
    ├── client.py
    ├── reader.py
    └── writer.py
```

建议在 `infrastructure/database/` 提供以下接口：

- `create_index_binding(binding_doc)`：首次创建绑定（幂等失败即冲突）
- `get_binding_by_domain_tag(domain_type, tag)`：按域和标签读取绑定
- `get_binding_by_domain_index(domain_type, kb_index)`：按域和索引读取绑定
- `deactivate_binding(domain_type, kb_index)`：软删除绑定
- `write_content_docs(domain_type, kb_index, docs)`：写入检索内容

实现收敛要求：

- 不单独设计 `search_profile_store.py`
- `KNOWLEDGE_BASE` 的“绑定读写 + 内容写入”统一由 `store_knowledge_base.py` 编排调用 `database/` 接口

### 4.3 默认实现示例（OpenSearch）

以下示例仅是 `database/` 的默认 OpenSearch 适配实现，外层接口不变。

#### 4.3.1 元数据索引 mapping

```json
PUT /v4_index_binding
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 1
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "domain_type": {"type": "keyword"},
      "kb_index": {"type": "keyword"},
      "tag": {"type": "keyword"},
      "parser_script_name": {"type": "keyword"},
      "parser_script_source": {"type": "keyword"},
      "parser_script_sha256": {"type": "keyword"},
      "vector_model": {"type": "keyword"},
      "search_profile_json": {"type": "object", "enabled": false},
      "search_profile_sha256": {"type": "keyword"},
      "created_at": {"type": "date"},
      "created_by": {"type": "keyword"},
      "deleted_at": {"type": "date"},
      "is_active": {"type": "boolean"}
    }
  }
}
```

#### 4.3.2 字段说明（回答常见疑问）

- `search_profile_json`：完整保存解析脚本返回的 `search_profile`，检索阶段直接读取并编译 DSL
- `parser_script_source`：来自“解析脚本选择流程”，取值为：
  - `upload`：请求上传脚本
  - `dir_discovery`：域内 `parsers/` 命中 `parse_{tag}.py`（或固定脚本）
  - `default`：未命中时回落默认脚本
- `domain_type`：来自 API 路由域（`KNOWLEDGE_BASE/SKILL/MEMORY`）
- `dynamic: strict`：OpenSearch mapping 选项，表示拒绝未声明字段，避免脏字段写入
- `is_active`：业务字段，不是 OpenSearch 内部强制要求；用于软删除与快速过滤

#### 4.3.3 绑定文档示例（首次创建，含完整 `search_profile`）

```json
PUT /v4_index_binding/_doc/KNOWLEDGE_BASE::kb_design_main?op_type=create
{
  "domain_type": "KNOWLEDGE_BASE",
  "kb_index": "kb_design_main",
  "tag": "design",
  "parser_script_name": "parse_design.py",
  "parser_script_source": "dir_discovery",
  "parser_script_sha256": "a1b2c3d4...",
  "vector_model": "bge-large-zh-v1.5",
  "search_profile_json": {
    "tag": "design",
    "search_type_profile": {
      "keyword": {
        "enabled": true,
        "term_fields": [
          {"field": "title.keyword", "weight": 1.0}
        ]
      },
      "title": {
        "enabled": true,
        "match_fields": [
          {"field": "title", "weight": 2.0}
        ]
      },
      "text": {
        "enabled": true,
        "multi_match_type": "most_fields",
        "fields": [
          {"field": "content", "weight": 3.0},
          {"field": "content.english", "weight": 2.0},
          {"field": "content.standard", "weight": 1.0},
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
      "hybrid": {
        "enabled": true,
        "default_vector_weight": 0.6
      }
    }
  },
  "search_profile_sha256": "f00dbabe...",
  "created_at": "2026-04-22T10:00:00Z",
  "created_by": "api_user",
  "is_active": true
}
```

#### 4.3.4 按 `domain + tag` 查询绑定记录

```json
POST /v4_index_binding/_search
{
  "size": 1,
  "query": {
    "bool": {
      "filter": [
        {"term": {"domain_type": "KNOWLEDGE_BASE"}},
        {"term": {"tag": "design"}},
        {"term": {"is_active": true}}
      ]
    }
  }
}
```

### 4.4 不可修改约束

- 绑定主键建议为 `_id = {domain_type}::{kb_index}`，通过 `op_type=create` 保证首次绑定原子创建
- `parser_script_*`、`vector_model`、`search_profile_*` 字段禁止变更
- 仅允许两类写操作：
  1. 首次创建（`PUT ...?op_type=create`）
  2. 软删除（仅更新 `is_active=false` 与 `deleted_at`）
- `tag` 唯一性由应用层在写入前校验（查重后写入）

### 4.5 向量模型生命周期（`infrastructure/vector/`）

v4 中向量相关能力统一放在 `app/infrastructure/vector/`：

- `vector_tool.py`：对外提供向量化接口（模型就绪检查、文本向量生成）
- `model_preloader.py`：应用启动阶段按配置预加载向量模型

导入时（按需）流程：

1. 请求未传 `vector_model`：跳过向量化
2. 请求传了 `vector_model`：
   - 先在本地缓存目录检查指定模型（离线路径优先）
   - 若本地不存在：从 HuggingFace 下载模型并缓存
   - 模型就绪后对 `chunks` 进行向量化（例如生成 `content_vector`）

启动时（可配置）流程：

1. `main.py` 加载配置后读取 `vector.preload_on_startup`
2. 若为 `true`：调用 `infrastructure/vector/model_preloader.py` 预加载全部配置模型
3. 预加载逐个执行“本地检查 -> 缺失下载 -> 缓存预热”
4. 若为 `false`：不预加载，导入时按需加载

---

## 5. 导入处理流程（v4 原生）

1. 校验请求参数（`files/kb_index/tag`）
2. 选择最终解析脚本
3. 脚本安全检查（AST + 运行策略）
4. 对每个文件执行 `parse(file_path, context)`
5. 合并 `chunks`，校验 `search_profile` 一致性
6. 检查绑定：
   - 若 `kb_index` 未绑定：由 `store_knowledge_base.py` 创建绑定记录
   - 若已绑定：必须与已绑定 `parser/search_profile/vector_model` 完全一致
7. 若请求携带 `vector_model`：通过 `infrastructure/vector/vector_tool.py` 执行“本地检查 -> 缺失下载 -> chunks 向量化”
8. 通过 `database/` 适配层写入内容索引（默认实现可为 OpenSearch）
9. 记录导入日志（见第 8 节）

---

## 6. 检索处理流程（按 tag 驱动）

1. 接收 `query + tag + search_type...`
2. 根据路由域 + `tag` 查找绑定记录
3. 取出绑定的 `kb_index/search_profile/vector_model`
4. 将 `search_profile` 编译为对应 `search_type` 的 DSL
5. 执行检索并返回结果

约束：

- 若请求显式传入 `vector_model`，必须与绑定模型一致
- 响应不返回 `chunk_id`，不返回 `took_ms`

---

## 7. 自定义脚本安全限制（明确清单）

### 7.1 文件级限制

- 仅允许 `.py`
- 单次请求最多 1 个脚本文件
- 脚本大小 `<= 256KB`
- 脚本必须是 UTF-8

### 7.2 AST 语法限制

### 允许的顶层结构

- `import` / `from ... import ...`
- 常量定义
- 单个顶层函数 `parse`

### 禁止的 AST 节点

- `ClassDef`
- `Lambda`
- `With` / `AsyncWith`
- `AsyncFunctionDef` / `Await`
- `Try` / `TryStar`
- `Global` / `Nonlocal`
- `Delete`
- `Yield` / `YieldFrom`

### 导入白名单（仅允许）

- `json`
- `re`
- `math`
- `datetime`
- `typing`
- `collections`
- `itertools`

> 未在白名单中的模块一律拒绝。

### 函数调用黑名单（禁止）

- `eval`
- `exec`
- `compile`
- `open`
- `input`
- `__import__`
- `globals`
- `locals`

### 属性访问黑名单（禁止）

- `*.system`
- `*.popen`
- `*.fork`
- `*.spawn`
- `*.remove`
- `*.unlink`
- `*.rmdir`
- `*.chmod`

### dunder 限制

- 禁止访问任意 `__*__` 属性（含 `__dict__`、`__class__`）

### 7.3 容器运行限制

- 镜像：最小 Python 运行时
- 用户：非 root
- 网络：禁用（`--network none`）
- 文件系统：根文件系统只读
- 挂载：仅输入目录只读、输出目录可写
- 资源限制：
  - CPU：1 核
  - 内存：256MB
  - 进程数：64
  - 单文件执行超时：10 秒

### 7.4 输出限制

- 单次解析最大 `chunks` 数：5000
- 单个 `chunk.content` 最大长度：32KB
- 单次脚本总输出最大：10MB
- 输出必须是合法 JSON，且符合契约

---

## 8. 日志与审计要求（SKILL/MEMORY 强制）

当前阶段不处理双写一致性，但必须具备可追踪日志。

每次导入至少记录：

- `request_id`
- `domain_type`
- `kb_index`
- `tag`
- `parser_script_source`
- `parser_script_sha256`
- `search_profile_sha256`
- `vector_model`
- `file_name`
- `database_write_status`（success/fail）
- `file_write_status`（success/fail，仅 skill/memory）
- `error_code`
- `error_message`
- `duration_ms`

日志用途：

- 人工回溯
- 离线修复
- 后续一致性治理的数据基础

---

## 9. 架构审视结论（聚焦自定义解析）

这套设计的核心价值是“把可变点前移到解析契约”，并通过绑定机制保证运行期稳定。  
关键成功条件有三条：

1. **契约强约束**：默认和自定义解析器必须同构，否则导入/检索会分叉
2. **绑定不可变**：`kb_index` 一旦绑定脚本、profile、模型，就必须冻结
3. **执行可控**：AST + 容器限制必须可审计、可观测、可拒绝

只要这三条落地，v4 可以在不增加核心服务复杂度的前提下，支持大量文档类型差异化。

