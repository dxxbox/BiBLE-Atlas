# Vector DB Analysis for BiBLE Atlas

## Should We Introduce a Dedicated Vector Database?

**Date:** 2026-06-08
**Status:** Analysis / Recommendation

---

## Executive Summary / 摘要

BiBLE Atlas currently uses **OpenSearch** as its sole backend for full-text search (BM25), vector search (k-NN via HNSW), metadata filtering, and async task storage. This analysis evaluates whether introducing a dedicated vector database (Chroma, Qdrant, Weaviate, or Milvus) alongside or in place of OpenSearch would be the right move.

**Short answer: Not right now.** OpenSearch is well-suited to BiBLE's current scale and feature needs. The largest ROI play is **upgrading OpenSearch** (to 3.x for GPU-accelerated indexing, RRF-native hybrid search, and Lucene-on-Faiss) rather than introducing a second database. However, a **Qdrant sidecar for vector-only paths** becomes compelling once any of these triggers fire: more than 10 million vectors, P99 latency consistently above 50ms, or the team needs per-query vector tuning that OpenSearch 2.x cannot provide.

**简短结论：现阶段不建议引入。** OpenSearch 完全满足 BiBLE 当前的规模和功能需求。投入产出比最高的选择是升级 OpenSearch（至 3.x 以获得 GPU 加速索引、RRF 原生混合搜索和 Lucene-on-Faiss），而不是引入第二个数据库。但当以下任一条件触发时，Qdrant 作为向量专用 sidecar 就变得极具吸引力：向量数量超过 1000 万、P99 延迟持续高于 50ms、或者团队需要 OpenSearch 2.x 无法提供的逐查询向量调优。

---

## 1. Current State: How BiBLE Uses OpenSearch Today / 现状

### 1.1 Architecture / 架构

```
┌──────────────────────────────────────────────────────┐
│                   Search Request                      │
│              (keyword | text | vector | hybrid)        │
└──────────────────────────┬───────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
     ┌────────▼────────┐     ┌─────────▼─────────┐
     │  VectorTool      │     │  QueryProfile     │
     │  (embed query)   │     │  Compiler         │
     │  sentence-trans. │     │  → OpenSearch DSL │
     └────────┬────────┘     └─────────┬─────────┘
              │                         │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │   OpenSearch            │
              │   - k-NN (HNSW/Lucene)  │
              │   - BM25 full-text      │
              │   - Metadata filtering  │
              │   - Async task storage  │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │   RerankTool            │
              │   (cross-encoder)       │
              │   Post-search rescoring │
              └────────────┬────────────┘
                           │
                     Final Results
```

### 1.2 Key Implementation Details / 关键实现细节

| Aspect | How BiBLE Does It | Code Location |
|---|---|---|
| **Embedding model** | sentence-transformers (BGE/E5/MiniLM/MPNet), loaded from HuggingFace cache, cross-process `fcntl` lock for downloads | `bible/infrastructure/vector/vector_tool.py` |
| **Vector storage** | OpenSearch `knn_vector` type, index created on-the-fly with `knn: true` settings | `bible/infrastructure/database/opensearch/writer.py:556-637` |
| **Similarity metric** | OpenSearch default (L2 for Lucene HNSW, configurable) | Not explicitly set in code |
| **Index algorithm** | HNSW (OpenSearch default via Lucene engine) | No explicit engine selection in code |
| **Hybrid search** | `bool.should` with `function_score` — BM25 arm × `text_weight` + k-NN arm × `vector_weight` | `bible/features/search/common/query_profile_compiler.py:229-309` |
| **num_candidates** | Stripped from query body — OpenSearch 2.11 doesn't accept it; uses index-level `ef_search` instead | `writer.py:669-690` |
| **Rerank** | Python-side cross-encoder (BGE Reranker, MS MARCO), post-search, semaphore-limited to 3 concurrent calls | `bible/infrastructure/vector/rerank_tool.py` |
| **Encoding concurrency** | 3-thread semaphore for both embedding and reranking | `vector_tool.py:51`, `rerank_tool.py:45` |
| **DB abstraction** | `IDatabaseWriter` protocol, implementations for OpenSearch, Elasticsearch, PostgreSQL | `bible/infrastructure/database/` |

### 1.3 Implicit Limitations Visible in the Current Code / 代码中的隐性限制

1. **`num_candidates` stripped at query time** (`writer.py:680-690`): OpenSearch 2.11 doesn't support per-query `num_candidates` in the k-NN body. The workaround is index-level `ef_search`, which means **every query to the same index uses the same search width**. You cannot say "this query is exploratory, give me a wider search" without changing the index setting.

2. **Hybrid search is score-fusion, not native RRF** (`query_profile_compiler.py:285-309`): The current implementation uses `function_score` with manual weights. OpenSearch 2.12+ has native RRF (Reciprocal Rank Fusion) which typically yields better recall. BiBLE's approach is functionally correct but may underperform RRF at the margin.

3. **No quantization** — vectors are stored at full precision. At scale, product quantization (PQ) or scalar quantization (SQ) could reduce memory by 4–16× with minimal recall loss.

4. **HNSW only** — no option for IVF (better for high-throughput, lower-recall-requirement workloads) or DiskANN (billion-scale where RAM is constrained).

5. **Rerank fetches top_k × multiplier results** — the rerank multiplier (default 6× in config) means fetching 60 results to return 10. This is standard practice but adds network overhead that a DB-side rerank could eliminate.

6. **PostgreSQL backend has no vector path** — the `IDatabaseWriter` protocol doesn't include a vector search method; PostgreSQL implementers would need pgvector and a separate code path.

7. **No `search_content_docs` vector-specific signature** — the `IDatabaseWriter.search_content_docs` takes a raw DSL dict. There is no typed vector search interface. This makes it hard to plug in a different vector backend without DSL translation.

---

## 2. The Candidates / 候选方案

### 2.1 Comparison Matrix / 对比矩阵

| Dimension | **OpenSearch** (current) | **Chroma** | **Qdrant** | **Weaviate** |
|---|---|---|---|---|
| **Language** | Java | Python | Rust | Go |
| **License** | Apache 2.0 | Apache 2.0 | Apache 2.0 | BSD-3 |
| **Deployment** | JVM, moderate weight | `pip install`, embedded | Single binary (~15MB) | Single binary, moderate |
| **Vector index types** | HNSW, IVF, Faiss | HNSW only | HNSW only | HNSW |
| **Quantization** | PQ, SQ (2.9+) | No | **Yes**: PQ, Scalar, Binary | Yes: PQ, BQ, SQ |
| **Hybrid search** | BM25 native (same engine) | No (manual only) | No (separate engine needed) | **Best-in-class** (BM25 + vector in one API) |
| **Metadata filtering** | Full Lucene query DSL | Basic `where` | **Best**: payload indexing, nested filters | GraphQL-based |
| **Multi-vector per doc** | Yes (nested, 2.12+) | No | Yes (named vectors) | Yes |
| **Sparse vectors** | Limited (pre-2.12) | No | Yes (1.7+) | Yes (native) |
| **Disk-based index** | Yes (Lucene segments + page cache) | No (in-memory) | Yes (Memmap) | No (primarily in-memory) |
| **Embedding generation** | No (ML Commons plugin, separate) | Yes (built-in) | No (manual) | Yes (built-in modules) |
| **Practical scale ceiling** | 1B+ vectors (Uber) | ~1M vectors | 100M+ vectors | 100M vectors |
| **P99 latency (1M, 768d)** | ~5ms | ~150ms | **~3ms** | ~5ms |
| **Pure vector QPS** | ~2,000 | ~800 | **~5,000** | ~2,500 |
| **Operational complexity** | Medium (JVM tuning, index mgmt) | **Lowest** | Low | Medium |

### 2.2 What Each Would Change in BiBLE's Architecture / 对 BiBLE 架构的影响

#### Chroma

```
BiBLE Server
    │
    ├── OpenSearch ── text search, metadata, async tasks (KEEP)
    │
    └── Chroma ── vector embedding + vector search (NEW)
         (embedded, same process)
```

- **What improves**: Dead simple API. Embedding generation is built-in (no separate `VectorTool` needed for the Chroma path). Zero operational overhead.
- **What breaks**: No hybrid search in a single query. You would run BM25 on OpenSearch + ANN on Chroma, then merge/fuse results in Python. This is strictly worse than BiBLE's current single-query hybrid approach.
- **Critical problem**: Chroma is an embedded library (SQLite/DuckDB for vectors). In BiBLE's multi-process architecture (FastAPI + Celery workers), each process gets its own copy — no shared state. Reads and writes from different processes see different data.
- **Verdict**: **Not suitable.** Chroma is for prototyping and single-user tools. BiBLE is a multi-client server. The architectural regression (losing native hybrid search, gaining per-process vector state) makes this a downgrade, not an upgrade.

#### Qdrant

```
BiBLE Server
    │
    ├── OpenSearch ── text search, metadata, async tasks (KEEP)
    │
    └── Qdrant ── vector storage + ANN search (NEW)
         (separate service, gRPC + REST)
```

- **What improves**: Best P99 latency (~3ms vs ~5ms). Payload filtering is excellent — Qdrant's approach to metadata filtering with indexed payload fields is genuinely better than OpenSearch's for pure vector + filter queries. Quantization (PQ/scalar) reduces memory 4–8×. Sparse vectors are native. Per-query `ef` tuning. Single Rust binary — far lighter than OpenSearch.
- **What breaks**: Hybrid search now requires two services — BM25 on OpenSearch, ANN on Qdrant, then fuse in Python. This adds a network round-trip and fusion logic that BiBLE currently gets for free inside OpenSearch.
- **Architecture decision**: If BiBLE introduces Qdrant, the right pattern is **vector-only path → Qdrant; text + hybrid → OpenSearch**. Do not try to replace OpenSearch entirely — its text search is excellent and already deeply integrated. Qdrant becomes a performance accelerator for the specific case where pure vector search latency/throughput matters.
- **Verdict**: **Best candidate IF a dedicated vector DB is needed.** But the trigger should be measured performance pain, not feature envy. The operational cost of a second database is real.

#### Weaviate

```
BiBLE Server
    │
    └── Weaviate ── text search + vector search + embedding (REPLACE OpenSearch?)
         (separate service, GraphQL + REST)
```

- **What improves**: Native hybrid search (BM25 + vector) is Weaviate's killer feature — it is genuinely better than OpenSearch's RRF in some benchmarks. Built-in embedding generation could simplify BiBLE's `VectorTool` → OpenSearch pipeline. GraphQL API is powerful. Knowledge graph capabilities align conceptually with BiBLE's multi-domain model.
- **What breaks**: Weaviate would need to **replace** OpenSearch, not complement it. Running both would be redundant — they compete on the same feature set. The migration is massive: re-index all data, rewrite all search DSL to GraphQL, move async task storage elsewhere (back to Redis? separate PostgreSQL?). The `IDatabaseWriter` abstraction would need a full Weaviate implementation from scratch.
- **What's new**: Weaviate's module ecosystem (text2vec, generative, reranker) could let BiBLE drop `VectorTool` and `RerankTool` entirely — Weaviate handles embedding and reranking server-side. But this means giving up control over the embedding pipeline and adding a Go service to a primarily Python/TypeScript stack.
- **Verdict**: **Too disruptive for now.** Weaviate is a replacement, not a complement. The migration cost is enormous relative to the marginal improvement over a well-tuned OpenSearch. Consider only if rebuilding BiBLE's search architecture from scratch in a v2.

#### Milvus

- **Verdict**: **Overkill.** Milvus is the performance king for billion-scale pure vector search, but its operational footprint (etcd + Pulsar/Kafka + multiple microservices) is unjustifiable for BiBLE's current scale. If BiBLE ever needs to manage 100M+ vectors with sub-2ms P99 latency, revisit.

---

## 3. The Real Question: Upgrade OpenSearch vs. Add Something New / 真正的问题

### 3.1 What OpenSearch 3.x Brings / OpenSearch 3.x 带来什么

BiBLE's codebase shows patterns consistent with OpenSearch 2.x (num_candidates stripping, no RRF usage). OpenSearch 3.0 (released 2025) brings substantial improvements:

| Feature | Impact on BiBLE |
|---|---|
| **Lucene-on-Faiss** | 2× throughput for quantized vectors. BiBLE could store vectors at 4–8× less memory with minimal recall loss |
| **GPU-accelerated indexing** | 6–13× faster index builds. Relevant when re-indexing large knowledge bases after import |
| **Native RRF hybrid search** | Better recall@10 than BiBLE's current `function_score` approach. Could simplify `QueryProfileCompiler._compile_hybrid()` |
| **Apache Lucene 10 + JVM 21** | ~20% faster queries, 10× throughput vs 1.x. Free performance |
| **Pluggable storage** | Vectors can live on S3/MinIO, not just local disk. Aligns with BiBLE's existing S3/MinIO file_system support |
| **Concurrent segment search** | Better utilization on multi-core machines for large indices |
| **Per-query `ef_search`** | Fixes the exact limitation in `writer.py:680` — `num_candidates` can be passed per-query again, enabling search-profile-level tuning |

**Bottom line:** Upgrading OpenSearch from 2.x to 3.x would directly address several implicit limitations visible in BiBLE's codebase today, without introducing a second database.

### 3.2 The Operational Cost of a Second Database / 引入第二个数据库的运维成本

Adding any dedicated vector DB means:

1. **Deployment**: New service to containerize, configure, monitor, upgrade, and secure
2. **Data sync**: Two sources of truth — text chunks in OpenSearch, vectors in Qdrant. Must keep them consistent during imports, updates, and deletes. A partial failure (vector written but text not, or vice versa) creates invisible inconsistency
3. **Query fan-out for hybrid**: Hybrid search fans out to two services, adding network latency and a new failure mode (one service down = degraded results)
4. **Backup/restore**: Two backup schedules, two restore procedures, two consistency models
5. **Developer cognitive load**: New query language (Qdrant's filter DSL, Weaviate's GraphQL), new client library, new failure modes, new monitoring
6. **Cost**: Additional compute resources for the second service running 24/7

For a team building an agent-native database, this operational complexity is non-trivial. The bar for "worth it" should be high.

---

## 4. Decision Framework / 决策框架

### 4.1 Stay with OpenSearch-Only When / 什么情况下保持现状

- Vector count below 10 million
- Hybrid search is the primary use case (not pure vector)
- P99 latency is acceptable (no user complaints)
- Team size is small and operational simplicity matters
- Full-text search quality matters as much as vector search
- You value having one query language, one backup, one monitor

→ **Stay with OpenSearch. Upgrade to 3.x. This is BiBLE's position today.**

### 4.2 Add Qdrant as a Sidecar When / 什么时候引入 Qdrant

- Vector count exceeds 10 million and indexing time becomes painful
- Pure vector search latency (P99 > 50ms) is the measured bottleneck
- You need per-query vector tuning (different `ef_search`, quantization levels per query) that search profiles already model
- You want to experiment with sparse vectors (SPLADE, etc.) alongside dense vectors
- Memory cost of OpenSearch vector storage becomes prohibitive (Qdrant's PQ can reduce memory 4–8×)

→ **Add Qdrant as a vector-only accelerator. Keep OpenSearch for text, hybrid, and async tasks. Implement a `QdrantWriter` behind the `IDatabaseWriter` protocol for vector paths.**

### 4.3 Consider Weaviate When / 什么时候考虑 Weaviate

- You are rebuilding BiBLE's search architecture from scratch (v2/v3)
- Native hybrid search + knowledge graph become central product features
- You want to offload embedding generation to the database
- The team is comfortable adding Go to the operational stack

→ **Full migration. But this is a v2/v3 decision, not an incremental improvement.**

### 4.4 Use Chroma When / 什么时候用 Chroma

- Quick prototype, demo, or single-user tool
- Tests that need an in-memory vector DB without Docker
- Local development where OpenSearch is not running

→ **Chroma for testing/dev only. Not for production BiBLE.**

---

## 5. Concrete Recommendations / 具体建议

### 5.1 Immediate (This Sprint) / 立即可做

1. **Upgrade OpenSearch target version** — From 2.x to 3.x in documentation and deployment scripts. The query API is backward-compatible; the main changes are configuration (JVM 21, new k-NN settings).

2. **Switch hybrid search to RRF** — Once on OpenSearch 2.12+, replace the `function_score` hybrid in `QueryProfileCompiler._compile_hybrid()` with a native RRF query template. This is approximately a 50-line change and yields better recall for free. It also removes the need for `text_weight`/`vector_weight` parameters (RRF doesn't use them).

3. **Remove the `num_candidates` workaround** — Delete `_strip_num_candidates_from_knn` and `_prepare_search_dsl` (writer.py:669-690) once the target version supports per-query `ef_search`. This unlocks per-search-profile tuning.

### 5.2 Near-Term (Next Quarter) / 近期可做

4. **Add quantization configuration** — Expose PQ/SQ settings in `bible-atlas.yaml` under the `vector:` config section. Allow users to trade recall for memory on large indices.

5. **Benchmark current performance** — Before considering Qdrant, measure: (a) P50/P99 search latency at current scale, (b) memory per vector, (c) indexing time for a typical import. You cannot decide "X is faster" without knowing your own numbers.

6. **Add vector-specific methods to `IDatabaseWriter`** — Currently `search_content_docs` takes a raw DSL dict. Consider adding typed methods like `search_by_vector(index, vector, top_k, filters)` to make the vector path backend-agnostic. This prepares the abstraction for a future Qdrant backend.

### 5.3 Medium-Term (When Vectors Exceed 10M) / 中期规划

7. **Implement `QdrantWriter`** behind the existing `IDatabaseWriter` protocol. Add `QdrantClientProvider` in the database factory. Route vector-only workloads to Qdrant while keeping text + hybrid on OpenSearch.

8. **Add `vector_backend` config** — Let `bible-atlas.yaml` specify `vector_backend: opensearch | qdrant`. Default stays `opensearch`. Qdrant becomes an opt-in accelerator.

### 5.4 What NOT to Do / 不要做的事

- **Do not replace OpenSearch entirely** — its text search (BM25, multi_match, bool queries) is excellent, battle-tested, and deeply integrated into BiBLE's import pipeline, binding system, and async task storage
- **Do not add a vector DB "just in case"** — the operational cost is real even if the software is free. Every new service is a new failure domain
- **Do not use Chroma for production** — it is a single-node embedded library, not a multi-client server
- **Do not run OpenSearch + Weaviate together** — they are redundant; pick one
- **Do not make this decision without benchmarking YOUR workload** — every benchmark online uses different data, hardware, and query patterns than BiBLE

---

## 6. Appendix: BiBLE's Current Vector Code Path (End-to-End) / 附录：完整链路

```
 1. API Layer
    bible/api/search/memory_search_api.py
    → POST /api/search/memory {query, search_type: "hybrid", top_k: 10}

 2. Service Layer
    bible/features/search/memory_search/memory_search_service.py
    → Resolves index binding, validates search_type, selects vector_model

 3. Searcher
    bible/features/search/memory_search/searcher/search_memory.py
    → Step 1: vector_tool.ensure_model_ready(model_name) + embed_query(query)
    → Step 2: compiler.compile(search_type="hybrid", query_vector=...)
        → _compile_hybrid() builds:
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
    → Step 3: db_writer.search_content_docs(index, dsl)
        → writer.py: _prepare_search_dsl() strips num_candidates from knn body
        → _client.search() hits OpenSearch
    → Step 4: map_hits(raw_hits) → cleaned result dicts

 4. Rerank (in Service Layer, post-search)
    bible/infrastructure/vector/rerank_tool.py
    → rerank(query, passages, model_name) → cross-encoder scores
    → Re-sort results by rerank score

 5. Response
    → {kb_index, total, items: [{...}, ...]}
```

---

## Sources / 参考来源

- [OpenSearch: Using OpenSearch as a Vector Database](https://opensearch.org/blog/using-opensearch-as-a-vector-database/)
- [OpenSearch: Lucene-on-Faiss for high-performance vector search](https://opensearch.org/blog/lucene-on-faiss-powering-opensearchs-high-performance-memory-efficient-vector-search/)
- [AWS: Billion-scale vector databases with GPU acceleration on OpenSearch](https://aws.amazon.com/blogs/big-data/build-billion-scale-vector-databases-in-under-an-hour-with-gpu-acceleration-on-amazon-opensearch-service/)
- [Uber: Powering Billion-Scale Vector Search with OpenSearch](https://www.uber.com/ng/en/blog/powering-billion-scale-vector-search-with-opensearch/)
- [OpenSearch: Concurrent vector graph construction](https://opensearch.org/blog/breaking-the-single-thread-bottleneck-concurrent-vector-graph-construction-in-opensearch/)
- [OpenSearch: Enhanced multi-vector support in k-NN search](https://opensearch.org/blog/enhanced-multi-vector-support-in-opensearch-knn/)
- [OpenSearch K-NN vs Aurora pgvector](https://swac.blog/opensearch-k-nn-vs-aurora-pgvector-choosing-your-vector-store-on-aws/)
- [Portkey: Vector DB Comparison (GitHub)](https://github.com/portkeys/vector-db-comparison)
- [Vector DB Benchmark: Qdrant, Milvus, Weaviate, ChromaDB](https://github.com/scriptstar/vector-db-benchmark)
