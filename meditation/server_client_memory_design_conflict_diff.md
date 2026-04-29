# Server/Client 设计冲突对照（Memory 相关）

## 对照基线

- Server 文档：`docs/designs/server_part/09_Import_Search_procedure_memory_design.md`
- Client 文档：`docs/designs/client_part/01-bible-vscode-extension-design.md`
- 本文只聚焦两类冲突：
  - 设计层/关键约束冲突
  - interface / message structure 冲突

## 已确认冲突（Confirmed Conflicts）

### 1) 统一检索入口表述过强（Boundary Ambiguity）

- 对应修订建议：[`P0-1 统一检索入口语义（外部契约固定）`](../backlog/server_client_memory_design_revision_suggestions.md#p0-1)

- Client 侧约束：
  - 明确“综合知识检索可统一使用顶层命令 `bible search --query <Q>`”，并通过 `--enable-hit` 附带 `skill,memory` 命中。
  - 同时存在对 `memory/skill` 进行独立 search 与其他管理操作的场景，不能被解释为“仅允许统一入口”。
  - Extension 强约束为“只经 CLI 调用，不直连 server”。
- Server 侧约束：
  - 明确 MEMORY “使用独立端点 `POST /api/v1/memory/search`，无需兼容通用 Search API”。
- 冲突点：
  - 若将 Client 的“统一入口”误读为“唯一入口”，会与 Server 的 memory 独立能力形成表面冲突。
  - 实质问题不是能力互斥，而是“综合检索入口”和“专项检索/管理入口”的边界未被显式写清。
- 风险：
  - 评审与实现者可能错误收敛为“禁用 memory/skill 独立命令”；
  - `bible_knowledge_search` 的命中行为与 server 实际实现漂移；
  - agent 侧 hit 类型/返回结构不稳定，影响工具提示词与测试。
- 建议对齐：
  - 将“统一入口”限定为综合检索主入口（推荐路径），而非唯一入口；
  - 保留 memory/skill 独立 search 与管理命令，作为专项能力入口；
  - Server 独立 API 可保留为内部实现，并在文档中明确“CLI 对外提供统一语义，同时允许专项命令直达对应能力”。

### 2) 会话保存消息结构与 Memory Import 两文件契约未闭合（Unresolved Contract Gap）

- 对应修订建议：[`P0-2 session save -> memory ingest 契约（two-file 内聚到 server）`](../backlog/server_client_memory_design_revision_suggestions.md#p0-2)

- Client 侧输入结构（`bible_session_save`）：
  - 主要字段为 `title` + `messages[]`（示例消息仅 `role/content`）。
- Server 侧 Import 输入结构：
  - 强制 `message.json + meta.json` 两文件；
  - `message.json.memory_id` 必填且需与 `meta.json.memory_id` 一致；
  - `meta.json.title` 必填，且索引构建阶段对摘要字段有额外约束。
- 冲突点：
  - Client 未定义 `session save -> memory import` 的结构映射规则：
    - `memory_id` 生成策略；
    - `meta.json` 组装规则；
    - `abstract/overview` 缺失时的行为边界。
- 风险：
  - CLI 实现会出现“隐式补字段”，但设计文档缺乏统一规则；
  - 可能出现同一输入在不同版本 CLI 下导入结果不一致。
- 建议对齐：
  - 在 Client 或 CLI 契约文档新增显式映射规范：`session save` 如何稳定转为 `message.json/meta.json`；
  - 将 `memory_id` 生成、`abstract` fallback、缺失字段的 reject/warn 策略写成可测试约束。

### 3) 响应 envelope 约束不一致（Message Structure Conflict）

- 对应修订建议：[`P0-3 统一响应 envelope（API 与 CLI 明确分层）`](../backlog/server_client_memory_design_revision_suggestions.md#p0-3)

- Client 侧约束：
  - 强调 CLI 统一输出：
    - 成功：`{"ok": true, "data": {...}}`
    - 失败：`{"ok": false, "error": {"code": "...", "message": "..."}}`
- Server 侧示例/Schema：
  - Memory Search：`{"success": true, "total": ..., "memories": [...], "warnings": [...]}`；
  - Memory Import：`{"success": true, "task_id": ..., ...}`。
- 冲突点：
  - `ok/data/error` 与 `success + 业务字段平铺` 是两套不同 envelope。
  - 若 CLI 不显式声明“API -> CLI envelope 转换”，扩展侧会面临解析分叉。
- 风险：
  - Extension 工具实现出现“按命令特判 JSON 结构”；
  - 错误处理与 telemetry 埋点难统一。
- 建议对齐：
  - 固化规则：Server API 可保持 `success` 风格，但 CLI 对外一律转换为 `ok/data/error`；
  - 在 client 设计文档中补充 memory 相关输出样例，避免实现猜测；
  - 采用 Schema First（JSON Schema/OpenAPI）管理 request/response 契约，并在 CI 增加 contract tests 阻断结构漂移。

### 4) 错误码体系覆盖范围冲突（Coupling Risk / Drift）

- 对应修订建议：[`P1-1 错误码映射补全（Memory 专有错误）`](../backlog/server_client_memory_design_revision_suggestions.md#p1-1)

- Client 侧错误处理策略：
  - 重点列出通用错误码：`NOT_FOUND`、`INVALID_SKILL_PACKAGE`、`SEV_NOT_IMPLEMENTED`、`UNAVAILABLE`、`TIMEOUT` 等。
- Server 侧 memory 错误码：
  - Import 明确为 `MEMORY_MISSING_MESSAGE`、`MEMORY_ID_MISMATCH`、`MEMORY_FILE_TOO_LARGE`、`MEMORY_MISSING_SUMMARY_TEXT` 等。
- 冲突点：
  - Client 错误码列表未覆盖 MEMORY 专有错误码及 422 场景；
  - 若不定义映射策略，Extension 无法稳定给出期望提示语。
- 风险：
  - agent 提示不准确（例如把输入校验错误误判为服务不可用）；
  - 业务错误被降格为“未知错误”。
- 建议对齐：
  - 定义 memory 错误码到 CLI 通用错误模型的映射表（透传/归一化两层都要写清）；
  - 在 Client 文档补充 memory 相关错误处理分支。

## 待澄清但高概率漂移点（Needs Clarification）

### A) `bible search --enable-hit` 的 memory 命中返回结构

- 对应修订建议：[`P1-2 统一搜索中的 memory 命中字段子集`](../backlog/server_client_memory_design_revision_suggestions.md#p1-2)

- Client 文档示例使用 `knowledge`、`skill`，并描述默认附带 `memory`，但未给出 `memory` 命中的字段契约。
- Server 文档定义了较完整 `MemorySearchItem` 字段集（如 `match_scope`、`matched_message_preview`、`storage_path_ref`）。
- 需要明确：
  - 统一检索输出里 `memory` 命中的字段最小子集；
  - 是否保留 server 原字段名还是做 CLI 层重命名。
- 本轮结论（建议固定）：
  - `memory` 命中最小稳定字段集为：`memory_id`、`title`、`abstract`、`score`、`match_scope`；
  - `matched_message_preview` 为条件字段（仅在 message 命中时返回）；
  - `storage_path_ref` 为可选定位字段（有存储引用时返回）；
  - 其余字段归类为扩展字段，不作为调用方长期稳定依赖。

### B) 二阶段 raw 下载接口在 Client 侧未形成可执行约束

- 对应修订建议：[`P2-1 二阶段 raw 下载策略（LLM 决策 + 平台约束）`](../backlog/server_client_memory_design_revision_suggestions.md#p2-1)

- Server 明确建议 Search 返回 preview，完整 raw 通过 `GET /api/v1/download/memory/{memory_id}` 二阶段获取。
- Client 当前工具/命令设计中未明确 memory raw 下载工具或触发路径。
- 需要明确：
  - memory raw 下载是否暴露为独立 CLI/Tool；
  - 权限、确认、体积限制如何在 extension 侧体现。
- 本轮结论（建议固定）：
  - Server 的二阶段下载建议合理：`search --enable-hit` 返回 preview，raw 通过独立下载接口获取；
  - 在 `search --enable-hit` 场景下，是否触发 raw 下载可由 LLM 决策；
  - 下载约束必须由 CLI/Extension 策略层强制执行（权限校验、超阈值确认、体积限制/截断、超时与重试）；
  - 结论口径：LLM 负责“是否触发”，平台负责“是否允许与如何受控执行”。

## 建议优先级（Resolution Checklist）

- P0：统一“外部契约入口”——明确 `bible search` 是综合检索主入口；同时保留 memory/skill 专项检索与操作入口，避免“唯一入口”误读。
- P0：补齐 `session save -> memory two-file` 映射规范（`memory_id` 生成、meta 组装、缺失字段处理）。
- P0：固定 API 与 CLI 的 envelope 转换规则，保证 extension 只消费 `ok/data/error`。
- P1：补全 memory 错误码映射与文档化处理分支。
- P1：定义 unified search 中 `memory hit` 的字段子集与命名。
- P2：决定是否对外提供 memory raw 下载工具，并补充交互与安全边界。

## 建议的单一真相（Source of Truth）落位

- 对外调用契约（给 Extension/Agent）：以 Client 文档 + CLI contract 为准。
- 服务内部实现契约（Server API、索引、落盘）：以 Server 文档为准。
- 连接两者的桥接契约（最关键）：应补一份 CLI Memory Contract（或在 client `02 spec` 中新增 dedicated 小节），避免再出现语义双轨。
