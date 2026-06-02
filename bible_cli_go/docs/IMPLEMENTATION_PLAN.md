# bible_cli_go v4 对齐实现计划

> 当前状态（2026-05-20）：本文原始 Step 1-4 已完成，并在后续补齐了 `knowledge import`、`memory download` 单文件/批量下载、通用 `task get/status/cancel`、`memory list`/`skills list` 参数透传与相关测试。下方原计划保留为历史背景；继续开发应以本节和 `STATUS_AND_ROADMAP.md` 为准。

## 0. 当前完成状态

### 0.1 已对齐 / 已实现

| 能力 | 状态 |
|---|---|
| `Search()` hit helpers 复用 v4 `SkillSearch()` / `MemorySearch()` | ✅ 已完成 |
| `KnowledgeSearch()` 迁移到 `POST /api/search/knowledge-base` | ✅ 已完成 |
| `knowledge search --tag` | ✅ 已完成 |
| 顶层 `search --knowledge-tag` | ✅ 已完成 |
| `KnowledgeList()` 优先 `/api/control/docs/list`，404 fallback `/api/v1/knowledge/list` | ✅ 已完成 |
| `memory get/save` 与 `session` deprecated 兼容 | ✅ 已完成 |
| `knowledge import` | ✅ 已完成，`POST /api/import/knowledge-base` |
| `memory download` 单文件 | ✅ 已完成，`POST /api/download/memory/file` |
| `memory download` 批量 | ✅ 已完成，`POST /api/download/memory/batch` |
| `skills download` 批量 | ✅ 已完成，`POST /api/download/skill/batch` |
| `task get/status/cancel` | ✅ 已完成，`GET/DELETE /api/control/admin/tasks/{id}` |
| `memory list --page/--tag/--since` 请求体透传 | ✅ 已完成 |
| `skills list --page/--tag` 请求体透传 | ✅ 已完成 |

### 0.2 当前剩余事项

| 项目 | 说明 |
|---|---|
| 真实 Atlas E2E 冒烟 | 需要实际服务端 + Worker，覆盖 import → task → search → download |
| `Download by-search` | v4 文档标注为未来演进，当前不属于既定完成范围 |
| `memory upload --output table` | 与统一 JSON 输出契约冲突，建议暂不实现，除非后续设计明确交互输出模式 |

### 0.3 当前验证命令

```bash
go test ./...
go vet ./...
go build ./...
```

完整构建可执行：

```bash
./build.sh
```

## 1. 当前状态分析

### 1.1 已对齐 v4 的端点

| 方法 | 端点 | 状态 |
|---|---|---|
| `ImportMemory()` | `POST /api/import/memory` | ✅ v4 |
| `ImportSkill()` | `POST /api/import/skill` | ✅ v4 |
| `MemorySearch()` | `POST /api/search/memory` | ✅ v4 |
| `SkillSearch()` | `POST /api/search/skill` | ✅ v4 |
| `GetTask()` / `PollTask()` | `GET /api/control/admin/tasks/{id}` | ✅ v4 |
| `DownloadFile()` | `POST /api/download/{domain}/file` | ✅ v4 |
| `GetArtifact()` | `GET /api/download/{domain}/artifact/{id}` | ✅ v4 |

### 1.2 仍使用 v3 端点（待迁移）

| 方法 | 当前端点 (v3) | 目标端点 (v4) | 影响范围 |
|---|---|---|---|
| `searchSkill()` private | `POST /api/v1/skills/search` | 复用 `SkillSearch()` (v4) | `Search()` hit 路径 |
| `searchMemory()` private | `POST /api/v1/memory/search` | 复用 `MemorySearch()` (v4) | `Search()` hit 路径 |
| `KnowledgeSearch()` | `GET /api/v1/knowledge/search?query=X` | `POST /api/search/knowledge-base` (JSON body) | `bible search`, `bible knowledge search` |
| `KnowledgeList()` | `GET /api/v1/knowledge/list` | `GET /api/control/docs/list` + fallback | `bible knowledge list` |
| `Status()` | `GET /api/v1/system/status` + fallback `/health` | 保持现状（v4 未定义 control/admin/status 路径） | `bible system status` |
| `Info()` | `GET /api/v1/system/info` + fallback `/health` | 保持现状 | `bible system info` |

### 1.3 CLI 命令缺口（vs v4 设计）

| CLI 命令 | 问题 | 修复方案 |
|---|---|---|
| `bible knowledge search [query]` | 无 `--tag` 参数，v4 API 要求 `tag` 必填 | 增加 `--tag` flag（必填） |
| `bible search --query X` | `--knowledge-tag` 缺失；直接调 `KnowledgeSearch` 无 tag | 增加可选 `--knowledge-tag`；无 tag 时跳过 knowledge 段 |
| `bible session list/get/save` | v4 将 SESSION 更名为 MEMORY；`session` 命令语义需同步 | 在 `memory` 子命令下增加 `list/get/save` 别名；保留 `session` 并标记 deprecated |

---

## 2. 实现步骤

### Step 1 — 修复 `Search()` hit helpers（风险：低）

**目标**：删除 `searchSkill()` / `searchMemory()` 两个私有方法，在 `Search()` 内直接调用已对齐 v4 的公有方法。

**变更文件**：
- `internal/client/http/client.go`
- `internal/client/http/client_test.go`

**具体改动**：

1. `client.go` — `Search()` 函数内：
   ```
   c.searchSkill(options.Query, options.TopK)
   → c.SkillSearch(SkillSearchRequest{Query: options.Query, TopK: options.TopK, SearchType: "text"})

   c.searchMemory(options.Query, options.TopK)
   → c.MemorySearch(MemorySearchRequest{Query: options.Query, TopK: options.TopK, SearchType: "text"})
   ```

2. `client.go` — 删除 `searchSkill()` 和 `searchMemory()` 两个私有方法。

3. `client_test.go` — 将以下测试中的 mock 路径从 v3 改为 v4：
   - `TestSearchIncludesSkillAndMemoryHitsWhenEnabled`
   - `TestSearchHitRequestsRunConcurrently`
   - `TestSearchHitFailureDoesNotBreakMainKnowledgeResult`

   路径映射：
   - `/api/v1/skills/search` → `/api/search/skill`
   - `/api/v1/memory/search` → `/api/search/memory`

   注：`/api/v1/knowledge/search` 在这几个测试里也出现，Step 2 后再统一改。

**验证**：`cargo test`（无；Go 用 `go test`）
```bash
cd bible_cli_go && go test ./internal/client/http/... -v -run TestSearch
```

---

### Step 2 — 迁移 `KnowledgeSearch()` 到 v4 POST 端点 + 补充 `--tag`（风险：中）

**目标**：
- 将 `KnowledgeSearch(query string)` 改为 `KnowledgeSearch(req KnowledgeSearchRequest)`
- 端点从 `GET /api/v1/knowledge/search?query=X` 改为 `POST /api/search/knowledge-base`
- CLI `knowledge search` 增加 `--tag`（必填）
- CLI `bible search` 增加 `--knowledge-tag`（可选，空则跳过 knowledge 结果段）

**新增类型**（`internal/client/http/memory.go` 或新文件）：
```go
// KnowledgeSearchRequest holds parameters for KnowledgeSearch.
type KnowledgeSearchRequest struct {
    Query      string
    Tag        string
    TopK       int
    SearchType string
}
```

**变更文件**：
- `internal/client/http/client.go`（`KnowledgeSearch` 方法 + `Search` 调用处）
- `internal/client/http/memory.go`（添加 `KnowledgeSearchRequest` 结构体）
- `internal/commands/handlers.go`（`handleKnowledge` 接收 tag）
- `internal/cli/run.go`（`knowledge search` 解析 `--tag`；`search` 解析 `--knowledge-tag`）
- `internal/client/http/client_test.go`（更新 knowledge search 相关测试路径 + 方法）
- `internal/cli/run_test.go`（`TestRunKnowledgeSearch*` 系列补充 `--tag`）

**CLI 行为变化**：
```
# 旧：
bible knowledge search faith

# 新（tag 必填）：
bible knowledge search --tag design faith

# 旧 bible search（包含 knowledge 段）：
bible search --query faith

# 新（不含 knowledge tag 时，knowledge 段缺席）：
bible search --query faith                          # knowledge 段 absent
bible search --query faith --knowledge-tag design   # 包含 knowledge 段
```

**`Search()` 逻辑变化**：
```go
// SearchOptions 中增加：
KnowledgeTag string  // "" = skip knowledge search

// Search() 中：
if options.KnowledgeTag != "" {
    knowledgePayload, err = c.KnowledgeSearch(KnowledgeSearchRequest{
        Query: options.Query,
        Tag:   options.KnowledgeTag,
        TopK:  options.TopK,
    })
    // ... 加入 result["knowledge"]
}
```

**验证**：
```bash
go test ./internal/client/http/... -v -run TestKnowledge
go test ./internal/cli/... -v -run TestRunKnowledge
go test ./...
```

---

### Step 3 — 迁移 `KnowledgeList()` 到 v4（风险：低）

**目标**：
将 `GET /api/v1/knowledge/list` 迁移为 `GET /api/control/docs/list`，采用与 `Status()` 相同的 fallback 模式（v4 路径失败时回落 v3）。

**变更文件**：
- `internal/client/http/client.go`（`KnowledgeList` 方法）
- `internal/client/http/client_test.go`（`TestErrorEnvelopeMapsToCLIError`、`TestErrorEnvelopeFor501`、`TestHTTPTransportTimeout` 中的路径更新）

**改动**：
```go
func (c *Client) KnowledgeList() (map[string]any, error) {
    return c.getEnvelopeOrPlain("/api/control/docs/list", "/api/v1/knowledge/list")
}
```

**验证**：
```bash
go test ./internal/client/http/... -v -run TestKnowledgeList
go test ./...
```

---

### Step 4 — `session` → `memory` 别名 + help 更新（风险：低）

**目标**：
v4 将 `SESSION` 类型统一为 `MEMORY`，CLI 中 `session list/get/save` 需要在 `memory` 子命令下同样可访问，原 `session` 路径保留（不删除）以免破坏现有用法。

**具体方案**：
- `memory` 命令增加 `list`、`get`、`save` 三个 action，路由到 `SessionExecute`（或直接在 `MemoryExecute` 中新增 case 复用 session 逻辑）
- 当 `memory save` 时用 `MemoryImportRequest` 发 `POST /api/import/memory`（已有实现），保持与 `session save` 行为一致
- `session` 的 `list`/`get` 两个 action 仍调用 `POST /api/search/memory`（已 v4）
- 更新 `printHelp()` 中 `session` 行加注 `(deprecated, use memory)`，并新增 `memory list/get/save` 说明

**变更文件**：
- `internal/commands/memory.go`（在 `MemoryExecute` 中增加 `list`/`get`/`save` case，委托到已有 session 逻辑）
- `internal/cli/memory_flags.go`（增加 `list`/`get`/`save` 的 flag 解析分支，复用 session flag 解析函数）
- `internal/cli/run.go`（`printHelp` 更新）

**验证**：
```bash
go test ./internal/commands/... -v
go test ./internal/cli/... -v
go test ./...
```

---

## 3. 验证矩阵

每步完成后执行：
```bash
cd /var/fpwork/w77wang/BiBLE/BiBLE-Atlas/bible_cli_go
go build ./...            # 编译检查
go test ./...             # 全量测试
go vet ./...              # 静态检查
```

完整回归（全部步骤完成后）：
```bash
go test ./... -race       # 并发安全
go test ./... -count=3    # 稳定性
```

---

## 4. 不在本次范围内

- `Status()` / `Info()` 的 v4 迁移：v4 文档未定义 control 路径，现有 fallback 机制已足够
- `KNOWLEDGE_BASE` 导入 CLI 命令（`bible knowledge import`）：当前无此命令，v4 服务端已有 `POST /api/import/knowledge-base`，CLI 侧留作后续
- Download `by-search` 异步导出：v4 文档标注为"未来演进"
