# bible-oc-plugin 两版设计对比分析报告

## 对比对象

- 早先设计：`docs/bible-oc-plugin-plan.md`
- 新设计：`meditation/oc-plugin/README.md` 及 `01` 到 `05` 系列文档

## 总体结论

两版设计在核心方向上高度一致：都把 `bible-oc-plugin` 定位为 OpenClaw 到 BiBLE Atlas 的全生命周期集成插件，而不是单纯检索工具；都要求占用 `contextEngine` 槽位，实现 `assemble`、`afterTurn`、`compact`；都采用远程 HTTP 模式、运行时耦合与编译时解耦；都覆盖 hooks、tools、setup/status、`bypassSessionPatterns` 和本地手动安装。

主要差异不在“是否要做”，而在设计颗粒度和默认策略：

- 早先设计更像实施任务拆解，优点是路径、文件、phase、依赖关系和验证项非常直接，适合进入编码。
- 新设计更像系统契约说明，优点是把 OpenClaw manifest、Context Engine 最小类型、召回 pipeline、compact fallback、tool 输出、安装约束和漂移风险写得更清楚，适合评审和长期维护。
- 需要融合的最大决策点是自动召回默认源：早先设计默认 `memory + knowledge`，可切换 `memory + skill`；新设计默认只启用 memory，skill/knowledge 显式开启。最终采纳分阶段策略：第一开发阶段采用 memory-only，后续扩展到 `memory + knowledge`、`memory + skill` 和全量 preset。

## 共识项

### 插件定位一致

两版都明确插件不是单一知识库、记忆或技能检索插件，而是覆盖 OpenClaw 到 BiBLE Atlas 的集成层。

一致职责包括：

- Context Engine：`assemble`、`afterTurn`、`compact`
- Hook：`session_start`、`session_end`、`before_reset`
- Tool：memory、knowledge、skill 相关能力
- Runtime/CLI：`openclaw bible setup/status`
- Remote mode：连接已有 BiBLE Atlas HTTP 服务
- Bypass：通过 `bypassSessionPatterns` 对特定 session 旁路

### OpenClaw 依赖策略一致

两版都采用：

- 基线 `openclaw >= 2026.5.18`
- `index.ts` 本地定义 `OpenClawPluginApi` 鸭子类型
- 运行时依赖宿主注入 `registerTool`、`registerContextEngine`、`on` 等能力
- 编译时避免绑定 OpenClaw 私有类型
- `openclaw.plugin.json` 声明 `kind`、`contracts`、`setup`、`configSchema`

新设计进一步补充了 `runtimeExtensions`、`runtimeSetupEntry` 和 `setup.requiresRuntime=false` 的打包/发现约束。

### Context Engine 与自动召回方向一致

两版都要求：

- `assemble` 在回复前自动召回
- 并行检索 BiBLE Atlas 的多个域
- 对结果去重、阈值过滤、重排、预算控制
- 注入到当前用户消息末尾
- 使用 `<relevant-memories>` 标签

新设计补充了更具体的 pipeline：查询预处理、统一 `RecallHit`、跨域去重、线性重排、预算分配、prompt injection 防护和空结果降级。

### 捕获、归档、compact 方向一致

两版都要求：

- `afterTurn` 增量捕获
- 达到阈值后异步 commit
- `compact` 同步 commit 并返回压缩结果
- `before_reset` 强制提交以降低丢失风险
- 避免 afterTurn 与 compact 重复提交

新设计补充了 session state、commit 请求模型、fallback summary、commit 超时、buffer hard cap 和错误分类。

### 工具层与 CLI 方向一致

两版都要求：

- 工具层通过 HTTP 封装 `bible_cli_go` 当前和未来能力
- `openclaw bible setup/status` 管理配置和状态
- 本地手动安装，ClawHub 后续再考虑

新设计更强调工具不 shell 调用 `bible_cli_go`，而是把 `bible_cli_go` 作为端点和行为语义参考。

## 关键差异

### 1. 文档形态：任务计划 vs 设计体系

- 已采纳。`05-implementation-plan.md` 保留原有高层阶段，并新增“可执行实施清单”和“落地文件清单”，用于承接早先设计中的 Steps、依赖关系和 Relevant files。

### 2. 插件目录命名不一致

- 已采纳。新设计文档统一使用 `bible-oc-plugin` 作为目录名、npm package name、OpenClaw plugin id 和文档称呼；`bible_oc_plugin` 仅在本报告中作为早先设计的历史引用出现。

### 3. 自动召回默认源策略不同

- 基本采纳，并明确分阶段落地。第一开发阶段采用新方案的 memory-only 默认策略，降低交付难度和外部依赖；早先方案更贴近最终产品目标，作为后续扩展开发内容，通过 `memory-knowledge`、`memory-skill` 和 `all` preset 逐步补齐。

### 4. 工具命名与范围不同

- 已采纳。工具统一采用 `bible_*` 前缀；首版 `contracts.tools` 只声明 core tools；task/system/status 归入 ops 层，upload/uploadAll/download 归入 heavy/optional 层，后续实现后再加入 manifest。

### 5. 安装脚本语义不同

- 已采纳。`scripts/install-local.mjs` 只负责本地安装/链接、构建产物和 manifest 检查；`openclaw bible setup --write` 负责远程服务连通性校验、运行时配置写入和 `contextEngine` slot 启用。无服务时允许纯安装，但必须阻断 setup 写入和 slot 启用。

### 6. Hook 异常隔离在新设计中不够显式

- 已采纳。早先设计对 Hook priority、timeout、错误隔离的要求合理，已在 `03-capture-archive-compact.md` 补充 Hook Safety 小节，并在 `05-implementation-plan.md` 增加对应验收和测试矩阵要求。

### 7. 运行时门面在早先设计中更明确

- 已采纳。`01-architecture-and-contracts.md` 已补充 `runtime/bible-runtime.ts` 作为共享业务门面，明确 Context Engine、tools、CLI、hooks 都通过 runtime facade 访问 BiBLE Atlas 业务能力；`05-implementation-plan.md` 的文件清单和 Phase 2 已保留该实现任务。

### 8. Manifest activation/tool metadata 早先设计覆盖更多

- 已采纳。`01-architecture-and-contracts.md` 已在 `package.json` 草案补充 `openclaw.compat` 和 `openclaw.build` baseline，并在 `openclaw.plugin.json` 草案补充 `activation` 和 `toolMetadata`。`05-implementation-plan.md` 已将这些字段纳入契约测试和漂移防护。

## 建议融合后的最终决策

### 目录与模块

采用：

```text
bible-oc-plugin/
  src/
    index.ts
    types/openclaw.ts
    config/
      schema.ts
      types.ts
    http/
      client.ts
      endpoints.ts
      errors.ts
    runtime/
      bible-runtime.ts
    context/
      engine.ts
      recall.ts
      ranking.ts
      injection.ts
      capture.ts
    hooks/
      lifecycle.ts
      bypass.ts
    tools/
      register.ts
      memory.ts
      knowledge.ts
      skill.ts
      system.ts
    cli/
      register.ts
      setup.ts
      status.ts
  scripts/
    install-local.mjs
  tests/
    unit/
    integration/
```

### 默认召回策略

采用：

```text
phase 1 default: memory
phase 2 preset: memory-knowledge，需要至少一个 knowledgeTag
phase 2 preset: memory-skill
phase 2 advanced: memory + skill + knowledge
```

这同时满足第一阶段可交付性和早先设计的最终目标：先完成 memory-only 的 Context Engine 替换，再扩展 knowledge/skill 并行召回。

### 工具命名与范围

采用 `bible_*` 前缀命名：

- v1 core：`bible_memory_search`、`bible_memory_save`、`bible_memory_get`、`bible_knowledge_search`、`bible_knowledge_list`、`bible_skill_search`、`bible_skill_get`
- v1 ops：`bible_task_status`、`bible_system_health`、`bible_system_status`
- v1 optional/heavy：`bible_memory_upload`、`bible_memory_upload_all`、`bible_skill_upload`、`bible_skill_download`

`contracts.tools` 按实际首版范围声明，不提前声明未注册工具。

### 安装与 setup

采用职责拆分：

- `install-local.mjs`：安装/链接/manifest 检查
- `openclaw bible setup --write`：连通性校验、配置写入、slot 启用
- `openclaw bible status`：健康、slot、工具契约、召回和捕获状态

可提供一键参数，但默认不隐式改 slot。

### Hook safety

补充为强制实现要求：

- session hooks 使用明确 timeout。
- `before_reset` bounded flush。
- `session_end` 在 shutdown/restart reason 下遵守宿主预算。
- hook 失败不阻断宿主主流程，只记录 warning/error。
- commit 失败保留 buffer，后续重试。

## 修订覆盖状态

以下为本报告曾建议对 `meditation/oc-plugin` 做的增量修订；当前均已覆盖：

1. `01-architecture-and-contracts.md`
   - 已完成：统一目录名为 `bible-oc-plugin/`，并说明目录名、npm package name、OpenClaw plugin id 和文档称呼一致。
   - 已完成：在 `package.json` 草案补充 `compat.pluginApi`、`compat.minGatewayVersion` 和 build baseline。
   - 已完成：在 `openclaw.plugin.json` 草案补充可选 `activation`、`toolMetadata`。
   - 已完成：增加 `runtime/bible-runtime.ts` 作为共享业务门面。

2. `02-auto-recall.md`
   - 已完成：增加分阶段召回策略，第一开发阶段为 memory-only。
   - 已完成：将 `memory-knowledge`、`memory-skill`、`all` 归入后续扩展 preset。
   - 已完成：说明早先默认 `memory + knowledge` 更贴近最终目标，但不作为第一阶段默认目标。

3. `03-capture-archive-compact.md`
   - 已完成：增加 Hook Safety 小节，覆盖 priority、timeout、错误隔离。
   - 已完成：明确 `before_reset`、`session_end`、`compact` 连续触发时通过 turn range / pending buffer 状态避免重复提交。

4. `04-tools-and-cli.md`
   - 已完成：增加工具分层：core、ops、heavy/optional。
   - 已完成：明确 system health/status 不进入首版 core，可作为 ops tool 或 CLI/runtime 内部能力后续引入。
   - 已完成：增加 `bible_task_status` 所属 ops 层说明；首版不提前加入 `contracts.tools`。

5. `05-implementation-plan.md`
   - 已完成：吸收早先设计的 numbered Steps 和 Relevant files。
   - 已完成：加入早先 Verification，并按当前分阶段策略修订为 E2E 验收清单。
   - 已完成：将 `install-local.sh` 的意图迁移为 `install-local.mjs`，并解释无服务时纯安装不阻断、setup 写入和 slot 启用必须阻断。

## 风险清单

### ~~R1：默认 knowledge 召回导致无 tag 失败~~

~~如果采用早先默认 `memory + knowledge`，但没有配置 `knowledgeTags`，`POST /api/search/knowledge-base` 可能无法构造合法请求。~~

覆盖状态：已覆盖。当前设计采用 Phase 1 memory-only；`memory-knowledge` preset 属于后续扩展，开启时强制要求至少一个 `knowledgeTag`。

### ~~R2：工具范围过大导致首版交付发散~~

~~早先 v1 工具范围包含 uploadAll、download、system 等，容易拉长首版。~~

覆盖状态：已覆盖。当前设计将工具分为 core、ops、heavy/optional；首版 `contracts.tools` 只声明 core tools，upload/uploadAll/download 不进入首版 core。

### ~~R3：安装脚本隐式启用 slot 影响用户已有 Context Engine~~

~~如果安装脚本自动激活 `contextEngine` 槽位，可能覆盖用户已有配置。~~

覆盖状态：已覆盖。当前设计明确 `scripts/install-local.mjs` 只做本地安装/链接；`contextEngine` slot 只能通过 `openclaw bible setup --write` 或显式一步式 setup 校验后写入。

### ~~R4：Context Engine 返回结构仍需以 OpenClaw 实测为准~~

~~新设计提出 `appendContext / user-message suffix` 两种可能，但最终实现必须以 OpenClaw 实测 Context Engine contract 为准。~~

覆盖状态：resolved。OpenClaw 2026.5.22 实测要求 `info`、`ingest()`、新版 `assemble()` 和必需 `compact()`；当前实现通过 `systemPromptAddition` 注入 `<relevant-memories>`，并在 smoke test 中校验 `info` / `ingest` contract。

### ~~R5：commit API 与 server 当前能力可能有差距~~

~~两版都假设 memory commit/save 能通过 HTTP 完成，但当前可能需要 multipart import 或 `bible_cli_go` 已封装的 save 语义。~~

覆盖状态：partially resolved / blocked by server capability。当前设计要求内部只暴露 `commitSessionMemory` runtime 方法；底层可适配 multipart import、JSON save 或后续 server API，而不影响 Context Engine / hooks。当前 BiBLE Atlas Server 尚未部署 session memory import/commit，开发期可通过 `captureEnabled=false` 关闭自动归档。

## 最终建议

以新设计文档作为主线，因为它更完整地描述了 OpenClaw 契约、召回细节、捕获失败路径和长期维护边界；同时吸收早先设计的任务清单、文件拆分、runtime facade、hook safety、完整验证项和工具范围分层。

最优融合路径更新为：

1. 设计文档修订已完成，本报告提到的差异均已在 `meditation/oc-plugin` 中覆盖。
2. 下一步根据融合后的 `05-implementation-plan.md` 创建 `bible-oc-plugin/` 工程骨架。
3. 第一轮实现只做 core：manifest/package、HTTP runtime、core tools、memory-only recall、afterTurn/compact/before_reset。
4. 第二轮再开启 knowledge/skill preset、ops/heavy tools、端到端 OpenClaw smoke test。
