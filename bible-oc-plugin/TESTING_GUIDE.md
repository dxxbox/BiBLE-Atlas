# BiBLE Atlas OpenClaw Plugin 测试指南

本文用于指导同事在全新的 OpenClaw 环境中安装、启用并验证 `bible-oc-plugin`。所有命令默认在仓库根目录或 `bible-oc-plugin/` 下执行。

## 1. 前置条件

1. OpenClaw `>= 2026.5.22`。最低兼容基线仍是 `2026.5.18`，但当前 ContextEngine contract 已按 `2026.5.22` 验证。
2. Node.js `>=20`。
3. BiBLE Atlas HTTP 服务已启动，示例地址为 `http://127.0.0.1:5555`。
4. OpenClaw 已完成基础初始化，配置文件通常为 `~/.openclaw/openclaw.json`。

先确认基础环境：

```bash
openclaw --version
openclaw config validate
curl -i http://127.0.0.1:5555/health
```

`/health` 应返回 2xx 和可解析 JSON。若服务地址不同，后续命令替换 `--base-url`。

## 2. 构建与本地测试

```bash
cd bible-oc-plugin
npm install
npm run typecheck
npm test
npm run build
```

确认以下文件存在：

```bash
test -f dist/index.js
test -f dist/context/engine.js
test -f openclaw.plugin.json
```

## 3. 安装到全新 OpenClaw

推荐使用 OpenClaw 官方插件安装命令，而不是手工复制文件：

```bash
openclaw plugins install . --force
```

预期输出包含：

```text
Installed plugin: bible-oc-plugin
Restart the gateway to load plugins.
```

然后确认 OpenClaw 能发现插件和 CLI surface：

```bash
openclaw plugins inspect bible-oc-plugin
openclaw bible --help
```

`openclaw bible --help` 应显示 `setup` 和 `status` 子命令。如果提示 unknown command，先运行：

```bash
openclaw plugins list
openclaw config validate
```

## 4. 启用插件

先 dry-run，确认 health check 和将写入的配置：

```bash
openclaw bible setup --base-url http://127.0.0.1:5555
```

确认返回 `ok: true` 后写入：

```bash
openclaw bible setup --base-url http://127.0.0.1:5555 --write
```

写入后检查配置：

```bash
openclaw config validate
openclaw bible status
openclaw bible status --json
```

重点确认：

- `enabled: yes`
- `contextEngine slot: bible-oc-plugin`
- `baseUrl: http://127.0.0.1:5555`
- `health: ok`
- `tools: 7 registered / 7 declared`

当前默认 `contextEngineId` 必须是 `bible-oc-plugin`，不是 `bible-atlas`。

## 5. 重启 Gateway

安装或重新安装插件后必须重启 OpenClaw Gateway，否则正在运行的进程可能继续持有旧模块。

常用方式：

```bash
openclaw gateway restart
```

如果当前版本没有 `gateway restart`，使用已有运维方式停止并重新启动 gateway，例如：

```bash
openclaw gateway stop
openclaw gateway run
```

重启后再次执行：

```bash
openclaw bible status
```

## 6. 日志验证

开发阶段建议打开一个独立终端跟踪日志：

```bash
openclaw logs --follow
```

执行 `openclaw bible status` 时，应看到类似日志：

```text
[plugins] [bible-oc-plugin] plugin.register start
[plugins] [bible-oc-plugin] runtime.probeHealth start
[plugins] [bible-oc-plugin] runtime.probeHealth done
[plugins] [bible-oc-plugin] cli.status done
```

一次普通会话应能看到：

```text
[bible-oc-plugin] context.assemble start
[bible-oc-plugin] recall.pipeline start
[bible-oc-plugin] runtime.searchMemory start
[bible-oc-plugin] context.afterTurn done
```

`warn` / `error` 日志应包含结构化错误字段，例如 `code`、`statusCode`、`serverErrorCode`、`message`、`stack`。

## 7. ContextEngine Contract 验证

如果日志出现 `invalid ContextEngine`，说明安装副本或 gateway 仍在使用旧构建。可用以下 smoke check 验证安装副本：

```bash
node --input-type=module -e "const plugin=(await import(process.env.HOME+'/.openclaw/extensions/bible-oc-plugin/dist/index.js')).default; let factory; const api={config:{baseUrl:'http://127.0.0.1:5555',contextEngineId:'bible-oc-plugin'},logger:{info(){},warn(){},error(){}},registerCli(){},registerTool(){},on(){},registerContextEngine(id,f){console.log('id='+id); factory=f;}}; plugin.register(api); const engine=await factory({}); console.log(JSON.stringify({info:engine.info, ingest:typeof engine.ingest, assemble:typeof engine.assemble, compact:typeof engine.compact}));"
```

预期：

```json
{"info":{"id":"bible-oc-plugin","name":"BiBLE Atlas","version":"0.1.0"},"ingest":"function","assemble":"function","compact":"function"}
```

## 8. 功能验证

1. 在 OpenClaw 中开启普通会话，发送一条与已保存 memory 相关的问题。
2. 在日志中确认触发 `context.assemble`、`recall.pipeline`、`runtime.searchMemory`。
3. 若服务端已有可检索 memory，回复前模型上下文应通过 `systemPromptAddition` 包含 `<relevant-memories>`。
4. 调用 core tools，确认 tool execute 日志和返回结构：
   - `bible_memory_search`
   - `bible_memory_save`
   - `bible_memory_get`
   - `bible_knowledge_search`
   - `bible_knowledge_list`
   - `bible_skill_search`
   - `bible_skill_get`
5. 如配置 `bypassSessionPatterns`，创建命中 pattern 的 session，确认不会触发 recall HTTP 请求。

## 9. 已知限制：Session Memory Commit

当前 BiBLE Atlas 服务端如果尚未部署 session memory import/commit 能力，插件在 `captureEnabled=true` 且达到阈值时会尝试归档会话，日志可能出现：

```text
BIBLE_NOT_FOUND BiBLE session commit failed
BiBLE threshold commit failed
```

这表示自动写回 memory 失败，不影响 recall/search/tools。开发阶段可临时关闭 capture 避免日志噪音：

```bash
openclaw config set plugins.entries.bible-oc-plugin.config.captureEnabled false
openclaw config validate
```

服务端补齐 `/api/import/memory` multipart import 或专用 session commit JSON API 后，再打开：

```bash
openclaw config set plugins.entries.bible-oc-plugin.config.captureEnabled true
```

## 10. 常见问题

- `openclaw bible` unknown command：确认已执行 `openclaw plugins install . --force`，并重启 gateway；再检查 `openclaw plugins inspect bible-oc-plugin`。
- `setup --write` 失败：先检查 `baseUrl`、token 和 `/health`。
- `status` 显示 slot 不正确：检查 `plugins.slots.contextEngine`，应为 `bible-oc-plugin`。
- `invalid ContextEngine: missing info, missing ingest()`：说明运行的是旧 dist，重新 `npm run build && openclaw plugins install . --force` 并重启 gateway。
- 没有召回内容：确认已有可检索 memory，`enableMemoryRecall=true`，且 score 未低于 `recallMinScore`。
- 工具数量不一致：检查 `openclaw.plugin.json#contracts.tools` 是否与 `CORE_TOOL_NAMES` 对齐。
- `plugins.allow` provenance warning：这是 OpenClaw 对非 bundled 插件的信任提示。若要在受控环境收敛插件集合，需谨慎设置完整 `plugins.allow`，避免误禁用其他插件。
