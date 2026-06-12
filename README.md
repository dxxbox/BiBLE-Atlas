<p align="center">
  <h1 align="center">BiBLE Atlas</h1>
  <p align="center"><strong>Agent-Native Context Management Database</strong><br>Agent-native 上下文管理数据库</p>
</p>

---

BiBLE Atlas is a semantic search backend purpose-built for AI agents. It stores, indexes, and retrieves context across three knowledge domains — <strong>Knowledge Bases</strong>, <strong>Skills</strong>, and <strong>Memory</strong> — and surfaces the right information at the right time through a unified REST API. Agent plugins consume that API to auto-recall relevant context before each LLM turn, capture conversations as persistent memory, and expose search/save tools directly to the agent.

BiBLE Atlas 是一个专为 AI Agent 打造的语义检索引擎。它跨三个知识域（<strong>知识库</strong>、<strong>技能包</strong>、<strong>会话记忆</strong>）存储与索引上下文，通过统一的 REST API 在正确的时间呈现正确的信息。Agent 插件消费该 API，在每次 LLM 调用前自动召回相关上下文，将对话持久化为记忆，并向 Agent 暴露搜索/保存工具。

---

## Table of Contents / 目录

- [Architecture / 架构](#architecture--架构)
- [Quick Start / 快速开始](#quick-start--快速开始)
- [Project Layout / 项目结构](#project-layout--项目结构)
- [Server / 服务端](#server--服务端)
- [Clients / 客户端](#clients--客户端)
- [Configuration / 配置](#configuration--配置)
- [Development / 开发](#development--开发)

---

## Architecture / 架构

```
                           BiBLE Atlas Server (FastAPI)
                          ┌─────────────────────────────┐
  ┌──────────┐            │  POST /api/search/*          │
  │ Go CLI   │─── HTTP ──▶│  POST /api/import/*          │──── OpenSearch / ES / PG
  └──────────┘            │  POST /api/download/*        │──── Redis (Celery broker)
  ┌──────────┐            │  GET  /api/control/admin/*   │──── Local / MinIO / S3
  │ VS Code  │─── HTTP ──▶│                              │──── HuggingFace models
  │ Extension│            │  Three-Domain Model:          │
  └──────────┘            │  KNOWLEDGE_BASE · SKILL · MEMORY │
  ┌──────────┐            └─────────────────────────────┘
  │ OC       │─── HTTP ──▶
  │ Plugin   │
  └──────────┘
```

### Three-Domain Model / 三域模型

| Domain / 域 | Purpose / 用途 | Import / 导入 | Search / 搜索 | Download / 下载 |
|---|---|---|---|---|
| `KNOWLEDGE_BASE` | Structured docs, design specs, code references / 结构化文档与参考资料 | `POST /api/import/knowledge-base` | `POST /api/search/knowledge-base` | — |
| `SKILL` | Reusable `.skill` packages for agent invocation / 可复用技能包 | `POST /api/import/skill` | `POST /api/search/skill` | `POST /api/download/skill/*` |
| `MEMORY` | Conversation context persisted across sessions / 跨会话持久记忆 | `POST /api/import/memory` | `POST /api/search/memory` | `POST /api/download/memory/*` |

### Search Pipeline / 检索流水线

```
Query → Keyword Match + Vector Semantic Search → Score Fusion → Rerank → Filter → Results
查询 → 关键词匹配 + 向量语义检索 → 分数融合 → 重排序 → 筛选 → 结果
```

- **Keyword**: Full-text search via OpenSearch / 基于 OpenSearch 的全文检索
- **Vector**: Semantic similarity via sentence-transformers (BGE / E5 / MiniLM) / 基于 sentence-transformers 的语义相似度
- **Hybrid**: Weighted combination of both / 加权混合
- **Rerank**: Cross-encoder re-scoring of top candidates / 对候选结果进行 cross-encoder 重打分
- **Filter**: None, elbow, or gap-statistic result trimming / 无筛选、肘部法则或间隙统计

### Async Import / 异步导入

```
POST /api/import/* → 202 {task_id}
                      │
                      ▼
              Celery Worker picks up task
                      │
                      ▼
         Sandboxed parser (AST-checked, timeout-guarded)
                      │
                      ▼
         Chunks → OpenSearch  +  Files → Storage
                      │
                      ▼
         GET /api/control/admin/tasks/{id} → status
```

All imports are asynchronous. The API returns `202` immediately. Clients poll task status or use `--wait`.

所有导入均为异步。API 立即返回 `202`。客户端可轮询任务状态或使用 `--wait`。

---

## Quick Start / 快速开始

### Prerequisites / 环境要求

| Tool | Min Version | Purpose |
|---|---|---|
| Python | 3.10+ | Server runtime |
| [uv](https://docs.astral.sh/uv/) | latest | Package & venv management |
| Go | 1.20+ | CLI (optional) |
| Node.js | 20+ | VS Code / OC plugin (optional) |
| Docker or Podman | 20+ / 4+ | OpenSearch & Redis (optional, not needed for Test Mode) |

### 1. Clone & Install / 克隆并安装

```bash
git clone <repo-url> && cd BiBLE-Atlas
uv sync --all-extras
source .venv/bin/activate
```

### 2. Start Infrastructure / 启动基础设施

Use `env-prepare.sh` as the entry point — it runs pre-flight checks (Docker availability, required CLIs, Python venv) before touching any service.

使用 `env-prepare.sh` 作为入口——它会先执行前置检查（Docker 可用性、所需 CLI、Python 虚拟环境），再操作服务。

```bash
# Full backend (OpenSearch + Redis + Celery, requires Docker running / 完整后端，需要 Docker 运行)
./scripts/env-prepare.sh setup

# Test Mode (lightweight, no Docker needed / 轻量模式，无需 Docker)
./scripts/env-prepare.sh setup --test-mode
```

In interactive full-backend mode, `env-prepare.sh` asks for a Docker registry mirror and OpenSearch CPU/memory, using Docker-aware defaults. For automation, set the same values through environment variables:

完整后端交互模式会询问 Docker 镜像站和 OpenSearch CPU/内存，并根据 Docker 可用资源给出默认值。自动化场景可通过环境变量指定：

```bash
BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ \
BIBLE_OPENSEARCH_CPU_CORES=2 \
BIBLE_OPENSEARCH_MEMORY_GB=6 \
./scripts/env-prepare.sh setup --full opensearch
```

Teardown is conservative by default: it stops services and removes local build artifacts, but preserves user-level config/plugin state and repo runtime data. Use explicit purge flags when you really want to remove those:

默认清理偏保守：停止服务并删除本地构建产物，但保留用户级配置/插件状态和项目运行时数据。如需删除这些内容，需要显式加 purge 参数：

```bash
./scripts/env-prepare.sh teardown --force
./scripts/env-prepare.sh teardown --force --purge-workspace --purge-config --uninstall-plugins
```

For manual control, the underlying deploy scripts are at `scripts/opensearch_deploy/deploy.sh` and `scripts/redis_celery_deploy/deploy.sh` — but note they do **not** perform pre-flight checks.

如需手动控制，底层部署脚本位于 `scripts/opensearch_deploy/deploy.sh` 和 `scripts/redis_celery_deploy/deploy.sh`——但注意它们**不**做前置检查。

### 3. Configure & Run / 配置并运行

Edit `bible-atlas.yaml` — set your OpenSearch host, Redis broker URL, and optional model preferences.
编辑 `bible-atlas.yaml`，设置 OpenSearch 地址、Redis broker URL 和可选模型偏好。

```bash
uv run python -m bible.main
# → http://127.0.0.1:5555
```

### 4. Verify / 验证

```bash
curl http://127.0.0.1:5555/health
# → {"status": "ok"}
```

### Optional Extras / 可选依赖

```bash
uv sync --extra vector   # sentence-transformers for vector search
uv sync --extra minio    # MinIO object storage backend
uv sync --extra s3       # AWS S3 backend
uv sync --extra test     # pytest, fakeredis, httpx
uv sync --extra dev      # mypy, ruff
```

---

## Project Layout / 项目结构

```
BiBLE-Atlas/
├── bible/                       # Python server (FastAPI) / Python 服务端
│   ├── api/                     #   REST route definitions (thin layer) / 路由定义
│   │   ├── search/              #     Search endpoints (memory, knowledge, skill)
│   │   ├── upload/              #     Import endpoints (memory, skill)
│   │   ├── control/             #     Admin endpoints (task management)
│   │   ├── knowledge.py         #     Knowledge base route aggregation
│   │   ├── system.py            #     Health-check & system info
│   │   └── deps.py              #     FastAPI dependency injection
│   ├── features/                #   Business logic / 业务逻辑
│   │   ├── search/              #     Search engine (keyword + vector + hybrid + rerank)
│   │   ├── upload/              #     Import pipeline (parser sandbox + storage)
│   │   └── async_task/          #     Celery app, dispatcher, worker
│   ├── infrastructure/          #   Backend abstractions / 基础设施
│   │   ├── database/            #     OpenSearch / Elasticsearch / PostgreSQL
│   │   ├── file_system/         #     Local / MinIO / S3
│   │   └── vector/              #     Embedding & rerank model management
│   ├── config/                  #   YAML config loader (hot-reload)
│   ├── test_mode/               #   Fixture-driven test server (no real backends needed)
│   └── main.py                  #   Application entry point
│
├── bible_cli_go/                # Go CLI / Go 命令行客户端
│   ├── cmd/bible-cli/           #   Entry point
│   └── internal/                #   Commands, HTTP client, config, cache, protocol
│
├── bible_vscode/                # VS Code Extension / VS Code 扩展
│   └── src/                     #   TypeScript: core infrastructure + domain modules
│
├── bible-oc-plugin/             # OpenClaw Plugin / OpenClaw 插件
│   └── src/                     #   TypeScript: context engine + agent tools
│
│
├── tests/                       # Python server tests / 服务端测试
├── docs/                        # Design docs & user manuals / 设计文档与用户手册
├── scripts/                     # Deployment & ops scripts / 部署运维脚本
├── bible-atlas.yaml             # Server configuration (hot-reload) / 服务端配置
├── pyproject.toml               # Python project metadata & tool config
├── build_all.sh                 # One-click build: all modules → release/
└── CLAUDE.md                    # AI coding agent guidance / AI 编码指南
```

---

## Server / 服务端

### Tech Stack / 技术栈

| Component | Choice |
|---|---|
| Framework | FastAPI (Python 3.10+) |
| Database | OpenSearch (primary), Elasticsearch, PostgreSQL |
| Message Queue | Celery + Redis |
| File Storage | Local disk, MinIO, AWS S3 |
| Vector Models | sentence-transformers (BGE, E5, MiniLM, MPNet) |
| Rerank Models | Cross-encoder (BGE Reranker, MS MARCO) |

### Key Endpoints / 主要接口

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/v1/system/status` | System status & version |
| `POST` | `/api/search/knowledge-base` | Search knowledge bases (keyword/vector/hybrid) |
| `POST` | `/api/search/memory` | Search memory |
| `POST` | `/api/search/skill` | Search skills |
| `POST` | `/api/import/knowledge-base` | Import knowledge base files (async) |
| `POST` | `/api/import/memory` | Import memory (async) |
| `POST` | `/api/import/skill` | Import skill package (async) |
| `POST` | `/api/download/memory/file` | Download memory artifact |
| `POST` | `/api/download/skill/file` | Download skill artifact |
| `POST` | `/api/download/{domain}/batch` | Batch download (ZIP) |
| `GET` | `/api/control/admin/tasks/{id}` | Query async task status |
| `DELETE` | `/api/control/admin/tasks/{id}` | Cancel async task |
| `GET` | `/api/control/docs/list` | List knowledge base indices |

### Test Mode / 测试模式

A fixture-driven test server that requires no real backend — useful for plugin development and CI.

无需真实后端的测试服务器，适合插件开发和 CI。

```bash
uv run python -m bible.test_mode.server --port 5555
```

### Running Tests / 运行测试

```bash
uv run pytest tests/ -v                           # all tests
uv run pytest tests/ -v -k "test_search"          # single test
BIBLE_ATLAS_CONFIG=bible-atlas.yaml uv run pytest tests/ -v  # with real config
```

---

## Clients / 客户端

### Go CLI (`bible_cli_go/`)

A full-featured command-line client. All output is structured JSON. Exit codes: 0 = success, 1 = error, 3 = not implemented.

功能完整的命令行客户端。所有输出为结构化 JSON。

```bash
go build -o ./target/bible ./cmd/bible-cli/

# Health & system
./target/bible health
./target/bible system status

# Knowledge base search (--tag required)
./target/bible knowledge search --tag design "scheduler algorithm"

# Memory operations
./target/bible memory search "deployment config" --top-k 10
./target/bible memory upload /path/to/session --kb-index my-kb --wait
./target/bible memory download --output /tmp/ <memory_id>

# Skill operations
./target/bible skills search "L2PS scheduler" --top-k 5
./target/bible skills upload --file demo.skill --kb-index my-kb --wait

# Aggregated search (knowledge + skill + memory)
./target/bible search --query "scheduler" --knowledge-tag design --enable-hit

# Async task management
./target/bible task get <task_id>
./target/bible task cancel <task_id>
```

See [bible_cli_go/README.md](bible_cli_go/README.md) for full documentation.
完整文档见 [bible_cli_go/README.md](bible_cli_go/README.md)。

### VS Code Extension (`bible_vscode/`)

A VS Code / Cursor extension providing memory save/search/download directly in the editor. Features:

- **Search Memory** — Interactive QuickPick with preview and load-to-chat
- **Save Current Chat as Memory** — Export Copilot Chat, extract metadata via LM, submit via CLI
- **Self-Check** — Probe CLI availability and capabilities
- **Dry-Run mode** — Validate payloads without a real CLI or server
- Requires the Go CLI binary to be installed

在 VS Code / Cursor 中直接提供记忆保存/搜索/下载的扩展。

```bash
cd bible_vscode
npm install
npm run vsix              # package .vsix
code --install-extension bible-vscode.vsix --force
```

See [bible_vscode/README.md](bible_vscode/README.md) for full documentation.

### OpenClaw Plugin (`bible-oc-plugin/`)

A `context-engine` plugin for OpenClaw that provides:

- **Auto-recall** — Searches BiBLE Atlas before each LLM turn via the `assemble` lifecycle method
- **Session capture** — Buffers and flushes conversation turns via `afterTurn`
- **7 agent tools** — `bible_memory_search/save/get`, `bible_knowledge_search/list`, `bible_skill_search/get`
- **CLI commands** — `setup` and `status`
- **Graceful degradation** — Skips all hooks and tools if unconfigured

```bash
cd bible-oc-plugin
npm install
npm run typecheck && npm run build && npm test
```

### Hermes Plugin (`bible-hermes-plugin/`)

> **This plugin has been split into its own repository.**
> See [bible-hermes-plugin](https://github.com/dxxbox/bible-hermes-plugin) for installation, usage, and development guide.

### Plugin Architecture / 插件架构

All plugins share the same design — they are thin HTTP wrappers around the BiBLE Atlas API:

1. **Auto-Recall Pipeline**: Query → deduplicate → score-filter → token-budget-truncate → inject as context block
2. **Session Capture**: Buffer exchanges → flush at turn-count or character-count thresholds
3. **Agent Tools**: Direct HTTP wrappers — no search logic in the plugin
4. **Graceful Degradation**: If `base_url` is not set, only CLI setup/status register; all hooks and tools skip

所有插件共享同一设计——它们只是 BiBLE Atlas API 的薄 HTTP 封装层。

---

## Configuration / 配置

Server configuration lives in `bible-atlas.yaml` with hot-reload support (no restart needed on config changes).
服务端配置位于 `bible-atlas.yaml`，支持热更新（修改后无需重启）。

### Key Sections / 主要配置节

| Section | Description |
|---|---|
| `log` | Log level, format, and output target |
| `workspace` | Runtime artifacts root directory |
| `file_system` | File storage backend: `local`, `minio`, or `s3` |
| `database` | Database backend: `opensearch`, `elasticsearch`, or `postgres` |
| `celery` | Async task broker URL and worker concurrency |
| `import_memory` | Memory import: parser dirs, sandbox timeout, TTL |
| `import_skill` | Skill import: parser dirs, allowed extensions, limits |
| `search` | Search defaults: `top_k`, search types, filter mode |
| `vector` | Embedding models: BGE / E5 / MiniLM / MPNet |
| `rerank` | Cross-encoder re-ranking: BGE Reranker / MS MARCO |
| `copilot_config` | Optional AI-enhanced search via Copilot CLI |

### Plugin Configuration / 插件配置

Plugins resolve config from env vars → host config file:

| Env Variable | OC (`openclaw.json`) | Default |
|---|---|---|---|
| `BIBLE_ATLAS_BASE_URL` `baseUrl` | *(required)* |
| `BIBLE_ATLAS_TOKEN` | `token` | — |
| — | `enableMemoryRecall` | `true` |
| — | `recallTopK` | `8` |
| — | `recallMinScore` | `0.35` |
| — | `injectionTokenBudget` | `1200` |

---

## Development / 开发

### One-Click Build / 一键编译

```bash
./build_all.sh              # Full: lint, build, test → release/
./build_all.sh --skip-test  # Skip tests
```

Artifacts are written to `release/` (gitignored). A `BUILD_INFO.md` is auto-generated.
产物输出到 `release/`（已 gitignore），自动生成 `BUILD_INFO.md`。

### Lint & Type Check / 代码检查

```bash
# Python
uv run ruff format bible/          # format
uv run ruff check bible/            # lint
uv run mypy bible/                  # type check

# Go
cd bible_cli_go && go vet ./... && go test ./... -race

# TypeScript (VS Code / OC plugin)
cd bible_vscode && npx tsc --noEmit
cd bible-oc-plugin && npm run typecheck

```

### CI / 持续集成

GitHub Actions run on `push` and `pull_request`:

| Workflow | Coverage |
|---|---|
| `_lint.yml` | `ruff format --check` + `ruff check` + `mypy` on changed `.py` files |
| `_test_lite.yml` | pytest across Python 3.10 / 3.11 / 3.12 |
| `_go_cli.yml` | Go vet + build + test with race detection |

### Commit Conventions / 提交规范

- Branch: feature work on `feature/*`, merge to `main` after CI passes
- Commit messages: brief title (≤72 chars), explain "why" in body, split unrelated changes
- Never commit `release/`, `.env`, API keys, or secrets

---

## License

See [LICENSE](LICENSE).
