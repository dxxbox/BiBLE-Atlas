# 总体架构与插件契约

## 目标定位

`bible-oc-plugin` 是 OpenClaw 与 BiBLE Atlas 的生命周期集成层，覆盖四类职责：

1. Context Engine：注册并占用 `contextEngine` 槽位，实现 `assemble`、`afterTurn`、`compact`。
2. Hook 层：监听 `session_start`、`session_end`、`before_reset`，必要时补充 `gateway_start`/`gateway_stop` 做健康检查和资源清理。
3. 工具层：注册 memory、knowledge、skill 等 OpenClaw agent tools，统一通过 BiBLE Atlas HTTP API 执行。
4. 运行时与 CLI：提供 `openclaw bible setup/status`，管理插件配置、远程服务连接和槽位启用状态。

相关细节见：

- [自动召回设计](./02-auto-recall.md)
- [自动捕获、归档与记忆抽取](./03-capture-archive-compact.md)
- [工具层与运行时 CLI](./04-tools-and-cli.md)
- [工程编译、部署与开发计划](./05-implementation-plan.md)

## 依赖策略

基线版本为 `openclaw-2026.5.18`。插件遵循“运行时耦合 + 编译时解耦”：

- 运行时耦合：依赖宿主 OpenClaw 注入 `registerContextEngine`、`registerTool`、`on`、`registerCli`、`logger`、`config` 等能力。
- 编译时解耦：插件源码不从 `3rd/openclaw/plugin-sdk` 导入运行时类型；只在本地定义 `OpenClawPluginApi` 鸭子类型和最小 context-engine 类型。
- 契约防漂移：`package.json` 声明 `engines.openclaw >= 2026.5.18`，`openclaw.plugin.json` 声明 `kind`、`contracts`、`setup`、`configSchema`。
- 参考源码而不绑定源码：允许参考 `3rd/openclaw/plugin-sdk` 和 `docs/3rd/openclaw/plugins` 的公开契约，但不把 OpenClaw 内部路径作为插件构建依赖。

## 运行时拓扑

```text
OpenClaw host
  |
  | loads native plugin
  v
bible-oc-plugin
  |-- registerContextEngine("bible-oc-plugin", factory)
  |-- on("session_start" | "session_end" | "before_reset", handler)
  |-- registerTool(memory / knowledge / skill tools)
  |-- registerCli(openclaw bible setup/status)
  |
  v
BiBLE Atlas HTTP service
  |-- /health
  |-- /api/search/memory
  |-- /api/search/skill
  |-- /api/search/knowledge-base
  |-- /api/import/memory
  |-- /api/import/skill
  |-- /api/control/admin/tasks/{id}
```

插件只以远程模式工作。本地纯安装只检查构建产物、manifest 和 plugin entry；执行 `openclaw bible setup --write` 启用插件前必须有可访问的 HTTP 服务。本插件不内嵌 server、不管理 Python 服务进程、不持有索引存储。

## 插件目录与命名决策

统一使用 `bible-oc-plugin` 作为仓库目录名、npm package name、OpenClaw plugin id 和文档称呼。不要再引入下划线目录别名，避免目录、包名和插件 id 出现双命名。

```text
bible-oc-plugin/
  package.json
  openclaw.plugin.json
  tsconfig.json
  src/
    index.ts                 # 插件 runtime entry，本地定义 OpenClawPluginApi
    types/openclaw.ts        # 鸭子类型与 context-engine 最小类型
    config/schema.ts         # configSchema 对应的运行时解析和默认值
    config/types.ts          # 插件配置类型
    http/client.ts           # BiBLE Atlas 低层 HTTP client
    http/endpoints.ts        # BiBLE Atlas endpoint 常量
    http/errors.ts           # HTTP / server 错误映射
    runtime/bible-runtime.ts # 共享业务门面
    context/engine.ts        # assemble / afterTurn / compact
    context/recall.ts        # 查询预处理、并行检索、重排、注入预算
    context/capture.ts       # turn buffer、commit、summary、extract
    hooks/session.ts         # session_start/session_end/before_reset
    tools/register.ts        # 工具注册入口
    tools/memory.ts
    tools/knowledge.ts
    tools/skill.ts
    cli/register.ts          # openclaw bible setup/status
    cli/setup.ts
    cli/status.ts
    install/manual.ts        # 本地手动安装辅助脚本逻辑，可选
  scripts/
    install-local.mjs
```

## `index.ts` 注册草案

```typescript
import { createBibleContextEngine } from "./context/engine";
import { registerBibleCli } from "./cli/register";
import { resolveBibleConfig } from "./config/schema";
import { registerBibleSessionHooks } from "./hooks/session";
import { createBibleRuntime } from "./runtime/bible-runtime";
import { registerBibleTools } from "./tools/register";
import type { OpenClawPluginApi } from "./types/openclaw";

export default {
  id: "bible-oc-plugin",
  name: "BiBLE Atlas OpenClaw Plugin",
  description: "OpenClaw context-engine, lifecycle, tools, and CLI integration for BiBLE Atlas.",
  register(api: OpenClawPluginApi) {
    const config = resolveBibleConfig(api.config);
    const runtime = createBibleRuntime({ config, logger: api.logger });
    const captureStore = new SessionCaptureStore({ config, runtime, logger: api.logger });

    api.registerContextEngine(config.contextEngineId, () =>
      createBibleContextEngine({ config, runtime, logger: api.logger, captureStore }),
    );
    registerBibleSessionHooks(api, { config, runtime, logger: api.logger, captureStore });
    registerBibleTools(api, { config, runtime });
    registerBibleCli(api, { config, runtime, openclawConfig: api.config });
  },
};
```

## 运行时门面

采纳早先设计中的 `runtime/bible-runtime.ts`。低层 `http/client.ts` 只负责 HTTP 传输、endpoint、timeout、JSON envelope 和错误映射；`runtime/bible-runtime.ts` 是 Context Engine、tools、CLI、hooks 共享的业务门面。

`BibleRuntime` 负责：

- `probeHealth()` / `status()`：setup/status 和启动诊断使用。
- `searchMemory()`、`searchKnowledge()`、`searchSkill()`：自动召回和 agent tools 共享。
- `commitSessionMemory()`：`afterTurn`、`compact`、`before_reset` 共享的归档入口。
- `saveMemory()` / `getMemory()`：手动工具能力。
- `getTask()` / `pollTask()`：异步任务状态。
- 统一错误码、重试、timeout、warnings、bounded result trimming。

Context Engine、tools、CLI 不直接拼 HTTP endpoint；所有业务语义都通过 `BibleRuntime` 进入，避免三处重复处理认证、任务轮询和错误映射。

## 本地鸭子类型边界

`src/types/openclaw.ts` 只保留插件实际使用的字段。任何新增宿主能力都必须先进入此文件，避免在业务代码里散落隐式依赖。

```typescript
export interface OpenClawPluginApi {
  id?: string;
  config?: unknown;
  logger?: PluginLogger;
  registerContextEngine(id: string, factory: ContextEngineFactory): void;
  registerTool(tool: OpenClawTool, opts?: { optional?: boolean }): void;
  registerCli?(registrar: CliRegistrar, opts?: CliRegistrationOptions): void;
  on?(event: OpenClawHookName, handler: HookHandler, opts?: HookOptions): void;
  registerHook?(events: OpenClawHookName | OpenClawHookName[], handler: HookHandler, opts?: HookOptions): void;
}

export type OpenClawHookName =
  | "session_start"
  | "session_end"
  | "before_reset"
  | "gateway_start"
  | "gateway_stop";
```

`api.on` 是首选；若宿主只提供 `registerHook`，插件可在入口处做一次轻量兼容封装。不要引入 OpenClaw 内部 `plugins/types.js` 或 `context-engine/types.js`。

## Context Engine 最小类型

OpenClaw 2026.5.22 会校验 Context Engine factory 的返回对象。插件本地类型必须覆盖当前宿主必需 contract，同时保持编译时不依赖 OpenClaw 内部源码。

```typescript
export interface ContextEngine {
  readonly info: {
    id: string;
    name: string;
    version?: string;
  };
  ingest(input: { sessionId: string; sessionKey?: string; message: OpenClawMessage }): Promise<{ ingested: boolean }>;
  assemble(input: AssembleInput): Promise<{
    messages: OpenClawMessage[];
    estimatedTokens: number;
    systemPromptAddition?: string;
  }>;
  afterTurn?(input: AfterTurnInput): Promise<void>;
  compact(input: CompactInput): Promise<CompactResult>;
}

export type ContextEngineFactory = (ctx: ContextEngineFactoryContext) => ContextEngine | Promise<ContextEngine>;
```

输入字段只使用稳定语义：`sessionKey`、`sessionId`、`messages`、`prompt`、`availableTools`、`citationsMode`、`tokenBudget`。召回注入通过 `systemPromptAddition` 返回，避免把 `<relevant-memories>` 写入永久会话消息。如果宿主字段缺失，插件应降级到不注入或只使用当前用户消息，而不是猜测内部结构。

## `package.json` 契约

```json
{
  "name": "bible-oc-plugin",
  "version": "0.1.0",
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "engines": {
    "node": ">=20",
    "openclaw": ">=2026.5.18"
  },
  "openclaw": {
    "extensions": ["./src/index.ts"],
    "runtimeExtensions": ["./dist/index.js"],
    "setupEntry": "./src/setup-entry.ts",
    "runtimeSetupEntry": "./dist/setup-entry.js",
    "compat": {
      "pluginApi": ">=2026.5.18",
      "minGatewayVersion": "2026.5.18"
    },
    "build": {
      "openclawVersion": "2026.5.18",
      "pluginSdkVersion": "2026.5.18"
    },
    "install": {
      "localPath": ".",
      "defaultChoice": "local",
      "minHostVersion": ">=2026.5.18"
    }
  }
}
```

初期只支持本地手动安装。`runtimeExtensions` 和 `runtimeSetupEntry` 为后续打包安装保留，避免发布后依赖宿主 TypeScript 编译。

## `openclaw.plugin.json` 契约

```json
{
  "id": "bible-oc-plugin",
  "name": "BiBLE Atlas",
  "description": "Remote BiBLE Atlas context engine, lifecycle capture, tools, and CLI integration.",
  "version": "0.1.0",
  "kind": "context-engine",
  "activation": {
    "onStartup": false,
    "onConfigPaths": ["plugins.entries.bible-oc-plugin"],
    "onCapabilities": ["tool", "hook"]
  },
  "contracts": {
    "tools": [
      "bible_memory_search",
      "bible_memory_save",
      "bible_memory_get",
      "bible_knowledge_search",
      "bible_knowledge_list",
      "bible_skill_search",
      "bible_skill_get"
    ]
  },
  "toolMetadata": {
    "bible_memory_search": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_memory_save": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_memory_get": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_knowledge_search": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_knowledge_list": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_skill_search": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    },
    "bible_skill_get": {
      "configSignals": [
        {
          "rootPath": "plugins.entries.bible-oc-plugin.config",
          "required": ["baseUrl"]
        }
      ]
    }
  },
  "setup": {
    "requiresRuntime": false,
    "providers": [
      {
        "id": "bible-oc-plugin",
        "label": "BiBLE Atlas HTTP Service",
        "envVars": ["BIBLE_ATLAS_BASE_URL", "BIBLE_CLI_BASE_URL"],
        "authMethods": ["none", "bearer-token"]
      }
    ]
  },
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": [],
    "properties": {
      "baseUrl": { "type": "string", "description": "BiBLE Atlas HTTP base URL" },
      "token": { "type": "string", "description": "Optional bearer token" },
      "timeoutMs": { "type": "integer", "minimum": 1000, "default": 30000 },
      "contextEngineId": { "type": "string", "default": "bible-oc-plugin" },
      "enableMemoryRecall": { "type": "boolean", "default": true },
      "enableSkillRecall": { "type": "boolean", "default": false },
      "enableKnowledgeRecall": { "type": "boolean", "default": false },
      "knowledgeTags": { "type": "array", "items": { "type": "string" }, "default": [] },
      "recallTopK": { "type": "integer", "minimum": 1, "maximum": 50, "default": 8 },
      "recallMinScore": { "type": "number", "minimum": 0, "maximum": 1, "default": 0.35 },
      "injectionTokenBudget": { "type": "integer", "minimum": 128, "default": 1200 },
      "captureEnabled": { "type": "boolean", "default": true },
      "captureCommitThresholdTurns": { "type": "integer", "minimum": 1, "default": 8 },
      "captureCommitThresholdChars": { "type": "integer", "minimum": 1000, "default": 16000 },
      "bypassSessionPatterns": { "type": "array", "items": { "type": "string" }, "default": [] }
    }
  }
}
```

`contracts.tools` 必须与运行时 `registerTool` 名称一致。首版只声明实际注册的 core tools；ops 和 heavy/optional tools 在实现并默认启用或显式注册后再加入 manifest。`toolMetadata` 只声明 cheap config availability signals，帮助 OpenClaw 在不加载 runtime 的情况下判断工具是否可能可用。`activation` 是 planner metadata，不注册运行时行为；实际行为仍由 `index.ts` 注册。`kind: "context-engine"` 用于 `plugins.slots.contextEngine` 选择；插件是否真正启用由 OpenClaw 配置决定。

## OpenClaw 配置示例

```json
{
  "plugins": {
    "entries": {
      "bible-oc-plugin": {
        "enabled": true,
        "config": {
          "baseUrl": "http://127.0.0.1:5555",
          "timeoutMs": 30000,
          "enableMemoryRecall": true,
          "enableSkillRecall": false,
          "enableKnowledgeRecall": false,
          "bypassSessionPatterns": ["^agent:debug:", "^scratch:"]
        }
      }
    },
    "slots": {
      "contextEngine": "bible-oc-plugin"
    }
  }
}
```

## 旁路策略

`bypassSessionPatterns` 是插件自身策略，优先于召回和捕获：

- 命中 session：`assemble` 返回空增量，不检索、不注入。
- 命中 session：`afterTurn` 不写入 buffer，不触发 commit。
- 命中 session：`compact` 不向 BiBLE Atlas 提交内容，但仍返回宿主可接受的最小压缩结果。
- Hook 层只记录 bounded diagnostic，不把消息内容写入日志。

正则编译失败应在 `setup/status` 或插件启动阶段报错，避免运行中静默失效。
