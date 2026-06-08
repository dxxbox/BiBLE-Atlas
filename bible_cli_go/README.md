# bible-cli-go

Go 语言实现的 BiBLE Atlas CLI 客户端。通过 HTTP 与 BiBLE Atlas 服务端通信，支持知识库检索、记忆导入导出、技能管理等操作。

---

## 目录

- [需求与背景](#需求与背景)
- [架构](#架构)
- [目录结构](#目录结构)
- [命令参考](#命令参考)
- [配置](#配置)
- [构建与运行](#构建与运行)
- [测试](#测试)
- [API 端点映射（v4）](#api-端点映射v4)
- [输出格式](#输出格式)
- [错误码](#错误码)

---

## 需求与背景

BiBLE Atlas 服务端提供三类知识域的管理能力：

| 域 | 说明 |
|---|---|
| `KNOWLEDGE_BASE` | 结构化知识库（设计文档/算法/代码等），按 `tag` 分索引 |
| `SKILL` | 技能包（`.skill` 格式），供 AI Agent 调用 |
| `MEMORY` | 会话记忆，保存 AI 对话上下文 |

CLI 目标：
- 在终端/脚本/CI 中完整操作上述三域
- 支持异步任务提交（202 响应）+ 可选等待（`--wait`）
- 本地幂等性缓存（避免重复上传相同内容）
- 所有输出为结构化 JSON，便于脚本解析

---

## 架构

```
bible <command> <action> [flags]
         │
         ▼
  internal/cli/run.go          ← 参数解析、flag 分发
         │
         ▼
  internal/commands/           ← 业务逻辑层
    handlers.go                  health / system / knowledge
    memory.go                    memory 子命令
    skills.go                    skills 子命令
    session.go                   session 子命令（deprecated）
         │
         ▼
  internal/client/http/        ← HTTP 客户端层
    client.go                    Search / KnowledgeSearch / KnowledgeList
    memory.go                    ImportMemory / ImportSkill / MemorySearch /
                                  SkillSearch / DownloadFile / GetArtifact /
                                  GetTask / PollTask
         │
         ▼
  BiBLE Atlas Server（v4 API）
```

### 关键设计

**配置层级**（高优先级覆盖低优先级）：
```
env BIBLE_CLI_BASE_URL  >  ~/.bible/config.json  >  默认值 http://127.0.0.1:5555
```

**本地幂等缓存**：`memory upload` 完成后在 session 目录写入 `.bible-memory-cache.json`，记录 `meta_hash + kb_index + task_id`。下次使用 `--skip-if-exists`（默认开启）时跳过重复上传。

**异步任务模式**：所有 import/download 操作服务端立即返回 `202 + task_id`。CLI 默认异步（打印 task_id 即退出），加 `--wait` 则轮询 `GET /api/control/admin/tasks/{id}` 直到完成或超时。

**并发 hit-search**：`bible search --enable-hit` 会并发调用 skill 和 memory 检索，某个域失败不影响其他域结果，降级返回并附 `hit_warnings`。

---

## 目录结构

```
bible_cli_go/
  cmd/bible-cli/
    main.go              入口
  internal/
    cli/
      run.go             命令路由、flag 解析
      run_test.go        集成测试
      memory_flags.go    memory 子命令 flag 解析
      memory_test.go
      skills_flags.go    skills 子命令 flag 解析
      session_flags.go   session 子命令 flag 解析
    commands/
      handlers.go        health / system / knowledge dispatch
      memory.go          memory 业务逻辑
      skills.go          skills 业务逻辑
      session.go         session 业务逻辑
    client/http/
      client.go          核心 HTTP 方法 + Search / KnowledgeSearch / KnowledgeList
      client_test.go     HTTP 客户端单元测试
      memory.go          Import / Search / Download 方法 + 请求结构体定义
    config/
      config.go          FromEnv() 快速加载（legacy）
      loader.go          LoadResolvedConfig()（推荐，含文件 + env 合并）
      loader_test.go
      model.go           MemoryConfig / SkillConfig 结构体
    cache/
      memory_cache.go    .bible-memory-cache.json 读写 + SHA-256 计算
    meta/
      builder.go         从 message.json 生成 meta.json
    protocol/
      error.go           CLIError + NotImplemented + WrapAsCLIError
      output.go          统一 JSON 输出（PrintSuccess / PrintFailure）
  testdata/golden/       期望输出的 golden 文件
  docs/                  内部设计文档
```

---

## 命令参考

### 基础命令

```bash
bible health
bible system status
bible system info
```

### Knowledge 命令（v4，需 --tag）

```bash
# 列出知识库
bible knowledge list

# 检索知识库（--tag 必填，指定要查的知识索引分类）
bible knowledge search --tag design "周期调度"
bible knowledge search --tag flow "RLC AM 流程"

# 导入知识库文件（异步提交；--wait 等待任务完成）
bible knowledge import --file /path/to/design.md --kb-index my-kb --tag design
bible knowledge import --file a.md --file b.md --kb-index my-kb --tag flow --wait
```

### Memory 命令

```bash
# 单个导入（需 message.json 在 session 目录下）
bible memory upload /path/to/session_dir --kb-index my-kb

# 等待任务完成
bible memory upload /path/to/session_dir --kb-index my-kb --wait

# 批量导入（扫描 base_dir 下所有含 message.json 的子目录）
bible memory upload-all /path/to/base_dir --kb-index my-kb --workers 4

# 仅生成 meta.json，不上传
bible memory build-meta /path/to/session_dir

# 查询任务状态
bible memory status <task_id>
bible memory status --memory-id <memory_id>

# 列出记忆
bible memory list --limit 20 --tag my-tag

# 检索记忆
bible memory search "调度算法" --top-k 10
# 插件/IDE 联调：`--test` 不访问服务器，返回与真实检索相同字段结构的预设 JSON（见 internal/fixtures/memory_search_test.json）
bible memory search "任意查询" --top-k 10 --test
# 同上，`memory upload` / `memory download` / `memory import` 等子命令也接受 `--test`（与 Cursor/VS Code 扩展在 bible.cli.testMode 下追加的标志一致）

# 下载记忆产物（单文件）
bible memory download --output /tmp/ <memory_id>
bible memory download --storage-path /server/path/memory.zip --output /tmp/

# 批量下载记忆产物（生成 ZIP）
bible memory download --storage-path memory/a --storage-path memory/b --package-name memories.zip --include-metadata --output /tmp/

# 查看本地上传缓存状态
bible memory cache-status /path/to/base_dir

# (v4 别名) 获取指定记忆
bible memory get --id <memory_id>

# (v4 别名) 保存会话为记忆
bible memory save --input '{"title":"...","messages":[{"role":"user","content":"..."}]}' --kb-index my-kb
```

### Skills 命令

```bash
bible skills list --limit 20
bible skills search "L2PS 调度" --top-k 5
bible skills get <name_or_id> --content
bible skills upload --file /path/to/skill.skill --kb-index my-kb --wait
bible skills download <name_or_id> --output /tmp/
bible skills download --storage-path skill/a.skill --storage-path skill/b.skill --package-name skills.zip --output /tmp/
```

### Task 命令

```bash
bible task get <task_id>
bible task status <task_id>
bible task cancel <task_id>
```

### 聚合搜索

```bash
# 仅 knowledge（需 --knowledge-tag）
bible search --query "调度" --knowledge-tag design

# knowledge + skill + memory
bible search --query "调度" --knowledge-tag design --enable-hit --hit-types skill,memory

# 仅 skill + memory（不含 knowledge，省略 --knowledge-tag）
bible search --query "调度" --enable-hit
```

### Session 命令（deprecated，请改用 memory）

```bash
bible session list
bible session get --id <id>
bible session save --input '...' --kb-index my-kb
```

---

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BIBLE_CLI_BASE_URL` | 服务器地址（最高优先级） | — |
| `BIBLE_ATLAS_BASE_URL` | 服务器地址（备用） | — |
| `BIBLE_CLI_TOKEN` | Bearer Token | — |
| `BIBLE_CLI_TIMEOUT_SECONDS` | 请求超时（秒） | 30 |
| `BIBLE_MEMORY_KB_INDEX` | memory 上传默认 kb_index | — |
| `BIBLE_MEMORY_VECTOR_MODEL` | memory 上传默认向量模型 | — |
| `BIBLE_CLI_LEGACY_STDERR` | `1` 时把错误同时打到 stderr | — |
| `BIBLE_CLI_STUB_MODE` | `1` / `true` / `yes` 时 **不连服务器**，`memory search` / `import` / `list` 等返回与插件契约一致的伪造 JSON（联调扩展用） | — |
| `BIBLE_CLI_LOG_FILE` | 结构化 NDJSON 日志（默认 `~/.bible/cli.log`），不影响 stdout。`go test` 构建且未设置本变量时，默认写到 `$TMPDIR/bible-cli-go-test-<pid>.log`，避免污染用户目录下的 cli.log | — |
| `BIBLE_CLI_LOG_DISABLE` | 设为 `1` 时关闭写文件日志（仅 stdout 协议） | — |

**离线 / 无后端联调**：请使用扩展 **`bible.cli.testMode`**（向 CLI 追加 `--test`，`memory search` 走 fixtures、其它 memory 子命令走无 HTTP 的约定响应），或设置 **`BIBLE_CLI_STUB_MODE=1`**（全局 stub，响应中带 `stub: true`）。**未设置上述二者时，网络错误会直接失败**（`ok: false` / `UNAVAILABLE` 等），不再静默返回伪造成功数据。

### 配置文件

用户配置：`~/.bible/config.json`
系统配置：`/etc/bible/config.json`

```json
{
  "base_url": "http://your-server:5555",
  "token": "your-bearer-token",
  "timeout_seconds": 60,
  "memory": {
    "upload": {
      "kb_index": "default-kb",
      "vector_model": "bge-m3",
      "skip_if_exists": true,
      "workers": 4,
      "abstract_truncate": true
    },
    "download": {
      "poll_interval_seconds": 3,
      "poll_timeout_seconds": 300
    }
  }
}
```

---

## 构建与运行

```bash
cd bible_cli_go

# 编译
go build -o ./target/bible ./cmd/bible-cli/

# 直接运行（无需编译）
go run ./cmd/bible-cli/ health

# 指定服务器
export BIBLE_CLI_BASE_URL=http://your-server:5555
./target/bible health
```

---

## 测试

```bash
# 全量测试
go test ./...

# 详细输出
go test ./... -v

# 运行单个测试
go test ./internal/cli/... -v -run TestRunHealth

# 带竞态检测（推荐在 PR 前运行）
go test ./... -race

# 稳定性验证
go test ./... -race -count=3

# 仅编译检查
go build ./...

# 静态分析
go vet ./...
```

所有测试完全自包含，使用 `httptest.NewServer` 模拟服务端，无需启动真实服务。

### 插件和服务端未就绪时如何验证

当前应采用 contract-first 验证方式：先证明 CLI 的命令解析、JSON 输出契约、HTTP 请求形状、错误映射和异步流程正确，不等待 VSCode 插件和真实服务端全部完成。

推荐本地门禁：

```bash
go test ./...
go vet ./...
go build ./...
```

用 CLI 直接代替插件调试：

```bash
go build -o ./target/bible ./cmd/bible-cli/

./target/bible health
./target/bible knowledge import --file README.md --kb-index kb_test --tag design
./target/bible knowledge search --tag design "test"
./target/bible memory download --storage-path memory/a --storage-path memory/b --package-name memories.zip --output /tmp
./target/bible task get task-123
```

插件侧未来只应依赖 stdout JSON 与 exit code：

```json
{"ok":true,"data":{"task_id":"task-123","status":"queued"}}
{"ok":false,"error":{"code":"INVALID_ARGS","message":"--tag is required for knowledge search."}}
```

服务端未完成时，新增功能应使用 `httptest.NewServer` mock 服务端，并断言：

- HTTP method/path 正确。
- JSON body 或 multipart 字段正确。
- 失败响应映射到正确 `error.code`。
- import/download 的 submit -> task poll -> artifact download 流程能跑通。

服务端和 Worker ready 后，再跑真实 E2E 冒烟：

```bash
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555

./target/bible health
./target/bible knowledge import --file README.md --kb-index kb_test --tag design --wait
./target/bible knowledge search --tag design "test"
./target/bible memory upload /path/to/session --kb-index kb_test --wait
./target/bible memory search "test"
./target/bible skills upload --file /path/to/demo.skill --kb-index kb_test --wait
./target/bible task get <task_id>
```

如果 import/download 一直停在 `queued`，优先检查 Celery Worker 是否启动；不要在 CLI 中加入临时假逻辑绕过服务端。

### 本地 mock Atlas server

仓库内提供一个轻量测试服务器，便于在真实服务端和插件未完成时验证 CLI：

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go

# 终端 1：启动 mock server
go run ./cmd/bible-mock-server --addr 127.0.0.1:5555

# 终端 2：编译并指向 mock server
go build -o ./target/bible ./cmd/bible-cli/
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555

./target/bible health
./target/bible system status
./target/bible knowledge list
./target/bible knowledge import --file README.md --kb-index kb_test --tag design --wait
./target/bible knowledge search --tag design "test"
./target/bible search --query "test" --knowledge-tag design --enable-hit
./target/bible memory download --storage-path memory/a --storage-path memory/b --package-name memories.zip --output /tmp
./target/bible skills download --storage-path skill/a.skill --storage-path skill/b.skill --package-name skills.zip --output /tmp
./target/bible task get task-123
./target/bible task cancel task-123
```

mock server 覆盖：

- `/health`
- `/api/v1/system/status`、`/api/v1/system/info`
- `/api/control/docs/list`
- `/api/search/knowledge-base`、`/api/search/memory`、`/api/search/skill`
- `/api/import/knowledge-base`、`/api/import/memory`、`/api/import/skill`
- `/api/download/{memory|skill}/file`
- `/api/download/{memory|skill}/batch`
- `/api/download/{memory|skill}/artifact/{artifact_id}`
- `/api/control/admin/tasks/{task_id}` 的 `GET` / `DELETE`

注意：这个 server 只用于 CLI 契约调试，不验证真实解析、向量化、OpenSearch、Celery Worker 或文件存储行为。

---

## API 端点映射（v4）

| CLI 操作 | HTTP 方法 | 端点 |
|---|---|---|
| `memory upload` | POST multipart | `/api/import/memory` |
| `skills upload` | POST multipart | `/api/import/skill` |
| `knowledge import` | POST multipart | `/api/import/knowledge-base` |
| `memory search` / `memory get` | POST JSON | `/api/search/memory` |
| `skills search` / `skills get` | POST JSON | `/api/search/skill` |
| `knowledge search` | POST JSON | `/api/search/knowledge-base` |
| `knowledge list` | GET | `/api/control/docs/list` → fallback `/api/v1/knowledge/list` |
| `skills download` | POST JSON | `/api/download/skill/file` |
| `skills download` / `memory download` | POST JSON | `/api/download/{domain}/file` |
| `skills download` / `memory download` batch | POST JSON | `/api/download/{domain}/batch` |
| `skills download` / `memory download` artifact | GET | `/api/download/{domain}/artifact/{id}` |
| `memory status` / `task get` | GET | `/api/control/admin/tasks/{id}` |
| `task cancel` | DELETE | `/api/control/admin/tasks/{id}` |
| `system status` | GET | `/api/v1/system/status` → fallback `/health` |
| `health` | GET | `/health` |

---

## 输出格式

所有输出为单行 JSON，统一信封格式：

```json
{"ok":true,"data":{...}}
{"ok":false,"error":{"code":"INVALID_ARGS","message":"..."}}
```

退出码规则：

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 错误（参数错误、服务端错误、网络错误等） |
| 3 | 命令未实现（`CLI_NOT_IMPLEMENTED`） |

---

## 错误码

| 代码 | 含义 |
|---|---|
| `INVALID_ARGS` | 参数错误（含服务端 400） |
| `UNAUTHENTICATED` | 未认证（401） |
| `PERMISSION_DENIED` | 无权限（403） |
| `NOT_FOUND` | 资源不存在（404） |
| `CONFLICT` | 资源冲突（409） |
| `INTERNAL` | 内部错误（500） |
| `UNAVAILABLE` | 服务不可用（503） |
| `TIMEOUT` | 超时（504 / 网络超时） |
| `CLI_NOT_IMPLEMENTED` | CLI 命令尚未实现 |
| `SEV_NOT_IMPLEMENTED` | 服务端返回 501 |
