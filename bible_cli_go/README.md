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

---

## API 端点映射（v4）

| CLI 操作 | HTTP 方法 | 端点 |
|---|---|---|
| `memory upload` | POST multipart | `/api/import/memory` |
| `skills upload` | POST multipart | `/api/import/skill` |
| `memory search` / `memory get` | POST JSON | `/api/search/memory` |
| `skills search` / `skills get` | POST JSON | `/api/search/skill` |
| `knowledge search` | POST JSON | `/api/search/knowledge-base` |
| `knowledge list` | GET | `/api/control/docs/list` → fallback `/api/v1/knowledge/list` |
| `skills download` | POST JSON | `/api/download/skill/file` |
| `memory status` / `task poll` | GET | `/api/control/admin/tasks/{id}` |
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
