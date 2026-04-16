# Import/Search 流程 session 详细设计

本文档仅细化 SESSION 类型在 import 与 search 中的处理分支，不重写通用 import、search 主流程。通用分层以 `01_架构总览.md` 为准，通用 Import 主链路以 `08_Import_no_session_skill_detail_design.md` 为准，通用 Search 主链路以 `07_Search流程_no_session_skill_详细设计.md` 为准，OpenSearch 基础设施边界以 `06_OpenSearch部署和接口设计文档.md` 为准；本文只补 session 在这些既有流程中的文件集合、字段规范、目录职责、函数边界与返回收口。

---

## 1. 本次细化范围与非目标

### 1.1 本次细化范围

- 仅讨论 SESSION 类型在 import 中的文件接收、校验、落盘、摘要生成、索引构建。
- 仅讨论 SESSION 类型在 search 中的查询字段、过滤字段、命中整形、返回边界。
- 仅讨论四文件集合 message.json、.abstract.md、.overview.md、meta.json 的生成责任、格式规范与 strict/lite 差异。
- 仅讨论 session 分支需要新增或下沉到 repositories/session 的目录、文件、函数职责。

### 1.2 非目标

- 不重写通用 Import API、Search API 的主流程。
- 不扩展 CODE、SCT、BUILD、SKILL 等其他类型的 import/search 设计。
- 不定义 download API 的完整协议，只说明 search 与 download 的边界。
- 不展开 session merge、delete、全局向量检索、权限控制、脱敏策略的完整实现。
- 不写业务代码，仅输出可执行设计。

---

## 2. 设计定位与主链路衔接

SESSION 与其他文档类型的关键差异如下：

- import 侧不仅要建立可检索元数据，还要保留原始会话文件集。
- search 侧默认只返回轻量结果，不直接把完整 `message.json` 作为主响应载荷。
- session 的事实源不是单文件正文，而是四文件集合：`message.json`、`.abstract.md`、`.overview.md`、`meta.json`。

因此，session 的实现定位应明确为“挂接在既有主链路上的增量分支”，而不是单独再造一套上传、检索、存储体系。

主原则如下：

- API 层只保留 HTTP 协议、入参校验和错误映射，不新增 session 专属复杂编排。
- Import 主链路继续复用 `08` 中的 `import_api.py -> ImportService -> domain/infrastructure -> Celery/OpenSearch` 结构；session 只在 Import 内部增加专属识别、校验、四文件处理与索引文档构建。
- Search 主链路继续复用 `07` 中的 `search_api.py -> SearchService -> SearchRepositoryFactory -> Repository` 结构；session 只把占位空仓储替换为真实 `SessionSearchRepository`。
- OpenSearch 侧继续复用 `06` 中的 `search_manager.py`、`document_manager.py`、`chunks.json`；session repository 不手写底层检索 DSL，也不直接承担 bulk 写入细节。

与既有主链路的衔接关系可直接理解为两条文字链路：

- Import 链路：`import_api.py` -> `ImportService` -> `features/import/infrastructure/session/*` -> `document_manager.py`
- Search 链路：`search_api.py` -> `SearchService` -> `SearchRepositoryFactory` -> `features/search/repositories/session/*` -> `search_manager.py`

session 分支只负责以下增量职责：

- 识别当前 import/search 是否命中 `SESSION` 业务。
- 把会话事实统一规整为四文件集合和稳定的 `session_id/document_key`。
- 构建适合 OpenSearch 主索引与 chunk 索引的 session 文档模型。
- 对 session 搜索结果做聚合、裁剪和 raw 内容返回边界控制。

下列能力继续显式复用通用框架，不在本文中重写：

- 通用 Import Job 生命周期、异步任务状态机、Celery 提交与重试。
- 通用 Search 的 `enable_hit`、多索引并发、分桶合并、统一响应结构。
- OpenSearch 的底层 DSL、`_search/_msearch`、`bulk_import`、索引 mapping 管理。
- download、安全权限、全局治理、rerank/AI 平台能力。

---

## 3. 四文件生成责任方案比较

### 3.0 输入理解：API 视角与 session 内部视角

先明确“输入”这件事要分成两层理解。

API 视角只关心下面几件事：

- 本次 import 请求是否被识别或显式标记为 `SESSION`。
- 请求里是否带了 session 相关文件集合。
- 四文件里哪些文件存在，哪些缺失。
- 调用方选择的是 `strict` 还是 `lite`。

也就是说，API 层不需要理解 `message.json` 内部复杂结构，只需要完成“是否是 session”“文件是否齐”“模式是什么”的协议判断，并把原始输入交给 ImportService。

session 内部视角才关心下面几件事：

- 四文件各自承载什么业务语义。
- 哪些关键字段必须从文件内容中提取。
- 哪些字段进入结构化元数据，哪些进入轻量摘要，哪些进入 chunk/向量索引。
- 当文件缺失或字段不足时，`strict/lite` 分别如何处理。

因此，本文后续的设计会按“先定义输入文件语义，再定义 import/search 模块职责，再定义数据库存储契约”展开，而不是站在 API 协议层面展开内部细节。

### 3.1 四文件与角色定义

| 文件 | 角色 | 定位 | 主要消费方 |
|------|------|------|------|
| message.json | raw_json | 原始会话事实源 | import 校验、download、再摘要、审计 |
| .abstract.md | abstract | 一句话总结 | search 列表首屏、快速命中摘要 |
| .overview.md | overview | 段落级总结 | search 预览、下载前判断 |
| meta.json | meta | 结构化元数据 | 过滤、标签召回、治理、排序 |

### 3.2 方案 1：client 直接生成并上传 4 个文件

定义：client 一次性提交四个文件；server 主要负责校验、落盘、规范化和索引。

优点：

- 服务端职责相对轻，导入链路更直接。
- 若 client 已掌握会话语境，摘要可能更贴近采集场景。
- 内部受控采集端可以更快接入。

缺点：

- 对 client 能力要求高，不同 client 的摘要、标签、字段风格容易漂移。
- .abstract.md、.overview.md、meta.json 的一致性难保证。
- 服务端虽然不主生成，但仍需做大量兜底校验和规范化。

适用场景：

- 内部受控 client。
- 接入源少，且可接受一定的摘要风格差异。

### 3.3 方案 2：client 生成 message.json，server 生成另外 3 个文件

定义：client 至少上传 message.json；server 基于 raw_json 生成 .abstract.md、.overview.md、meta.json，并写入索引。

优点：

- 原始事实源集中保真，便于后续重算摘要、补标签、回放与审计。
- 摘要和结构化元数据由服务端统一生成，格式和质量更稳定。
- 更适合多 client 并行接入后的统一知识库治理。

缺点：

- 服务端复杂度更高。
- 需要明确摘要生成失败、回退生成、异步增强等机制。
- 若 client 完全拿不出 message.json，则必须依赖 lite 模式降级。

适用场景：

- 以服务端统一知识库质量为目标。
- 需要稳定的标签体系、可重算能力和统一检索表现。

### 3.4 推荐结论

推荐采用“方案 2 为主、方案 1 兼容”的双入口：

- strict 模式下，message.json 必填，server 负责生成 .abstract.md、.overview.md、meta.json；若 client 已上传这 3 个文件，只能作为候选输入，服务端仍可覆盖式规范化。
- lite 模式下，允许 client 缺少 message.json，但必须提供可生成摘要的最小信息；server 仍负责产出 .abstract.md、.overview.md、meta.json，并显式标记 has_raw_json=false、validation_mode=lite。
- 不建议把“client 直接生成 4 个文件”定义为唯一主路径，否则文档标准难以收敛。

### 3.5 message.json 是否必填、原始还是简化、strict/lite 是否适用

#### message.json 是否必填

- strict：必填。原因是它承担原始事实源职责，决定 download、重放、再摘要、责任追踪能力。
- lite：非必填但强推荐。缺失时只能提供摘要型能力，不能伪造 raw 内容。

#### message.json 是原始内容还是简化内容

- 推荐把 message.json 定义为原始会话事实源，而不是简化摘要容器。
- 可接受的简化只包括：截断超长正文、去掉无关渲染字段、附件只保留引用、对敏感片段打脱敏标记。
- 不可接受的简化包括：仅保留一段总摘要却仍命名为 message.json；删除消息顺序、角色、时间信息导致无法还原结构。

#### strict/lite 是否适用

- 适用，且建议保留。
- strict 用于保证高质量知识库和原始会话可追溯。
- lite 用于保证弱能力 client 也能接入，但必须通过 validation_mode 与 has_raw_json 显式暴露降级事实。

---

## 4. 四文件内容格式规范
### 4.0 从示例 message.json 提取的结构（实测示例：request_0b60e0ce-782c-4b6d-9ec1-e66b097e5007/message.json）

以下为对工作区示例 `message.json` 的结构化提取，作为 meta.json 字段设计与向量化分块策略的事实依据。

- 顶层字段（observed）:
  - `responderUsername`: string
  - `initialLocation`: string
  - `requests`: array — 每个 request 包含 `requestId`、`message`、`variableData`、`response` 等
  - `timestamp` / `modelId` / `responseId` / `result` 等（agent 执行与模型输出相关元信息）

- `message` 对象常见结构:
  - `message.text`: 主文本字符串（完整用户指令或描述）
  - `message.parts`: array，分片文本（带 editorRange、range、kind），用于精确定位与高亮

- `variableData`:
  - `variables`: array，每项含 `kind`（例如 file、promptFile、promptText）、`id`、`name`、`value`（可为文件引用或内联文本）
  - 常见用于携带附件、.netrc 引用、用户选择的文件片段等

- `response` 数组:
  - 含一系列条目，条目类型包括 `thinking`（链路推理/思路）、`prepareToolInvocation`、`toolInvocationSerialized`、`value`（最终文字回复）等
  - 每条 response 可能含 `id`、`kind`、`value`（文本或复杂对象）、`metadata`（如 timings、toolCallIds）

- `agent` / `extension` 元信息:
  - 包含 agent 名称、版本、extensionId、locations、modes 等，对审计与回溯有价值

规范化建议（用于内部 session schema）:

```json
{
  "schema_version":"1.0",
  "session_id":"<use requestId or generated session id>",
  "responderUsername":"...",
  "initialLocation":"...",
  "requests":[
    {
      "id":"request_...",
      "text":"原始用户文本",
      "parts":[{"kind":"text","text":"...","start":0,"end":100}],
      "variables":[{"kind":"file","name":".netrc","path":"/home/.../.netrc"}],
      "responses":[{"kind":"thinking","text":"...","timestamp":"..."}]
    }
  ],
  "agent_meta":{"modelId":"...","responseId":"...","timestamp":"..."}
}
```

以上为从示例抽取的最小可用事实模型，建议作为 `message.json` 的强化约定（便于后续生成 meta.json 与切分向量化）。

### 4.0.1 从示例导出的对 meta.json 的字段映射建议（关键）

基于上面 message.json 的结构，meta.json 应至少包含下列字段（优先级按前后）：

- `session_id` (string) — 必填，取自 requestId 或 service 生成的唯一 id
- `title` (string) — 优先来源：`generatedTitle` / 最早的 `message.text` 摘要；若无则由 server 生成简短标题
- `created_at` (datetime) — 首次请求或第一条 message 的时间戳
- `updated_at` (datetime) — 最后写入或索引时间
- `validation_mode` (string) — strict|lite
- `has_raw_json` (boolean) — 表示是否存在可下载的原始 `message.json`
- `participants` (array[string]) — 由 messages[].role 或 variableData 派生（例如 user, assistant）
- `feature_tags` / `task_ids` / `domain_tags` (array[string]) — 从 variableData、message 内容或 server 提取的结构化标签
- `source_client` (string) — client 标识（若 variableData 中有来源文件或 promptFile）
- `summary_source` (string) — server_generated | client_provided
- `storage_path_ref` (string) — 指向四文件逻辑路径的引用
- `download_ref` (string) — 原始内容下载引用（若 has_raw_json=true）
- `raw_message_count` (integer) — messages 数量
- `quality_flags` (array[string]) — 例如 `truncated`、`redacted`、`partial_parse` 等

示例（基于当前 message.json 的抽取）：

```json
{
  "session_id":"request_0b60e0ce-782c-4b6d-9ec1-e66b097e5007",
  "title":"Developed web crawler script with pagination",
  "created_at":"2026-02-03T...Z",
  "updated_at":"2026-02-03T...Z",
  "validation_mode":"strict",
  "has_raw_json":true,
  "participants":["user","assistant"],
  "feature_tags":["crawler","pronto"],
  "source_client":"vscode-extension:GitHub.copilot-chat",
  "summary_source":"server_generated",
  "storage_path_ref":"session://session/request_0b60e0ce/...",
  "download_ref":"session://download/request_0b60e0ce/...",
  "raw_message_count":12
}
```

注：上例中的 `title` 可优先由 message.json 中出现的 `generatedTitle` 或 response 中最强显著的 `value` 抽取。

### 4.0.2 并行存储策略与 OpenSearch 数据契约（文本 + 向量检索）

总体思路：保留四文件存储作为权威事实源，同时把 session 检索能力映射到 `06` 定义的 OpenSearch 主索引与 `chunks` 索引。session 分支负责准备文档与字段，底层写入继续复用 `document_manager.py`，底层检索继续复用 `search_manager.py`。

索引组织建议：

- 业务主键使用 `session_id`，并映射为稳定的 `document_key`，供 `document_manager.py` 做幂等写入、按逻辑文档删除与 chunk 聚合。
- 列表页与过滤常用字段放在轻量文档层：`title`、`abstract`、`overview_excerpt`、`validation_mode`、`has_raw_json`、`feature_tags`、`task_ids`、`participants`、`download_ref`、`storage_path_ref`。
- 长文本与语义召回内容放入 `chunks` 索引：`message`、`overview`、`abstract`、`response`、可解析的附件文本。
- 同一 `session_id` 的多个 chunk 在 Search 返回前按 session 维度聚合，避免前端直接消费 chunk 粒度结果。

哪些字段需要进入 chunk 或向量化（优先级）：

- 高优先级（必向量化）：
  - `.abstract.md`（一句话摘要，单独向量）
  - `.overview.md`（段落级概览，单独向量）
  - `messages[].content`（逐条消息的语义内容，分块后入向量库）
  - `response` 中的 `thinking` / `value` 文本（模型推理、代码片段、解决方案描述）

- 中优先级（可选向量化）：
  - 代码片段与补丁文本（按代码块语义切分），用于代码语义检索
  - 附件文本内容（若为文本型附件，如 README、日志），以单独 chunk 入向量库

- 不做向量化（结构化过滤用）：
  - `feature_tags`、`task_ids`、`participants`、`validation_mode` 等结构化字段，用于精确过滤而非语义检索

分块（chunking）建议：

- 基本原则：以语义单元为界（消息级或段落级），当单元过长时按 token 限制切分并保留重叠（overlap）以保持上下文连贯。
- 建议参数：
  - chunk_size: 200–400 tokens（约 1500–3000 字符取决于语言）
  - overlap: 20%（相邻 chunk 重叠以保留上下文）
  - short texts (如 `.abstract.md`) 保持为单 chunk
  - `.overview.md` 若 <= 600 tokens 保持为单 chunk，否则按段落或 300-token 窗口切分
  - 对代码块：按函数/类或逻辑块切分，若不可分则 200-token 窗口

chunk 条目的最小元数据应包含：

- `chunk_id` (uuid)
- `session_id`
- `document_key`
- `source` ("message" | "overview" | "abstract" | "response" | "attachment")
- `message_id` (如有)
- `role` (user/assistant/system)
- `chunk_index` (int)
- `char_offset` / `token_count`
- `storage_path_ref`（定位到原始文件与 byte/char 范围或 pageN.html）
- `created_at`
- `index_version` / `last_indexed_at`（便于重建与回滚）

写入边界建议：

- `index_document_builder` 只生成 session 轻量文档与 chunk 文档，不直接调 OpenSearch SDK。
- Import 主链路中的异步同步阶段继续调用 `document_manager.bulk_import(...)` 写入 OpenSearch。
- 若写入失败，仍沿用 `08` 中“主存储为真相源、搜索引擎异步同步”的恢复思路，不把一致性治理逻辑塞进 session repository。

检索流程参考（结构化过滤 + 文本/向量召回）：

1. 接收 query 后，先按 `feature_tags/task_ids/participants/time` 等结构化条件缩小候选范围。
2. `query_builder` 只产出 session 检索规格，如目标字段、过滤条件、是否需要向量、权重建议。
3. `SessionSearchRepository` 把该规格交给 `search_manager.py`，由后者组装 OpenSearch DSL 并执行 `_search/_msearch`。
4. `result_mapper` 把 chunk 级命中聚合回 `session_id`，合并得分、整理 `match_reason`，再按返回边界输出摘要、preview 或 ref。

存储与同步注意：session 只约定字段和聚合语义，写入与检索的一致性策略继续复用通用 Import/Search 框架，并在 metadata 中保留 `index_version` 与 `last_indexed_at` 字段以便重算。

---

### 4.1 逻辑存储目录

session 文件集的逻辑存储模型建议保持如下语义：

```text
session_files/
└── <session_id>/
    ├── message.json
    ├── .abstract.md
    ├── .overview.md
    └── meta.json
```

说明：

- 这是逻辑目录语义，不要求对外暴露真实绝对路径。
- search 结果只返回 storage_path_ref 与 download_ref，不直接暴露底层物理路径。
- 四文件逻辑固定有助于 import、search、download 使用同一语义约定。

### 4.2 message.json 规范

定位：原始会话事实源，不承担列表摘要职责。

最小结构建议：

| 字段 | 类型 | 必填性 | 说明 |
|------|------|------|------|
| schema_version | string | 推荐必填 | 便于后续演进 |
| session_id | string | 推荐必填 | 与目录主键一致 |
| messages | array | strict 必填 | 原始消息数组 |
| messages[].message_id | string | 选填但推荐 | 单条消息标识 |
| messages[].role | string | 推荐必填 | user/assistant/system 等 |
| messages[].content | string 或 array | 推荐必填 | 消息内容或分段内容 |
| messages[].created_at | string(datetime) | 选填但推荐 | 用于排序与追踪 |
| messages[].attachments | array | 选填 | 附件引用 |

示例：

```json
{
  "schema_version": "1.0",
  "session_id": "session-20260408-001",
  "messages": [
    {
      "message_id": "m1",
      "role": "user",
      "content": "请细化 session import/search 设计",
      "created_at": "2026-04-08T09:30:00Z"
    },
    {
      "message_id": "m2",
      "role": "assistant",
      "content": "建议拆分为 session repository 子目录，并把 raw 返回边界与摘要职责分离。",
      "created_at": "2026-04-08T09:31:30Z"
    }
  ]
}
```

strict/lite 处理：

- strict：必须存在。
- lite：允许不存在，但结果必须写 has_raw_json=false，且 search 不能承诺 raw download。

### 4.3 .abstract.md 规范

定位：一句话总结。

要求：

- 仅 1 段 1 句，不分标题。
- 建议不超过 120 到 180 个中文字符。
- 优先包含主题、对象、结论或动作。
- strict 与 lite 都应保证该文件存在；若 client 未提供，由 server 生成。

示例：

```markdown
本会话围绕 SESSION 类型在 import/search 流程中的四文件职责、strict/lite 校验和 search 返回边界展开，结论是由服务端统一生成摘要与元数据，并默认只返回摘要和下载引用。
```

### 4.4 .overview.md 规范

定位：段落级总结。

建议结构：

- 背景/触发原因
- 讨论主题/核心问题
- 关键结论/决策
- 后续动作/未决事项

要求：

- 推荐 1 到 4 个自然段，或按上述 4 小节组织。
- strict 下应尽量形成完整段落；lite 下允许生成简版，但仍建议落文件。
- 不追求逐轮消息复现，重点是可读的段落级总结。

示例：

```markdown
# 背景
需要把 SESSION 类型从原则说明细化为可指导 import/search 落地的设计稿。

# 讨论主题
- message.json 是否必须保留为原始事实源
- strict/lite 如何影响导入和检索返回
- search 是否允许直接下发完整 raw_json

# 关键结论
- strict 下 message.json 必填
- .abstract.md 由服务端保证生成，且必须是一句话总结
- search 默认只返回摘要、preview 或 ref，不直接返回完整 message.json

# 后续动作
需要团队进一步统一 lite 模式最小输入集与 message.json 脱敏策略。
```

### 4.5 meta.json 规范

定位：session 检索、过滤、治理的结构化元数据。

字段建议：

| 字段 | 类型 | 必填性 | 生成方建议 | 说明 |
|------|------|------|------|------|
| session_id | string | 必填 | client 或 server | 最低必填项 |
| title | string | 推荐必填 | client 或 server | search 展示主标题 |
| created_at | string(datetime) | 推荐必填 | client 或 server | 排序与追踪 |
| updated_at | string(datetime) | 推荐必填 | server | 更新时间 |
| validation_mode | string | 推荐必填 | server | strict 或 lite |
| has_raw_json | boolean | 推荐必填 | server | 是否可提供 raw download |
| task_ids | array[string] | 选填 | client/server | 结构化任务号 |
| feature_tags | array[string] | 选填 | client/server | feature 号或 feature 名 |
| domain_tags | array[string] | 选填 | client/server | 领域标签 |
| component_tags | array[string] | 选填 | client/server | 组件标签 |
| participants | array[string] | 选填 | client/server | 参与者 |
| source_client | string | 选填 | client | 来源标识 |
| summary_source | string | 选填 | server | 摘要生成来源 |
| storage_path_ref | string | 选填 | server | 存储引用 |
| download_ref | string | 选填 | server | 下载引用 |
| raw_message_count | integer | 选填 | server | 原始消息数量 |
| quality_flags | array[string] | 选填 | server | 质量或降级标记 |

规则：

- session_id 至少必须存在。
- 推荐把 title、created_at、updated_at、validation_mode、has_raw_json 视为推荐必填。
- task_ids、feature_tags、domain_tags、participants 等允许缺失，不阻塞导入，禁止伪造占位值。

示例：

```json
{
  "session_id": "session-20260408-001",
  "title": "SESSION import/search 设计讨论",
  "created_at": "2026-04-08T09:30:00Z",
  "updated_at": "2026-04-08T10:12:45Z",
  "validation_mode": "strict",
  "has_raw_json": true,
  "task_ids": ["TASK-9021"],
  "feature_tags": ["session-import", "session-search"],
  "domain_tags": ["retrieval"],
  "component_tags": ["search_service", "import_service"],
  "participants": ["user", "assistant"],
  "summary_source": "server_generated",
  "download_ref": "session://download/session-20260408-001"
}
```

### 4.6 strict/lite 汇总矩阵

| 项目 | strict | lite |
|------|------|------|
| message.json | 必填 | 非必填但强推荐 |
| .abstract.md | 必须落盘 | 必须落盘 |
| .overview.md | 必须落盘 | 建议落盘，缺失时由 server 生成简版 |
| meta.json | 必须含 session_id | 必须含 session_id |
| has_raw_json | 通常为 true | 可为 false |
| search raw 返回 | 仅 preview/ref | 仅 preview/ref，且可能 unavailable |
| download 原始内容 | 可支持 | message.json 缺失时不可支持 |

---

## 5. import 中 session 分支目录与函数职责

### 5.1 目录建议

```text
app/
├── api/
│   └── v1/
│       └── import_api.py
├── features/
│   └── import/
│       ├── application/
│       │   └── import_service.py
│       ├── domain/
│       │   └── repositories/
│       └── infrastructure/
│           └── session/
│               ├── __init__.py
│               ├── repository.py
│               ├── validator.py
│               ├── storage_mapper.py
│               ├── metadata_builder.py
│               └── index_document_builder.py
└── infrastructure/
    └── opensearch/
        └── document_manager.py
```

职责原则：

- import_api.py 只做 HTTP 参数校验与 service 调用。
- `ImportService` 只识别 SESSION 分支并统一编排，不下沉到底层 SDK。
- `features/import/infrastructure/session/` 下各文件分别承接校验、路径规划、落盘、元数据规范化、索引文档构建。
- OpenSearch 写入继续通过共享的 `document_manager.py` 完成，session 分支只准备其输入文档。

### 5.2 import 调用关系

为了减少图示，这里直接给出 import 分支的调用链和每一步的输入输出。

调用链：

1. `app/api/v1/import_api.py`
   - 接收 `files/files_config/validation_mode/tag` 等请求参数。
   - 只判断“是否是 session 请求”“四文件里哪些文件存在”。
   - 调用 `ImportService.create_import_job_with_files(...)`。
2. `app/features/import/application/import_service.py`
   - 识别当前任务是否进入 `SESSION` 分支。
   - 若不是 session，走既有通用 import 流程。
   - 若是 session，顺序调用 `validator -> storage_mapper -> repository -> metadata_builder -> index_document_builder`。
3. `validator.py`
   - 校验 `strict/lite`、四文件存在性、最小输入集、必要字段可提取性。
   - 输出 `SessionBundleValidationResult`。
4. `storage_mapper.py`
   - 规划 `session_id` 对应的四文件逻辑目录和引用路径。
   - 输出 `SessionStorageLayout`。
5. `repository.py`
   - 把收到或规范化后的文件真正落盘。
   - 输出 `StoredSessionBundle`，其中要明确 `has_raw_json`。
6. `metadata_builder.py`
   - 从 `message.json` 或候选摘要文件中抽取标题、摘要、标签、参与者、引用路径等。
   - 输出 `SessionMetadataPayload`，同时负责补全 `.abstract.md`、`.overview.md`、`meta.json`。
7. `index_document_builder.py`
   - 把 session 四文件整理成“轻量文档 + chunk 文档”两类写库输入。
   - 输出 `SessionImportDocuments`。
8. 通用异步同步阶段
   - 调用 `app/infrastructure/opensearch/document_manager.py` 的 `bulk_import(...)`。
   - 完成 OpenSearch 写入，不在 session 子目录里重复封装底层接口。

这一段的核心边界是：session 分支负责准备“应该写什么”，通用 OpenSearch 基础设施负责执行“怎么写进去”。

### 5.3 import 函数职责表

| 目录/文件 | 函数 | 输入 | 输出 | 职责边界 |
|------|------|------|------|------|
| app/api/v1/import_api.py | create_import_job | files、files_config、validation_mode、session_id、title、import_options | success、job_id、session_id、accepted_files、warnings | 只做 HTTP 入参校验与 service 调用 |
| app/features/import/application/import_service.py | create_import_job_with_files | ImportCreateRequest | ImportAcceptedResponse | 识别 SESSION 分支并编排调用，不直接写文件或调 OpenSearch SDK |
| app/features/import/infrastructure/session/validator.py | validate_session_bundle | files、files_config、validation_mode、request_fields | SessionBundleValidationResult | 校验角色、格式、必填项、strict/lite 降级 |
| app/features/import/infrastructure/session/storage_mapper.py | build_session_storage_layout | session_id、normalized_files | SessionStorageLayout | 仅负责 `sessions/session_id` 四文件路径规划 |
| app/features/import/infrastructure/session/repository.py | store_session_bundle | normalized_files、storage_layout | StoredSessionBundle | 仅负责落盘、回传 stored_files、checksum、has_raw_json |
| app/features/import/infrastructure/session/metadata_builder.py | normalize_session_metadata | stored_bundle、request_fields | SessionMetadataPayload | 统一生成或规范化 `.abstract.md`、`.overview.md`、`meta.json` |
| app/features/import/infrastructure/session/index_document_builder.py | build_session_import_documents | metadata_payload、stored_bundle | SessionImportDocuments | 生成轻量文档与 chunk 文档，禁止把完整 `message.json` 放入主索引返回字段 |
| app/infrastructure/opensearch/document_manager.py | bulk_import | index_name、documents | success_count、error_count、errors | 负责 OpenSearch bulk 写入，session 分支只提供 documents 输入 |

### 5.4 import 分支关键失败点

- strict 缺少 message.json：直接拒绝。
- lite 缺少 message.json：允许导入，但必须标记 has_raw_json=false。
- title 无法从 request/meta/overview 推断：拒绝导入。
- meta.json 非法或角色冲突：拒绝导入。
- 可检索字段全部为空：拒绝构建索引文档。
- OpenSearch bulk 导入失败：沿用通用 Import 异步失败状态，不在 session 分支内单独设计重试协议。

### 5.5 import 输出到向量数据库的内容

session import 最终要准备两类数据给向量数据库或 OpenSearch：

- 轻量文档
  - 用于列表展示、过滤、快速命中。
  - 典型字段：`session_id`、`document_key`、`title`、`abstract`、`overview_excerpt`、`validation_mode`、`has_raw_json`、`feature_tags`、`task_ids`、`participants`、`download_ref`、`storage_path_ref`。
- chunk 文档
  - 用于文本召回、向量召回、snippet 提取。
  - 典型字段：`chunk_id`、`session_id`、`document_key`、`source`、`message_id`、`role`、`content`、`content_vector`、`chunk_index`、`token_count`、`storage_path_ref`。

对应到文件/函数：

| 文件 | 函数 | 产物 |
|------|------|------|
| `metadata_builder.py` | `normalize_session_metadata` | `.abstract.md`、`.overview.md`、`meta.json` |
| `index_document_builder.py` | `build_session_import_documents` | `light_documents`、`chunk_documents` |
| `document_manager.py` | `bulk_import` | 把上述 documents 写入目标索引 |

这样可以把“文件语义整理”和“数据库接口调用”拆开，便于后续替换底层引擎。

---

## 6. search 中 session 分支召回与返回边界

### 6.1 目录建议

```text
app/
├── api/
│   └── v1/
│       └── search_api.py
├── features/
│   └── search/
│       ├── search_service.py
│       └── repositories/
│           └── session/
│               ├── __init__.py
│               ├── repository.py
│               ├── query_builder.py
│               ├── result_mapper.py
│               └── filters.py
```

职责原则：

- search_service.py 只做 SESSION 分支识别、仓储路由、聚合排序。
- query_builder.py 只负责 session 查询规格、字段权重与过滤归一化，不直接手写 OpenSearch DSL。
- repository.py 负责把 session 查询规格交给 `search_manager.py` 执行。
- result_mapper.py 只负责返回边界控制，不决定下载协议。

### 6.2 search 调用关系

search 分支同样用文字调用链描述，不再展开图。

调用链：

1. `app/api/v1/search_api.py`
   - 接收统一 `SearchRequest`。
   - 不理解 session 内部结构，只把请求交给 `SearchService.execute_search(...)`。
2. `app/features/search/search_service.py`
   - 根据 `tag/index_name/query` 判断是否命中 `SESSION`。
   - 若未命中，走现有非 session 仓储。
   - 若命中，交给 `SearchRepositoryFactory` 创建 `SessionSearchRepository`。
3. `filters.py`
   - 归一化 session 专属过滤条件，如 `feature/task/participant/time`。
4. `query_builder.py`
   - 生成 `SessionQuerySpec`。
   - 明确要查哪些字段、是否启用向量、`top_k` 如何放大、过滤条件如何组合。
5. `repository.py`
   - 把 `SessionQuerySpec` 转交 `search_manager.py`。
   - 不自己写底层 OpenSearch JSON。
6. `search_manager.py`
   - 调用底层数据库查询接口，返回原始 hits。
7. `result_mapper.py`
   - 把 chunk 级命中聚合回 session 级结果。
   - 整理 `match_reason`、`overview_excerpt`、`raw_content_preview/ref`、`warnings`。
8. `SearchService`
   - 把 session 结果与其它桶统一合并排序，最后返回给 client。

这一段的核心边界是：session 分支负责“查什么、怎么整形”，通用 Search 基础设施负责“怎么发起数据库查询”。

### 6.3 查询字段、查询规格与召回规则

SESSION 检索不应以完整 `message.json` 原文作为默认主召回字段，而应优先命中下列轻量字段：

| 字段 | 用途 | 建议匹配方式 |
|------|------|------|
| title | 标题召回主字段 | match、match_phrase_prefix、fuzzy |
| abstract | 列表摘要召回 | match |
| overview | 段落级概览召回 | match、bm25 |
| feature_tags | feature 号与 feature 标签 | keyword 精确匹配 + prefix/模糊兜底 |
| task_ids | 任务号 | keyword 精确匹配 + prefix |
| domain_tags | 领域标签 | terms 过滤 + 模糊 query 兜底 |
| component_tags | 组件标签 | terms 过滤 + 模糊 query 兜底 |
| participants | 会话参与者 | terms 过滤 |

结论：

- 标题、feature 号、标签都属于 session 检索的一级召回字段。
- feature 号应优先进入 meta.json 的 feature_tags 或 task_ids，而不是退化为正文字符串搜索。
- query_text 可对 title、abstract、overview、标签名称做模糊命中；filters 优先做结构化精确筛选。
- `query_builder.py` 只产出 `SessionQuerySpec`，例如目标字段、过滤条件、是否需要向量检索、字段权重与 top_k 放大策略。
- OpenSearch 原始 DSL 的组装与执行继续放在 `app/infrastructure/opensearch/search_manager.py`，与 `06` 的职责边界保持一致。

### 6.4 search 函数职责表

| 目录/文件 | 函数 | 输入 | 输出 | 职责边界 |
|------|------|------|------|------|
| app/api/v1/search_api.py | search_documents | SearchRequest | SearchResponse | 只处理 HTTP 协议与响应封装 |
| app/features/search/search_service.py | execute_search | SearchRequest | SearchExecutionResult | 根据 tag、index_name 或 query 识别 SESSION 分支并聚合结果 |
| app/features/search/repositories/session/filters.py | normalize_session_filters | session_filters | SessionSearchFilters | 只处理 feature/task/participant/time 等 session 专属过滤条件 |
| app/features/search/repositories/session/query_builder.py | build_session_query_spec | query_text、search_type、filters、options | SessionQuerySpec | 只产出字段选择、过滤条件、是否启用向量与权重，不直接拼底层 DSL |
| app/features/search/repositories/session/repository.py | search_sessions | query_spec、top_k | list[RawSessionHit] | 调用 `search_manager.py` 执行检索，不做最终响应映射 |
| app/infrastructure/opensearch/search_manager.py | search/search_many | OpenSearchQuerySpec | ScoredSearchPage | 负责 OpenSearch DSL、`_search/_msearch` 和结果格式化 |
| app/features/search/repositories/session/result_mapper.py | map_session_hits | raw_hits、include_raw_content、raw_content_mode | list[SessionSearchItem] | 聚合同一 `session_id` 的多 chunk 命中，并负责 warning、preview/ref 生成 |

### 6.5 search 返回边界

默认返回字段建议如下：

| 字段 | 默认返回 | 说明 |
|------|------|------|
| session_id | 是 | 唯一主键 |
| title | 是 | 展示标题 |
| abstract | 是 | 列表摘要 |
| overview_excerpt | 是 | 段落级节选 |
| feature_tags/domain_tags/component_tags | 是 | 标签与过滤回显 |
| task_ids | 选填 | 结构化任务号 |
| participants | 选填 | 参与者 |
| has_raw_json | 是 | 是否可返回 raw preview/ref |
| validation_mode | 是 | strict 或 lite |
| storage_path_ref | 推荐 | 存储引用 |
| download_ref | 推荐 | 原始内容下载引用 |
| match_reason | 推荐 | 命中原因 |
| warnings | 选填 | raw_content_unavailable 等提示 |

明确边界：

- search 默认不直接返回完整 message.json。
- include_raw_content=true 时，也只允许返回 raw_content_preview 或 raw_content_ref，不返回完整 raw_json。
- has_raw_json=false 时，应返回 warning 或 unavailable 语义，而不是返回空壳 message.json。
- 完整原始内容应通过 download 二阶段获取。

### 6.6 search 返回前的数据整合

从数据库拿回结果后，session 分支还需要额外做一次整合，避免把底层命中直接暴露给 client。

整合规则建议如下：

1. 先按 `session_id` 合并多条 chunk 命中。
2. 对同一 session 的多条命中，保留最高分并汇总 `match_reason`。
3. 从 `title/abstract/overview` 中选择最适合列表展示的摘要字段。
4. 若命中的是 message chunk，则只回传受限长度的 preview，不回传完整 raw。
5. 若 `has_raw_json=false`，补充 `warnings=["raw_content_unavailable"]`。
6. 最终输出统一的 `SessionSearchItem`，再交给上层 SearchService 合并。

对应到文件/函数：

| 文件 | 函数 | 职责 |
|------|------|------|
| `repository.py` | `search_sessions` | 获取原始 hits |
| `result_mapper.py` | `group_hits_by_session` | 按 `session_id` 聚合 |
| `result_mapper.py` | `build_match_reason` | 整理命中原因 |
| `result_mapper.py` | `build_preview_or_ref` | 生成 preview/ref |
| `result_mapper.py` | `map_session_hits` | 输出最终 `SessionSearchItem` |

示例：

```json
{
  "tag": "SESSION",
  "results": [
    {
      "session_id": "session-20260408-001",
      "title": "SESSION import/search 设计讨论",
      "abstract": "本会话围绕 SESSION 四文件职责、strict/lite 校验和 search 返回边界展开，结论是由服务端统一生成摘要与元数据，并默认只返回摘要和下载引用。",
      "overview_excerpt": "需要把 SESSION 类型从原则说明细化为可指导实现的设计稿，重点收口到 import 与 search 分支。",
      "feature_tags": ["session-import", "session-search"],
      "task_ids": ["TASK-9021"],
      "has_raw_json": true,
      "validation_mode": "strict",
      "download_ref": "session://download/session-20260408-001",
      "match_reason": ["title_fuzzy", "feature_tags_exact"],
      "raw_content_ref": "session://raw-preview/session-20260408-001"
    }
  ]
}
```

---

## 7. 小结

本次 session 细化结论如下：

- import/search 只补 `SESSION` 分支，不改通用主流程；Import 复用 `08` 的 `ImportService` 主链路，Search 复用 `07` 的 `SearchService -> RepositoryFactory` 主链路。
- 四文件中 `message.json` 是原始事实源，`.abstract.md` 是一句话总结，`.overview.md` 是段落级总结，`meta.json` 至少要求 `session_id` 必填。
- 推荐采用“client 提供 `message.json`、server 统一生成其余三文件”的主路径，并保留 client 全量上传四文件的兼容入口。
- strict/lite 继续保留，差异通过 `validation_mode` 与 `has_raw_json` 显式对外暴露。
- OpenSearch 侧由 session 分支提供轻量文档与 chunk 文档，底层检索与 bulk 写入继续复用 `search_manager.py` 和 `document_manager.py`。
- search 默认只返回摘要、引用或 preview/ref，不直接返回完整 `message.json`。

---

## 8. 待讨论项

以下内容作为方案初稿保留，尚未在本文中固化为最终规范：

- client 端到底只负责“传文件并标记 session”，还是允许承担部分字段预提取职责，需要团队统一；当前本文按“API 只关心文件存在和 session 标记，内部字段提取由服务端负责”为主路径设计。
- lite 模式最小输入集到底是“title + 任意补充文本”还是“title + meta.json”作为硬门槛，需要团队统一。
- .overview.md 是否强制固定四段模板，还是允许可扩展模板，需要团队统一。
- message.json 的脱敏规则、最大体积、截断策略，需要形成通用规范。
- task_ids、feature_tags、domain_tags、participants 缺失后的回填机制与 SLA 尚未定义。
- raw_content_preview 的默认长度、权限控制和 raw_content_ref 的使用方式仍需结合前端与安全方案继续讨论。
- feature 号究竟统一建模为 feature_tags 还是 task_ids 的一个子类，需要团队统一，否则查询字段会漂移。
