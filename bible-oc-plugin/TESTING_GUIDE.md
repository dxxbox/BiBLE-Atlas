# BiBLE Atlas OpenClaw Plugin 测试指南

本文用于指导测试人员在真实 OpenClaw 环境中安装并验证 `bible-oc-plugin`。

## 前置条件

1. 已安装 OpenClaw `>= 2026.5.18`。
2. 本机 Node.js `>=20`。
3. BiBLE Atlas HTTP 服务已启动，并可访问 `GET /health`。
4. 已知 OpenClaw 配置文件路径，例如 `~/.openclaw/config.json`。

## 构建插件

```bash
cd bible-oc-plugin
npm install
npm run build
npm test
```

确认 `dist/index.js` 和 `openclaw.plugin.json` 存在。

## 本地安装

先执行 dry-run，确认将写入的 plugin entry：

```bash
node scripts/install-local.mjs --openclaw-config ~/.openclaw/config.json
```

确认输出无误后写入：

```bash
node scripts/install-local.mjs --openclaw-config ~/.openclaw/config.json --write
```

该步骤只安装插件入口，不启用 `contextEngine` slot，也不要求 BiBLE Atlas 服务可用。

## 启用插件

确认 BiBLE Atlas 服务健康：

```bash
curl http://127.0.0.1:5555/health
```

然后通过 OpenClaw CLI 写入插件运行时配置并启用 slot：

```bash
openclaw bible setup --base-url http://127.0.0.1:5555 --write
```

如果服务不可访问，`setup --write` 应失败，且不应写入启用配置。

## 状态检查

```bash
openclaw bible status
openclaw bible status --json
```

重点确认：

- `enabled: yes`
- `contextEngine slot: bible-oc-plugin`
- `health: ok`
- `memory recall: enabled`
- `skill recall: disabled`
- `knowledge recall: disabled`
- `tools: 7 registered / 7 declared`

## 功能验证

1. 在 OpenClaw 中开启一个普通会话，发送一条与已保存 memory 相关的问题。
2. 确认回复前触发 memory-only 自动召回，模型上下文中应包含 `<relevant-memories>`。
3. 创建命中 `bypassSessionPatterns` 的会话，确认不会访问 BiBLE Atlas，也不会注入记忆。
4. 连续对话超过配置阈值后，确认 `afterTurn` 会触发异步 memory commit。
5. 执行 reset 或结束会话，确认 `before_reset` / `session_end` 会进行 bounded flush。
6. 调用 core tools：`bible_memory_search`、`bible_memory_save`、`bible_memory_get`、`bible_knowledge_search`、`bible_knowledge_list`、`bible_skill_search`、`bible_skill_get`。

## 常见问题

- `setup --write` 失败：先检查 `baseUrl`、token 和 `/health`。
- `status` 显示 slot 未启用：检查 OpenClaw 配置中的 `plugins.slots.contextEngine`。
- 工具数量不一致：检查 `openclaw.plugin.json#contracts.tools` 是否与运行时注册一致。
- 没有召回内容：确认已有可检索 memory，且 score 未低于 `recallMinScore`。
- bypass 会话仍有提交：检查 `bypassSessionPatterns` 正则是否正确编译并匹配 session key。
