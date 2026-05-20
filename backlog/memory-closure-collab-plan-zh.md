---
name: VSCode 插件 Memory 闭环 2 人协作工作计划
overview: 围绕"先打通 MEMORY 端到端闭环（save / search / download）"目标，规划 bible VSCode 插件（TypeScript）2 人小组的角色分工、并行节奏与对外依赖（bible CLI、server v4）的对接方式。强调以"对外接口契约 + 内部模块边界"为唯一硬约束，AI 协助下任务粒度尽量粗，靠集成节点同步而不是细任务派工。
---

# VSCode 插件 Memory 闭环 2 人协作工作计划

## 1. 适用范围与基本假设

- **目标交付**：VSCode 插件 MEMORY 域端到端闭环（对应 `03-vscode-extension-framework-v4.md` F0 ~ F3 里程碑）。
- **范围**：**仅 VSCode 插件**（TypeScript）。
- **不在范围**：
  - `bible_cli_go` 的开发由 CLI 线独立推进（详见 `bible-cli-go-full-rewrite-plan-zh.md`）；本组**只消费 CLI**，不实现 CLI。
  - `bible-server` v4 落地由 server 线独立推进；本组通过 CLI 间接对接，不直连 server。
- **团队规模**：2 人（Role 1 = Platform / Role 2 = Memory Domain）；同处一个仓库。
- **协作哲学**：
  1. **对外契约 > 内部模块边界 > 实现代码**。先把"对 CLI / server 的接口期望"和"组内两人之间的模块边界"签字冻结，再各自动手。
  2. **靠 mock 解耦对外依赖**。CLI / server 的实现进度不在本组掌控；用 mock CLI 把组内开发节奏与外部解耦，不允许 "等 CLI 实现我再开始"。
  3. **粗任务粒度**。AI 协助下不切到 "实现某个函数" 级别；每人按"模块边界"领工作，自己拆分。
  4. **集成节点上同步**。每个 Fx 验收节点是双向集成点，节点之间不强行同步细节。
- **不适用**：3 人以上、Cursor / 其它 IDE 兼容（F4 之后再看）。

## 1.1 关联文档与优先级

冲突时优先级：

1. `docs/manual/cli-contract-v1.md`（冻结契约，本组对 CLI 的输出协议依赖）
2. `docs/designs/server_part/v4/02_API接口文档.md`（间接依赖，决定 CLI 行为）
3. `docs/designs/client_part/03-vscode-extension-framework-v4.md`（v4 框架设计）
4. `docs/designs/client_part/04-vscode-extension-memory-spec-v4.md`（待写；W0 必产，是本组的"接口圣经"）
5. 本文（When / Who / 验收口径）
6. `docs/designs/client_part/01-bible-vscode-extension-design.md`（Why）

外部线计划文档（本组只读，不维护）：

- `backlog/bible-cli-go-full-rewrite-plan-zh.md` — CLI 线进度，决定本组哪些命令"已可用真 CLI、哪些还得用 mock"。

> 本文中的"周节奏"与"角色分工"用于推动协作，不覆盖以上契约文档；任何契约改动必须先改文档，再改代码。

---

## 2. 角色与责任划分

> 两人都是 TypeScript 开发；按"框架平台 vs 业务域"切，对应 03 文档的分层架构。

### 2.1 Role 1 — Platform Engineer

**主战场**：`src/core/*` + `src/domains/control/` + `src/manifest/` + 跨域基础设施。

**核心交付**：

- `core/cli`：`CliRunner` / `BibleCliError` / `cli-detector`
- `core/task`：`TaskTracker` / `task-store`（完整异步任务模型）
- `core/registry`：`tool-registry` / `command-registry` / `capability-probe`
- `core/lm`：`model-selector`（偏好 + fallback） / `budget`（字符预算与截断）
- `core/chat`：`chat-export`（双策略 fallback）
- `core/ui`：`notifications` / `quick-pick`（0/1/N 选择 helper） / `output-channel`
- `core/config`：`extension-config`（带 onDidChange）
- `core/tool`：`BibleTool` / `AsyncBibleTool` 抽象基类
- `domains/control`：`bible_health` / `bible_task_status` Tool + `Bible: Run Self-Check` Command
- `extension.ts` 装配 + `scripts/gen-contributes.ts`
- **Mock CLI 维护者**（详见 §5）

**兼顾**：

- F4 起的 `domains/skill/` 骨架（最小占位，验证扩展性）
- F5 起的状态栏 + 错误向导
- E2E 框架（mock-only / real-cli 两套）

**不负责**：memory 域内业务实现、LM prompt 调优、Copilot Chat 数据结构解析。

### 2.2 Role 2 — Memory Domain Engineer

**主战场**：`src/domains/memory/` 全部。

**核心交付**：

- `memory-service`（对 CLI 的薄封装）
- `memory-types`（`MemoryHit` / `MemorySearchResult` / `MemoryMeta` / `ChatSource`）
- `memory-builder`（LM 提取 + 规则 fallback；产出 `meta.json`）
- `memory-format`（search 结果 → LM 注入文本）
- `tools/`：`memory-search.tool.ts` / `memory-import.tool.ts` / `memory-download.tool.ts`
- `commands/`：`search-memory` / `save-chat` / `download-memory`
- `participant/memory-participant.ts`：`@bible-memory /save /search /load /help`
- `manifest/tools.manifest.ts` 中 memory 域的 schema
- LM prompt 工程 + 规则 fallback 逻辑

**兼顾**：

- 起草 `04-memory-spec-v4.md` 中 memory 业务部分（meta.json schema、Tool 入参 JSON Schema、LM Tool modelDescription 措辞）
- Memory 域单测（mock CliRunner + mock LM）

**不负责**：core 基础设施、`TaskTracker` 实现、CLI 调用细节封装。

### 2.3 责任交叠区（避免扯皮）

| 议题 | 谁主导 | 谁评审 |
|---|---|---|
| `04-memory-spec-v4.md` 起草 | Role 1 主导 CLI 命令期望章节、错误码归一表；Role 2 主导 Tool/Command/Participant 契约、`meta.json` schema | 互评 |
| Mock CLI 行为契约（§5） | Role 1 主导 | Role 2 评审（消费者视角） |
| `BibleTool` / `AsyncBibleTool` 基类设计 | Role 1 | Role 2 在第一个 Tool 实现时反向验证 |
| 错误码归一表（03 文档 §9） | 任一方发现新错误码都要补，PR 双 review | — |
| LM 模型选择 / 字符预算 | Role 1 提供 helper，Role 2 决定 memory 域用什么参数 | — |
| Chat 导出 fallback 策略 | Role 1 实现 helper，Role 2 决定 memory 域如何使用 | — |

---

## 3. 共享契约（W0 必须冻结）

> 这一节是协作的核心。分两类：**对外契约**（对 CLI / server 团队）和**内部契约**（组内两人之间）。任何一方发现契约不够用、想加字段、想改命令名时，**先改 04 文档，等对方 ACK，再改代码**。

### 3.1 对外契约 — bible CLI 命令期望

> 来源：`03-vscode-extension-framework-v4.md` §8.1 / §8.2。本组对 CLI 线的需求清单；W0 时由 Role 1 整理为"CLI 需求 issue"提给 CLI 线。

| # | 命令 | 关键入参 | data 输出 | 同/异步 | 阶段 | CLI 线现状 |
|---|---|---|---|---|---|---|
| C1 | `bible memory search` | `--query`、`--tag memory`、`[--top-k]`、`[--search-type]`、`[--vector-model]` | `{ results: MemoryHit[], total, kb_index, tag }` | 同步 | F1 | 待实现；过渡可用 `bible search --enable-hit --hit-types memory` |
| C2 | `bible memory import` | `--tag memory`、`--kb-index`、`--source-file`、`--meta-file`、`[--vector-model]`、`[--parser-script]` | `{ task_id, status, kb_index, tag, session_id }` | 异步 | F2 | 待实现 |
| C3 | `bible memory download file` | `--tag memory`、`--storage-path`、`[--download-name]` | `{ task_id, status }` | 异步 | F3 | 待实现 |
| C4 | `bible memory download batch` | `--tag memory`、`--paths-file`、`[--package-name]`、`[--include-metadata]` | `{ task_id, status }` | 异步 | F3 | 待实现 |
| C5 | `bible memory artifact fetch` | `--id`、`--out` | `{ path, size_bytes, content_type }` | 同步流 | F3 | 待实现 |
| C6 | `bible task get` | `--id` | `{ task_id, task_type, status, result?, error?, created_at, updated_at }` | 同步 | F2 | 待实现 |
| C7 | `bible task cancel` | `--id` | `{ task_id, status: 'cancelled' }` | 同步 | F2 | 待实现 |
| C8 | `bible health` | — | `{ cli, version, server? }` | 同步 | F0 | **已就绪** |

冻结口径（本组对 CLI 线提出）：

- 命令名 / 子命令路径 / flag 名 / data 字段名一旦 sign-off 不可改；新增字段或 flag 必须向后兼容。
- 输出协议（`{ok, data, error}` envelope + 退出码 0/1/3）严格遵守 `cli-contract-v1.md`。
- v4 业务错误码（`INDEX_BINDING_CONFLICT` / `PARSER_SCRIPT_RISK` / `DOWNLOAD_ARTIFACT_EXPIRED` / ...）必须**原样**透传到 `error.code`，不允许 CLI 聚合成 `INTERNAL`。

CLI 线交付节奏对本组的影响：

- **C1 是 F1 的硬阻塞**。CLI 线如未实现 C1，本组 F1 走真集成需要 fallback 到 `bible search --enable-hit --hit-types memory` 这条已实现的过渡路径。
- **C2 / C6 / C7 是 F2 的硬阻塞**。如未就绪，F2 验收只能用 mock 跑通，真集成推迟。
- **C3 / C5 是 F3 的硬阻塞**。
- 所有"硬阻塞"在 W0 时由 Role 1 与 CLI 线确认时间表，写入本文 §4 对应行的"风险标注"。

### 3.2 对外契约 — 双文件 import 的产物 schema

import 链路涉及两份文件，是本组与 CLI / server 协作面：

**`source` 文件**（Role 2 产出，CLI 透传不解析；server 端落 artifact）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | string | 与 meta.session_id 必须一致 |
| `exported_at` | string (ISO) | 导出时间 |
| `messages` | `Array<{role, content}>` | 解析后的纯文本 turn |
| `raw` | object | Copilot Chat 原始 export JSON（无损） |

**`meta.json`**（Role 2 用 LM 产出 / 规则 fallback；CLI 透传；server 端 `parse_memory.py` 解析为 chunks）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | ✓ | 与 source.session_id 一致 |
| `abstract` | string (≤220) | ✓ | 单行检索摘要 |
| `overview` | string (markdown) | ✓ | 多段正文 |
| `primary_request_intent` | string | ✓ | 用户真实目标 |
| `key_concepts` | string[] | ✓ | 关键概念 |
| `pending_tasks` | string[] | ✓ | 未完成事项 |
| `session_kind` | enum | 推荐 | implementation / analysis / mixed |
| `code_change_status` | enum | 推荐 | modified / not_modified / unknown |
| 其它 | (见 03 §6.4) | 可选 | actual_actions / final_result / touched_files / ... |

冻结口径：

- 必填字段不可减；新增可选字段双方 ACK 即可。
- `session_id` 是 source 与 meta 关联的唯一锚，server 端依据它建立 artifact ↔ chunks 映射。
- 本组与 server 团队就 schema 达成一致后，写入 04 文档；后续 schema 演进由 Role 2 跟 server 团队协调。

### 3.3 对外契约 — 异步任务模型

- 所有 `import` / `download` 命令立即返回 `{task_id, status:'queued'}`。
- 客户端用 C6 `bible task get` 轮询，状态机：`queued → running → completed | failed | cancelled`，可见 `retrying`。
- 用户取消 → 客户端调 C7 `bible task cancel`。
- `task get` 在 `completed` 时返回 `result` 内含业务结果（如 `artifact_id` / `session_id` / `chunks_count`）。

### 3.4 内部契约 — 组内模块边界

> 两人不能跨边界改对方代码；要改必须 PR 评审。

| 模块路径 | 谁拥有 | 对方使用方式 |
|---|---|---|
| `src/core/**` | Role 1 | 只通过导出的接口（`CliRunner` / `TaskTracker` / `Notifications` / `quick-pick` / `selectPreferredModel` / `exportCurrentChat` / ...）使用 |
| `src/domains/memory/**` | Role 2 | Role 1 不直接引用 |
| `src/domains/control/**` | Role 1 | 仅暴露 LM Tool / Command，不导出 service |
| `src/domains/skill/**`（F4） | Role 1 | 仅作为扩展性验证 |
| `src/manifest/tools.manifest.ts` | 共享 | memory 域 schema 由 Role 2 维护，其它由 Role 1；改时各自负责自己的部分 |
| `src/extension.ts` | Role 1 | Role 2 加自己的 module 时改一行 `modules.push(...)`，其余不动 |

依赖方向严格单向：`domains/memory → core`，绝不反向。

### 3.5 内部契约 — 命名空间

- LM Tool 命名：`bible_<domain>_<verb>`（例：`bible_memory_search`）。
- VSCode Command id：`bible.<domain>.<verb>`（例：`bible.memory.saveCurrentChat`）。
- Chat Participant id：`bible.memoryParticipant`，slash 命令：`/save /search /load /help`。
- 配置 key：`bible.<area>.<setting>`（例：`bible.memory.lmModelPriority`）。
- 这些名字进入 LM 推理上下文与 `package.json` `contributes`，**改动等于破坏外部接口**，必须双 ACK。

---

## 4. 并行节奏（W0 ~ W4+）

> 周（W）只是节奏单位，不强制日历周；按里程碑 Fx 锚定。
>
> 每周末 30 min 接口对齐会，只看契约文档 diff，不 review 代码。

| 周 | Role 1 — Platform | Role 2 — Memory Domain | 集成事件（双方共同验收） | 对外依赖状态 |
|---|---|---|---|---|
| **W0** 契约冲刺 | 与 Role 2 一起完成 04-spec 的 CLI 命令章节、错误码归一表；起草 mock CLI v0 | 与 Role 1 一起完成 04-spec 的 Tool/Command/`meta.json` schema 章节；提交 LM Tool `modelDescription` 措辞 | **04 文档 sign-off**；mock CLI v0 跑通 `bible health` | 与 CLI 线开 1 次接口对齐会，确认 C1-C7 时间表 |
| **W1** F0 + F1（mock） | `core/cli` + `core/task` + `core/registry` 落地；`control` 域 `bible_health` Tool；mock CLI 完成 §5.2 全部命令 | `memory-service` 接口签名定稿；`memory-search` Tool/Command 用 mock 跑通；`memory-format` 注入文本初版 | **F0 验收**：插件用 `bible_health` 与真 CLI 跑通；**F1 mock 验收** | 无 |
| **W2** F1 真集成 + F2 起步 | `core/lm` + `core/chat` 完成；`BibleTool` / `AsyncBibleTool` 基类 finalize；mock 加 §5.3 错误注入 | `memory-search` 切真 CLI（如 C1 未就绪用过渡路径）；`chat-export` + `memory-builder` 落地；`memory-import` Tool 走 mock 跑通端到端 | **F1 真集成验收**；保存对话用 mock 端到端通 | C1 期望就绪；C2/C6 在路上 |
| **W3** F2 真集成 | `TaskTracker` 持久化 + 取消链路 finalize；OutputChannel 三类专项事件落地 | LM 失败 fallback 单测；session_id 复制按钮；进度通知 | **F2 验收**：保存当前 chat → server 同时存到 artifact + chunks；规则 fallback case 通过 | C2/C6/C7 期望就绪 |
| **W4** F2.5 + F3 | mock 加 download / artifact fetch 行为；`Bible: Run Self-Check` 命令 | Chat Participant 全部 slash 命令；`memory-download` Tool/Command + artifact 自动 fetch | **F2.5 验收**：`@bible-memory /save` 不消耗 LM token；**F3 验收**：下载拉回 source 原文 | C3/C5 期望就绪 |
| **W5+** 收尾 | `domains/skill/` 骨架（F4 扩展性验证）；状态栏；错误向导 | 批量下载 Command；E2E case 补全；LM prompt 二轮调优 | **F4 + F5 验收** | C4 期望就绪 |

并行原则：

- **任何 Fx 验收必须用真 CLI 跑一次**；mock 只是开发期解锁。
- 任意一方提前完成可以"拉对方一把"（Role 1 提前完成 core 后，可以帮 Role 2 写第一个 Tool 的样板代码）。
- **任何契约改动当周关闭**，不允许跨周拖；拖了就回退到 mock 状态等下一节点。

---

## 5. Mock CLI — 对外依赖隔离层

> Mock CLI 是本组**对 CLI 线进度的隔离机制**，不是某个 Role 的内部工具。Role 1 维护，Role 2 消费，行为契约共享。

### 5.1 Mock CLI 形态

- 实现：一个 Bash / Node 脚本（Role 1 选择），可执行二进制形态。
- 安装：通过 `bible.cliPath` 指向 mock 二进制；不污染 PATH。
- 行为：实现 §3.1 全部 8 条命令的"假返回"，输出严格遵守 `cli-contract-v1.md`。
- **不替代真 CLI 验收**：每个 Fx 节点必须用真 CLI 再跑一次。

### 5.2 Mock 行为契约

| 命令 | mock 行为 |
|---|---|
| `bible health` | `{ok:true, data:{cli:"mock", version:"0.0.0-mock"}}` |
| `bible memory search` | 返回固定 3 条 `MemoryHit` 假数据；`--query` 含 `error` → 返回 `INTERNAL` |
| `bible memory import` | 立即返回 `task_id="mock-imp-<uuid>"`；后续 `task get` 第 1 次 `running`，第 3 次 `completed`，`result.session_id` 用 meta 中读出的 |
| `bible memory download file` | 立即返回 `task_id="mock-dl-<uuid>"`；轮询同上；`completed` 时 `result.artifact_id="mock-art-<uuid>"` |
| `bible memory artifact fetch` | 写一个固定内容到 `--out`；返回 `{path, size_bytes, content_type:"application/json"}` |
| `bible task get` | 内存外用临时文件存状态；按上述脚本推进 |
| `bible task cancel` | 把状态置为 `cancelled` |

### 5.3 错误注入开关

环境变量 `BIBLE_MOCK_INJECT=<scenario>`（W2 完成）：

| 值 | 效果 |
|---|---|
| `not_implemented` | 任意命令返回 exit=3 + `CLI_NOT_IMPLEMENTED`，验插件降级 |
| `slow` | task `running` 拖到第 10 次轮询才 `completed`，验进度条/取消 |
| `task_failed` | task 第 3 次轮询返回 `failed` + 业务错误码 |
| `index_conflict` | import 直接返回 `INDEX_BINDING_CONFLICT` |
| `artifact_expired` | download 完成但 fetch 时返回 `DOWNLOAD_ARTIFACT_EXPIRED` |
| `lm_unavailable` | 这个开关在插件侧（不是 mock CLI），强制 `selectPreferredModel` 返回 undefined，验规则 fallback |

### 5.4 Mock 与真 CLI 的对齐

- Mock 的 schema 与真 CLI 必须保持一致；如真 CLI 实现时发现 schema 漂移，**优先改 mock**（因为真 CLI 必须遵守 §3.1，无法擅改）。
- 每周对齐会上确认本周 CLI 线哪些命令"已可用真 CLI"，把 §4 表格的"对外依赖状态"列同步更新。

---

## 6. 协作机制

### 6.1 PR / 评审规则

| 改动范围 | 要求 |
|---|---|
| 只在自己责任域内（§3.4 模块边界） | 单方合入，commit 描述清楚 |
| 改到 §3.1 / §3.2 / §3.3 对外契约 | 必须先 PR 04 文档，对端 ACK 后才改代码；同时同步 CLI / server 团队 |
| 改 §3.4 / §3.5 内部契约 | 必须双方 ACK |
| 改 03 框架文档 | 双方都要 review |
| 改 mock CLI 行为 | Role 1 主导，Role 2 review；变更要在 §5.2 同步更新 |
| Hotfix 错误码归一表 | 任意一方先 PR 修，然后在周对齐会同步 |

### 6.2 沟通节奏

- **W0**：契约冲刺，密度高（每天 30 min 短对齐）。
- **W1+**：每周末 30 min 接口对齐会 + 一次 Fx 验收会。
- **集成失败**：当天拉 30 min 紧急对齐，定位是契约误解还是实现 bug；契约误解必须当周修文档。
- **与 CLI 线 / server 线沟通**：Role 1 是组内对接 owner（CLI 线）；Role 2 是组内对接 owner（server 线 schema 议题）。
- **异步沟通**：在 04 文档 issue / commit 上批注，不在私聊里讨论契约。

### 6.3 单一信息源

- "现在能用什么真 CLI 命令" → 看 `bible-cli-go-full-rewrite-plan-zh.md` §2.1 Snapshot。
- "插件应该用什么命令 / 字段" → 看 `04-memory-spec-v4.md`。
- "Why 这么设计" → 看 03 / 01。
- "周进度 / 谁负责 / 谁 owner 哪个外部线" → 看本文。

---

## 7. 风险清单

| # | 风险 | 触发条件 | 处理 |
|---|---|---|---|
| K1 | 对外契约（§3.1）频繁变更导致 mock 漂移 | W1 后还在改 CLI 命令清单 | 锁定契约会议；冻结 1 周再放开；必要时拉 CLI 线一起开 |
| K2 | CLI 线 / server 线进度落后 | W2/W3 时 C1/C2/C6 还没真实现 | 验收降级：用过渡路径（C1 用 `bible search --enable-hit`）或用 mock 顶过去，并在本文 §4 标注；F2/F3 真集成可推迟 1 周 |
| K3 | LM token 预算把 `meta.json` 提取打爆 | LM 调用 timeout / quota 超限 | Role 2 必须保证规则 fallback 一直可用；CI 跑 fallback case；用 `BIBLE_MOCK_INJECT=lm_unavailable` 验证 |
| K4 | Copilot Chat 私有命令 `chat.exportSession` 在某些 VSCode 版本不存在 | F2 验收时部分人无法保存 | Role 1 必须保留双策略 fallback；自检命令探测后禁用 `/save` |
| K5 | 大 chat 导出超过 multipart 上传限制 | source 文件 > server 配置上限 | 提需求给 CLI 线在 CLI 层做 size 检查，超限报 `RESOURCE_EXHAUSTED`；插件提示用户 |
| K6 | TaskTracker 轮询爆服务 | 多任务同时跟踪 | Role 1 在 TaskTracker 内做限速 + 指数退避 |
| K7 | 04 文档晚于代码 | W0 还没出 04，W1 就开搞 | 不允许跳过 W0；W0 完不成就推迟所有 Fx |
| K8 | 二人节奏不齐（一个快一个慢） | W2 时一个 F1 完一个还在 F0 | 慢的一方暂停，快的一方协助 mock / 写测试，绝不 "我先往 F2 跑" |
| K9 | core 抽象设计踩雷需返工 | W2 时第一个 Tool 实现发现 `BibleTool` 基类不好用 | Role 1 立即重构基类，Role 2 暂停 import 链路；返工成本 ≤ 2 天为可接受 |
| K10 | server 端 `parse_memory.py` 对 `meta.json` 字段理解与本组不一致 | F2 真集成时 chunks 内容异常 | Role 2 拉 server 团队对齐 schema 实际解析行为；必要时回退 04 §3.2 |

---

## 8. 各 Fx 验收清单（双方共同签字）

### F0（W1 末）

- [ ] 真 CLI `bible health` + 插件 `bible_health` Tool 链路通
- [ ] `core/cli` 错误归一覆盖 §3.1 全部错误码（mock 注入测试）
- [ ] `core/registry` 能动态禁用 Tool（mock 注入 `not_implemented`）
- [ ] OutputChannel 有结构化日志

### F1（W2 末）

- [ ] mock 验收：`bible_memory_search` Tool 与 `Bible: Search Memory` Command 都能在 Copilot Chat / 命令面板触发；返回符合 §3.1 C1 schema
- [ ] 真集成验收：用真 CLI（C1 就绪）或过渡路径（`bible search --enable-hit --hit-types memory`）跑通
- [ ] 0 / 1 / N 命中三种交互全部走通
- [ ] LM 注入文本格式由 Role 2 给出样例，Role 1 确认 OutputChannel 日志清晰

### F2（W3 末，核心闭环）

- [ ] 端到端：在 Copilot Chat 触发"保存对话" → 服务端能查到
  - 一个 source artifact（按 `session_id` 关联，可被 download file 拉回）
  - 一份 chunks 索引（可被 search 命中）
- [ ] LM 失败时规则 fallback 也能成功 import（用 `BIBLE_MOCK_INJECT=lm_unavailable` 验证）
- [ ] 进度通知 / 用户取消 / `bible task cancel` 链路通
- [ ] 通知带"复制 session_id" 按钮
- [ ] OutputChannel 记录 chat-export 策略 / LM 模型 / task 终态

### F2.5（W4 中）

- [ ] `@bible-memory /save /search /load /help` 全可用
- [ ] `/save` 不消耗 LM token（验证：disable Copilot 也能跑）

### F3（W4 末）

- [ ] `bible memory download file`（C3）→ artifact fetch（C5）链路通
- [ ] 下载到本地的是 source 原文（可读到完整对话）
- [ ] `DOWNLOAD_ARTIFACT_EXPIRED` 自动重试一次的逻辑覆盖

### F4 / F5（W5+，可选）

- [ ] 新增 `SkillModule` 不动 core，证明开放-封闭
- [ ] 状态栏 + 自检命令 + 错误向导
- [ ] 任务面板：用户能看到所有进行中任务

---

## 9. 一句话总结

> **2 人都是插件 TS 开发，按"core 平台 vs memory 业务"切分；CLI 是外部依赖，本组只消费、用 mock 隔离其进度风险。W0 把 §3 共享契约（对外的 CLI 命令期望 + source/meta schema + 异步任务模型；对内的模块边界 + 命名空间）签字冻结进 04 文档，之后两人靠 mock CLI 解耦并行，按 Fx 节点同步集成。**
