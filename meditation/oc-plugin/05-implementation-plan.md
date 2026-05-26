# 工程编译、部署与开发计划

本文给出 `bible-oc-plugin` 的落地计划。架构契约见 [总体架构与插件契约](./01-architecture-and-contracts.md)，自动召回见 [自动召回设计](./02-auto-recall.md)，捕获归档见 [自动捕获、归档与记忆抽取](./03-capture-archive-compact.md)，工具和 CLI 见 [工具层与运行时 CLI](./04-tools-and-cli.md)。

## 交付范围

首版交付：

- Native OpenClaw plugin 包结构。
- `openclaw.plugin.json` + `package.json` 契约。
- 本地定义 `OpenClawPluginApi` 和 Context Engine 最小类型。
- Context Engine：`assemble`、`afterTurn`、`compact`。
- Hooks：`session_start`、`session_end`、`before_reset`。
- Tools：memory、knowledge、skill 初始工具集。
- CLI：`openclaw bible setup/status`。
- 本地手动安装脚本。
- 单元测试、HTTP mock 测试、基础集成 smoke test。

不在首版范围：

- ClawHub 发布。
- 本地启动或管理 BiBLE Atlas Server。
- 引入额外 reranker 模型。
- 覆盖 OpenClaw 内部未公开 API。

## 阶段计划

### P0：插件骨架与契约

目标：

- 建立 `bible-oc-plugin` 目录。
- 写入 `package.json`、`openclaw.plugin.json`、`tsconfig.json`。
- 实现本地鸭子类型。
- 实现 config schema 对应的运行时解析。
- 建立 HTTP client 基础设施和 health/status。

验收：

- `npm run build` 通过。
- `openclaw.plugin.json` 能被 OpenClaw discovery 识别。
- `setup/status` 能检查远程 `/health`。

### P1：工具层

目标：

- 注册首版 core tools：`bible_memory_search`、`bible_memory_save`、`bible_memory_get`、`bible_knowledge_search`、`bible_knowledge_list`、`bible_skill_search`、`bible_skill_get`。
- 将 task/system 诊断工具归入 ops 层，将 upload/uploadAll/download 归入 heavy/optional 层，后续阶段再实现或显式启用。
- 建立工具参数校验、输出裁剪和错误映射。

验收：

- mock server 覆盖 success、4xx、5xx、timeout。
- `contracts.tools` 与运行时注册一致。
- tool `content` 中包含模型可见摘要，`details` 中包含结构化结果。

### P2：自动召回

目标：

- 实现 `createBibleContextEngine`。
- 实现 `assemble` 主流程。
- 第一阶段实现 memory-only 自动召回，完成查询预处理、memory 检索、统一命中结构、阈值过滤、重排和预算裁剪。
- 实现 `<relevant-memories>` 渲染。
- 实现 `bypassSessionPatterns`。
- 将 `memory-knowledge`、`memory-skill` 和 `all` 作为后续 preset 扩展，不阻塞第一阶段交付。

验收：

- bypass session 不访问 HTTP。
- memory 默认参与召回，skill/knowledge 默认关闭。
- 第一阶段不要求配置 knowledge tag，也不要求 skill/knowledge 并行检索通过。
- 单域失败不影响其他域。
- 注入内容在预算内，格式固定。

### P3：捕获、归档、compact

目标：

- 实现 `afterTurn` buffer。
- 实现阈值异步 commit。
- 实现 `compact` 同步 commit 和 fallback summary。
- 实现 `session_start`、`session_end`、`before_reset` hooks。

验收：

- 阈值触发异步 commit。
- `compact` 提交 pending turns 并返回 summary。
- `before_reset` 触发 bounded flush。
- hook priority、timeout 和错误隔离策略通过 mock runtime 验证。
- `before_reset`、`session_end`、`compact` 连续触发时不会重复提交同一 turn range。
- 失败时保留 buffer 并可重试。

### P4：本地安装与端到端验证

目标：

- 提供 `scripts/install-local.mjs`。
- 文档化本地安装路径。
- 增加 smoke test：本地 OpenClaw 加载插件、占用 contextEngine slot、执行一次召回。
- 增加 `status --json`，支持 CI 检查。

验收：

- 纯安装不要求 BiBLE Atlas 服务可访问，只检查构建产物、manifest 和本地 plugin entry。
- 没有可访问 BiBLE Atlas 服务时，`openclaw bible setup --write` 明确失败且不写入启用配置。
- 服务可访问时，`setup --write` 可写入插件配置和 `contextEngine` slot，并通过 `openclaw bible status` 检查。

## 可执行实施清单

本节吸收早先 `docs/bible-oc-plugin-plan.md` 的 Steps，把高层阶段进一步拆成可落地任务。主设计仍以本目录文档为准；本清单用于编码排期、issue 拆分和验收跟踪。

### 当前实现状态（2026-05-26）

- resolved：工程骨架已落地于 `bible-oc-plugin/`，包含 manifest、package metadata、runtime/setup entries、TypeScript build、Vitest 测试和 `scripts/install-local.mjs`。
- resolved：插件 id、npm package name、contextEngine slot 和默认 `contextEngineId` 已统一为 `bible-oc-plugin`，不再使用 `bible-atlas` 作为 engine id。
- resolved：OpenClaw 2026.5.22 ContextEngine contract 已对齐；factory 返回 `info`、`ingest()`、新版 `assemble()`、`afterTurn()`、`compact()`，召回通过 `systemPromptAddition` 注入。
- resolved：未配置状态下仍可注册 `openclaw bible` CLI；manifest 不再把 `baseUrl` 设为安装前硬性 required，避免 setup 命令被配置校验挡住。
- resolved：`openclaw bible setup --write` 写入 `~/.openclaw/openclaw.json`（或 `OPENCLAW_CONFIG_PATH`）并设置 `plugins.slots.contextEngine = "bible-oc-plugin"`；`status` 可从宿主 config snapshot 读取 enabled/slot。
- resolved：开发期日志已接入 `plugin.register`、CLI、runtime HTTP、ContextEngine、recall、capture、hooks 和 tool execute，使用 `[bible-oc-plugin]` 前缀，失败时输出结构化 error meta。
- resolved：本地验证通过 `npm run typecheck`、`npm test`、`npm run build`，并可通过 `openclaw bible status` 看到 slot、health、工具契约和插件日志。
- known gap：BiBLE Atlas Server 尚未部署 session memory import/commit 能力；`captureEnabled=true` 时 threshold/lifecycle commit 会对 `/api/import/memory` 报 404。开发期可临时关闭 `captureEnabled`，待 server 提供 multipart memory import 或专用 session commit API 后再恢复。

### Phase 1：工程骨架与契约对齐

1. 初始化 `bible-oc-plugin/` 工程结构，建立 `src/index.ts`、`src/types/openclaw.ts`、`src/config/`、`src/http/`、`src/runtime/`、`src/context/`、`src/hooks/`、`src/tools/`、`src/cli/`、`scripts/install-local.mjs`。
2. 在 `src/types/openclaw.ts` 本地定义 `OpenClawPluginApi`、Context Engine 最小类型、hook/tool/CLI 注册所需鸭子类型。
3. 编写 `package.json`，声明 `engines.openclaw >= 2026.5.18`、runtime entry、setup entry、`openclaw.compat.pluginApi`、`openclaw.compat.minGatewayVersion` 和 build baseline。
4. 编写 `openclaw.plugin.json`，声明 `kind: "context-engine"`、`contracts.tools`、`setup`、`configSchema`、`activation` 和 `toolMetadata`。
5. 建立 `tsconfig.json`、测试配置和 manifest/package fixture 测试。

### Phase 2：配置与远程运行时

1. 定义配置模型：`baseUrl`、`token`、`timeoutMs`、`bypassSessionPatterns`、`recall`、`capture`、`knowledgeTags`、tool 开关。
2. 实现配置严格校验、默认值合并和 `bypassSessionPatterns` 正则预编译错误报告。
3. 实现低层 HTTP client：baseUrl join、Bearer token、timeout/abort、JSON envelope、错误映射。
4. 集中定义 endpoints：health/status、memory/knowledge/skill search、memory/skill import、download、task status/poll。
5. 实现 `runtime/bible-runtime.ts` 门面，封装 setup/status、检索、commit、上传、轮询、重试和错误映射。
6. 确保远程模式在 setup/status 和插件启动健康检查中可探活，但不负责启动 BiBLE Atlas 服务。

### Phase 3：Context Engine 核心路径

1. 在 `context/engine.ts` 实现引擎构造、`assemble`、`afterTurn`、`compact`，并在 `index.ts` 注册 `registerContextEngine("bible-oc-plugin", factory)`。
2. 在 `context/recall.ts` 实现第一阶段 memory-only 召回查询预处理、memory 检索、超时保护和失败降级。
3. 在 `context/ranking.ts` 实现统一 `RecallHit`、阈值过滤、线性重排和 prompt injection 降权标记；跨域去重随后续 preset 扩展补齐。
4. 在 `context/injection.ts` 实现 `<relevant-memories>` 渲染、token 预算估算、条目裁剪和注入 hard cap。
5. 在 `context/capture.ts` 实现 `afterTurn` 增量捕获、session buffer、阈值异步 commit、commitInFlight 和失败重试。
6. 实现 `compact` 同步 commit、fallback summary、commit range 去重，确保与 `afterTurn` 状态一致。

### Phase 4：Hook 层与旁路策略

1. 在 `hooks/lifecycle.ts` 注册 `session_start`、`session_end`、`before_reset`。
2. 在 `hooks/bypass.ts` 实现 `bypassSessionPatterns` 匹配，并在 `assemble`、`afterTurn`、`compact`、hooks 中统一复用。
3. 增加 hook priority、timeout 和错误隔离策略，保证插件异常不阻塞宿主主流程。
4. `before_reset` 必须触发 bounded flush，并通过 commit range 或 pending buffer 状态避免重复提交。
5. `session_end` 在 `shutdown` / `restart` reason 下遵守宿主 finalizer 时间预算。

### Phase 5：工具层与 CLI

1. 在 `tools/register.ts` 注册首版 core tools，并保持 `contracts.tools` 与实际注册一致。
2. 在 `tools/memory.ts`、`tools/knowledge.ts`、`tools/skill.ts` 实现输入 schema、HTTP runtime 调用、输出裁剪、错误码映射。
3. 在 `tools/system.ts` 预留 ops 工具实现位置；`bible_task_status`、`bible_system_health`、`bible_system_status` 后续按需注册。
4. 将 `bible_memory_upload`、`bible_memory_upload_all`、`bible_skill_upload`、`bible_skill_download` 归入 heavy/optional 工具，后续实现时增加权限、确认、体积限制和超时策略。
5. 实现 `openclaw bible setup/status`：setup 写入插件配置并做连通性校验，status 汇总插件启用、slot、工具契约、召回/捕获配置和服务健康状态。
6. 实现 `status --json`，供 CI 和脚本稳定解析。
7. 编写 `scripts/install-local.mjs`：检查构建产物、manifest 和本地 plugin entry；默认不隐式启用 slot。

### Phase 6：测试、文档与交付

1. 单元测试：召回预处理、并行检索、去重重排、预算注入、旁路匹配、hook 提交流程。
2. 集成测试：mock BiBLE Atlas HTTP，覆盖成功、超时、阈值过滤、异步任务、`before_reset` 提交。
3. 插件注册回归：mock OpenClaw API，验证 contextEngine/hooks/tools/CLI 注册。
4. 契约测试：校验 `openclaw.plugin.json` 与 `contracts.tools`、`configSchema`、setup、activation、toolMetadata 字段一致，并校验 `package.json` 的 compat/build baseline。
5. 端到端 smoke：本地 OpenClaw 加载插件、占用 `contextEngine` slot、执行一次 memory-only 召回。
6. 文档交付：安装前置、配置项、第一阶段 memory-only 策略、后续召回 preset、旁路策略、setup/status 使用和故障排查。

## 端到端验收清单

本清单吸收早先 `docs/bible-oc-plugin-plan.md` 的 Verification，并按当前已采纳的分阶段策略修订：

1. 运行插件单测与集成测试，验证 `assemble`、`afterTurn`、`compact` 与 hook 触发顺序、timeout 和错误隔离。
2. 在 mock BiBLE Atlas 场景下验证 Phase 1 memory-only 自动召回：查询预处理、memory 检索、阈值、重排、预算控制、`<relevant-memories>` 注入位置。
3. 在启用后续 recall preset 的测试中验证 memory/knowledge/skill 并行检索、跨域去重、单域失败降级和预算重分配。
4. 验证旁路：命中 `bypassSessionPatterns` 时，Context Engine 不检索、不注入，capture/hooks 不提交会话内容。
5. 验证 `before_reset` 强制提交会执行，且与 `compact`、`session_end` 连续触发时不会重复提交同一 turn range。
6. 验证首版 core tools 全部注册成功，输入 schema 校验、错误码映射、输出裁剪和 tool `content/details` 分层符合设计。
7. 执行 `openclaw bible setup`：校验 HTTP 连通性失败/成功路径、配置写入幂等；执行 `openclaw bible status`：校验运行时状态、slot、工具契约和服务健康聚合。
8. 执行 `scripts/install-local.mjs`：无服务时可完成纯安装但阻断 setup/slot 启用；有服务时可通过 `setup --write` 完成配置写入和 `contextEngine` slot 启用。
9. 校验 `openclaw.plugin.json` 的 `contracts`、`setup`、`configSchema`、`activation`、`toolMetadata` 与实际实现一致，校验 `package.json` 的 `engines.openclaw`、compat/build baseline 与基线一致。

## 落地文件清单

推荐实现文件如下。统一使用 `bible-oc-plugin/` 作为目录名、npm package name、OpenClaw plugin id 和文档称呼。

```text
bible-oc-plugin/
  package.json                         # 插件包元数据、engines.openclaw、runtime entries
  openclaw.plugin.json                 # kind/contracts/setup/configSchema/activation
  tsconfig.json
  src/
    index.ts                           # 插件入口，注册 contextEngine/hooks/tools/cli
    types/
      openclaw.ts                      # OpenClawPluginApi 鸭子类型与上下文接口
    config/
      schema.ts                        # 配置 schema 与默认策略
      types.ts                         # 配置类型
    http/
      client.ts                        # 低层 HTTP 调用封装
      endpoints.ts                     # BiBLE Atlas endpoint 常量
      errors.ts                        # 错误码映射
    runtime/
      bible-runtime.ts                 # 远程运行时门面
    context/
      engine.ts                        # assemble/afterTurn/compact 主入口
      recall.ts                        # 自动召回总流程与并行检索
      ranking.ts                       # 去重、阈值过滤、重排
      injection.ts                     # <relevant-memories> 注入与预算控制
      capture.ts                       # afterTurn 增量捕获与 compact 同步提交
    hooks/
      lifecycle.ts                     # session_start/session_end/before_reset
      bypass.ts                        # bypassSessionPatterns 判定
    tools/
      register.ts                      # 工具注册总线
      memory.ts                        # memory 工具实现
      knowledge.ts                     # knowledge 工具实现
      skill.ts                         # skill 工具实现
      system.ts                        # health/status/task 工具实现，可选
    cli/
      register.ts                      # openclaw bible setup/status 注册
      setup.ts                         # setup 命令与配置写入
      status.ts                        # status 命令与状态聚合
  scripts/
    install-local.mjs                  # 本地手动安装脚本
  tests/
    unit/
    integration/
```

参考文件：

- `bible_cli_go/internal/client/http/client.go`：HTTP 基础能力和 knowledge/system 语义参考。
- `bible_cli_go/internal/client/http/memory.go`：memory、skill、import、task 协议参考。
- `docs/3rd/openclaw/plugins/hooks.md`：hook 事件、优先级、timeout 语义参考。
- `docs/3rd/openclaw/plugins/sdk-overview.md`：`registerTool`、`registerContextEngine`、`registerCli` 参考。
- `docs/3rd/openclaw/plugins/manifest.md`：`contracts`、`setup`、`configSchema` 规范参考。
- openclaw plugin-sdk 源代码可以在`3rd/openclaw/plugin-sdk` 目录下找到
- openclaw plugin 设计文档可以在`docs/3rd/openclaw` 目录下检索

## 本地手动安装与启用

纯安装前置条件：

1. 本地已安装 OpenClaw `>= 2026.5.18`。
2. Node.js 满足插件 `engines.node`。
3. 插件已完成构建，`dist/index.js` 和 `openclaw.plugin.json` 存在。

启用/setup 前置条件：

1. BiBLE Atlas HTTP 服务已启动。
2. `GET /health` 可访问。
3. token、timeout、recall/capture 配置可通过 schema 校验。

建议流程：

```bash
cd bible-oc-plugin
npm install
npm run build
node scripts/install-local.mjs --openclaw-config ~/.openclaw/config.json
openclaw bible setup --base-url http://127.0.0.1:5555 --write
openclaw bible status
```

安装脚本职责：

- 检查 `dist/index.js` 和 `openclaw.plugin.json`。
- 把插件路径加入 OpenClaw 本地 plugin entries。
- 不覆盖已有用户配置，所有变更先输出 diff。
- 不检查远程 BiBLE Atlas 服务，不自动启用 `contextEngine` slot，不写入运行时配置。

`openclaw bible setup --write` 职责：

- 检查远程 BiBLE Atlas 服务连通性。
- 校验 token、timeout、recall/capture、`bypassSessionPatterns` 等配置。
- 写入插件运行时配置。
- 设置 `plugins.slots.contextEngine = "bible-oc-plugin"`。

如果需要一步式体验，可在安装脚本中提供显式组合参数，例如 `--setup --base-url ... --enable-slot`。该路径必须先执行 setup 校验；无服务时可以完成纯安装，但必须阻断 setup 和 slot 启用。

## 构建方案

建议使用 TypeScript：

```json
{
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "test": "vitest run",
    "lint": "eslint src --ext .ts"
  }
}
```

构建输出：

```text
dist/
  index.js
  setup-entry.js
  ...
  index.d.ts
```

编译约束：

- 不从 `3rd/openclaw/plugin-sdk` 导入类型。
- 不使用 OpenClaw 内部相对路径。
- HTTP client 和工具层可独立单元测试。
- `openclaw.plugin.json` 和 `package.json#openclaw` 纳入 fixture 测试。

## 测试矩阵

| 层级 | 测试 |
|---|---|
| config | schema 默认值、必填 baseUrl、regex 编译失败 |
| HTTP client | health、search、import、task polling、timeout、error envelope |
| tools | 参数校验、输出裁剪、错误映射 |
| recall | 查询预处理、并行检索、去重、阈值、重排、预算 |
| context engine | assemble 空结果、注入结果、bypass |
| capture | afterTurn buffer、阈值 commit、commit failure retry |
| compact | 同步 commit、fallback summary、metadata warnings |
| hooks | session_start/end、before_reset flush、priority、timeout、错误隔离、重复提交防护 |
| CLI | setup dry-run/write、status text/json |
| packaging | manifest contracts、activation、toolMetadata、engines.openclaw、compat/build baseline、runtimeExtensions 存在 |

## 漂移防护

需要自动检查：

- `openclaw.plugin.json#contracts.tools` 与 `src/tools/register.ts` 的 tool name 一致。
- `package.json#engines.openclaw` 不低于 `2026.5.18`。
- `package.json#openclaw.compat.pluginApi`、`package.json#openclaw.compat.minGatewayVersion` 和 build baseline 与 `2026.5.18` 对齐。
- `openclaw.plugin.json#kind` 为 `context-engine`。
- `openclaw.plugin.json#activation` 明确 `onStartup`，并用 config/capability metadata 支持冷路径规划。
- `openclaw.plugin.json#toolMetadata` 只引用已声明在 `contracts.tools` 中的工具。
- `configSchema` 包含 `baseUrl`、召回开关、捕获开关、`bypassSessionPatterns`。
- 文档中的 endpoint 与 HTTP client 常量一致。

建议新增一个 `npm run verify:contracts` 脚本读取 manifest、package 和源码导出的 tool registry。

## 风险与决策点

### Context Engine 类型漂移

状态：resolved for OpenClaw 2026.5.22。

风险：OpenClaw 公开 re-export 的 Context Engine 类型可能在后续版本扩展。2026.5.22 已要求 `info`、`ingest()`、新版 `assemble()` 和必需 `compact()`；旧的 `appendContext`/双参数 `assemble(input, ctx)` 会被宿主判为 invalid ContextEngine。

策略：

- 插件只依赖当前宿主校验的最小字段：`info.id/name`、`ingest()`、`assemble()`、`compact()`。
- 未识别字段透传忽略。
- `engines.openclaw` 固定下限，status 中展示宿主版本。
- 如果宿主缺少 `registerContextEngine`，启动时报明确错误。
- 每次升级 OpenClaw 后必须执行 `openclaw bible status` 和一次真实会话 smoke，确认没有 `invalid ContextEngine` 日志。

### `systemPromptAddition` 与召回注入位置

状态：resolved for OpenClaw 2026.5.22。

风险：OpenClaw 的 Context Engine 返回形态不是直接改写用户消息。当前宿主使用 `AssembleResult.messages` 加 `systemPromptAddition`。

策略：

- 首选宿主推荐的 `systemPromptAddition` 字段。
- 语义固定为“仅本 turn 生效的参考材料”，不写入永久会话消息。
- 测试用 mock runtime 验证 `systemPromptAddition` 中包含 `<relevant-memories>`。

### Commit API 未完全稳定

状态：open / blocked by server capability。

风险：BiBLE Atlas Server 对 JSON save、multipart import、任务轮询的契约继续演进。

策略：

- 插件内部只暴露 `commitSessionMemory`。
- HTTP client 当前调用 `/api/import/memory`，但 server 尚未部署 session memory import/commit 能力时会返回 404；开发期应允许关闭 `captureEnabled`。
- 若 server 提供更合适的 JSON commit API，只替换 client 映射，不改 Context Engine 和 hooks。

### 开发期可观测性

状态：resolved。

策略：

- 所有关键动作使用 `[bible-oc-plugin]` 前缀输出 start/done/failed。
- `warn`/`error` 包含结构化错误字段：`name`、`message`、`stack`、`code`、`statusCode`、`serverErrorCode`。
- 日志元数据避免记录完整 prompt/query/token；只记录长度、数量、sessionKey、tool/domain、耗时和状态。
- 调试时使用 `openclaw logs --follow` 或 `openclaw bible status` 触发 CLI/runtime 路径验证日志。

### 召回延迟

风险：多域并行检索影响首 token 延迟。

策略：

- memory 默认启用，skill/knowledge 默认关闭。
- 单域 timeout 小于 assemble 总预算。
- 所有域失败返回空，不阻断回复。
- status 展示平均召回耗时和失败率可作为后续观测增强。

## 后续 ClawHub 路径

当本地手动安装稳定后，再补：

- npm package metadata 和发布流程。
- `openclaw.install.clawhubSpec` / `npmSpec`。
- artifact integrity。
- 版本迁移和 config migration。
- ClawHub smoke tests。

ClawHub 发布前必须确保 runtime entry 全部指向 `dist/*.js`，不能依赖用户机器上的 TypeScript loader。
