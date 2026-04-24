# Bible VSCode Extension — 可执行技术规格

> 面向 AI 实现。所有路径、接口、代码精确到可直接运行。
> 阅读本文档前无需阅读其他文档，所有必要上下文已内嵌。
>
> **约定**：CLI 用 Go，VSCode Extension 用 TypeScript，用户独立安装 CLI。目标态采用统一 `ok/data/error` JSON 协议；当前骨架阶段仍存在兼容输出差异（见 A2.1）。

---

## 目录

- [Part A：Go CLI](#part-a-go-cli)
- [Part B：VSCode Extension](#part-b-vscode-extension)
- [Part C：平台限制](#part-c-平台限制)
- [Part D：Server API 对照表](#part-d-server-api-对照表)
- [Part E：待填空项](#part-e-待填空项)

## 与设计文档/重写计划的关系

本文件是可执行规格（Implementation Contract），与以下文档形成协同关系：

1. `docs/designs/client_part/01-bible-vscode-extension-design.md`：提供架构目标、职责边界与设计动机。
2. `backlog/bible-cli-go-full-rewrite-plan-zh.md`：提供迁移阶段、完成状态、验收门槛与 CI 要求。

冲突与优先级处理：

1. 输出协议/错误码/退出码以 `docs/manual/cli-contract-v1.md` 为冻结契约基线。
2. 可执行行为与参数细节以本文件为实现依据。
3. 阶段进度与 "是否已完成" 以 rewrite plan 的 "当前状态" 标注为准。
4. 若本文件与 rewrite plan 存在阶段性差异，应在两处同步更新并记录决议日期。

---

## Part A：Go CLI

> 命令前缀约定：本文命令示例使用 `bible ...`，并且默认二进制名为 `bible`；`bible-cli-go` 仅作为兼容别名保留。

### A1. 项目结构

```
bible_cli_go/
├── main.go
├── go.mod                          # module: github.com/your-org/bible
├── go.sum
├── cmd/
│   ├── root.go                     # cobra root command + --config flag
│   ├── search.go                   # bible search
│   ├── skills.go                   # bible skills ls / search / get / upload / download
│   ├── session.go                  # bible session list / get / save
│   └── data.go                     # bible data delete
├── internal/
│   ├── config/
│   │   └── config.go               # 读写 ~/.bible/config.json
│   ├── client/
│   │   └── client.go               # HTTP client，所有 Server API 调用
│   └── output/
│       └── output.go               # 统一 JSON 输出工具
└── Makefile
```

### A2. 统一 JSON 输出协议（目标态）

所有命令 stdout **只输出一行 JSON，UTF-8**，退出码 0 表示成功，非 0 表示失败。

```go
// internal/output/output.go
package output

import (
    "encoding/json"
    "fmt"
    "os"
)

type Response struct {
    OK    bool         `json:"ok"`
    Data  any          `json:"data,omitempty"`
    Error *ErrorDetail `json:"error,omitempty"`
}

type ErrorDetail struct {
    Code    string `json:"code"`
    Message string `json:"message"`
}

// Success 输出成功响应并正常退出
func Success(data any) {
    b, _ := json.Marshal(Response{OK: true, Data: data})
    fmt.Println(string(b))
}

// Failure 输出失败响应并以退出码 1 退出
func Failure(code, message string) {
    b, _ := json.Marshal(Response{OK: false, Error: &ErrorDetail{Code: code, Message: message}})
    fmt.Println(string(b))
    os.Exit(1)
}
```

**错误码：**

| 代码 | 场景 |
|---|---|
| `NOT_FOUND` | 请求的资源不存在 |
| `INVALID_ARGS` | 参数格式或值错误 |
| `INVALID_SKILL_PACKAGE` | .skill 包校验失败（ZIP 损坏、SKILL.md 缺失、字段不完整）|
| `UNAUTHENTICATED` | 认证失败（HTTP 401） |
| `PERMISSION_DENIED` | 权限不足（HTTP 403） |
| `CONFLICT` | 资源冲突（HTTP 409） |
| `FAILED_PRECONDITION` | 前置条件不满足（HTTP 412） |
| `RESOURCE_EXHAUSTED` | 资源限制（HTTP 429） |
| `SEV_NOT_IMPLEMENTED` | 服务端能力未实现（HTTP 501） |
| `UNAVAILABLE` | 服务暂不可用（HTTP 503） |
| `TIMEOUT` | 对外主码：请求超时 |
| `DEADLINE_EXCEEDED` | 内部/调试兼容码：超时细分（可与 `TIMEOUT` 映射） |
| `INTERNAL` | 服务端内部错误（HTTP 5xx 其他场景） |
| `CLI_ERROR` | 其他本地错误 |

错误码约束：

1. 不使用单一 `SERVER_ERROR` 聚合码，服务端错误保留细分语义。
2. 对外文档与调用方优先使用 `TIMEOUT`；调试信息可携带 `DEADLINE_EXCEEDED`。
3. `SEV_NOT_IMPLEMENTED`（HTTP 501）与 `CLI_NOT_IMPLEMENTED`（命令占位未实现）必须显式区分。

### A2.1 当前骨架兼容现状（截至 2026-04）

当前 `bible_cli_go` 已落地命令遵循以下行为（过渡态）：

1. 成功：`stdout` 单行 JSON（通常为服务端 envelope 解包后的 payload）。
2. 失败：`stderr` 文本 `Error[<CODE>]: <message>`，并返回非零退出码。
3. 未实现命令：错误码 `CLI_NOT_IMPLEMENTED`，退出码 `3`。

说明：

1. 该行为用于骨架阶段快速验证路由与错误映射。
2. 后续按重写计划迁移到 A2 目标协议（`ok/data/error`）。

### A3. 配置文件

路径：`~/.bible/config.json`

```json
{
  "server_url": "https://api.bible.example.com"
}
```

```go
// internal/config/config.go
package config

import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
)

type Config struct {
    ServerURL string `json:"server_url"`
}

func Load() (*Config, error) {
    home, _ := os.UserHomeDir()
    path := filepath.Join(home, ".bible", "config.json")
    b, err := os.ReadFile(path)
    if err != nil {
        return nil, fmt.Errorf("config not found: create ~/.bible/config.json with server_url")
    }
    var cfg Config
    return &cfg, json.Unmarshal(b, &cfg)
}
```

---

### A4. 命令规格

#### A4.0 当前骨架已实现命令（过渡态）

当前 `bible_cli_go` 实际可用/占位命令如下：

- `health`
- `search --query <string> [--top-k <int>] [--enable-hit] [--hit-types skill,memory]`
- `system status`
- `system info`
- `knowledge list`
- `knowledge search [query]`
- `memory show`（占位，返回 `CLI_NOT_IMPLEMENTED`）
- `skills list`（占位，返回 `CLI_NOT_IMPLEMENTED`）

说明：

1. 上述已存在子命令（含占位）后续统一按本规格收敛到目标命令模型。
2. `knowledge search` 在核心使用上被顶层 `search` 替代， `knowledge search` 无`enable-hit`等扩展能力。
3. 后续开发需保持简写与全写保持兼容：`ls` 等价 `list`。

#### `bible health` - 知识库心跳包

Server API：`GET /health`

```json
{
  "ok": true,
  "data": {
    "service": "alive" | "bare" | "not_configured"
  }
}
```

#### `bible system info` - 返回Bible Server Info & readiness

Server API: `GET /api/v1/system/info`

```json
{
  "ok": true,
  "data": {
    "server":    "0.1.dev51",
    "vectordb":   "ok" | "unhealthy" | "not_configured",
    "fs":         "ok",
    "apimanager": "ok" | "not_configured"
  }
}
```

#### `bible system status` - 返回系统工作状态（兼容回退）

Server API: `GET /api/v1/system/status`

兼容回退：当 `/api/v1/system/status` 返回 404 时，回退调用 `GET /health`。

```json
{
  "ok": true,
  "data": {
    "service": "up"
  }
}
```

#### `bible search` — 知识库搜索，附带 skill/memory 命中（可降级）

Server API：`POST /api/v1/knowledge/search`

语义说明：
- `bible search` 是 CLI 聚合入口（面向工具调用的统一命令）。
- 当前实现中，主检索底层调用 `knowledge search` 对应接口，并在 `--enable-hit` 时附带调用 `skills/memory` 命中检索。
- 因此 `bible search` 与 `knowledge search` 是“入口与底层能力”的关系，不是冲突的两套功能定义。

```
bible search --query <string> [--top-k <int, default 5>] [--enable-hit] [--hit-types <csv, default: skill,memory>]
```

`--enable-hit`：附带关联命中结果。默认同时附带 `skill` 与 `memory`（等价 `--hit-types skill,memory`）。

降级规则：附带检索分支（skill 或 memory）失败不影响主知识检索返回；失败分支写入 `data.hit_warnings`。

```json
{
  "ok": true,
  "data": {
    "knowledge": [
      {
        "id": "entry-uuid",
        "title": "内存管理最佳实践",
        "content": "匹配片段...",
        "score": 0.92
      }
    ],
    "skill": [
      {
        "skill_id": "skill-abc123",
        "name": "memory_leak_checker",
        "description": "检查 C++ 代码中的内存泄漏，生成分析报告",
        "author": "xiapei",
        "tags": ["cpp", "memory", "analysis"],
        "score": 0.87
      }
    ],
    "memory": [
      {
        "memory_id": "mem-001",
        "title": "CNI-12345 并发修复记录",
        "abstract": "并发场景下 context 未初始化导致 NPE，建议入口判空。",
        "score": 0.83
      }
    ],
    "total": 42,
    "query": "C++ 内存泄漏处理"
  }
}
```

---

#### `bible skills ls` — 列出所有已注册 skill

Server API：`GET /api/v1/skills?page=N&limit=N&tag=TAG`

```
bible skills ls [--page <int, default 1>] [--limit <int, default 20>] [--tag <string>]
```

兼容说明：`bible skills list ...` 与 `bible skills ls ...` 等价。

```json
{
  "ok": true,
  "data": {
    "skills": [
      {
        "skill_id": "skill-abc123",
        "name": "memory_leak_checker",
        "description": "检查 C++ 代码中的内存泄漏，生成分析报告",
        "author": "xiapei",
        "tags": ["cpp", "memory", "analysis"],
        "updated_at": "2026-04-15T10:30:45Z"
      }
    ],
    "total": 25,
    "page": 1,
    "limit": 20
  }
}
```

---

#### `bible skills search` — 主动语义搜索 skill 元数据

Server API：`POST /api/v1/skills/search`

```
bible skills search --query <string> [--top-k <int, default 10>] [--threshold <float, default 0.0>] [--tag <string>]
```

```json
{
  "ok": true,
  "data": {
    "skills": [
      {
        "skill_id": "skill-abc123",
        "name": "memory_leak_checker",
        "description": "检查 C++ 代码中的内存泄漏，生成分析报告",
        "author": "xiapei",
        "tags": ["cpp", "memory", "analysis"],
        "score": 0.94,
        "download_url": "/api/v1/skills/skill-abc123/download"
      }
    ],
    "total": 3
  }
}
```

---

#### `bible skills get` — 获取 skill 元数据，可选附带 SKILL.md 全文

Server API：`GET /api/v1/skills/{name_or_id}`

```
bible skills get <name_or_id> [--content]
```

`--content`：同时返回 SKILL.md 全文（`skill_md_content` 字段）。Server 端从 `.skill` 包提取。

```json
{
  "ok": true,
  "data": {
    "skill_id": "skill-abc123",
    "name": "memory_leak_checker",
    "description": "检查 C++ 代码中的内存泄漏，生成分析报告",
    "author": "xiapei",
    "tags": ["cpp", "memory", "analysis"],
    "package_hash": "sha256:8d4e...",
    "updated_at": "2026-04-15T10:30:45Z",
    "download_url": "/api/v1/skills/memory_leak_checker/download",
    "skill_md_content": "---\nname: memory_leak_checker\ndescription: ...\n---\n\n# Memory Leak Checker\n..."
  }
}
```

> `skill_md_content` 仅在 `--content` 时存在，其他情况下省略。

---

#### `bible skills upload` — 上传 `.skill` 包

Server API：`POST /api/v1/skills/upload`（multipart/form-data）

```
bible skills upload --file <absolute-path-to-.skill>
```

客户端本地校验：文件扩展名必须为 `.skill`，否则报 `INVALID_ARGS` 不发送请求。

```json
{
  "ok": true,
  "data": {
    "skill_id": "skill-abc123",
    "name": "memory_leak_checker",
    "action": "created",
    "package_hash": "sha256:8d4e...",
    "status": "ready"
  }
}
```

`action`：`"created"`（首次）或 `"replaced"`（同名覆盖）。

---

#### `bible skills download` — 下载 `.skill` 包到本地

Server API：`GET /api/v1/skills/{name_or_id}/download`

```
bible skills download <name_or_id> [--output <dir, default: ~/.claude/skills/>]
```

**下载行为：**
1. 下载 `.skill` 包到临时目录
2. 校验 ZIP 完整性（CRC 校验）
3. 原子替换 `<output_dir>/<name>/`（先写到临时，再重命名）
4. 写入 `<output_dir>/<name>/.bible-skill-cache.json`（含 hash 和 updated_at）

读取响应头：`X-Skill-Hash`、`X-Skill-Updated-At`。

```json
{
  "ok": true,
  "data": {
    "name": "memory_leak_checker",
    "output_path": "/home/user/.claude/skills/memory_leak_checker",
    "package_hash": "sha256:8d4e...",
    "updated_at": "2026-04-15T10:30:45Z",
    "action": "updated"
  }
}
```

`action`：`"created"`（首次）或 `"updated"`（覆盖已有版本）。

---

#### `bible session list` — 列出历史会话

```
bible session list [--limit <int, default 10>] [--uid <string>]
```

从bible server 查询 `uid`名下的 [--limit] 条session memory, 默认查询本客户端 `uid` 名下的session memory.

```json
{
  "ok": true,
  "data": {
    "sessions": [
      {
        "id": "sess-uuid",
        "title": "C++ 内存泄漏处理讨论",
        "created_at": "2026-04-20T10:00:00Z",
        "message_count": 18,
        "preview": "用户：我的项目里怎么处理 C++ 内存泄漏..."
      }
    ],
    "total": 25
  }
}
```

---

#### `bible session get` — 获取会话完整内容

```
bible session get --id <session-id>
```

```json
{
  "ok": true,
  "data": {
    "session": {
      "id": "sess-uuid",
      "title": "C++ 内存泄漏处理讨论",
      "created_at": "2026-04-20T10:00:00Z",
      "messages": [
        { "role": "user", "content": "我的项目里怎么处理 C++ 内存泄漏？" },
        { "role": "assistant", "content": "根据你的知识库..." }
      ]
    }
  }
}
```

---

#### `bible session save` — 保存对话记录

```
bible session save --input <json-string>
```

`--input` 的 JSON 结构：

```json
{
  "title": "可选标题，省略时服务端自动生成",
  "messages": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

```json
{
  "ok": true,
  "data": {
    "session_id": "sess-uuid",
    "title": "C++ 内存泄漏处理讨论",
    "message_count": 18
  }
}
```

---

#### `bible data delete` — 删除知识条目

```
bible data delete --key <string> [--hard]
```

默认软删除（可恢复）。`--hard` 永久删除。

```json
{
  "ok": true,
  "data": {
    "key": "entry-key",
    "deleted_at": "2026-04-23T12:00:00Z",
    "hard": false
  }
}
```

---

#### 通用错误响应（任意命令）

```json
{
  "ok": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Skill 'unknown_skill' not found."
  }
}
```

---

```makefile
.PHONY: build build-all test lint

build:
	go build -ldflags="-s -w" -o bin/bible ./...

build-all:
	GOOS=darwin  GOARCH=arm64  go build -ldflags="-s -w" -o dist/bible-darwin-arm64   ./...
	GOOS=darwin  GOARCH=amd64  go build -ldflags="-s -w" -o dist/bible-darwin-amd64   ./...
	GOOS=linux   GOARCH=amd64  go build -ldflags="-s -w" -o dist/bible-linux-amd64    ./...
	GOOS=windows GOARCH=amd64  go build -ldflags="-s -w" -o dist/bible-windows-amd64.exe ./...

test:
	go test ./...

lint:
	golangci-lint run ./...
```

---

## Part B：VSCode Extension

### B1. 项目结构

```
bible-vscode/
├── package.json
├── tsconfig.json
├── esbuild.js
├── src/
│   ├── extension.ts               # 激活入口
│   ├── commands.ts                # VSCode 命令（搜索/上传）
│   ├── setup-check.ts             # CLI 可用性检测
│   ├── cli.ts                     # execFile 封装 + JSON 解析
│   └── tools/
│       ├── index.ts               # 工具注册汇总
│       ├── knowledge-search.ts    # bible_knowledge_search
│       ├── skill-list.ts          # bible_skill_list
│       ├── skill-search.ts        # bible_skill_search
│       ├── skill-get.ts           # bible_skill_get
│       ├── skill-upload.ts        # bible_skill_upload
│       ├── skill-download.ts      # bible_skill_download
│       ├── session-list.ts        # bible_session_list
│       ├── session-get.ts         # bible_session_get
│       ├── session-save.ts        # bible_session_save
│       └── data-delete.ts         # bible_data_delete
└── .vscode/
    └── launch.json
```

### B2. package.json（完整）

```json
{
  "name": "bible-vscode",
  "displayName": "Bible",
  "description": "Personal knowledge base tools for Copilot agents",
  "version": "0.1.0",
  "engines": { "vscode": "^1.99.0" },
  "categories": ["AI", "Chat"],
  "activationEvents": ["onStartupFinished"],
  "main": "./dist/extension.js",
  "contributes": {
    "configuration": {
      "title": "Bible",
      "properties": {
        "bible.cliPath": {
          "type": "string",
          "default": "bible",
          "description": "Path to the bible CLI binary. Defaults to 'bible' (resolved from PATH)."
        }
      }
    },
    "commands": [
      {
        "command": "bible.searchKnowledge",
        "title": "Bible: Search Knowledge Base",
        "icon": "$(search)"
      },
      {
        "command": "bible.uploadSkill",
        "title": "Bible: Upload Skill Package (.skill)",
        "icon": "$(cloud-upload)"
      }
    ],
    "languageModelTools": [
      {
        "name": "bible_knowledge_search",
        "displayName": "Search Knowledge Base",
        "modelDescription": "Semantically search the user's personal knowledge base. Returns ranked knowledge entries and optional related skill/memory hits. When skill results are returned, consider using bible_skill_get to load skill instructions as additional context. Always call this before answering domain-specific questions.",
        "userDescription": "Search bible knowledge base (includes related skill/memory hits)",
        "toolReferenceName": "bibleSearch",
        "canBeReferencedInPrompt": true,
        "tags": ["bible"],
        "icon": "$(search)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query":     { "type": "string",  "description": "Natural language search query" },
            "topK":      { "type": "number",  "description": "Max knowledge results to return (default 5)" },
            "enableHit": { "type": "boolean", "description": "Whether to include related skill/memory hits (default true)" },
            "hitTypes": {
              "type": "array",
              "description": "Optional hit types to include when enableHit=true. Defaults to ['skill','memory'].",
              "items": { "type": "string", "enum": ["skill", "memory"] }
            }
          },
          "required": ["query"]
        }
      },
      {
        "name": "bible_skill_list",
        "displayName": "List All Skills",
        "modelDescription": "List all skills registered in the user's bible knowledge base. Use when the user asks what skills are available, or to browse skills by tag.",
        "userDescription": "List all registered skills",
        "toolReferenceName": "bibleSkillList",
        "canBeReferencedInPrompt": true,
        "tags": ["bible"],
        "icon": "$(list-unordered)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "tag":   { "type": "string", "description": "Filter by tag (optional)" },
            "page":  { "type": "number", "description": "Page number (default 1)" },
            "limit": { "type": "number", "description": "Results per page (default 20)" }
          }
        }
      },
      {
        "name": "bible_skill_search",
        "displayName": "Search Skills",
        "modelDescription": "Semantically search the skill library by name, description, and tags. Use when the user wants to find a specific type of skill, or when bible_knowledge_search surfaces skill hints and you need more skill options.",
        "userDescription": "Semantic search across skill library",
        "toolReferenceName": "bibleSkillSearch",
        "canBeReferencedInPrompt": true,
        "tags": ["bible"],
        "icon": "$(tools)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query":     { "type": "string", "description": "Natural language description of the desired skill" },
            "topK":      { "type": "number", "description": "Max results (default 10)" },
            "threshold": { "type": "number", "description": "Minimum similarity score 0.0-1.0 (default 0.0)" },
            "tag":       { "type": "string", "description": "Filter by tag (optional)" }
          },
          "required": ["query"]
        }
      },
      {
        "name": "bible_skill_get",
        "displayName": "Get Skill Instructions",
        "modelDescription": "Retrieve the full SKILL.md documentation for a skill by name. Use after bible_knowledge_search or bible_skill_search surfaces a relevant skill, to load its instructions as context. In VSCode, skill scripts cannot be executed — only SKILL.md is available. To use scripts, the user must download the skill via bible_skill_download and run it in Claude Code.",
        "userDescription": "Load skill instructions (SKILL.md) into context",
        "toolReferenceName": "bibleSkillGet",
        "canBeReferencedInPrompt": true,
        "tags": ["bible"],
        "icon": "$(book)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "name": { "type": "string", "description": "Skill name (from search results)" }
          },
          "required": ["name"]
        }
      },
      {
        "name": "bible_skill_upload",
        "displayName": "Upload Skill Package",
        "modelDescription": "Upload a .skill package file to the bible knowledge base. Use when the user provides a .skill file path and wants to register or update a skill. Same-name skills are replaced.",
        "userDescription": "Upload a .skill package to bible",
        "tags": ["bible"],
        "icon": "$(cloud-upload)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "filepath": { "type": "string", "description": "Absolute path to the .skill file (must end in .skill)" }
          },
          "required": ["filepath"]
        }
      },
      {
        "name": "bible_skill_download",
        "displayName": "Download Skill to Local",
        "modelDescription": "Download a .skill package to the local ~/.claude/skills/ directory for use with Claude Code CLI. Use when the user wants to execute a skill's scripts (not just read instructions). After downloading, the skill is available in Claude Code via the Skill tool.",
        "userDescription": "Download skill to ~/.claude/skills/ for Claude Code",
        "tags": ["bible"],
        "icon": "$(cloud-download)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "name":      { "type": "string", "description": "Skill name to download" },
            "outputDir": { "type": "string", "description": "Target directory (default: ~/.claude/skills/)" }
          },
          "required": ["name"]
        }
      },
      {
        "name": "bible_session_list",
        "displayName": "List Sessions",
        "modelDescription": "List recent conversation sessions saved in bible. Use when the user asks about past conversations, 'what we discussed before', or wants to recall previous context. Optionally pass uid to list sessions under a specific user scope.",
        "userDescription": "List saved bible sessions",
        "tags": ["bible"],
        "icon": "$(history)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "limit": { "type": "number", "description": "Max sessions to return (default 10)" },
            "uid": { "type": "string", "description": "Optional user scope. If omitted, use current client uid context." }
          }
        }
      },
      {
        "name": "bible_session_get",
        "displayName": "Get Session Content",
        "modelDescription": "Retrieve the full message history of a specific session by ID. Use after bible_session_list to read the content of a past conversation.",
        "userDescription": "Get full content of a saved session",
        "tags": ["bible"],
        "icon": "$(file-text)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "sessionId": { "type": "string", "description": "Session ID from session list" }
          },
          "required": ["sessionId"]
        }
      },
      {
        "name": "bible_session_save",
        "displayName": "Save Current Chat",
        "modelDescription": "Save a conversation to the bible knowledge base for future retrieval. Pass the messages from the current conversation. Call ONLY when the user explicitly asks to save, archive, or remember this conversation. Do not call automatically.",
        "userDescription": "Save a conversation to bible knowledge base",
        "toolReferenceName": "bibleSave",
        "canBeReferencedInPrompt": true,
        "tags": ["bible"],
        "icon": "$(save)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "title": { "type": "string", "description": "Optional title for this session. Auto-generated from content if omitted." },
            "messages": {
              "type": "array",
              "description": "The conversation messages to save. Provide the messages from the current agent conversation.",
              "items": {
                "type": "object",
                "properties": {
                  "role":    { "type": "string", "description": "Message role: 'user' or 'assistant'" },
                  "content": { "type": "string", "description": "Message content" }
                },
                "required": ["role", "content"]
              }
            }
          },
          "required": ["messages"]
        }
      },
      {
        "name": "bible_data_delete",
        "displayName": "Delete Knowledge Entry",
        "modelDescription": "Delete a knowledge base entry by key. Use ONLY when the user explicitly asks to delete a specific entry. Defaults to soft delete (recoverable). Hard delete is permanent.",
        "userDescription": "Delete an entry from bible knowledge base",
        "tags": ["bible"],
        "icon": "$(trash)",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key":  { "type": "string",  "description": "Entry key to delete" },
            "hard": { "type": "boolean", "description": "If true, permanently delete (irreversible). Default: soft delete." }
          },
          "required": ["key"]
        }
      }
    ]
  },
  "dependencies": {},
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/vscode": "^1.99.0",
    "esbuild": "^0.21.0",
    "typescript": "^5.4.0"
  }
}
```

### B3. tsconfig.json

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2022",
    "lib": ["ES2022"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*"]
}
```

### B4. esbuild.js

```js
const esbuild = require('esbuild');
esbuild.build({
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  sourcemap: true,
}).catch(() => process.exit(1));
```

### B5. src/cli.ts — CLI 封装 + JSON 解析

```typescript
import { execFile } from 'child_process';
import { promisify } from 'util';
import * as vscode from 'vscode';

const execFileAsync = promisify(execFile);

interface CliResponse<T> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

/**
 * 执行 bible CLI，返回 data 字段。失败时抛出包含 [CODE] message 的 Error。
 */
export async function runCli<T>(args: string[]): Promise<T> {
  const cliPath = vscode.workspace
    .getConfiguration('bible')
    .get<string>('cliPath', 'bible');

  let stdout: string;
  try {
    const result = await execFileAsync(cliPath, args, {
      timeout: 30_000,
      maxBuffer: 10 * 1024 * 1024, // 10MB
    });
    stdout = result.stdout.trim();
  } catch (err: any) {
    if (err.code === 'ENOENT') {
      throw new Error(
        `bible CLI not found at "${cliPath}". ` +
        `Install it or set bible.cliPath in settings.`
      );
    }
    // CLI 以非零退出码退出，stdout 仍可能含有效 JSON
    stdout = err.stdout?.trim() ?? '';
    if (!stdout) {
      throw new Error(
        `bible CLI exited with code ${err.code ?? '?'}: ` +
        (err.stderr?.trim() ?? err.message)
      );
    }
  }

  let response: CliResponse<T>;
  try {
    response = JSON.parse(stdout);
  } catch {
    throw new Error(
      `bible CLI returned non-JSON output: ${stdout.slice(0, 300)}`
    );
  }

  if (!response.ok || response.error) {
    const { code, message } = response.error ?? { code: 'UNKNOWN', message: stdout };

    // 显式处理服务端能力未实现，便于上层给出更可读提示。
    if (code === 'SEV_NOT_IMPLEMENTED') {
      throw new Error(`[${code}] Service capability is not implemented yet: ${message}`);
    }

    throw new Error(`[${code}] ${message}`);
  }

  return response.data as T;
}
```

### B6. 工具实现（全部 10 个）

---

**src/tools/knowledge-search.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input {
  query: string;
  topK?: number;
  enableHit?: boolean;
  hitTypes?: ('skill' | 'memory')[];
}

interface KnowledgeHit {
  id: string; title: string; content: string; score: number;
}
interface SkillHit {
  skill_id: string; name: string; description: string;
  author: string; tags: string[]; score: number;
}
interface MemoryHit {
  memory_id: string; title: string; abstract: string; score: number;
}
interface SearchData {
  knowledge: KnowledgeHit[];
  skill?: SkillHit[];
  memory?: MemoryHit[];
  hit_warnings?: string[];
  total: number;
  query: string;
}

export class KnowledgeSearchTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { query, topK = 5, enableHit = true, hitTypes = ['skill', 'memory'] } = options.input;
    const args = ['search', '--query', query, '--top-k', String(topK)];
    if (enableHit) {
      args.push('--enable-hit');
      args.push('--hit-types', hitTypes.join(','));
    }

    const data = await runCli<SearchData>(args);
    const parts: string[] = [];

    if (data.knowledge.length > 0) {
      parts.push('**Knowledge Results:**');
      data.knowledge.forEach((h, i) => {
        parts.push(`${i + 1}. **${h.title}** (score: ${h.score.toFixed(2)})\n${h.content}`);
      });
    } else {
      parts.push(`No knowledge results for: ${query}`);
    }

    if (data.skill?.length > 0) {
      parts.push('\n**Related Skills** — use `bible_skill_get` to load instructions:');
      data.skill.forEach(s => {
        const tagStr = s.tags.length ? ` [${s.tags.join(', ')}]` : '';
        parts.push(`- \`${s.name}\` (score: ${s.score.toFixed(2)}): ${s.description}${tagStr}`);
      });
    }

    if (data.memory?.length > 0) {
      parts.push('\n**Related Memory:**');
      data.memory.forEach(m => {
        parts.push(`- **${m.title}** (score: ${m.score.toFixed(2)}): ${m.abstract}`);
      });
    }

    if (data.hit_warnings?.length) {
      parts.push('\n**Hit Warnings:**');
      data.hit_warnings.forEach(w => parts.push(`- ${w}`));
    }

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(parts.join('\n\n'))
    ]);
  }
}
```

---

**src/tools/skill-list.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { tag?: string; page?: number; limit?: number; }
interface SkillItem {
  skill_id: string; name: string; description: string;
  author: string; tags: string[]; updated_at: string;
}
interface SkillListData { skills: SkillItem[]; total: number; page: number; limit: number; }

export class SkillListTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { tag, page = 1, limit = 20 } = options.input;
    const args = ['skills', 'ls', '--page', String(page), '--limit', String(limit)];
    if (tag) args.push('--tag', tag);

    const data = await runCli<SkillListData>(args);

    if (data.skills.length === 0) {
      return new vscode.LanguageModelToolResult([
        new vscode.LanguageModelTextPart('No skills registered yet.')
      ]);
    }

    const lines = [
      `**Skills** (${data.total} total, page ${data.page}):`,
      ...data.skills.map(s => {
        const tagStr = s.tags.length ? ` [${s.tags.join(', ')}]` : '';
        return `- **${s.name}**${tagStr} — ${s.description} _(${s.author})_`;
      })
    ];

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(lines.join('\n'))
    ]);
  }
}
```

---

**src/tools/skill-search.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { query: string; topK?: number; threshold?: number; tag?: string; }
interface SkillSearchResult {
  skill_id: string; name: string; description: string;
  author: string; tags: string[]; score: number; download_url: string;
}
interface SkillSearchData { skills: SkillSearchResult[]; total: number; }

export class SkillSearchTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { query, topK = 10, threshold = 0.0, tag } = options.input;
    const args = [
      'skills', 'search', '--query', query,
      '--top-k', String(topK),
      '--threshold', String(threshold),
    ];
    if (tag) args.push('--tag', tag);

    const data = await runCli<SkillSearchData>(args);

    if (data.skills.length === 0) {
      return new vscode.LanguageModelToolResult([
        new vscode.LanguageModelTextPart(`No skills found for: ${query}`)
      ]);
    }

    const lines = [
      `**Skill Search Results** for "${query}":`,
      ...data.skills.map(s => {
        const tagStr = s.tags.length ? ` [${s.tags.join(', ')}]` : '';
        return `- \`${s.name}\` (score: ${s.score.toFixed(2)})${tagStr}: ${s.description}`;
      })
    ];

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(lines.join('\n'))
    ]);
  }
}
```

---

**src/tools/skill-get.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { name: string; }
interface SkillGetData {
  skill_id: string; name: string; description: string;
  author: string; tags: string[]; updated_at: string;
  skill_md_content: string;
}

export class SkillGetTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { name } = options.input;
    const data = await runCli<SkillGetData>(['skills', 'get', name, '--content']);

    const lines = [
      `**Skill: ${data.name}**`,
      `Description: ${data.description}`,
      data.tags.length ? `Tags: ${data.tags.join(', ')}` : null,
      `Author: ${data.author} | Updated: ${data.updated_at}`,
      '',
      '**SKILL.md Instructions:**',
      data.skill_md_content,
      '',
      '> **VSCode Note:** Skill scripts (.py/.sh) cannot be executed here. ' +
      'Use `bible_skill_download` to download and run scripts in Claude Code.',
    ].filter(l => l !== null).join('\n');

    return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(lines)]);
  }
}
```

---

**src/tools/skill-upload.ts**

```typescript
import * as vscode from 'vscode';
import * as path from 'path';
import { runCli } from '../cli';

interface Input { filepath: string; }
interface UploadData { skill_id: string; name: string; action: 'created' | 'replaced'; package_hash: string; }

export class SkillUploadTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { filepath } = options.input;
    if (!filepath.endsWith('.skill')) {
      throw new Error(`[INVALID_ARGS] File must have .skill extension: "${filepath}"`);
    }
    const data = await runCli<UploadData>(['skills', 'upload', '--file', filepath]);
    const verb = data.action === 'created' ? 'Uploaded' : 'Replaced';
    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `${verb} skill **${data.name}** (ID: \`${data.skill_id}\`)`
      )
    ]);
  }

  async prepareInvocation(options: vscode.LanguageModelToolInvocationPrepareOptions<Input>, _token: vscode.CancellationToken) {
    const filename = path.basename(options.input.filepath);
    return {
      invocationMessage: `Uploading ${filename} to bible...`,
      confirmationMessages: {
        title: 'Upload skill package?',
        message: new vscode.MarkdownString(
          `Upload \`${filename}\` to your bible knowledge base.\n\n` +
          `⚠️ If a skill with the same name exists, it will be **replaced**.`
        ),
      },
    };
  }
}
```

---

**src/tools/skill-download.ts**

```typescript
import * as vscode from 'vscode';
import * as os from 'os';
import * as path from 'path';
import { runCli } from '../cli';

interface Input { name: string; outputDir?: string; }
interface DownloadData {
  name: string; output_path: string;
  package_hash: string; updated_at: string; action: 'created' | 'updated';
}

export class SkillDownloadTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { name, outputDir } = options.input;
    const args = ['skills', 'download', name];
    if (outputDir) args.push('--output', outputDir);

    const data = await runCli<DownloadData>(args);
    const verb = data.action === 'created' ? 'Downloaded' : 'Updated';
    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `${verb} skill **${data.name}** to \`${data.output_path}\`\n\n` +
        `The skill is now available in Claude Code via the Skill tool.`
      )
    ]);
  }

  async prepareInvocation(options: vscode.LanguageModelToolInvocationPrepareOptions<Input>, _token: vscode.CancellationToken) {
    const { name, outputDir } = options.input;
    const targetDir = outputDir ?? path.join(os.homedir(), '.claude', 'skills', name);
    return {
      invocationMessage: `Downloading skill "${name}"...`,
      confirmationMessages: {
        title: `Download skill "${name}"?`,
        message: new vscode.MarkdownString(
          `Download \`${name}\` to:\n\`${targetDir}\`\n\n` +
          `Existing version will be replaced. ` +
          `The skill will then be available in Claude Code.`
        ),
      },
    };
  }
}
```

---

**src/tools/session-list.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { limit?: number; uid?: string; }
interface SessionItem { id: string; title: string; created_at: string; message_count: number; preview: string; }
interface SessionListData { sessions: SessionItem[]; total: number; }

export class SessionListTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { limit = 10, uid } = options.input;
    const args = ['session', 'list', '--limit', String(limit)];
    if (uid && uid.trim().length > 0) {
      args.push('--uid', uid.trim());
    }
    const data = await runCli<SessionListData>(args);

    if (data.sessions.length === 0) {
      return new vscode.LanguageModelToolResult([
        new vscode.LanguageModelTextPart('No saved sessions found.')
      ]);
    }

    const lines = [
      `**Saved Sessions** (${data.total} total):`,
      ...data.sessions.map((s, i) =>
        `${i + 1}. **${s.title}** (ID: \`${s.id}\`, ${s.message_count} msgs, ${s.created_at.slice(0, 10)})\n   _${s.preview}_`
      )
    ];

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(lines.join('\n\n'))
    ]);
  }
}
```

---

**src/tools/session-get.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { sessionId: string; }
interface Message { role: string; content: string; }
interface SessionData { session: { id: string; title: string; created_at: string; messages: Message[] }; }

export class SessionGetTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId } = options.input;
    const data = await runCli<SessionData>(['session', 'get', '--id', sessionId]);
    const { session } = data;

    const transcript = session.messages
      .map(m => `**${m.role === 'user' ? 'User' : 'Assistant'}:** ${m.content}`)
      .join('\n\n');

    const text = [
      `**Session: ${session.title}**`,
      `ID: \`${session.id}\` | Date: ${session.created_at.slice(0, 10)} | ${session.messages.length} messages`,
      '',
      transcript,
    ].join('\n');

    return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
  }
}
```

---

**src/tools/session-save.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Message { role: string; content: string; }
interface Input { title?: string; messages: Message[]; }
interface SavePayload { title?: string; messages: Message[]; }
interface SaveData { session_id: string; title: string; message_count: number; }

export class SessionSaveTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { title, messages } = options.input;
    if (!messages?.length) {
      throw new Error('[INVALID_ARGS] messages array is required and must not be empty.');
    }
    const payload: SavePayload = { title, messages };
    const data = await runCli<SaveData>(['session', 'save', '--input', JSON.stringify(payload)]);
    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `Saved session **"${data.title}"** — ${data.message_count} messages (ID: \`${data.session_id}\`)`
      )
    ]);
  }

  async prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<Input>,
    _token: vscode.CancellationToken
  ) {
    const { title, messages } = options.input;
    const titleLine = title ? `\n\n**Title:** ${title}` : '';
    const count = messages?.length ?? 0;
    return {
      invocationMessage: 'Saving chat session to bible...',
      confirmationMessages: {
        title: 'Save chat to bible?',
        message: new vscode.MarkdownString(
          `Save **${count} messages** to your knowledge base for future retrieval.${titleLine}`
        ),
      },
    };
  }
}
```

---

**src/tools/data-delete.ts**

```typescript
import * as vscode from 'vscode';
import { runCli } from '../cli';

interface Input { key: string; hard?: boolean; }
interface DeleteData { key: string; deleted_at: string; hard: boolean; }

export class DataDeleteTool implements vscode.LanguageModelTool<Input> {
  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<Input>,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    const { key, hard = false } = options.input;
    const args = ['data', 'delete', '--key', key];
    if (hard) args.push('--hard');

    const data = await runCli<DeleteData>(args);
    const deleteType = data.hard ? 'permanently deleted' : 'soft deleted (recoverable)';
    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(`Entry \`${data.key}\` has been ${deleteType}.`)
    ]);
  }

  async prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<Input>,
    _token: vscode.CancellationToken
  ) {
    const { key, hard = false } = options.input;
    const consequence = hard
      ? '⛔ **This is a permanent hard delete and cannot be undone.**'
      : 'This is a soft delete (recoverable).';
    return {
      invocationMessage: `Deleting entry "${key}"...`,
      confirmationMessages: {
        title: `Delete entry "${key}"?`,
        message: new vscode.MarkdownString(`Delete key: \`${key}\`\n\n${consequence}`),
      },
    };
  }
}
```

---

### B7. src/tools/index.ts

```typescript
import * as vscode from 'vscode';
import { KnowledgeSearchTool } from './knowledge-search';
import { SkillListTool }        from './skill-list';
import { SkillSearchTool }      from './skill-search';
import { SkillGetTool }         from './skill-get';
import { SkillUploadTool }      from './skill-upload';
import { SkillDownloadTool }    from './skill-download';
import { SessionListTool }      from './session-list';
import { SessionGetTool }       from './session-get';
import { SessionSaveTool }      from './session-save';
import { DataDeleteTool }       from './data-delete';

/**
 * 注册所有 10 个全局 bible 工具。
 */
export function registerTools(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.lm.registerTool('bible_knowledge_search', new KnowledgeSearchTool()),
    vscode.lm.registerTool('bible_skill_list',       new SkillListTool()),
    vscode.lm.registerTool('bible_skill_search',     new SkillSearchTool()),
    vscode.lm.registerTool('bible_skill_get',        new SkillGetTool()),
    vscode.lm.registerTool('bible_skill_upload',     new SkillUploadTool()),
    vscode.lm.registerTool('bible_skill_download',   new SkillDownloadTool()),
    vscode.lm.registerTool('bible_session_list',     new SessionListTool()),
    vscode.lm.registerTool('bible_session_get',      new SessionGetTool()),
    vscode.lm.registerTool('bible_session_save',     new SessionSaveTool()),
    vscode.lm.registerTool('bible_data_delete',      new DataDeleteTool()),
  );
}
```

### B8. src/commands.ts

```typescript
import * as vscode from 'vscode';
import { runCli } from './cli';

export function registerCommands(context: vscode.ExtensionContext): void {

  // Bible: Search Knowledge Base — QuickPick UI，不经过 LLM
  context.subscriptions.push(
    vscode.commands.registerCommand('bible.searchKnowledge', async () => {
      const query = await vscode.window.showInputBox({
        prompt: 'Search your knowledge base...',
        placeHolder: 'e.g. C++ memory management',
      });
      if (!query) return;

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Searching bible...', cancellable: false },
        async () => {
          try {
            const data = await runCli<any>([
              'search', '--query', query, '--top-k', '5', '--enable-hit', '--hit-types', 'skill,memory'
            ]);
            const items: vscode.QuickPickItem[] = [
              ...(data.knowledge ?? []).map((h: any) => ({
                label: `$(file-text) ${h.title}`,
                description: `score: ${h.score.toFixed(2)}`,
                detail: h.content,
              })),
              ...(data.skill ?? []).map((s: any) => ({
                label: `$(tools) [skill] ${s.name}`,
                description: `score: ${s.score.toFixed(2)} — ${s.tags?.join(', ') ?? ''}`,
                detail: s.description,
              })),
              ...(data.memory ?? []).map((m: any) => ({
                label: `$(history) [memory] ${m.title}`,
                description: `score: ${m.score.toFixed(2)}`,
                detail: m.abstract ?? '',
              })),
            ];
            if (items.length === 0) {
              vscode.window.showInformationMessage(`No results for: "${query}"`);
              return;
            }
            vscode.window.showQuickPick(items, {
              placeHolder: `${items.length} results for "${query}"`,
              matchOnDescription: true,
              matchOnDetail: true,
            });
          } catch (err: any) {
            vscode.window.showErrorMessage(`Bible search failed: ${err.message}`);
          }
        }
      );
    })
  );

  // Bible: Upload Skill Package — 文件选择器
  context.subscriptions.push(
    vscode.commands.registerCommand('bible.uploadSkill', async () => {
      const uris = await vscode.window.showOpenDialog({
        canSelectMany: false,
        filters: { 'Skill packages': ['skill'] },
        openLabel: 'Upload .skill Package',
      });
      if (!uris?.length) return;

      const filepath = uris[0].fsPath;
      const filename = filepath.split(/[/\\]/).pop();
      const confirmed = await vscode.window.showWarningMessage(
        `Upload "${filename}" to bible? Same-name skills will be replaced.`,
        { modal: true },
        'Upload'
      );
      if (confirmed !== 'Upload') return;

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Uploading ${filename}...`, cancellable: false },
        async () => {
          try {
            const data = await runCli<any>(['skills', 'upload', '--file', filepath]);
            const verb = data.action === 'created' ? 'Uploaded' : 'Replaced';
            vscode.window.showInformationMessage(`${verb} skill "${data.name}"`);
          } catch (err: any) {
            vscode.window.showErrorMessage(`Upload failed: ${err.message}`);
          }
        }
      );
    })
  );
}
```

### B9. src/setup-check.ts

```typescript
import { execFile } from 'child_process';
import { promisify } from 'util';
import * as vscode from 'vscode';

const execFileAsync = promisify(execFile);

/**
 * 激活时检查 CLI 是否可用。不可用时显示一次安装引导通知（不阻塞激活）。
 */
export async function checkCliAvailable(): Promise<void> {
  const cliPath = vscode.workspace
    .getConfiguration('bible')
    .get<string>('cliPath', 'bible');

  try {
    await execFileAsync(cliPath, ['--version'], { timeout: 5000 });
  } catch {
    const action = await vscode.window.showWarningMessage(
      `Bible CLI not found${cliPath !== 'bible' ? ` at "${cliPath}"` : ''}. ` +
      `Install it to enable bible tools in Copilot.`,
      'Installation Guide',
      'Set CLI Path'
    );
    if (action === 'Installation Guide') {
      vscode.env.openExternal(
        vscode.Uri.parse('https://github.com/your-org/bible#installation')
      );
    } else if (action === 'Set CLI Path') {
      vscode.commands.executeCommand('workbench.action.openSettings', 'bible.cliPath');
    }
  }
}
```

### B10. src/extension.ts

```typescript
import * as vscode from 'vscode';
import { registerTools }    from './tools/index';
import { registerCommands } from './commands';
import { checkCliAvailable } from './setup-check';

export function activate(context: vscode.ExtensionContext): void {
  // 1. 注册 10 个全局工具
  registerTools(context);

  // 2. 注册 2 个 VSCode 命令
  registerCommands(context);

  // 3. 异步检测 CLI 可用性，不阻塞激活
  checkCliAvailable();
}

export function deactivate(): void {}
```

### B11. .vscode/launch.json

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run Extension",
      "type": "extensionHost",
      "request": "launch",
      "args": ["--extensionDevelopmentPath=${workspaceFolder}"],
      "preLaunchTask": "npm: build",
      "outFiles": ["${workspaceFolder}/dist/**/*.js"]
    }
  ]
}
```

---

## Part C：平台限制

| 限制 | 技术原因 | 应对方案 |
|---|---|---|
| 无法执行 .skill 脚本 | VSCode 扩展无 Claude Code Skill tool 执行机制 | VSCode 中注入 SKILL.md 文档；脚本执行通过 `bible_skill_download` 下载后在 Claude Code 中完成 |
| `bible_session_save` 只能保存 LM 上下文内的消息 | `messages` 字段由调用 LM 提供，LM 只能访问当前 agent 对话范围内的历史 | 若需保存其他来源的内容，用户可在当前 agent 对话中描述内容后让 LM 整理保存 |

---

## Part D：Server API 对照表

### D1. 目标态 API（`02` 规格）

| CLI 命令 | Server API |
|---|---|
| `bible search` | `POST /api/v1/search` |
| `bible skills ls` | `GET /api/v1/skills` |
| `bible skills search` | `POST /api/v1/skills/search` |
| `bible skills get <name>` | `GET /api/v1/skills/{name_or_id}` |
| `bible skills upload` | `POST /api/v1/skills/upload` (multipart/form-data) |
| `bible skills download <name>` | `GET /api/v1/skills/{name_or_id}/download` |
| `bible session list` | `GET /api/v1/sessions` |
| `bible session get` | `GET /api/v1/sessions/{id}` |
| `bible session save` | `POST /api/v1/sessions` |
| `bible data delete` | `DELETE /api/v1/data/{key}` |

补充说明：D1 的 `bible search -> POST /api/v1/search` 表示目标态统一聚合端点；在当前过渡实现（D2）中，`bible search` 的主检索路径仍落到 `knowledge search`，并可附带 `skills/memory` 命中查询。

### D2. 当前骨架已实现 API（`bible_cli_go` 现状）

| 当前 CLI 命令 | 当前请求路径 | 备注 |
|---|---|---|
| `health` | `GET /health` | 无 |
| `system status` | `GET /api/v1/system/status` | 若 404 回退 `GET /health` |
| `system info` | `GET /api/v1/system/info` | 若 404 回退 `GET /health` |
| `search --query <q>` | `GET /api/v1/knowledge/search?query=...` | 已实现（主检索） |
| `search --enable-hit` | `POST /api/v1/skills/search` | 已实现（附带命中，失败可降级） |
| `search --enable-hit` | `POST /api/v1/memory/search` | 已实现（附带命中，失败可降级） |
| `knowledge list` | `GET /api/v1/knowledge/list` | 已实现 |
| `knowledge search [query]` | `GET /api/v1/knowledge/search?query=...` | query 可选 |

说明：`skills/session/data` 的 API 路径在目标态按 D1 逐步补齐，属于后续开发阶段范围。

---

## Part E：待填空项

实现前须替换的占位符：

| 占位符 | 所在位置 | 如何确认 |
|---|---|---|
| `github.com/your-org/bible` | `go.mod` | 确定 GitHub org/repo 名称 |
| `https://api.bible.example.com` | `~/.bible/config.json` 默认值 | 实际 server 部署地址 |
| `https://github.com/your-org/bible#installation` | `setup-check.ts` | 实际安装文档 URL |
| `bible skills get --content` server 实现 | Server 端需从 .skill 包提取 SKILL.md 并在 GET 响应中返回 | 需 server 端确认或新增此能力 |
