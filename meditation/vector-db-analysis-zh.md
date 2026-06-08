# BiBLE Atlas 向量数据库选型分析

## 是否需要引入专用向量数据库？

**日期：** 2026-06-08
**状态：** 分析报告 / 建议

---

## 摘要

BiBLE Atlas 当前使用 **OpenSearch** 作为唯一后端，同时承载全文检索（BM25）、向量搜索（k-NN，基于 HNSW）、元数据过滤和异步任务存储。本报告评估是否应该引入专用向量数据库（Chroma、Qdrant、Weaviate 或 Milvus）与 OpenSearch 并行工作，或替代 OpenSearch。

**结论：现阶段不建议引入。** OpenSearch 完全满足 BiBLE 当前的规模和功能需求。投入产出比最高的选择是**升级 OpenSearch**（至 3.x 版本，以获得 GPU 加速索引、RRF 原生混合搜索和 Lucene-on-Faiss），而不是引入第二个数据库。但当以下任一条件触发时，**Qdrant 作为向量专用 sidecar** 就变得极具吸引力：向量数量超过 1000 万、P99 延迟持续高于 50ms、或者团队需要 OpenSearch 2.x 无法提供的逐查询向量搜索参数调优。

---

## 1. 现状：BiBLE 如何使用 OpenSearch

### 1.1 当前架构

```
┌──────────────────────────────────────────────────────┐
│                    搜索请求                            │
│            (keyword | text | vector | hybrid)          │
└──────────────────────────┬───────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼────────┐     ┌─────────▼─────────┐
     │  VectorTool      │     │  QueryProfile     │
     │  (嵌入编码)       │     │  Compiler         │
     │  sentence-trans. │     │  → OpenSearch DSL │
     └────────┬────────┘     └─────────┬─────────┘
              │                         │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │   OpenSearch            │
              │   - k-NN (HNSW/Lucene)  │
              │   - BM25 全文检索        │
              │   - 元数据过滤           │
              │   - 异步任务存储         │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │   RerankTool            │
              │   (cross-encoder)       │
              │   搜索后重排序           │
              └────────────┬────────────┘
                           │
                      最终结果
```

### 1.2 关键实现细节

| 方面 | BiBLE 的实现方式 | 代码位置 |
|---|---|---|
| **嵌入模型** | sentence-transformers（BGE/E5/MiniLM/MPNet），从 HuggingFace 缓存加载，跨进程 `fcntl` 文件锁防止重复下载 | `bible/infrastructure/vector/vector_tool.py` |
| **向量存储** | OpenSearch `knn_vector` 类型，首次写入时自动创建索引并设置 `knn: true` | `bible/infrastructure/database/opensearch/writer.py:556-637` |
| **相似度度量** | OpenSearch 默认值（Lucene HNSW 默认为 L2，可配置） | 代码中未显式设置 |
| **索引算法** | HNSW（OpenSearch 默认，基于 Lucene 引擎） | 代码中未显式选择引擎 |
| **混合搜索** | `bool.should` + `function_score` — BM25 分支 × `text_weight` + k-NN 分支 × `vector_weight` | `bible/features/search/common/query_profile_compiler.py:229-309` |
| **num_candidates** | 在查询体中被剔除 — OpenSearch 2.11 不支持在 k-NN body 中传此参数；改用索引级 `ef_search` | `writer.py:669-690` |
| **重排序** | Python 端 cross-encoder（BGE Reranker、MS MARCO），搜索后执行，信号量限制并发为 3 | `bible/infrastructure/vector/rerank_tool.py` |
| **编码并发** | 嵌入和重排序各有 3 线程信号量限制 | `vector_tool.py:51`, `rerank_tool.py:45` |
| **数据库抽象** | `IDatabaseWriter` 协议，支持 OpenSearch、Elasticsearch、PostgreSQL 三种实现 | `bible/infrastructure/database/` |

### 1.3 代码中暴露的隐性限制

1. **`num_candidates` 在查询时被剔除**（`writer.py:680-690`）：OpenSearch 2.11 不支持逐查询传递 `num_candidates`。变通方案是索引级 `ef_search`，这意味着**同一索引的所有查询使用相同的搜索宽度**，无法按查询粒度调优。

2. **混合搜索是分数融合，非原生 RRF**（`query_profile_compiler.py:285-309`）：当前实现使用 `function_score` 加手动权重。OpenSearch 2.12+ 已支持原生 RRF（Reciprocal Rank Fusion），通常在召回率上优于手动加权。

3. **无量化支持** — 向量以全精度存储。大规模场景下，乘积量化（PQ）或标量量化（SQ）可在几乎不影响召回率的情况下将内存降低 4–16 倍。

4. **仅支持 HNSW** — 无 IVF（高通量场景）或 DiskANN（十亿级规模）选项。

5. **重排序需拉取 top_k × multiplier 条结果** — 重排序放大系数（默认 6×）意味着要拉取 60 条才能返回 10 条，增加了不必要的网络开销。

6. **PostgreSQL 后端无向量搜索路径** — `IDatabaseWriter` 协议缺少专用向量搜索方法，PostgreSQL 实现者需要 pgvector 和独立的代码路径。

7. **`search_content_docs` 传递原始 DSL 字典** — 无类型化的向量搜索接口，难以在不做 DSL 翻译的情况下接入不同向量后端。

---

## 2. 候选方案

### 2.1 综合对比矩阵

| 维度 | **OpenSearch**（当前） | **Chroma** | **Qdrant** | **Weaviate** |
|---|---|---|---|---|
| **开发语言** | Java | Python | Rust | Go |
| **开源协议** | Apache 2.0 | Apache 2.0 | Apache 2.0 | BSD-3 |
| **部署方式** | JVM，中等重量 | `pip install`，嵌入式 | 单二进制（~15MB） | 单二进制，中等 |
| **向量索引类型** | HNSW、IVF、Faiss | 仅 HNSW | 仅 HNSW | HNSW |
| **量化** | PQ、SQ（2.9+） | 不支持 | **支持**：PQ、Scalar、Binary | 支持：PQ、BQ、SQ |
| **混合搜索** | 原生 BM25（同引擎） | 不支持（需手动） | 不支持（需独立引擎） | **业界最佳**（BM25+向量单 API） |
| **元数据过滤** | 完整 Lucene DSL | 基础 `where` | **最佳**：负载索引、嵌套过滤 | 基于 GraphQL |
| **单文档多向量** | 支持（nested, 2.12+） | 不支持 | 支持（命名向量） | 支持 |
| **稀疏向量** | 有限（2.12 前） | 不支持 | 支持（1.7+） | 支持（原生） |
| **磁盘索引** | 支持（Lucene 段 + 页缓存） | 不支持（全内存） | 支持（Memmap） | 不支持（主要内存） |
| **嵌入生成** | 不支持（需 ML Commons） | 支持（内置） | 不支持（手动） | 支持（内置模块） |
| **实际规模上限** | 10 亿+ 向量（Uber） | ~100 万向量 | 1 亿+ 向量 | 1 亿向量 |
| **P99 延迟（100 万, 768d）** | ~5ms | ~150ms | **~3ms** | ~5ms |
| **纯向量 QPS** | ~2,000 | ~800 | **~5,000** | ~2,500 |
| **运维复杂度** | 中（JVM 调优、索引管理） | **最低** | 低 | 中 |

### 2.2 各方案对 BiBLE 架构的影响

#### Chroma

```
BiBLE Server
    │
    ├── OpenSearch ── 文本搜索、元数据、异步任务（保留）
    │
    └── Chroma ── 向量嵌入 + 向量搜索（新增）
         （嵌入式，同进程运行）
```

- **改进点**：API 极其简单。嵌入生成为内置功能。零运维开销。
- **破坏点**：无法在单次查询中实现混合搜索。需在 OpenSearch 跑 BM25 + Chroma 跑 ANN，然后在 Python 中合并——**明显比当前方案更差**。
- **致命问题**：Chroma 是嵌入式库（SQLite/DuckDB）。在 BiBLE 的多进程架构（FastAPI + Celery Worker）中，每个进程拥有独立的数据副本——**无共享状态**。
- **结论**：**不适合。** Chroma 适用于原型和单用户工具。BiBLE 是多客户端服务端。架构上的倒退使其成为降级而非升级。

#### Qdrant

```
BiBLE Server
    │
    ├── OpenSearch ── 文本搜索、元数据、异步任务（保留）
    │
    └── Qdrant ── 向量存储 + ANN 搜索（新增）
         （独立服务，gRPC + REST）
```

- **改进点**：最优 P99 延迟（~3ms vs ~5ms）。负载过滤极为出色——Qdrant 基于索引负载字段的元数据过滤方案在纯向量+过滤查询场景下确实优于 OpenSearch。量化（PQ/Scalar）可降低 4–8× 内存。原生稀疏向量。逐查询 `ef` 调优。单 Rust 二进制——远比 OpenSearch 轻量。
- **破坏点**：混合搜索需两个服务——BM25 on OpenSearch + ANN on Qdrant，然后在 Python 中融合。增加了一次网络往返和融合逻辑。
- **架构决策**：正确模式是**纯向量路径 → Qdrant；文本 + 混合搜索 → OpenSearch**。不要替代 OpenSearch——其文本搜索卓越且已深度集成。Qdrant 的定位是纯向量搜索延迟/吞吐量成为瓶颈时的性能加速器。
- **结论**：**如果需要专用向量数据库，Qdrant 是最佳候选。** 但触发条件应是实测性能痛点，而非功能羡慕。

#### Weaviate

```
BiBLE Server
    │
    └── Weaviate ── 文本搜索 + 向量搜索 + 嵌入生成（替代 OpenSearch？）
         （独立服务，GraphQL + REST）
```

- **改进点**：原生混合搜索（BM25 + 向量）是 Weaviate 的杀手级特性——在部分基准测试中优于 OpenSearch RRF。内置嵌入生成可简化 BiBLE 的 `VectorTool` 管线。GraphQL API 强大。知识图谱能力与 BiBLE 多域模型概念一致。
- **破坏点**：Weaviate 需要**替代** OpenSearch，而非补充。同时运行两者冗余。迁移量巨大：重索引所有数据、搜索 DSL 改 GraphQL、异步任务存储迁移至别处。`IDatabaseWriter` 需从头实现 Weaviate 版本。
- **结论**：**目前过于颠覆。** Weaviate 是替代品，非补充品。迁移成本远超边际改进。仅 v2 重建架构时考虑。

#### Milvus

- **结论**：**过于重型。** 十亿级纯向量搜索的性能之王，但运维 footprint（etcd + Pulsar/Kafka + 多微服务）对 BiBLE 当前规模不具合理性。未来若需管理 1 亿+ 向量且 P99 < 2ms，再重新评估。

---

## 3. 真正的问题：升级 OpenSearch vs. 引入新组件

### 3.1 OpenSearch 3.x 带来的提升

BiBLE 代码库表现出与 OpenSearch 2.x 一致的特征（剔除 num_candidates、未使用 RRF）。OpenSearch 3.0（2025 年发布）带来了显著改进：

| 特性 | 对 BiBLE 的影响 |
|---|---|
| **Lucene-on-Faiss** | 量化向量吞吐 2×。BiBLE 可在几乎不影响召回率的情况下，用 4–8× 更少内存存储向量 |
| **GPU 加速索引** | 索引构建 6–13× 加速。大规模知识库导入后重建索引时尤为关键 |
| **原生 RRF 混合搜索** | 比当前 `function_score` 方案更好召回率。可简化 `QueryProfileCompiler._compile_hybrid()` |
| **Apache Lucene 10 + JVM 21** | 查询速度提升约 20%，相比 1.x 吞吐 10×。免费性能提升 |
| **可插拔存储** | 向量可存 S3/MinIO。与 BiBLE 已有 S3/MinIO 文件系统支持一致 |
| **并发段搜索** | 大索引在多核机器上利用率更好 |
| **逐查询 `ef_search`** | 直接修复 `writer.py:680` 的局限性——`num_candidates` 可再次逐查询传递 |

**核心结论：** 升级 OpenSearch 从 2.x 到 3.x 可直接解决 BiBLE 代码库中多个隐性限制，而无需引入第二个数据库。

### 3.2 引入第二个数据库的运维成本

引入任何专用向量数据库意味着：

1. **部署**：新增需容器化、配置、监控、升级和安全加固的服务
2. **数据同步**：两个数据源——文本在 OpenSearch，向量在 Qdrant。必须在导入、更新和删除时保持一致。部分失败会产生不可见的脏数据
3. **混合搜索查询扇出**：向两个服务发起请求，增加网络延迟和新的故障模式（任一服务宕机 = 结果降级）
4. **备份/恢复**：两套计划、两套流程、两种一致性模型
5. **开发者认知负荷**：新查询语言、新客户端库、新故障模式、新监控指标
6. **成本**：第二个服务 7×24 运行的计算资源

对于正在构建 Agent 原生数据库的团队，这种运维复杂度不容忽视。"值得"的门槛应设得很高。

---

## 4. 决策框架

### 4.1 保持仅使用 OpenSearch 的场景

- 向量数量 < 1000 万
- 混合搜索是主要使用场景（非纯向量）
- P99 延迟可接受（无用户投诉）
- 团队规模小，运维简单性重要
- 全文搜索质量与向量搜索同等重要
- 重视单一查询语言、单一备份、单一监控

→ **保持 OpenSearch。升级到 3.x。这是 BiBLE 当前的定位。**

### 4.2 引入 Qdrant 作为 Sidecar 的场景

- 向量数量 > 1000 万，索引构建时间成为痛点
- 实测证明纯向量搜索延迟（P99 > 50ms）是瓶颈
- 需要搜索配置已建模的逐查询调优
- 想在密集向量之外实验稀疏向量（SPLADE 等）
- OpenSearch 向量存储的内存成本不可接受

→ **引入 Qdrant 作为纯向量加速器。保留 OpenSearch 处理文本、混合搜索和异步任务。在 `IDatabaseWriter` 协议下实现 `QdrantWriter`。**

### 4.3 考虑迁移到 Weaviate 的场景

- 正在从头重建 BiBLE 搜索架构（v2/v3）
- 原生混合搜索 + 知识图谱成为核心产品特性
- 想将嵌入生成卸载到数据库端
- 团队愿意在运维栈中加入 Go

→ **全面迁移。但这是 v2/v3 的决策，非渐进式改进。**

### 4.4 使用 Chroma 的场景

- 快速原型、演示或单用户工具
- 需内存向量数据库且不想启动 Docker 的测试
- OpenSearch 未运行的本地开发环境

→ **Chroma 仅用于测试/开发。不用于生产。**

---

## 5. 具体建议

### 5.1 立即可做（本迭代）

1. **升级 OpenSearch 目标版本** — 文档和部署脚本中从 2.x 升级到 3.x。查询 API 向后兼容；主要变更是配置层面（JVM 21、新 k-NN 设置）。

2. **混合搜索切换为 RRF** — 升级到 2.12+ 后，将 `QueryProfileCompiler._compile_hybrid()` 中的 `function_score` 替换为原生 RRF 查询模板。约 50 行改动，免费获得更好召回率。同时可移除 `text_weight`/`vector_weight` 参数（RRF 不使用权重）。

3. **移除 `num_candidates` 变通方案** — 目标版本支持逐查询 `ef_search` 后，删除 `_strip_num_candidates_from_knn` 和 `_prepare_search_dsl`（`writer.py:669-690`）。解锁搜索配置级别的独立调优。

### 5.2 近期可做（下季度）

4. **增加量化配置** — 在 `bible-atlas.yaml` 的 `vector:` 配置节下暴露 PQ/SQ 设置。

5. **基准测试当前性能** — 在考虑 Qdrant 前，测量：(a) P50/P99 搜索延迟，(b) 每向量内存占用，(c) 典型导入的索引构建时间。没有自身数据，无法判断"X 更快"。

6. **为 `IDatabaseWriter` 增加向量专用方法** — 当前 `search_content_docs` 接收原始 DSL 字典。增加类型化方法如 `search_by_vector(index, vector, top_k, filters)`，使向量路径与后端解耦，为未来 Qdrant 后端准备。

### 5.3 中期规划（向量 > 1000 万时）

7. **实现 `QdrantWriter`** — 在 `IDatabaseWriter` 协议下实现。数据库工厂中增加 `QdrantClientProvider`。纯向量负载路由到 Qdrant，文本+混合保留在 OpenSearch。

8. **增加 `vector_backend` 配置** — `bible-atlas.yaml` 中支持 `vector_backend: opensearch | qdrant`。默认 `opensearch`。Qdrant 为可选加速器。

### 5.4 不要做的事

- **不要完全替换 OpenSearch** — 其文本搜索（BM25、multi_match、bool 查询）卓越、久经考验，且已深度集成到导入管线、绑定系统和异步任务存储
- **不要"以防万一"加向量数据库** — 运维成本真实存在。每增加一个服务就增加一个故障域
- **不要将 Chroma 用于生产** — 单节点嵌入式库，非多客户端服务端
- **不要同时运行 OpenSearch + Weaviate** — 功能重叠；选一个
- **不要在做基准测试前做这个决策** — 网上每个基准测试的数据、硬件和查询模式都与 BiBLE 不同

---

## 6. 附录：BiBLE 当前向量搜索完整链路

```
 1. API 层
    bible/api/search/memory_search_api.py
    → POST /api/search/memory {query, search_type: "hybrid", top_k: 10}

 2. Service 层
    bible/features/search/memory_search/memory_search_service.py
    → 解析索引绑定，验证 search_type，选择 vector_model

 3. Searcher
    bible/features/search/memory_search/searcher/search_memory.py
    → 步骤1: vector_tool.ensure_model_ready(model_name) + embed_query(query)
    → 步骤2: compiler.compile(search_type="hybrid", query_vector=...)
        → _compile_hybrid() 构建:
          {
            "size": 10,
            "query": {
              "bool": {
                "should": [
                  {"function_score": {"query": {BM25 multi_match}, "weight": 0.2}},
                  {"function_score": {"query": {"knn": {"content_vector": {...}}}, "weight": 0.8}}
                ]
              }
            }
          }
    → 步骤3: db_writer.search_content_docs(index, dsl)
        → writer.py: _prepare_search_dsl() 从 knn body 中剔除 num_candidates
        → _client.search() 请求 OpenSearch
    → 步骤4: map_hits(raw_hits) → 清洗后的结果字典

 4. 重排序（Service 层，搜索后执行）
    bible/infrastructure/vector/rerank_tool.py
    → rerank(query, passages, model_name) → cross-encoder 分数
    → 按重排序分数重新排列结果

 5. 响应
    → {kb_index, total, items: [{...}, ...]}
```

---

## 参考来源

- [OpenSearch: Using OpenSearch as a Vector Database](https://opensearch.org/blog/using-opensearch-as-a-vector-database/)
- [OpenSearch: Lucene-on-Faiss for high-performance vector search](https://opensearch.org/blog/lucene-on-faiss-powering-opensearchs-high-performance-memory-efficient-vector-search/)
- [AWS: Billion-scale vector databases with GPU acceleration on OpenSearch](https://aws.amazon.com/blogs/big-data/build-billion-scale-vector-databases-in-under-an-hour-with-gpu-acceleration-on-amazon-opensearch-service/)
- [Uber: Powering Billion-Scale Vector Search with OpenSearch](https://www.uber.com/ng/en/blog/powering-billion-scale-vector-search-with-opensearch/)
- [OpenSearch: Concurrent vector graph construction](https://opensearch.org/blog/breaking-the-single-thread-bottleneck-concurrent-vector-graph-construction-in-opensearch/)
- [OpenSearch: Enhanced multi-vector support in k-NN search](https://opensearch.org/blog/enhanced-multi-vector-support-in-opensearch-knn/)
- [OpenSearch K-NN vs Aurora pgvector](https://swac.blog/opensearch-k-nn-vs-aurora-pgvector-choosing-your-vector-store-on-aws/)
- [Portkey: Vector DB Comparison (GitHub)](https://github.com/portkeys/vector-db-comparison)
- [Vector DB Benchmark: Qdrant, Milvus, Weaviate, ChromaDB](https://github.com/scriptstar/vector-db-benchmark)
