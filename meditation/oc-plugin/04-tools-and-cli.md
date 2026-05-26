# 工具层与运行时 CLI

本文定义 `bible-oc-plugin` 的 OpenClaw tool 注册、HTTP 封装和 `openclaw bible setup/status`。总体契约见 [总体架构与插件契约](./01-architecture-and-contracts.md)，工程计划见 [工程编译、部署与开发计划](./05-implementation-plan.md)。

## 原则

- 工具层对 OpenClaw agent 暴露稳定 tool name 和 JSON 参数。
- 工具执行不 shell 调用 `bible_cli_go`，而是复用同一套 HTTP client 直连 BiBLE Atlas Server。
- `bible_cli_go` 是当前 CLI 行为和端点映射的重要参考，插件工具应与其语义对齐。
- 新增 BiBLE Atlas 能力时，先补 HTTP client 方法，再补 OpenClaw tool，再同步 `contracts.tools`。
- 所有 tool 输出都保持 bounded，避免把完整大文档或超长 memory 原文直接送回模型。

## 工具命名与范围分层

所有 OpenClaw agent tool 统一使用 `bible_*` 前缀，不使用 `memory.search` 这类点号命名。这样更适合 OpenClaw 全局 tool namespace，也更容易与 `openclaw.plugin.json#contracts.tools` 做静态一致性校验。

首版只承诺 core tools；ops 和 heavy tools 作为后续扩展。`contracts.tools` 只声明当前实际注册的工具，不提前声明尚未实现或默认关闭的工具。

### Core Tools

首版必选，覆盖检索、查看和保存等低风险能力：

| Tool name | 领域 | 说明 |
|---|---|---|
| `bible_memory_search` | memory | 检索会话记忆 |
| `bible_memory_save` | memory | 保存一段结构化会话/摘要为 memory |
| `bible_memory_get` | memory | 获取指定 memory 的摘要或详情 |
| `bible_knowledge_search` | knowledge | 按 tag 检索知识库 |
| `bible_knowledge_list` | knowledge | 列出知识库/tag |
| `bible_skill_search` | skill | 检索技能 |
| `bible_skill_get` | skill | 获取技能详情或内容 |

### Ops Tools

运维/诊断能力，建议 v1.1 引入，也可以只在 `openclaw bible status` 内部使用，不一定暴露给 agent：

| Tool name | 领域 | 说明 |
|---|---|---|
| `bible_task_status` | task | 查询异步任务状态 |
| `bible_system_health` | system | 检查 BiBLE Atlas `/health` |
| `bible_system_status` | system | 查询服务状态 |

### Heavy / Optional Tools

上传、批量上传、下载等重操作默认不进入首版 core。后续启用时应作为 optional tools，并考虑权限、确认、体积限制和超时：

| Tool name | 领域 | 说明 |
|---|---|---|
| `bible_memory_upload` | memory | 上传本地 memory 目录或文件 |
| `bible_memory_upload_all` | memory | 批量上传 memory，适合维护/迁移 |
| `bible_skill_upload` | skill | 上传技能包 |
| `bible_skill_download` | skill | 下载技能包 |

早先设计中的 `memory.commit` 语义不作为独立 agent tool 暴露：普通手动保存使用 `bible_memory_save`，Context Engine 内部归档使用 `commitSessionMemory` runtime 方法，避免 agent tool 和生命周期 commit 混淆。

## Tool 参数草案

### `bible_memory_search`

```typescript
{
  query: string;
  topK?: number;
  searchType?: "text" | "vector" | "hybrid";
  minScore?: number;
}
```

返回：

```typescript
{
  hits: Array<{
    memoryId: string;
    title?: string;
    abstract?: string;
    preview?: string;
    score?: number;
    matchScope?: string;
  }>;
  warnings?: string[];
}
```

### `bible_knowledge_search`

```typescript
{
  query: string;
  tag: string;
  topK?: number;
  searchType?: "text" | "vector" | "hybrid";
}
```

`tag` 必填，与 `bible_cli_go` v4 对齐。

### `bible_skill_search`

```typescript
{
  query: string;
  topK?: number;
  searchType?: "text" | "vector" | "hybrid";
}
```

### `bible_memory_save`

```typescript
{
  title?: string;
  messages: Array<{ role: "user" | "assistant" | "tool"; content: string }>;
  kbIndex?: string;
  metadata?: Record<string, unknown>;
  wait?: boolean;
}
```

`wait` 为 `true` 时轮询任务完成；否则返回 task id。

## HTTP client 封装

统一封装：

```typescript
class BibleAtlasClient {
  health(): Promise<HealthResult>;
  systemStatus(): Promise<Record<string, unknown>>;
  searchMemory(req: MemorySearchRequest): Promise<MemorySearchResponse>;
  saveMemory(req: MemorySaveRequest): Promise<MemorySaveResponse>;
  getMemory(req: MemoryGetRequest): Promise<MemoryGetResponse>;
  searchKnowledge(req: KnowledgeSearchRequest): Promise<KnowledgeSearchResponse>;
  listKnowledge(): Promise<KnowledgeListResponse>;
  searchSkill(req: SkillSearchRequest): Promise<SkillSearchResponse>;
  getSkill(req: SkillGetRequest): Promise<SkillGetResponse>;
  uploadSkill(req: SkillUploadRequest): Promise<TaskAcceptedResponse>;
  getTask(taskId: string): Promise<TaskStatusResponse>;
  pollTask(taskId: string, opts: PollOptions): Promise<TaskStatusResponse>;
}
```

HTTP 层负责：

- baseUrl join 和路径规范化。
- Bearer token。
- timeout 和 abort。
- JSON envelope 解包。
- server 错误到 tool 错误的映射。
- 对可恢复失败返回 structured warning。

## 与 `bible_cli_go` 对齐

当前 `bible_cli_go` 已定义的关键端点：

| 能力 | HTTP |
|---|---|
| health | `GET /health` |
| system status | `GET /api/v1/system/status`，fallback `/health` |
| memory import | `POST /api/import/memory` |
| skill import | `POST /api/import/skill` |
| memory search | `POST /api/search/memory` |
| skill search | `POST /api/search/skill` |
| knowledge search | `POST /api/search/knowledge-base` |
| knowledge list | `GET /api/control/docs/list`，fallback `/api/v1/knowledge/list` |
| skill download | `POST /api/download/skill/file` |
| task status | `GET /api/control/admin/tasks/{id}` |

插件工具不必继承 CLI 的 stdout envelope；tool 返回应采用 OpenClaw tool result 结构。但字段语义和错误码应与 CLI 对齐，避免 agent 在 CLI 和插件工具之间遇到两套行为。

## 输出策略

Tool 输出分两层：

- `content`：模型可见的短文本摘要，适合直接阅读。
- `details`：结构化 JSON，供 UI、日志或后续工具链使用。

示例：

```typescript
return {
  content: "Found 5 BiBLE memory hits. Top hit: OpenClaw context engine integration (score 0.82).",
  details: {
    hits,
    warnings,
  },
};
```

不要只把关键信息放入 `details`，因为 OpenClaw 可能在模型回放或压缩时剥离 details。

## `openclaw bible setup`

目标：

- 检查远程 BiBLE Atlas HTTP 服务是否可访问。
- 验证 token、timeout、knowledgeTags、bypassSessionPatterns 等配置。
- 写入或提示写入 OpenClaw 插件配置。
- 设置 `plugins.slots.contextEngine = "bible-oc-plugin"`。
- 不启动 BiBLE Atlas 服务，不负责本地插件文件安装。

命令草案：

```bash
openclaw bible setup \
  --base-url http://127.0.0.1:5555 \
  --token-env BIBLE_CLI_TOKEN \
  --enable-memory-recall \
  --enable-skill-recall=false \
  --knowledge-tag design \
  --bypass-session '^scratch:' \
  --write
```

行为：

1. 读取现有 OpenClaw config。
2. 合并命令行参数和环境变量。
3. 调用 `/health`。
4. 校验配置 schema 和 regex。
5. dry-run 展示将写入的 config diff。
6. `--write` 时写入插件配置和 `contextEngine` slot。

`setup` 与 `scripts/install-local.mjs` 职责分离：安装脚本只做本地安装/链接和 manifest 检查；`setup --write` 才做远程服务连通性校验、运行时配置写入和 slot 启用。无服务时可以完成纯安装，但必须阻断 setup 写入。

## `openclaw bible status`

目标：

- 展示插件是否安装、启用、是否占用 `contextEngine` 槽位。
- 展示远程服务健康状态和版本信息。
- 展示工具契约是否与 manifest 对齐。
- 展示召回、捕获、bypass 配置。

输出草案：

```text
BiBLE Atlas plugin
  installed: yes
  enabled: yes
  contextEngine slot: bible-oc-plugin
  baseUrl: http://127.0.0.1:5555
  health: ok
  memory recall: enabled
  skill recall: disabled
  knowledge recall: disabled
  capture: enabled
  tools: 7 registered / 7 declared
```

加 `--json` 时输出结构化 JSON，便于脚本和 CI 使用。

## CLI 注册方式

使用 OpenClaw `registerCli`：

```typescript
api.registerCli?.(
  async ({ program }) => {
    registerBibleCommands(program, { config, clientFactory });
  },
  {
    descriptors: [
      {
        name: "bible",
        description: "Configure and inspect BiBLE Atlas integration",
        hasSubcommands: true,
      },
    ],
  },
);
```

`setup/status` 是 OpenClaw 插件运行时 CLI，不替代 `bible_cli_go`。用户仍可直接使用 `bible` CLI 管理 BiBLE Atlas 数据；OpenClaw CLI 只管理 OpenClaw 插件集成状态。

## 开发期日志

状态：resolved。

插件运行时统一使用 `[bible-oc-plugin]` 前缀输出结构化日志。开发阶段建议同时打开：

```bash
openclaw logs --follow
```

已覆盖的动作边界：

- plugin 注册：`plugin.register start/done`
- CLI：`cli.register`、`cli.setup`、`cli.status`
- runtime HTTP：`runtime.probeHealth`、`runtime.searchMemory`、`runtime.searchSkill`、`runtime.searchKnowledge`、`runtime.commitSessionMemory` 等
- Context Engine：`context.assemble`、`context.afterTurn`、`context.compact`
- recall：`recall.pipeline`、`recall.searchDomain`
- capture：`capture.startSession`、`capture.captureTurn`、`capture.flush`、`capture.endSession`
- hooks：`hook.session_start`、`hook.before_reset`、`hook.session_end`
- tools：`tool.execute`

日志策略：

- `info`：动作 start/done、耗时、工具名、domain、sessionKey、命中数量、是否注入。
- `warn`：可恢复问题，例如单域 recall 失败、tool 返回 error result、bounded flush warning。
- `error`：动作失败，包含 `name/message/stack/code/statusCode/serverErrorCode` 等错误元数据。
- 不记录完整 prompt、query、token、Authorization、API key；只记录长度、数量和状态。

## 错误映射

建议错误码：

| 场景 | Tool/CLI 错误码 |
|---|---|
| baseUrl 缺失 | `BIBLE_CONFIG_MISSING` |
| health 失败 | `BIBLE_SERVICE_UNAVAILABLE` |
| 认证失败 | `BIBLE_AUTH_FAILED` |
| 请求参数错误 | `BIBLE_INVALID_ARGS` |
| 服务端 422 | `BIBLE_CONTRACT_MISMATCH` |
| 任务超时 | `BIBLE_TASK_TIMEOUT` |
| 未实现能力 | `BIBLE_NOT_IMPLEMENTED` |

服务端原始错误码可放在 `details.serverErrorCode`。

## 验证要点

- `contracts.tools` 与实际注册工具名一致。
- 每个工具都有参数校验和输出大小限制。
- HTTP client 使用 mock server 测试 2xx、4xx、5xx、timeout。
- `setup --write` 前必须先 health check。
- `status --json` 可被 CI 稳定解析。
- `registerCli` 描述符覆盖 `bible` 根命令，支持 lazy help。
