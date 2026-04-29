# Server/Client Memory 设计文档修订建议（最小改动版）

## 目标

基于 `meditation/server_client_memory_design_conflict_diff.md`，将当前 Server/Client 设计文档中的冲突点收敛为可执行、可验收的文档修订任务。  
本建议强调“最小改动”：优先补桥接契约与边界声明，不重写整篇设计。

## 影响文档

- `docs/designs/client_part/01-bible-vscode-extension-design.md`
- `docs/designs/client_part/02-bible-vscode-extension-spec.md`（建议同步补充可执行约束）
- `docs/designs/server_part/09_Import_Search_procedure_memory_design.md`

---

<a id="p0-1"></a>
## P0-1 统一检索入口语义（外部契约固定）

### 要改哪里

- Client 设计文档：`四、4.4 被动搜索设计`
- Server 设计文档：`8. MEMORY Search API 说明`

### 建议改法

1. 在 Client 文档中补一段“综合检索主入口 + 专项入口并存”的约束：
   - 对 Extension/Agent：综合检索主入口为 `bible search --query ... [--enable-hit]`
   - `memory` 命中属于 `bible search` 的可选附带结果，不要求调用方直连 memory 专用 API
   - 同时保留 `memory/skill` 独立 search 与管理操作命令，避免被误读为“只能统一入口”
2. 在 Server 文档对应节增加“实现与契约分层”声明：
   - `POST /api/v1/memory/search` 是 server 内部能力边界
   - CLI 可以聚合此端点并对外输出统一搜索契约

### 可直接落文（建议文本）

```md
对外契约说明：对于 VSCode Extension/Agent 调用方，`bible search` 是综合检索主入口。  
`memory/skill` 的独立 search 与管理命令可继续作为专项能力入口。  
Server 的 `POST /api/v1/memory/search` 作为 memory 域内部检索实现，可由 CLI 聚合后对外暴露统一结果模型。
```

### 验收标准

- Client 与 Server 文档均不再表达“调用方必须直接使用 memory 独立端点”。
- 两份文档均明确“综合检索主入口（CLI）+ 专项入口并存”与“内部实现（Server API）”的边界。

---

<a id="p0-2"></a>
## P0-2 补齐 `session save -> memory ingest` 契约（two-file 内聚到 server）

### 要改哪里

- Client 设计文档：`七、7.3 场景 B2：用户保存对话`
- Client spec 文档：新增“SessionSave 原始上传契约”小节
- Server 文档：`3. 两文件格式规范`（增加“由 raw ingest 规范化生成”的约束说明）

### 建议改法

为 `bible_session_save` 定义“原始上传 + 服务端规范化”规则，至少覆盖：

- Client 上传责任（raw ingest）：
  - 上传 chat memory 原始数据（`title`、`messages[]`、可选 `language/source_client` 等）
  - 可选提供幂等键（如 `client_request_id`），不要求构造 `message.json/meta.json`
- Server 接收责任（normalize + persist）：
  - 接收 raw ingest 后生成 `memory_id`
  - 在服务端统一组装 `message.json` 与 `meta.json`
  - 两文件一致性校验仅由 server 执行，不外泄到 client 契约
- 缺失字段行为（server 统一裁决）：
  - `abstract` 缺失 -> fallback（来自 `overview` 或 messages 摘要）
  - `abstract` 与 `overview` 同时缺失 -> 明确 reject，并返回稳定错误码

### 可直接落文（建议文本）

```md
`bible_session_save` 对外契约为“上传 chat memory 原始数据”，不要求调用方构造 memory 两文件。  
Server 接收 raw ingest 后，负责生成 `memory_id` 并规范化落为 `message.json/meta.json`。  
若 `abstract` 缺失，允许由 `overview` 或消息内容生成 fallback；若 `abstract` 与 `overview` 同时缺失，返回可识别错误码并拒绝导入。
```

### 验收标准

- Client 不再承担 two-file 组装细节，不同实现者无需“猜”内部文件格式。
- Server 对同一 raw 输入生成稳定 two-file 结果（可测试、可回放）。
- 契约可直接转化为端到端样例（至少 3 个：正常、fallback、reject）。

---

<a id="p0-3"></a>
## P0-3 统一响应 envelope（API 与 CLI 明确分层）

### 要改哪里

- Client 设计文档：`三、3.2 CLI 输出格式用 JSON`
- Client spec 文档：每个 memory 相关命令输出示例
- Server 文档：`附录 A/B` 前增加“这是 API 原生结构”提示

### 建议改法

- 固定规则：Server API 保持 `success + 平铺字段` 不变；
- CLI 对外统一转换为：
  - 成功：`{"ok": true, "data": {...}}`
  - 失败：`{"ok": false, "error": {...}}`
- 补充一组“memory search/import”转换示例，避免 extension 端按命令分叉解析。
- 将 request/response 约束升级为“可执行契约”：
  - 采用 Schema First（JSON Schema 或 OpenAPI）作为唯一来源
  - Server 与 Client 均由 Schema 生成/校验模型，减少跨语言手写漂移
- 增加最小契约目录（建议）：
  - `schemas/server/memory-search.response.schema.json`
  - `schemas/server/memory-import.response.schema.json`
  - `schemas/cli/memory-search.response.schema.json`
  - `schemas/cli/memory-import.response.schema.json`
  - `schemas/common/error.schema.json`
- 固化 CLI 转换层职责：
  - 明确 `server envelope -> cli envelope` 的字段映射表
  - 明确错误码透传/归一化策略（与 P1-1 对齐）
- 在 CI 增加契约校验：
  - schema lint + breaking change 检查（删除字段/改类型即失败）
  - response contract tests（golden JSON 样例）
  - consumer 合约测试（extension 侧样例必须通过）

### 可直接落文（建议文本）

```md
Envelope 约束：Server API 响应结构可按服务域独立定义；CLI 对外输出统一封装为 `ok/data/error`。  
Extension 与 Agent 工具仅消费 CLI 统一封装，不直接依赖 Server 原生字段平铺结构。

格式约束采用 Schema First：请求/响应格式以 Schema 为单一真相来源，Server 与 Client 通过同一契约生成/校验类型与结构。  
CLI 层必须维护 `Server API -> CLI` 的显式转换规则，并在 CI 中执行契约测试，防止跨语言实现漂移。
```

### 验收标准

- Client 文档中不再出现“部分命令例外 envelope”。
- memory 相关工具示例均以 `ok/data/error` 表示。
- `schemas/server/*` 与 `schemas/cli/*` 均存在并通过校验。
- CI 能阻断非兼容结构变更（字段删除、类型变更、envelope 破坏）。

---

<a id="p1-1"></a>
## P1-1 错误码映射补全（Memory 专有错误）

### 要改哪里

- Client 设计文档：`八、错误处理策略`
- Client spec 文档：错误码表
- Server 文档：`11.1 Import 失败点`（补“建议对外映射名”列，可选）

### 建议改法

增加 mapping 表（示例）：

- `MEMORY_MISSING_MESSAGE` -> 透传（业务可读）
- `MEMORY_ID_MISMATCH` -> 透传
- `MEMORY_MISSING_SUMMARY_TEXT` -> 透传或映射为 `INVALID_ARGUMENT`
- `MEMORY_FILE_TOO_LARGE` -> 透传并附带 size limit

并在 Extension 侧声明对应用户提示策略，避免统一兜底成 `INTERNAL`。

### 验收标准

- Client 文档能覆盖 memory 典型失败路径；
- 新增错误码不需要再改 extension 主流程，只需补 mapping 配置或表。

---

<a id="p1-2"></a>
## P1-2 统一搜索中的 memory 命中字段子集

### 要改哪里

- Client spec 文档：`bible search --enable-hit` 输出结构
- Server 文档：`7.8 Search 返回字段边界`（补“用于 unified hit 的最小字段集”）

### 建议改法

先固定“最小稳定字段分层”：

- 必选字段：`memory_id`、`title`、`abstract`、`score`、`match_scope`
- 条件字段：`matched_message_preview`（仅在 message 命中时返回）
- 可选定位字段：`storage_path_ref`（有存储引用时返回）

其余字段标记为“扩展字段（可选）”，不作为调用方长期稳定依赖。

### 验收标准

- 调用方可以只依赖最小字段集完成展示；
- 扩展字段增减不破坏主链路兼容性。

---

<a id="p2-1"></a>
## P2-1 二阶段 raw 下载策略（LLM 决策 + 平台约束）

### 要改哪里

- Client 设计文档：`四、4.4 被动搜索设计`（补充 preview/raw 二阶段语义）
- Client spec 文档：新增 `memory raw download` 命令或工具契约小节
- Server 文档：`8. MEMORY Search API 说明` 与下载接口章节（补“preview-only + raw download”边界）

### 建议改法

- 固定二阶段模型：
  - `bible search --enable-hit` 仅返回 preview，不内联完整 raw
  - 完整内容通过独立下载接口获取（如 `GET /api/v1/download/memory/{memory_id}`）
- 固定职责分层：
  - LLM 负责“是否触发 raw 下载”的决策
  - CLI/Extension 策略层负责“是否允许、如何受控执行”
- 固定策略约束：
  - 权限校验（workspace/user policy）
  - 超阈值确认（体积、敏感度、批量下载）
  - 体积限制与截断策略
  - 超时/重试与审计日志

### 可直接落文（建议文本）

```md
Memory 检索采用二阶段模型：统一搜索仅返回 preview，完整 raw 需通过独立下载能力获取。  
在 `search --enable-hit` 场景下，是否触发 raw 下载可由 LLM 决策；但下载行为必须受 CLI/Extension 策略层强制约束（权限、确认、体积限制、超时重试、审计）。
```

### 验收标准

- Client 文档明确 preview 与 raw 的边界，不再隐式内联 raw。
- 存在可执行的 raw 下载命令/工具契约与错误处理分支。
- 超限、无权限、需确认等场景在 extension 侧可稳定复现与提示。

---

## 建议执行顺序（可直接建任务）

1. P0：统一入口语义（Client + Server 同步改）
2. P0：session save 映射契约（Client spec 主改，Server 补说明）
3. P0：envelope 分层与示例统一
4. P1：错误码映射表
5. P1：memory hit 最小字段集
6. P2：二阶段 raw 下载策略与工具约束

---

## Definition of Done（文档层）

- 三份文档（client design / client spec / server design）对同一能力不再出现双轨语义；
- 每个关键契约点都至少包含：
  - 约束描述
  - 示例（请求/响应或映射）
  - 失败行为
- 评审者可据此直接编写接口测试与 CLI 合约测试。
