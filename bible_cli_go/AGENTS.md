# bible-cli-go — AI Agent 指南

## 项目概览

`bible-cli-go` 是 BiBLE Atlas 系统的 **Go CLI 客户端**，通过 HTTP 与 FastAPI 服务端（v4 API）通信。

- **语言**：Go 1.20+
- **模块名**：`bible-cli-go`（见 `go.mod`）
- **入口**：`cmd/bible-cli/main.go`
- **对应服务端设计**：`docs/designs/server_part/v4/`

---

## 目录布局（必须了解）

```
cmd/bible-cli/main.go          ← 唯一二进制入口，只调用 cli.Run
internal/
  cli/
    run.go                     ← 命令路由 + flag 解析（主要改动入口）
    run_test.go                ← CLI 集成测试（含 httptest server）
    memory_flags.go            ← memory 子命令 flag 解析
    memory_test.go
    skills_flags.go
    session_flags.go
  commands/
    handlers.go                ← health / system / knowledge dispatch
    memory.go                  ← memory 全部业务逻辑（upload/list/search 等）
    skills.go                  ← skills 全部业务逻辑
    session.go                 ← session 业务逻辑（get/save/list）
  client/http/
    client.go                  ← HTTP 基础设施 + Search/KnowledgeSearch/KnowledgeList
    client_test.go             ← HTTP 客户端单元测试
    memory.go                  ← 所有请求结构体 + Import/Search/Download/Task 方法
  config/
    loader.go                  ← LoadResolvedConfig()（首选，合并 env + 文件 + 默认值）
    model.go                   ← 所有配置结构体（MemoryConfig 等）
  cache/
    memory_cache.go            ← 本地幂等缓存（.bible-memory-cache.json）
  meta/
    builder.go                 ← 从 message.json 自动生成 meta.json
  protocol/
    error.go                   ← CLIError 类型、NotImplemented、WrapAsCLIError
    output.go                  ← PrintSuccess / PrintFailure（统一 JSON 信封）
testdata/golden/               ← golden 期望文件，run_test.go 中加载
docs/                          ← 内部设计文档（实现计划等）
```

---

## 构建与测试命令

```bash
# 编译
go build ./...
go build -o ./target/bible ./cmd/bible-cli/

# 全量测试（必须在每次改动后执行）
go test ./...

# 推荐：带竞态检测
go test ./... -race

# 单个测试
go test ./internal/cli/... -v -run TestRunHealth
go test ./internal/client/http/... -v -run TestKnowledgeSearch

# 静态检查
go vet ./...
```

**注意**：所有测试完全自包含，使用 `httptest.NewServer` 模拟服务端，不需要启动任何外部服务。

---

## 关键约定（必须遵守）

### 添加新命令的模式

1. **`internal/cli/run.go`** — 在 `switch command` 中加 case，解析 flag，填充 opts 结构体
2. **`internal/cli/*_flags.go`** — 如果 flag 较多，单独放到对应 flags 文件
3. **`internal/commands/*.go`** — 在对应 `*Execute` 方法的 switch 中加 action case
4. **`internal/client/http/`** — 新增 HTTP 方法（在 `client.go` 或 `memory.go`）
5. **`printHelp()`** — 更新帮助文本
6. **`normalizeActionAlias()`** — 注册别名（在 `run.go` 底部）

### 输出格式规则（不可破坏）

- 所有成功输出：`{"ok":true,"data":{...}}`
- 所有失败输出：`{"ok":false,"error":{"code":"...","message":"..."}}`
- 使用 `protocol.PrintSuccess(stdout, payload)` 和 `protocol.PrintFailure(stdout, code, msg)`
- 永远不要直接 `fmt.Println` 到 stdout

### 错误处理规则

- 使用 `protocol.CLIError{Code: "...", Message: "...", ExitCode: N}` 返回错误
- 退出码：0 成功，1 错误，3 命令未实现
- 使用 `protocol.NotImplemented("command action")` 表示未实现
- 使用 `protocol.WrapAsCLIError(err)` 包装普通 error

### HTTP 客户端规则

- GET + JSON 信封响应：用 `c.getEnvelope(path)`
- GET + 带 fallback：用 `c.getEnvelopeOrPlain(primaryPath, fallbackPath)`（注意：fallback 也用 `c.getEnvelope`，而不是 `c.getJSON`，否则会丢失 result 解包）
- POST + JSON 信封响应：用 `c.postEnvelope(path, body)`
- 异步任务轮询：用 `c.PollTask(taskID, interval, timeout)`

### 请求结构体放置位置

所有 HTTP 请求/响应结构体（`XxxRequest`、`XxxImportRequest`）定义在 `internal/client/http/memory.go`，不在 `client.go`。

### 配置读取规则

- 始终用 `config.LoadResolvedConfig().ClientConfig`（在 `run.go` 中调用一次）
- `kb_index` 解析顺序：`--kb-index flag` → `BIBLE_MEMORY_KB_INDEX` env → `config.Memory.Upload.KbIndex`
- 不要在 commands 层自行读取环境变量，用 `resolveKbIndex(flag, cfg)` 工具函数

---

## v4 API 端点（当前已对齐）

| 操作 | 方法 | 路径 |
|---|---|---|
| memory 导入 | POST multipart | `/api/import/memory` |
| skill 导入 | POST multipart | `/api/import/skill` |
| memory 检索 | POST JSON | `/api/search/memory` |
| skill 检索 | POST JSON | `/api/search/skill` |
| knowledge-base 检索 | POST JSON | `/api/search/knowledge-base` |
| knowledge 列表 | GET | `/api/control/docs/list` (fallback: `/api/v1/knowledge/list`) |
| skill 下载 | POST JSON | `/api/download/skill/file` |
| 任务状态查询 | GET | `/api/control/admin/tasks/{id}` |
| health | GET | `/health` |
| system status | GET | `/api/v1/system/status` (fallback: `/health`) |

**尚未迁移（保持现状）**：`/api/v1/system/status`、`/api/v1/system/info` — v4 文档未定义 control 路径，fallback 机制已足够。

---

## 测试编写规范

### 单元测试（client 层）

```go
func TestXxx(t *testing.T) {
    server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
        if r.URL.Path != "/api/..." {
            w.WriteHeader(nethttp.StatusNotFound)
            return
        }
        _ = json.NewEncoder(w).Encode(map[string]any{
            "status": "ok",
            "result": map[string]any{"key": "value"},
        })
    }))
    defer server.Close()

    client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
    payload, err := client.XxxMethod(...)
    // assertions
}
```

### 集成测试（cli 层）

```go
func TestRunXxx(t *testing.T) {
    server := httptest.NewServer(...)
    defer server.Close()
    t.Setenv("BIBLE_CLI_BASE_URL", server.URL)  // 必须用 t.Setenv

    var out, errBuf bytes.Buffer
    exitCode := Run([]string{"command", "action", "--flag", "value"}, &out, &errBuf)
    if exitCode != 0 {
        t.Fatalf("expected exit 0, got %d", exitCode)
    }

    var response struct {
        OK   bool           `json:"ok"`
        Data map[string]any `json:"data"`
    }
    _ = json.Unmarshal(out.Bytes(), &response)
    // assertions on response.Data
}
```

### 必须覆盖的场景

每个新命令至少需要测试：
1. 成功路径（正常响应）
2. 缺少必填参数（退出码 1，`INVALID_ARGS`）
3. 服务端 404（确认 fallback 或正确报错）
4. 服务端 5xx（确认错误传播）

---

## 常见修改场景

### 新增一个 memory 子命令

1. `memory.go` 的 `MemoryCommandOptions` 加字段
2. `memory.go` 的 `MemoryExecute` switch 加 case
3. `memory_flags.go` 的 `parseMemoryFlags` switch 加 case，写 `parseXxxFlags` 函数
4. `run.go` 的 `normalizeActionAlias["memory"]` 注册别名
5. `run.go` 的 `printHelp` 添加说明行
6. `client/http/memory.go` 添加对应 HTTP 方法（如需要新端点）
7. 写测试

### 修改 HTTP 端点路径

1. 修改 `client/http/client.go` 或 `memory.go` 中对应方法
2. 同步更新 `client_test.go` 中的 mock 路径（`case "/old/path"` → `case "/new/path"`）
3. 同步更新 `cli/run_test.go` 中的 mock 路径（如有）

### 新增请求结构体字段

- 请求/响应结构体在 `client/http/memory.go`
- 修改后同步更新调用方（`commands/*.go`）和测试

---

## 禁止事项

- 不要在 stdout 上 `fmt.Print` 非 JSON 内容（破坏机器解析）
- 不要在 commands 层直接操作 HTTP（全部通过 `client` 层）
- 不要在 client 层读取配置文件（全部通过参数传入）
- 不要新增全局变量
- 不要在测试中使用真实服务器地址
- `getEnvelopeOrPlain` fallback 路径不要用 `getJSON`，要用 `getEnvelope`（否则 v3 envelope 格式响应会因未解包而丢失数据）

---

## 已知技术债

| 项目 | 文件 | 说明 |
|---|---|---|
| `session` 命令 | `run.go` | deprecated，别名路由到 memory get/save，保留向后兼容 |
| `system status/info` | `client.go` | 仍用 v3 路径（`/api/v1/system/...`），v4 文档未定义替代路径 |
| knowledge list | `client.go` | 双路径 fallback，v4 路径为 `/api/control/docs/list` |
