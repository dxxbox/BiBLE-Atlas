# 自动捕获、归档与记忆抽取

本文定义 `bible-oc-plugin` 如何把 OpenClaw 会话生命周期同步到 BiBLE Atlas。自动召回见 [自动召回设计](./02-auto-recall.md)，工具与 CLI 见 [工具层与运行时 CLI](./04-tools-and-cli.md)。

## 目标

插件需要在不阻塞常规回复的前提下，把有价值的 OpenClaw 会话沉淀为 BiBLE Atlas memory：

- `afterTurn`：增量捕获 turn，写入本地内存 buffer，达到阈值后异步 commit。
- `compact`：同步提交当前未归档内容，生成会话摘要，并把压缩结果返回给 OpenClaw。
- `before_reset`：reset 前触发一次同步或 bounded commit，降低会话丢失风险。
- `session_start` / `session_end`：管理 session 生命周期、打开/关闭归档记录。

## 状态模型

每个 OpenClaw session 维护一个轻量状态：

```typescript
interface BibleSessionState {
  sessionKey: string;
  sessionId?: string;
  startedAt: string;
  lastTurnAt?: string;
  turnCount: number;
  bufferedChars: number;
  pendingTurns: CapturedTurn[];
  lastCommitId?: string;
  lastMemoryId?: string;
  commitInFlight?: Promise<void>;
  bypassed: boolean;
}
```

状态只作为插件运行时缓存。权威持久化在 BiBLE Atlas Server；OpenClaw 重启后可从 session hooks 重新开始捕获，不要求恢复未提交内存 buffer。

## 捕获内容

`afterTurn` 捕获最小必要结构：

```typescript
interface CapturedTurn {
  turnId?: string;
  runId?: string;
  timestamp: string;
  userMessage?: string;
  assistantMessage?: string;
  toolCalls?: CapturedToolCall[];
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
  };
}
```

约束：

- 不保存大型 `toolResult.details`；只保存模型可见的 bounded content 或摘要。
- 默认不保存二进制附件内容，只保存引用和元数据。
- 对敏感内容的过滤策略应与 OpenClaw host policy 对齐；插件不绕过宿主安全策略。
- 命中 `bypassSessionPatterns` 时不捕获消息内容。

## `afterTurn` 增量路径

流程：

```text
afterTurn(input, ctx)
  |
  |-- resolve sessionKey
  |-- bypass check
  |-- normalize user/assistant/tool summary
  |-- append pendingTurns
  |-- update turnCount/bufferedChars
  |-- if threshold reached:
  |     |-- start async commit if no commitInFlight
  |
  v
return quickly
```

阈值：

- `captureCommitThresholdTurns`：默认 8 turn。
- `captureCommitThresholdChars`：默认 16000 chars。
- `session_end`、`before_reset`、`compact` 强制 flush。

异步 commit 必须 bounded：

- 不阻塞当前 turn 完成。
- 同一 session 只允许一个 `commitInFlight`。
- commit 失败保留 buffer，并在下一次阈值或生命周期事件重试。
- 如果 buffer 超过 hard cap，可丢弃最旧低价值内容并记录 warning，避免内存无限增长。

## commit 请求

推荐把 commit 封装为插件内部 `commitSessionMemory`，底层调用 BiBLE Atlas memory ingest/save 能力。若服务端只支持 multipart import，则插件需要在内存中构造与 `bible_cli_go` 兼容的 `message.json` / `meta.json` 语义；若服务端已有 JSON save API，则优先用 JSON。

逻辑请求：

```typescript
interface CommitSessionMemoryRequest {
  sessionKey: string;
  sessionId?: string;
  reason: "threshold" | "compact" | "before_reset" | "session_end" | "manual";
  title: string;
  messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }>;
  metadata: {
    source: "openclaw";
    pluginId: "bible-oc-plugin";
    openclawVersion?: string;
    turnCount: number;
    startedAt?: string;
    endedAt?: string;
  };
}
```

落到当前 v4 API 时可映射到：

- `POST /api/import/memory`
- 或 `bible_cli_go` 已暴露的 `memory save` 等价 HTTP 封装
- 异步任务用 `GET /api/control/admin/tasks/{id}` 轮询

## 会话摘要

摘要有两类：

- Commit 摘要：给 BiBLE Atlas memory 的 `title`、`abstract`、`overview` 或 metadata。
- Compact 摘要：返回给 OpenClaw，用于压缩当前会话上下文。

初期建议让 BiBLE Atlas Server 负责长期 memory 摘要和抽取；插件只生成保守的会话标题和 commit metadata。`compact` 需要同步返回时，插件可以：

1. 提交 pending turns 到 server。
2. 请求 server 生成或返回摘要。
3. 如果 server 未返回摘要，插件用本地轻量摘要策略生成 fallback。

本地 fallback 只做结构化压缩，不做复杂事实抽取：

```text
Summary:
- User goals:
- Decisions:
- Open tasks:
- Important files/symbols:
- Tool outcomes:
```

## `compact` 同步路径

`compact` 是丢失风险最高的路径，必须同步 flush：

```text
compact(input, ctx)
  |
  |-- bypass check
  |-- collect pendingTurns + compact input messages
  |-- commitSessionMemory(reason = "compact")
  |-- obtain summary / fallback summary
  |-- clear committed pendingTurns
  |
  v
CompactResult
```

返回建议：

```typescript
interface CompactResult {
  summary: string;
  metadata?: {
    bibleMemoryId?: string;
    bibleTaskId?: string;
    committedTurns?: number;
    warnings?: string[];
  };
}
```

如果同步 commit 超时：

- 返回 fallback summary，保证 OpenClaw compaction 不失败。
- 保留 pending buffer，后续 `afterTurn` 或 `session_end` 重试。
- metadata 写入 warning。

## Hook 层语义

### `session_start`

用途：

- 初始化 `BibleSessionState`。
- 记录 startedAt 和 session reason。
- 执行 bypass 匹配并缓存结果。
- 可选做一次远程 health lazy check，但不应阻塞 session 创建。

### `session_end`

用途：

- 对未提交 buffer 做 bounded flush。
- reason 为 `shutdown` / `restart` 时遵守宿主 finalizer 时间预算，不能无限等待。
- commit 成功后清理 session state。

### `before_reset`

用途：

- 在 `/reset` 或程序化 reset 前提交当前 buffer。
- 优先同步 commit，设置较短 timeout。
- 如果 commit 失败，记录 warning；不可阻止 reset，除非后续产品明确要求强一致保护。

### `gateway_start` / `gateway_stop`

可选：

- `gateway_start`：检查 baseUrl、token、schema 版本，提前发现配置错误。
- `gateway_stop`：flush 所有 active sessions，遵守 bounded timeout。

## Hook Safety

Hook 层必须显式处理 priority、timeout 和错误隔离。早先设计把这点作为独立要求是合理的，因为 session lifecycle hook 处在宿主关键路径上，插件不能因为远程服务慢、commit 失败或内部异常而拖垮 OpenClaw 主流程。

### 注册策略

- 首选 `api.on(event, handler, { priority, timeoutMs })` 注册 typed hooks。
- 若宿主只提供 `registerHook`，入口处做一次兼容封装，但仍保留 priority/timeout 的语义。
- `session_start`、`session_end`、`before_reset` 都应声明明确 timeout，而不是依赖无限等待。
- priority 只用于和其他插件协调顺序，不应假设自己总是最后运行。

建议默认：

| Hook | Priority | Timeout | 说明 |
|---|---:|---:|---|
| `session_start` | 0 | 1000 ms | 初始化本地状态，不阻塞会话创建 |
| `before_reset` | 50 | 5000 ms | reset 前 bounded flush |
| `session_end` | 10 | 5000 ms | session 结束时 bounded flush |
| `gateway_stop` | 10 | 8000 ms | 可选，全局 bounded flush |

具体数值可通过插件配置覆盖，但必须设置上限，不能让用户配置成无限等待。

### 错误隔离

- Hook handler 内部捕获所有异常，转为 bounded warning/error log。
- commit 失败不阻断宿主 session lifecycle；失败内容保留在 buffer，等待下一次 lifecycle 或 compact 重试。
- `before_reset` 默认不可阻止 reset。只有未来产品明确要求强一致保护时，才允许增加“失败则阻断 reset”的配置开关。
- `session_end` 的 `shutdown` / `restart` reason 必须遵守宿主 finalizer budget；超时后停止等待并记录 warning。
- Hook 日志不得包含完整会话内容，只记录 sessionKey、reason、turn count、buffer size、task id、错误码等 bounded metadata。

### 去重与重复提交

- 每次 commit 记录 `reason`、turn range、pending buffer hash 和 task/memory id。
- `before_reset`、`session_end`、`compact` 可能连续触发，必须通过 commit range 或 pending buffer 状态避免重复提交。
- 如果已有 `commitInFlight`，后续 hook 不启动第二个并发 commit；可选择等待 bounded 时间或标记 pending flush。
- commit 成功后只清理已确认提交的 pending turns，不能清空新写入的 turn。

## 记忆抽取

长期记忆抽取应该优先放在 BiBLE Atlas Server：

- server 拥有索引、向量模型、chunking 和 memory schema。
- plugin 只提供结构化会话原料和触发原因。
- 提取策略升级不需要重新发布 OpenClaw 插件。

插件侧仅负责：

- 标准化 OpenClaw 会话消息。
- 标注 source、sessionKey、turn range、tool summary。
- 传递抽取 hints，例如 `importantFiles`、`symbols`、`decisions`。

## 与自动召回的闭环

捕获提交成功后，后续 turn 的 `assemble` 可检索到新 memory。但要避免当前 turn 重复召回：

- commit 返回的 `memoryId` 进入 short-lived exclusion set。
- `assemble` 在 N 分钟内或当前 session 内过滤刚由同一 pending buffer 生成的 memory。
- 如果服务端检索仍返回该 memory，插件按 `source.sessionKey === currentSessionKey` 和 `committedTurnRange` 做去重。

## 失败处理

- 远程服务不可用：保留 buffer，下一生命周期点重试。
- 401/403：停止 commit，status 提示认证错误。
- 422：说明插件构造的 memory payload 与 server 契约漂移，记录 error 并进入 degraded mode。
- 5xx/timeout：指数退避，保留 buffer。
- buffer hard cap：丢弃最旧内容，保留最近 turns 和 compact fallback summary。

## 验证要点

- `afterTurn` 在阈值以下只写 buffer，不调用 commit。
- 达到 turns/chars 阈值后异步 commit，且同 session 不并发提交。
- `compact` 必定尝试同步 commit，并在失败时返回 fallback summary。
- `before_reset` 会触发一次 flush。
- `session_end` 在 shutdown/restart reason 下 bounded flush。
- hook priority、timeout 和错误隔离有单元测试或 mock runtime 测试。
- `before_reset`、`session_end`、`compact` 连续触发时不会重复提交同一 turn range。
- bypass session 不捕获、不提交。
