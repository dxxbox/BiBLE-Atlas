# Mock bible CLI

开发期"对外依赖隔离层"。实现 `bible_vscode` 所需的 CLI 命令集子集，行为见 `backlog/memory-closure-collab-plan-zh.md §5`。

## 使用

```bash
chmod +x mock-cli/bible
# VSCode 设置：
#   "bible.cliPath": "<abs>/bible_vscode/mock-cli/bible"
#   "bible.debug.dryRun": false   # ← 用 mock-cli 时必须关掉 dry-run
```

## 命令覆盖

| 命令 | 行为 |
|---|---|
| `bible health` | `{cli:"mock", version:"0.0.0-mock", server:{reachable:true, url:"mock://localhost"}}` |
| `bible memory search` | 按 profile 生成 N 条 MemoryHit（默认 3 条，可改条数 / 模板 / 长 abstract / 分数） |
| `bible memory import --source-file --meta-file` | 立即返 `task_id`；session_id 从 meta.json 解析（保持 source/meta 关联） |
| `bible memory download file` / `batch` | 立即返 `task_id`；profile.task.completeAt 决定第几次 poll 进入 completed |
| `bible memory artifact fetch --id --out` | 默认写小 JSON；profile.artifact.fixtureFile 设置后改为复制真文件 |
| `bible task get --id` | 用 `/tmp/bible-mock-tasks.json` 推进状态机 |
| `bible task cancel --id` | 置为 `cancelled` |

## Mock Profile（推荐：可编辑、保存即生效）

mock-cli 每次启动重新读 profile 文件，**改完保存下次 CLI 调用就生效，不需要 reload IDE 窗口**。

路径（按优先级）：
1. `BIBLE_MOCK_PROFILE` 环境变量
2. `~/.bible-mock.json`

最快打开方式：VSCode 命令面板 → **Bible: Open Mock Profile (debug)**（不存在则提示创建带注释的模板）

完整 schema：

```jsonc
{
  // 全局错误注入：覆盖 search/import/artifact/task 默认成功路径
  // 可选：not_implemented / slow / task_failed / index_conflict / artifact_expired
  //       index_not_bound / vector_model_conflict / download_limit / file_not_found
  // 环境变量 BIBLE_MOCK_INJECT 优先级更高
  "inject": null,

  // memory search 行为
  "search": {
    "count": 3,                                  // 返回结果数；0 = 空结果
    "abstractTemplate": "Discussion about {query} (#{i})", // 支持 {query} {i} {sessionId}
    "longAbstract": false,                       // true: abstract 重复 longAbstractRepeat 次（看截断/长文本 UI）
    "longAbstractRepeat": 12,
    "errorIfQueryContains": "error",             // query 含此子串 → INTERNAL 错误
    "scoreStart": 0.92,                          // 第 1 条分数
    "scoreStep": 0.08,                           // 每条递减
    "sessionIdPrefix": "mock-session",
    "hitField": "abstract",
    "sessionKind": "mixed"
  },

  // 异步任务状态机
  "task": {
    "completeAt": 3,    // 第 N 次 task get 进入 completed（默认 3 → 约 6s，配合 pollIntervalMs=2000）
    "failAt": null      // 第 N 次 task get 失败（覆盖 completeAt）；null 不失败
  },

  // artifact fetch
  "artifact": {
    "fixtureFile": null,        // 指向真实文件路径；fetch 时复制到 --out（用于看下载下来的真文件）
    "contentType": "application/json"
  }
}
```

## 常用验证剧本

### 看 search 空结果（验空态 UI）

```jsonc
{ "search": { "count": 0 } }
```

### 看长文本截断 / 滚动

```jsonc
{ "search": { "count": 2, "longAbstract": true, "longAbstractRepeat": 30 } }
```

### 看 10 条命中的列表渲染

```jsonc
{ "search": { "count": 10, "scoreStart": 0.99, "scoreStep": 0.05 } }
```

### 验下载的真文件（end-to-end 看到能打开真内容）

1. 准备一个真 chat 导出文件 `/tmp/real-source.json`
2. profile：
   ```jsonc
   { "artifact": { "fixtureFile": "/tmp/real-source.json", "contentType": "application/json" } }
   ```
3. 在 VSCode 跑 `Bible: Download Memory File` → artifact 完成后插件会把文件下到本地，打开就是真内容

### 验"Search 自动下载 + 缓存命中"（推荐链路）

插件 v0.0.2+ 引入了 `ensureLocalSource` 缓存：第一次 search Load 触发下载，第二次同条目 0 网络。

1. profile：
   ```jsonc
   { "search": { "count": 3 }, "artifact": { "fixtureFile": "/tmp/real-source.json" } }
   ```
2. `Bible: Search Memory` → 输词 → 选第一条 → **Load to @bible-memory** → 看到通知 "Downloaded source: ${ws}/.bible/memory/mock-session-001.json"
3. **再做一次** `Bible: Search Memory` → 选同一条 → 注意 Quick Pick 标题里 `(cached)` 标记 → 选 Load → 通知不再出现 "Downloaded"，直接进 chat，**没有触发 task 状态机**
4. OutputChannel `Bible` 里能看到对应事件：
   - 第一次：`memory.source.cacheMiss.startDownload` → `memory.source.downloaded`
   - 第二次：`memory.source.cacheHit`
5. 验缓存清理：`rm ${ws}/.bible/memory/mock-session-001.json` → 再 Load 即触发重新下载

### 验"任务卡很久"的进度 UI

```jsonc
{ "task": { "completeAt": 30 } }   // 30 次轮询 ≈ 60s
```

或用环境变量（向后兼容）：`export BIBLE_MOCK_INJECT=slow` 再重启 IDE。

### 验业务错误码降级

```jsonc
{ "inject": "index_conflict" }      // import 立刻 → INDEX_BINDING_CONFLICT
{ "inject": "artifact_expired" }    // artifact fetch → DOWNLOAD_ARTIFACT_EXPIRED
{ "inject": "task_failed" }         // task 第 3 次 poll 时 failed
```

## 状态文件

`/tmp/bible-mock-tasks.json` 记录所有 task 状态与"已轮询次数"。需要重置（让一个旧 task_id 重新走流程）时手动删除：`rm /tmp/bible-mock-tasks.json`

## 环境变量（向后兼容）

```bash
export BIBLE_MOCK_INJECT=index_conflict     # 等同于 profile.inject，优先级更高
export BIBLE_MOCK_PROFILE=/path/to/file     # 覆盖默认 ~/.bible-mock.json
```
