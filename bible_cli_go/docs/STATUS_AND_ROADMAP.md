# bible_cli_go 现状与后续开发路线

本文基于 `bibleV` v4 设计文档、CLI 契约、`bible_cli_go` 当前代码与测试整理。

当前验证状态：

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go
go test ./... && go vet ./... && go build ./...
```

以上命令已通过。

## 1. 项目目标

`bible_cli_go` 是 BiBLE Atlas 的 Go CLI 客户端，通过 HTTP 与服务端 v4 API 通信，为终端、脚本、CI、VSCode 插件提供稳定命令层。

整体系统按三类知识域组织：

- `KNOWLEDGE_BASE`：结构化知识库，通过 `tag` 区分 design、flow、alg 等子类。
- `SKILL`：技能包导入、检索、下载。
- `MEMORY`：会话记忆导入、检索、保存、下载等。

CLI 的核心契约：

- 成功输出：`{"ok":true,"data":...}`
- 失败输出：`{"ok":false,"error":{"code":"...","message":"..."}}`
- 默认业务错误写到 `stdout`，不写 `stderr`
- 退出码：`0` 成功，`1` 通用错误，`3` 命令未实现
- `BIBLE_CLI_BASE_URL` 优先于 `BIBLE_ATLAS_BASE_URL`
- `search --enable-hit` 的 skill/memory 分支失败时，主请求可降级成功并返回 `hit_warnings`

## 2. 当前已实现功能

### 基础与系统

- `bible health`
- `bible system status`
- `bible system info`

`system status/info` 仍使用 `/api/v1/system/*`，并 fallback 到 `/health`。v4 文档未定义新的 system control 路径，因此这是当前有意保留的兼容行为。

### Knowledge

- `bible knowledge list`
- `bible knowledge search --tag <tag> [query]`

当前已使用 v4 检索端点：

- `POST /api/search/knowledge-base`

列表接口优先使用：

- `GET /api/control/docs/list`

404 时 fallback 到：

- `GET /api/v1/knowledge/list`

### 顶层聚合搜索

- `bible search --query <query>`
- `--knowledge-tag <tag>`：指定后包含 knowledge 检索
- `--enable-hit`：启用 skill/memory 附加检索
- `--hit-types skill,memory`：控制附加检索类型

hit 检索已使用 v4：

- `POST /api/search/skill`
- `POST /api/search/memory`

### Memory

已实现：

- `memory upload`
- `memory upload-all`
- `memory build-meta`
- `memory status`
- `memory list`
- `memory search`
- `memory download`
- `memory cache-status`
- `memory get`
- `memory save`

涉及能力：

- 本地 `message.json` 到 `meta.json` 构建
- 本地 `.bible-memory-cache.json` 幂等缓存
- `POST /api/import/memory`
- `POST /api/search/memory`
- `POST /api/download/memory/file`
- `GET /api/download/memory/artifact/{id}`
- `GET /api/control/admin/tasks/{id}`
- `--wait` 轮询异步任务

### Skills

已实现：

- `skills list`
- `skills search`
- `skills get`
- `skills upload`
- `skills download`

涉及 v4 API：

- `POST /api/search/skill`
- `POST /api/import/skill`
- `POST /api/download/skill/file`
- `GET /api/download/skill/artifact/{id}`

### Session 兼容

`session list/get/save` 仍保留，但语义上 deprecated，建议使用：

- `memory list`
- `memory get`
- `memory save`

### Task

已实现：

- `task get`
- `task status`
- `task cancel`

涉及 v4 API：

- `GET /api/control/admin/tasks/{id}`
- `DELETE /api/control/admin/tasks/{id}`

## 3. 当前主要缺口

### 3.1 `knowledge import`

服务端 v4 已定义：

- `POST /api/import/knowledge-base`

CLI 已实现对应命令：

```bash
bible knowledge import --file <path> --kb-index <index> --tag <tag> [--vector-model <model>] [--wait]
```

也可支持多文件：

```bash
bible knowledge import --file a.md --file b.md --kb-index kb_design --tag design --wait
```

### 3.2 `memory download`

v4 已定义 MEMORY 下载：

- `POST /api/download/memory/file`
- `POST /api/download/memory/batch`
- `GET /api/download/memory/artifact/{artifact_id}`

CLI 已实现 `memory download`，复用异步下载任务与 artifact 拉取流程，支持单文件 `/file` 与多 `--storage-path` 触发的 `/batch` ZIP 下载。

### 3.3 通用 task 命令

已新增通用 task 命令：

```bash
bible task get <task_id>
bible task status <task_id>
bible task cancel <task_id>
```

对应：

- `GET /api/control/admin/tasks/{task_id}`
- `DELETE /api/control/admin/tasks/{task_id}`

### 3.4 已解析但未完整生效的参数

以下 list 参数已补齐请求体透传：

- `memory list --tag`
- `memory list --since`
- `memory list --page`
- `skills list --page`

仍需单独评估的低优先级项：

- `memory upload --output table`

当前 CLI 主输出契约是统一 JSON，`table` 输出会破坏机器可解析性，因此不建议默认实现；如果确有人工交互需求，应作为显式兼容模式另行设计。

### 3.5 文档状态滞后

`bible_cli_go/docs/IMPLEMENTATION_PLAN.md` 中部分“待迁移 v3 端点”的描述已经被当前代码完成，例如：

- `Search()` hit 已复用 v4 `SkillSearch()` / `MemorySearch()`
- `KnowledgeSearch()` 已迁移到 `POST /api/search/knowledge-base`
- `KnowledgeList()` 已优先使用 `/api/control/docs/list`
- `memory get/save` 与 `--knowledge-tag` 已落地

建议先更新该计划文档，避免后续开发误判。

## 4. 推荐后续开发步骤

### Step 1: 校准文档与契约

目标：

- 更新 `README.md`
- 更新 `docs/IMPLEMENTATION_PLAN.md`
- 明确 Go CLI 当前是 v4 主实现，不再以 Python phase1 CLI 作为功能上限
- 保留 Python 契约测试作为历史/兼容参考，而不是 Go CLI 完备性标准

验证：

```bash
go test ./...
```

### Step 2: 实现 `knowledge import`（已完成）

改动建议：

- `internal/cli/run.go`：解析 `knowledge import`
- `internal/cli`：必要时新增 knowledge flags 文件
- `internal/commands/handlers.go` 或新建 `knowledge.go`
- `internal/client/http/memory.go`：新增 `KnowledgeImportRequest`
- `internal/client/http`：实现 multipart `POST /api/import/knowledge-base`
- `printHelp()` 与 `normalizeActionAlias()`：补齐帮助和别名

必须支持：

- `--file`
- `--kb-index`
- `--tag`
- `--vector-model`
- `--wait`
- 可选 `--parser-context`

验证：

```bash
go test ./internal/client/http/... -v -run TestKnowledge
go test ./internal/cli/... -v -run TestRunKnowledge
go test ./...
```

### Step 3: 实现 `memory download`（已完成）

改动建议：

- 复用现有 `DownloadFile()`
- 复用现有 `PollTask()`
- 复用现有 `GetArtifact()`
- 参考 `skills download` 的输出路径、等待逻辑和错误处理

建议命令：

```bash
bible memory download <memory_id> --output <dir> [--wait]
bible memory download --storage-path <path> --output <dir> [--wait]
```

验证：

```bash
go test ./internal/cli/... -v -run TestRunMemory
go test ./...
```

### Step 4: 新增通用 `task` 命令（已完成）

建议命令：

```bash
bible task get <task_id>
bible task cancel <task_id>
```

实现路径：

- `internal/cli/run.go` 新增 `task`
- `internal/commands/task.go`
- `internal/client/http/memory.go` 增加 `CancelTask()`
- `printHelp()` 更新

验证：

```bash
go test ./internal/client/http/... -v -run TestTask
go test ./internal/cli/... -v -run TestRunTask
go test ./...
```

### Step 5: 补齐 flag 透传

逐项补齐：

- `memory list --tag`
- `memory list --since`
- `memory list --page`
- `skills list --page`
- `memory upload --output`

验证重点：

- 请求体是否包含对应字段
- 空值是否不传或按服务端契约传
- 默认值是否与 README/配置一致

### Step 6: 加强回归门禁

建议 PR 前执行：

```bash
go test ./...
go vet ./...
go build ./...
go test ./... -race
```

或直接：

```bash
./build.sh
```

## 5. 验证方法

当前上游 VSCode 插件和下游 Atlas 服务端尚未完全 ready 时，不应等待端到端链路完成后再验证 CLI。`bible_cli_go` 应按 **contract-first** 思路验证：先证明命令输入、输出协议、HTTP 请求形状、错误映射和异步流程正确。

### 5.1 本地快速验证

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go
go test ./...
go vet ./...
go build ./...
```

### 5.2 严格验证

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go
./build.sh
```

`build.sh` 会执行：

1. `go vet ./...`
2. `go build -o ./target/bible ./cmd/bible-cli/`
3. `go test ./... -race -count=1 -timeout=120s`

### 5.3 真实服务冒烟

需要 Atlas 服务端已启动：

```bash
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555

./target/bible health
./target/bible system status
./target/bible knowledge list
./target/bible search --query "test" --enable-hit
```

如果要验证 import/download，必须确认：

- API 进程已启动
- Celery Worker 已启动
- 相关 `kb_index`、`tag`、`vector_model` 与服务端配置一致

### 5.4 新命令测试要求

每个新增命令至少覆盖：

- 成功路径
- 缺少必填参数，返回 `INVALID_ARGS`
- 服务端 404 或 fallback 行为
- 服务端 5xx 错误传播
- 501 映射为 `SEV_NOT_IMPLEMENTED`
- 超时映射为 `TIMEOUT`

测试应使用 `httptest.NewServer`，不要依赖真实服务。

### 5.5 插件和服务端未就绪时的调试策略

#### 5.5.1 验证目标

在没有真实插件和完整服务端的情况下，重点验证以下内容：

- CLI 参数解析是否正确。
- 成功/失败是否都输出单行 JSON 信封。
- exit code 是否符合契约：`0` 成功，`1` 通用错误，`3` 未实现。
- HTTP method/path/body/multipart 字段是否符合 v4 API 文档。
- import/download 的异步流程是否能完成：submit -> task poll -> artifact download。
- HTTP 400/404/409/501/5xx/timeout 是否映射为正确错误码。

#### 5.5.2 使用 mock server 验证服务端契约

服务端未完成时，使用 Go 测试里的 `httptest.NewServer` 作为 mock server。测试应断言 CLI 发出的请求，而不是断言真实业务结果。

建议重点覆盖：

- `knowledge import` 是否请求 `POST /api/import/knowledge-base`。
- multipart 是否包含 `files`、`kb_index`、`tag`、可选 `parser_script`。
- `knowledge search` 是否请求 `POST /api/search/knowledge-base`，且 body 中包含 `query`、`tag`。
- `memory download` 单文件是否请求 `POST /api/download/memory/file`。
- `memory download` 多 `--storage-path` 是否请求 `POST /api/download/memory/batch`。
- `skills download` 多 `--storage-path` 是否请求 `POST /api/download/skill/batch`。
- `task cancel` 是否请求 `DELETE /api/control/admin/tasks/{task_id}`。

当前已有相关测试覆盖：

```bash
go test ./internal/cli/... -v
go test ./internal/client/http/... -v
```

#### 5.5.3 用 CLI 直接代替插件调试

插件未完成时，直接执行编译出的 CLI 来模拟插件调用：

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go
go build -o ./target/bible ./cmd/bible-cli/

./target/bible health
./target/bible knowledge import --file README.md --kb-index kb_test --tag design
./target/bible knowledge search --tag design "test"
./target/bible memory download --storage-path memory/a --storage-path memory/b --package-name memories.zip --output /tmp
./target/bible task get task-123
```

插件后续只需要读取 stdout JSON 和 exit code，例如：

```json
{"ok":true,"data":{"task_id":"task-123","status":"queued"}}
{"ok":false,"error":{"code":"INVALID_ARGS","message":"--tag is required for knowledge search."}}
```

因此在插件未 ready 前，CLI 的验收重点是：

- stdout 是否始终是 JSON。
- stderr 默认是否为空。
- `BIBLE_CLI_LEGACY_STDERR=1` 时是否额外输出历史文本错误。
- exit code 与 JSON `error.code` 是否一致。

#### 5.5.4 不做假集成

当前阶段不要为了“端到端看起来能跑”而在 CLI 中加入临时假逻辑或 fallback：

- 不要为了绕过服务端未实现而改 API 路径。
- 不要吞掉服务端错误码。
- 不要把失败输出改成非 JSON 文本。
- 不要在 commands 层直接访问文件或网络绕过 client 层。

正确做法是用 mock server 锁定 CLI 契约；等服务端 ready 后，只做真实 E2E 冒烟。

#### 5.5.5 服务端 ready 后的真实 E2E 冒烟

服务端和 Worker 都可用后，再执行真实链路：

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

如果 import/download 卡在 `queued`，优先检查 Celery Worker 是否启动，而不是修改 CLI。

### 5.6 本地 mock Atlas server

为了在真实服务端和插件都未完成时验证 CLI，项目内提供了轻量测试服务器：

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go

# 终端 1：启动 mock server
go run ./cmd/bible-mock-server --addr 127.0.0.1:5555

# 终端 2：构建 CLI 并指向 mock server
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

mock server 覆盖当前 CLI 需要的主要端点：

- `/health`
- `/api/v1/system/status`、`/api/v1/system/info`
- `/api/control/docs/list`
- `/api/search/knowledge-base`、`/api/search/memory`、`/api/search/skill`
- `/api/import/knowledge-base`、`/api/import/memory`、`/api/import/skill`
- `/api/download/{memory|skill}/file`
- `/api/download/{memory|skill}/batch`
- `/api/download/{memory|skill}/artifact/{artifact_id}`
- `/api/control/admin/tasks/{task_id}` 的 `GET` / `DELETE`

mock server 只验证 CLI 契约和调用流程，不验证真实服务端能力：

- 不做真实 parser 执行。
- 不做向量化。
- 不访问 OpenSearch。
- 不启动 Celery Worker。
- 不验证真实文件存储与权限。

因此 mock server 通过后，只能说明 CLI 的命令解析、请求形状、JSON 输出和异步流程正确；真实业务正确性仍需等 Atlas 服务端 ready 后做 E2E。

## 6. 开发规则摘要

新增命令按以下顺序修改：

1. `internal/cli/run.go`：命令解析与 opts 填充
2. `internal/cli/*_flags.go`：复杂 flag 单独拆文件
3. `internal/commands/*.go`：业务分发
4. `internal/client/http/*.go`：HTTP 方法
5. `printHelp()`：帮助文本
6. `normalizeActionAlias()`：别名
7. `*_test.go`：client 层和 CLI 层测试

必须遵守：

- stdout 只输出统一 JSON
- commands 层不直接发 HTTP
- client 层不读取配置文件
- 不新增全局变量
- 单测不依赖真实服务器

## 7. 建议优先级

推荐顺序：

1. 文档校准
2. `knowledge import`
3. `memory download`
4. `task get/cancel`
5. flag 透传补齐
6. race/golden/真实服务冒烟完善

这个顺序优先补齐服务端 v4 已定义但 CLI 未暴露的能力，风险较低，收益直接。
