# Mock bible CLI

开发期"对外依赖隔离层"。实现 `bible_vscode` 所需的 CLI 命令集子集，行为见 `backlog/memory-closure-collab-plan-zh.md §5`。

## 使用

```bash
chmod +x mock-cli/bible
# VSCode 设置：
#   "bible.cliPath": "<abs>/bible_vscode/mock-cli/bible"
```

## 命令覆盖

| 命令 | 行为 |
|---|---|
| `bible health` | 直接返回 `{cli:"mock", version:"0.0.0-mock"}` |
| `bible memory search` | 返回 3 条固定 MemoryHit；`--query` 含 `error` → `INTERNAL` |
| `bible memory import --source-file --meta-file` | 立即返 `task_id`；session_id 从 meta.json 解析（保持 source/meta 关联） |
| `bible memory download file` / `batch` | 立即返 `task_id`，3 轮后 `completed` 带 artifact_id |
| `bible memory artifact fetch --id --out` | 写一个小 JSON 到 `--out`，返回 path/size_bytes/content_type |
| `bible task get --id` | 内存外用 `/tmp/bible-mock-tasks.json` 推进状态机 |
| `bible task cancel --id` | 置为 `cancelled` |

## 错误注入

```bash
export BIBLE_MOCK_INJECT=index_conflict     # import → INDEX_BINDING_CONFLICT
export BIBLE_MOCK_INJECT=artifact_expired   # artifact fetch → DOWNLOAD_ARTIFACT_EXPIRED
export BIBLE_MOCK_INJECT=task_failed        # task 第 3 次 get 时变 failed
export BIBLE_MOCK_INJECT=slow               # task 第 10 次 get 才 completed
export BIBLE_MOCK_INJECT=not_implemented    # 任意命令 exit=3 + CLI_NOT_IMPLEMENTED
```

## 状态文件

`/tmp/bible-mock-tasks.json` 记录所有 task 的当前状态与"轮询次数"。需要重置时手动删除。
