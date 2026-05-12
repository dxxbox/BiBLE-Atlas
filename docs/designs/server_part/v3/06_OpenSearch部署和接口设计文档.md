# OpenSearch 部署与接口设计文档

本文档描述 Bible Atlas 服务侧与 **OpenSearch** 相关的 **集群部署**（第一章）与 **应用接口**（第二章）。第二章采用 **`infrastructure/opensearch/` 扁平结构**（`client.py`、`search_manager.py`、`index_manager.py`、`document_manager.py`、`mappings/`）：**检索与结果格式化**在 **`search_manager.py`**；**逻辑文档/章节导入与按文档删除**在 **`document_manager.py`**；**连接与探测**在 **`client.py`**（与 **[01_架构总览](./01_架构总览.md)** 中的模块划分一致：以 `search_manager` 承担检索与 DSL，以 `document_manager` 承担逻辑文档写入与删除；可不单独保留 `query_builder.py` 文件）。并显式对齐：

- **[system_startup_flow.puml](./pumls/system_startup_flow.puml)** 中 OpenSearch 分支的启动与失败策略；
- **[search_flow_with_hit_and_rerank.puml](./pumls/search_flow_with_hit_and_rerank.puml)** 中检索流水线（原图注为「ES」，存储后端为 OpenSearch 时行为等价）；
- **[04_API接口文档.md](./04_API接口文档.md)** 中健康检查、检索、索引与文档等 API 对底层存储的隐含要求。


---

## 一、部署设计

### 1.1 集群概览

| 项目 | 说明 |
|------|------|
| 集群名称 | `bible-opensearch` |
| 节点数量 | 3（`os01`、`os02`、`os03`） |
| 镜像 | `localhost/bible-opensearch:ik-knn`（需本地构建或导入，含 IK 分词与 k-NN 等插件能力） |
| 安全插件 | **已关闭**（`plugins.security.disabled=true`），HTTP 无 TLS/认证，**仅适合内网或受控网络** |
| JVM 堆内存 | 每节点 `-Xms2g -Xmx2g`（`OPENSEARCH_JAVA_OPTS`） |

### 1.2 节点角色与职责

| 节点 | 容器名 | 角色（`node.roles`） | 说明 |
|------|--------|---------------------|------|
| os01 | `opensearch-os01` | `cluster_manager` | 仅承担集群管理（原 master 职责），不参与 data/ingest |
| os02 | `opensearch-os02` | `data`, `ingest` | 数据与写入管道 |
| os03 | `opensearch-os03` | `data`, `ingest` | 数据与写入管道 |

**集群引导：**

- `cluster.initial_master_nodes=os01`：首次形成集群时，仅从 `os01` 作为初始 master-eligible 集合参与 bootstrap（与单 master 节点拓扑一致）。
- `discovery.seed_hosts=os01,os02,os03`：节点间通过服务名发现（需在同一 Docker 网络内解析，见下文）。

### 1.3 网络与端口映射

容器内统一监听：

- HTTP：`0.0.0.0:9200`
- Transport：`0.0.0.0:9300`

宿主机映射（便于本机或局域网访问 HTTP、排查集群通信）：

| 服务 | HTTP（宿主机 → 容器） | Transport（宿主机 → 容器） |
|------|----------------------|-----------------------------|
| os01 | `19200 → 9200` | `19300 → 9300` |
| os02 | `9201 → 9200` | `9301 → 9300` |
| os03 | `9202 → 9200` | `9302 → 9300` |

应用或运维通常通过 **HTTP** 访问集群，例如默认将客户端指向 **`http://<宿主机>:19200`**（os01）或配合负载均衡指向多个 HTTP 端口；具体以应用配置为准。

### 1.4 持久化卷

每个节点使用独立命名卷，数据目录挂载为 `/usr/share/opensearch/data`：

| 卷名 | 节点 |
|------|------|
| `os01_data` | os01 |
| `os02_data` | os02 |
| `os03_data` | os03 |

删除容器时若需保留数据，请勿随意删除对应 volume；清理集群数据前需评估备份与索引重建成本。

### 1.5 资源与内核限制

- **内存锁定**：`bootstrap.memory_lock=false`，同时 `ulimits.memlock` 为 `soft/hard: -1`（与常见 Docker 部署示例一致，避免 memlock 过小导致启动问题）。
- **文件句柄**：`nofile` soft/hard 均为 `65536`，满足高并发连接场景。

### 1.6 Docker Compose 定义（参考）

以下为当前环境的 **完整服务与卷声明**，可直接作为 `docker-compose.yml` 片段使用（需保证镜像 `localhost/bible-opensearch:ik-knn` 已存在）。

```yaml
services:
  os01:
    image: localhost/bible-opensearch:ik-knn
    container_name: opensearch-os01
    environment:
      - cluster.name=bible-opensearch
      - node.name=os01
      - discovery.seed_hosts=os01,os02,os03
      - cluster.initial_master_nodes=os01
      - node.roles=cluster_manager
      - bootstrap.memory_lock=false
      - plugins.security.disabled=true
      - network.host=0.0.0.0
      - http.port=9200
      - transport.port=9300
      - OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - os01_data:/usr/share/opensearch/data
    ports:
      - "19200:9200"
      - "19300:9300"

  os02:
    image: localhost/bible-opensearch:ik-knn
    container_name: opensearch-os02
    environment:
      - cluster.name=bible-opensearch
      - node.name=os02
      - discovery.seed_hosts=os01,os02,os03
      - cluster.initial_master_nodes=os01
      - node.roles=data,ingest
      - bootstrap.memory_lock=false
      - plugins.security.disabled=true
      - network.host=0.0.0.0
      - http.port=9200
      - transport.port=9300
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - os02_data:/usr/share/opensearch/data
    ports:
      - "9201:9200"
      - "9301:9300"

  os03:
    image: localhost/bible-opensearch:ik-knn
    container_name: opensearch-os03
    environment:
      - cluster.name=bible-opensearch
      - node.name=os03
      - discovery.seed_hosts=os01,os02,os03
      - cluster.initial_master_nodes=os01
      - node.roles=data,ingest
      - bootstrap.memory_lock=false
      - plugins.security.disabled=true
      - network.host=0.0.0.0
      - http.port=9200
      - transport.port=9300
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - os03_data:/usr/share/opensearch/data
    ports:
      - "9202:9200"
      - "9302:9300"

volumes:
  os01_data:
  os02_data:
  os03_data:
```

### 1.7 部署前置条件

1. **镜像**：在构建环境或部署机上存在 `localhost/bible-opensearch:ik-knn`（或改为私有仓库地址并同步修改 `image`）。
2. **Docker 网络**：三个服务需在同一 Compose 工程内，使主机名 `os01`、`os02`、`os03` 可互相解析；若拆分到多主机，需改为真实主机名/IP 并调整 `discovery.seed_hosts` 等。
3. **宿主机内存**：每节点 JVM 2GB 堆，宿主机需预留足够 RAM（含页缓存与操作系统开销），建议单节点可用内存显著大于 2GB。
4. **安全**：当前配置关闭 Security 插件，**禁止直接暴露到公网**；生产环境应启用 TLS、认证与网络隔离，并重新评估 `plugins.security.disabled`。

### 1.8 启动与健康检查

启动（在包含上述 `docker-compose.yml` 的目录）：

```bash
docker compose up -d
```

集群与节点状态（示例，指向 os01 的 HTTP 映射端口）：

```bash
curl -s "http://127.0.0.1:19200/_cluster/health?pretty"
curl -s "http://127.0.0.1:19200/_cat/nodes?v"
```

期望 `_cluster/health` 中 `status` 最终为 `green` 或 `yellow`（视副本与分片配置而定），且 `_cat/nodes` 列出三个节点。

---

## 二、应用与 OpenSearch 接口设计（扁平结构）

### 2.1 文件结构

与 **[01_架构总览.md](./01_架构总览.md)**（OpenSearch 替代方案）对齐：

```
infrastructure/opensearch/
├── client.py               # 连接、探测、底层 OpenSearch 客户端封装（供其余模块注入）
├── search_manager.py       # 五种检索 + DSL 组装 + _search/_msearch + 结果格式化
├── index_manager.py        # 索引级：创建/删除索引、mapping/settings、统计与运维查询
├── document_manager.py     # 逻辑文档级：章节 bulk 导入、按 document_key 删除、存在性检查、_id 规则
└── mappings/
    ├── documents.json      # 文档主索引映射
    └── chunks.json         # 文档块索引映射（session/skill 等大文档分块）
```

**职责边界**：**检索**仅通过 **`search_manager`**；**索引模板与索引是否存在**通过 **`index_manager`**；**某索引内向 OpenSearch 写入多条章节、按逻辑文档键清空**通过 **`document_manager`**；**`client.py`** 提供 **连接、探测** 及 **被上述三者复用的底层 API 能力**（如持有 `opensearch-py`、统一超时、`bulk`/`delete_by_query` 的**无业务语义**调用入口可由 `document_manager`/`search_manager` 组合使用）。

---

### 2.2 对 system_startup_flow.puml（OpenSearch 分支）的满足

对应 **[system_startup_flow.puml](./pumls/system_startup_flow.puml)** 中 `case (OpenSearch)`：

| 流程步骤 | 模块落点 | 说明 |
|----------|---------|------|
| 从配置读取连接信息 | `config/settings.py`（或 `.env`）中的 `OPENSEARCH_*` / `OPENSEARCH_URL` | 与 **[03_配置管理设计](./03_配置管理设计.md)** 静态配置一致。 |
| 创建 OpenSearch 客户端 | **`client.py`** | 封装 `opensearch-py`，单例或应用级持有；提供超时、重试策略。 |
| 测试连接 | **`client.py`** | 如 `ping()`、`info()` 或 `cluster.health()`；失败时抛出明确异常供 `main` 捕获。 |
| 连接成功则记录集群信息 | **`client.py`** 返回或 **`main`/健康模块** 记录 | 至少包含 **集群名、版本号、节点数**，供 **`GET /api/v1/health`** 使用（见 2.4）。 |
| 连接失败则记录错误并 **启动失败** | **应用入口** | 与 ES/PG 分支一致：**存储后端不可用则中止启动**（除非产品明确允许「降级无检索」，当前流程图为失败 `stop`）。 |

**实现提示**：`index_manager.py` **不参与**首次 TCP 级探测；首次连通性仅以 `client.py` 为准，避免循环依赖。

---

### 2.3 对 search_flow_with_hit_and_rerank.puml（存储为 OpenSearch）的满足

原图在 Repository 层写「执行 **ES** 检索」；后端为 OpenSearch 时，语义不变，实现映射如下：

| 流程要素 | 模块落点 | 说明 |
|----------|---------|------|
| 解析 TAG、`tag_to_index_mapping`、构造 `index_name_set` | **SearchService**（不变） | 与图一致。 |
| `enable_hit`、`hit_list`、多索引并入集合 | **SearchService**（不变） | 与图一致。 |
| `top_k` 与 rerank 时的 `top_k × multiplier` | **SearchService** | 向 Repository / **`search_manager`** 传入**放大后的 size**；OpenSearch 返回多条后再截断到 `original_top_k`。 |
| Repository 侧检索编排 | **`search_manager.py`** | 根据 `search_type`（**五种**：keyword / title / text / vector / hybrid）、`vector_weight`、`filter_mode` 等组装 **OpenSearch 2.x DSL**；向量部分使用 **knn** query；可在模块内用私有函数承担 query 拼装，**不**再单独要求 `query_builder.py` 文件。 |
| 执行检索与结果格式化 | **`search_manager.py`** | 调用 **`client`** 的传输能力执行 `POST /_search` 或 `_msearch`；将原始 hits **`_score` → 业务 `score`**、组装统一分页结构；多索引可 **`msearch`** 或并行 `search`（与 Service 编排一致）。 |
| 返回 `top_k` 条、带分值 | **`search_manager` 输出** → Repository 透传或再映射 | 输出多结果并带分值，与检索流水线约定一致。 |
| rerank | **RerankTool**（`infrastructure/vector`） | 在 Repository 返回后、Service 合并前或每路结果上，与图一致。 |
| 合并多索引结果 | **SearchService** | 与图一致；注意多索引 **分值尺度** 可选归一化（按产品对合并与排序的规则实现）。 |

**依赖关系**：`features/search/repositories/*.py` → 调用 **`search_manager.py`**（传入业务参数，由其在内部完成 DSL + `search`/`msearch` + 格式化）；**不**在 Repository 内手写原始 JSON；单测可 mock `search_manager` 或注入假 `client`。

---

### 2.4 对 04_API 健康检查与其它 API 的满足

#### 2.4.1 `GET /api/v1/health`（显式要求）

**[04_API接口文档](./04_API接口文档.md)** 示例响应含 `elasticsearch: { connected, cluster_name, version, nodes }`。存储后端为 OpenSearch 时建议：

- **方案 A（推荐）**：增加并列字段 **`opensearch`**，结构与之同构，例如：

```json
"opensearch": {
  "connected": true,
  "cluster_name": "bible-opensearch",
  "version": "2.x.x",
  "nodes": 3
}
```

- **方案 B**：保留单一键名 `elasticsearch`，值为「通用存储后端快照」，在文档中注明实际引擎为 OpenSearch（易混淆，不推荐长期）。

**启动阶段**已用 `client.py` 探测成功时，健康检查应 **复用同一客户端** 或 **短时 info 调用**，避免重复建连；`connected: false` 时整体 `status` 可为 **`degraded` 或 `unhealthy`**（与产品定义一致）。

#### 2.4.2 `POST /api/v1/search`（显式要求）

由 **Service + Repository + `search_manager` + `client`（传输）** 满足；字段与 **[04](./04_API接口文档.md)** 一致（`index_name`、`query`、`tag`、`enable_hit`、`search_type`、`vector_weight`、`top_k`、rerank 相关配置等）。

#### 2.4.3 其它 API 对 OpenSearch 的隐含要求（补充）

以下在 04 中存在，设计需保证 **底层可调用 OpenSearch 等价 API**：

| API（04） | 对 `client` / `index_manager` / `document_manager` 的期望 |
|-----------|-------------------------------------------|
| `GET /api/v1/indices`、`GET /api/v1/indices/{index_name}` | **`index_manager.py`**（或 `client` 薄封装）封装 `GET _cat/indices`、`_stats`、`_settings` 等，映射为 04 中的列表与单索引详情。 |
| `POST /api/v1/upload`、`GET /api/v1/tasks/...` | 异步任务最终 **`_bulk` 写入章节文档**；由 **`document_manager.py`** 组装 bulk 行为（或调用 `helpers.bulk`），**`client`** 提供连接；索引与 mapping 由 **`index_manager`** 确保存在；**`mappings/documents.json` 或 `chunks.json`**。 |
| `GET/PUT/DELETE /api/v1/docs/{doc_id}` | 单条/逻辑文档 CRUD：**读删改**可经 **`document_manager`**（按 `_id` 或 **`delete_by_query`** 按 `document_key`）；与 **单文档多章节** 设计一致（见 **§2.5.4**）。 |
| Session/Skill 多文件上传 | 大块走 **chunks 索引** + `chunks.json` + **`document_manager` bulk**；与 **upload_import_flow.puml** 一致。 |
| `POST /api/v1/admin/config/reload` | 不直接打 OpenSearch；但 **`dynamic_config`** 变更后 **`tag_to_index_mapping`、`hit_list`、`rerank`** 等影响 **下一轮 `search_manager` 行为**，无需重启（与 03 热更新边界一致）。 |

---

### 2.5 扁平模块的职责与推荐接口

本节约定：**索引**与「逻辑文档（多章节）」分离；**检索**与**写入**分离。

以下 **2.5.1～2.5.4** 在职责表之后，分别给出 **`client.py` / `search_manager.py` / `index_manager.py` / `document_manager.py` 中建议对外暴露的类与方法签名**（Python 风格；底层类型为 **`opensearch-py`** 的 `OpenSearch`；DSL 字段类型按本文 **OpenSearch** 约定，如 `knn_vector`）。

---

#### 2.5.1 `client.py`（OpenSearch 客户端封装；**不含**业务语义）

| 职责 | 说明 |
|------|------|
| 构造 | 读取 `Settings` 中的 OpenSearch URL/超时。 |
| 连接探测 | `ping` / `info` / `cluster.health`（或等价），供 **启动** 与 **`GET /api/v1/health`**。 |
| 通用能力 | 暴露 **`get_client()`**（或包内只读属性）供 **`search_manager` / `index_manager` / `document_manager`** 调用底层 `opensearch-py`；可封装 **重试、超时**。 |
| 原则 | **不**承载「五种检索」「按逻辑文档 bulk」「按 mapping 建索引」等业务方法；仅 **传输与集群级探测**。 |

**禁止**：业务层直接 import 原始 `OpenSearch` 类并散落调用（测试除外）。

**类名建议**：`OpenSearchClient`（与 **[system_startup_flow](./pumls/system_startup_flow.puml)** 中 `infrastructure/opensearch/client.py` 一致）。

| 方法 | 签名 | 说明 |
|------|------|------|
| 构造 | `__init__(self, opensearch_url: str, *, timeout: float \| None = None, ...)` | URL 来自 `Settings` / `OPENSEARCH_URL`。 |
| 探测 | `test_connection(self) -> tuple[bool, str]` | 成功返回 `(True, 摘要信息)`；失败 `(False, 错误信息)`，供启动失败分支。 |
| 集群快照 | `get_cluster_info(self) -> dict` | 至少含 `cluster_name`、`version`（字符串）、便于扩展 `number_of_nodes`；供 **`GET /api/v1/health`** 的 `opensearch` 字段。 |
| 存活 | `ping(self) -> bool` | 轻量探测。 |
| 原生句柄 | `get_client(self) -> OpenSearch` | 供 **`search_manager` / `index_manager` / `document_manager`** 调用 `indices.*`、`search`、`bulk`、`count`、`delete_by_query` 等（业务语义由上层封装）。 |

---

#### 2.5.2 `search_manager.py`（五种检索 + 结果格式化）

| 职责 | 说明 |
|------|------|
| **五种检索** | 与 **[04](./04_API接口文档.md)** 中 `search_type` 对齐：`keyword`、`title`、`text`、`vector`、`hybrid`；在模块内组装 DSL（`term` / `match` / `multi_match` / `knn` / `bool.should` 等），向量字段 **`knn_vector`**、查询 **`knn`**，中文 IK 与镜像一致；可实现为五个独立方法或统一 `search` + 内部分派。 |
| **执行检索** | 通过 **`client.get_client()`** 执行 `_search` / `_msearch`。 |
| **结果格式化** | `_score` → **`score`**、`max_score`、`took`、hits；可选 `score_raw` / `score_breakdown`。 |
| **可选** | `search_many`（`enable_hit` 多索引）；查询向量由 **上层或入参** 注入 **`VectorTool`** 结果，**不在 `client` 加载模型**。 |

实现上可在模块内拆私有 **`_build_query_*`**，**无需**单独 `query_builder.py` 文件。

**类名建议**：`SearchManager`；构造注入 **`OpenSearchClient`**。

**五类检索 + 格式化（OpenSearch 语义）**：

| 方法 | 签名 | 说明 |
|------|------|------|
| 关键字 | `keyword_search(self, index_name: str, query: str, top_k: int = 10, **kwargs) -> dict` | `term` 于 `section_title.keyword`（或 mapping 约定字段）；返回 **OS 原始** `search` 响应。 |
| 标题 | `title_search(self, index_name: str, query: str, top_k: int = 10, **kwargs) -> dict` | `match` 于 `section_title`（IK）。 |
| 文本 | `text_search(self, index_name: str, query: str, top_k: int = 10, **kwargs) -> dict` | `multi_match` 于 `content` / `section_title` / `breadcrumb` 等（字段 boost 按 mapping 与产品约定配置）。 |
| 向量 | `vector_search(self, index_name: str, query_vector: list[float], top_k: int = 10, *, vector_field: str = "content_vector", **kwargs) -> dict` | OpenSearch 使用 **`knn`** 子句；`num_candidates` 等参数可配置（以所用 OpenSearch 版本语法为准）。 |
| 混合 | `hybrid_search(self, index_name: str, query: str, query_vector: list[float], top_k: int = 10, vector_weight: float = 0.6, **kwargs) -> dict` | `bool.should` + `multi_match` 与 **`knn`** 组合，`vector_weight` 与 **[04](./04_API接口文档.md)** 对齐。 |
| 统一入口（可选） | `search(self, spec: "OpenSearchQuerySpec") -> "ScoredSearchPage"` | 根据 `spec.search_type` 分派至上述五类之一；`spec` 为 Pydantic 模型时类型更清晰。 |
| 多索引 | `msearch(self, bodies: list[tuple[str, dict]]) -> list[dict]` 或 `search_many(self, specs: list["OpenSearchQuerySpec"]) -> list["ScoredSearchPage"]` | 对应 **`enable_hit`** 多路检索；内部 `msearch` 或并行 `search`。 |
| 格式化 | `format_results(self, raw_results: dict) -> list[dict]` | 将每条 hit 的 **`_score` → `score`**，展开 `_source` 中与 **[04](./04_API接口文档.md)** 一致的字段；多索引场景可增加 `index` 等字段。 |
| 包装返回（可选） | `search_and_format(self, index_name, ..., search_type: str, ...) -> list[dict]` | 先 `*_search` 再 `format_results`，供 Repository 一行调用。 |

---

#### 2.5.3 `index_manager.py`（索引级；**不含**单逻辑文档 bulk/按文档删除)

| 职责 | 说明 |
|------|------|
| 创建/删除 **物理索引** | `PUT`/`DELETE` index；body 来自 **`mappings/*.json`** 与 settings（`index_exists`、`get_index_config`、`create_index` 等）。 |
| 存在性 | `HEAD` index。 |
| 运维查询 | `_stats`、`_cat/indices`、settings/mapping 读取（支撑 **04** `GET /api/v1/indices*`）。 |
| 向量 mapping 探测 | 可选 `detect_vector_config`（字段类型按 **`knn_vector`** 解析）。 |

**不在此模块**：面向业务的 **`_bulk` 导入多章节**、**按 `document_key` 的 `delete_by_query`** —— 归 **`document_manager.py`**，以免与「删整个索引」混淆。

**类名建议**：`IndexManager`；构造注入 **`OpenSearchClient`**。

| 方法 | 签名 | 说明 |
|------|------|------|
| 存在 | `index_exists(self, index_name: str) -> bool` | `indices.exists`。 |
| 配置 | `get_index_config(self, index_name: str) -> dict` | 聚合 **mappings + settings**。 |
| 向量探测 | `detect_vector_config(self, index_name: str) -> dict` | 返回 `has_vector`、`dims`、`model`（可按维度推断模型；向量字段类型按 **`knn_vector`** 判断）。 |
| 创建 | `create_index(self, index_name: str, use_vector: bool, vector_dims: int \| None = None, *, mapping_template: str \| None = None) -> bool` | 优先从 **`mappings/*.json`** 加载；`use_vector` 时写入 **`knn_vector`** 维度。 |
| 删除整索引 | `delete_index(self, index_name: str) -> tuple[bool, int]` | `(是否成功, 删除前文档条数)` 或 `(False, 0)`。 |
| 统计 | `get_index_stats(self, index_name: str) -> dict` | `doc_count`、`size_bytes`、`created_at` 等，供 **04 索引详情 API**。 |

---

#### 2.5.4 `document_manager.py`（逻辑文档级：导入、删除、存在性）

**依赖注入 `OpenSearchClient`（`client.py` 封装）**，负责 **索引内文档数据** 的生命周期，而非集群/索引模板本身。

| 职责 | 说明 |
|------|------|
| **标识与 _id** | 从文件名或业务规则生成稳定 **`document_key`**（如去扩展名、规范化路径或哈希）；章节级 **`_id`** 规则如 **`document_key#section_id`**，或 **`hash(document_key:section_id)`** 等稳定形式，保证 bulk 幂等。 |
| **存在性** | **`count` + `term` 查询** **`document_key`**，返回是否已有及章节数。 |
| **批量导入** | **`bulk_import`**：组装 `helpers.bulk` 所需 actions，写入后 **`indices.refresh`**；供 **Celery `import_document_task`** / 上传流水线调用。 |
| **按逻辑文档删除** | **`delete_by_query`** 按 **`document_key`** 删除该文档下全部章节；返回删除条数。 |
| **设计要点** | 单文档多章节、按 `document_key` 的 **`delete_by_query`** 与 **§2.3** 检索流水线、**§2.4** API 约束一致。 |

**依赖**：仅依赖 **`client`**；**不**依赖 `search_manager`；建索引前置条件由 **`index_manager`** 或运维保证。

**类名建议**：`DocumentManager`；构造注入 **`OpenSearchClient`**；内部使用 **`get_client()`** 调用 `bulk`、`count`、`delete_by_query`、`indices.refresh`。

| 方法 | 签名 | 说明 |
|------|------|------|
| document_key | `derive_document_key(self, filename: str) -> str` | 从文件名或业务规则得到稳定 **`document_key`**（去扩展名、规范化字符等），在索引内唯一标识逻辑文档。 |
| 复合 id | `generate_doc_id(self, document_key: str, section_id: str) -> str` | 如 `{document_key}#{section_id}`。 |
| 存在性 | `get_document_presence(self, index_name: str, document_key: str) -> tuple[bool, int]` | 对 **`document_key` 字段** `term` + `count`；返回 `(是否存在, 章节数)`。 |
| 批量导入 | `bulk_import(self, index_name: str, documents: list[dict]) -> dict` | 每项含 **`_id`** 与 `_source` 字段；返回 `success_count`、`error_count`、`errors`；末尾 **`refresh`**。 |
| 按文档删除 | `delete_by_document_key(self, index_name: str, document_key: str) -> int` | **`delete_by_query`**，对 **`document_key` 字段** `term`。 |

**说明**：`documents` 中 `_source` **须含** **`document_key`**（字段名与类型以 **`mappings/documents.json`** 为准）。

---

### 2.6 `mappings/` 与数据模型

| 文件 | 用途 |
|------|------|
| `documents.json` | 文档级主索引（字段含业务所需 `document_key`、`section_*`、向量字段等）。 |
| `chunks.json` | 块级索引（Session/Skill 大文档分块）；与 **upload_import_flow**、**05 存储方案** 中大文档策略一致。 |

索引模板版本变更时，建议 **别名切换** 或 **运维窗口** 重建索引，避免与 **04** 中线上 `index_name` 硬编码假设冲突。

---

### 2.7 与 PlantUML 的对应关系

| 图 | 与扁平模块的对应 |
|----|---------------------|
| [system_startup_flow.puml](./pumls/system_startup_flow.puml) OpenSearch 分支 | `client.py` 创建、测试、记录集群信息；失败则 `stop`。 |
| [search_flow_with_hit_and_rerank.puml](./pumls/search_flow_with_hit_and_rerank.puml) | **`search_manager.py`**（含 DSL + `_search`/`_msearch` + 格式化）+ **`client.py`（传输）** 替代图中「ES 检索」；多索引与 rerank 逻辑不变。 |
| [opensearch_search_sequence.puml](./pumls/opensearch_search_sequence.puml)（若使用） | 与 2.3 一致。 |
| [opensearch_multi_chapter_import_delete.puml](./pumls/opensearch_multi_chapter_import_delete.puml) | **`document_manager`**（bulk + `delete_by_query`）+ **`client`**；**非**整索引删除（整索引仍属 `index_manager`）。 |

---

### 2.8 本章小结

- **部署**：见第一章。  
- **代码结构**：**`client.py` + `search_manager.py` + `index_manager.py` + `document_manager.py` + `mappings/`**（检索归 `search_manager`；索引模板归 `index_manager`；章节导入/按文档删归 `document_manager`）。  
- **启动**：满足 **system_startup_flow** 的 OpenSearch 分支。  
- **检索**：满足 **search_flow_with_hit_and_rerank**（引擎为 OpenSearch，DSL 用 knn）。  
- **API**：满足 **[04](./04_API接口文档.md)** 的健康检查（增加或并列 **`opensearch`** 字段）、检索、索引列表/详情、上传与文档管理对底层的隐含要求。  
- **进阶模型**（多章节、`document_key`、分值）：细节见 **§2.3～§2.5** 与 **[04](./04_API接口文档.md)**；**写入/删除章节数据**由 **`document_manager` + `client`** 实现；**检索侧分值**由 **`search_manager`** 与 **04** 及动态配置中的字段约定对齐。
