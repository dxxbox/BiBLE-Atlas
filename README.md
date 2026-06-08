# BiBLE Atlas

BiBLE Atlas is an **agent-native context management database** that provides semantic retrieval and progressive content loading for AI agents. It lets you set up domain knowledge, maintain session memory, and equip agents with recallable skills — all through a unified HTTP API consumed by plugins across multiple LLM ecosystems (OpenClaw, Hermes, VSCode Copilot).

BiBLE Atlas provides both **rapid mode** (default) and **thinking mode** for different latency/quality trade-offs.

---

## Table of Contents

- [Architecture](#architecture)
- [Components](#components)
- [Quick Start](#quick-start)
- [Environment Setup](#environment-setup)
- [Configuration](#configuration)
- [Plugins](#plugins)
  - [bible-oc-plugin (OpenClaw)](#bible-oc-plugin-openclaw)
  - [bible-hermes-plugin (Hermes Agent)](#bible-hermes-plugin-hermes-agent)
  - [bible-vscode (VSCode Extension)](#bible-vscode-vscode-extension)
- [CLI Client](#cli-client)
- [API Overview](#api-overview)
- [Documentation](#documentation)
- [Development](#development)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Agent / User Layer                           │
│                                                                       │
│  OpenClaw Agent    Hermes Agent    VSCode Copilot    CLI / Scripts   │
│       │                 │                │                │          │
│  ┌────┴────┐      ┌────┴────┐      ┌────┴────┐      ┌────┴────┐     │
│  │ OC      │      │ Hermes  │      │ VSCode  │      │ Go CLI  │     │
│  │ Plugin  │      │ Plugin  │      │ Ext     │      │ Client  │     │
│  └────┬────┘      └────┬────┘      └────┬────┘      └────┬────┘     │
│       │                │                │                │          │
│       └────────────────┴────────────────┴────────────────┘          │
│                                 │ HTTP                                │
└─────────────────────────────────┼────────────────────────────────────┘
                                  │
┌─────────────────────────────────┼────────────────────────────────────┐
│                    BiBLE Atlas Server (FastAPI)                        │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐     │
│  │  Import  │  │  Search  │  │ Download │  │  System/Control  │     │
│  │  API     │  │  API     │  │  API     │  │  API             │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘     │
│       │              │             │                 │               │
│  ┌────┴──────────────┴─────────────┴─────────────────┴────┐          │
│  │                   Feature Layer                         │          │
│  │  knowledge_base / skill / memory   async_task (Celery) │          │
│  └────────────────────────┬───────────────────────────────┘          │
│                           │                                           │
│  ┌────────────────────────┴───────────────────────────────┐          │
│  │                 Infrastructure Layer                     │          │
│  │  OpenSearch / Elasticsearch / Postgres                  │          │
│  │  Local FS / MinIO / S3                                  │          │
│  │  Vector Embedding / Rerank Models                       │          │
│  └─────────────────────────────────────────────────────────┘          │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Components

### BiBLE Atlas Server (`bible/`)

Python FastAPI backend. The core server handles three knowledge domains:

| Domain | Description |
|---|---|
| **KNOWLEDGE_BASE** | Structured knowledge (design docs, algorithms, code, specs) — organized by `tag` → index |
| **SKILL** | Skill packages (`.skill` format) that AI agents can invoke |
| **MEMORY** | Session memories — conversation context persisted for future recall |

Key capabilities:
- **Semantic search** with hybrid text+vector retrieval, multi-model embedding (BGE-M3, E5, MPNet, MiniLM), and cross-encoder reranking
- **Async import pipeline** via Celery workers with custom parser sandboxing (AST guard + subprocess isolation)
- **Multi-backend storage**: OpenSearch (default), Elasticsearch, Postgres for search; Local FS, MinIO, S3 for file storage
- **Test mode**: Fixture-based integration testing with artifact capture and response replay

### BiBLE CLI (`bible_cli_go/`)

Go-based command-line client. Structured JSON output for scripting and CI.

```bash
bible health
bible knowledge search --tag design "query"
bible memory upload /path/to/session --kb-index my-kb --wait
bible skills search "skill name" --top-k 5
bible search --query "cross-domain search" --enable-hit
```

- Full coverage of knowledge, memory, skill, and task operations
- Async task submit + poll (`--wait` flag)
- Local idempotency cache (skip duplicate uploads)
- Config via env vars, `~/.bible/config.json`, or CLI flags

### BiBLE VSCode Extension (`bible_vscode/`)

VSCode extension integrating Bible Atlas with Copilot Chat.

- **LLM tools**: `bible_memory_search`, `bible_memory_save`, `bible_memory_get`, plus knowledge and skill tools
- **User commands**: `Bible: Save Current Chat as Memory`, `Bible: Search Memory`, `Bible: Run Self-Check`
- **Dry-run mode**: Validate CLI args and payload construction without a running server
- **Mock CLI**: Isolated development against a Node-based mock binary

---

## Plugins

### bible-oc-plugin (OpenClaw)

> **Location**: `bible-oc-plugin/` | **Language**: TypeScript | **Platform**: OpenClaw ≥ 2026.5.18

A **context-engine plugin** for [OpenClaw](https://openclaw.ai) that replaces the default memory system with BiBLE Atlas.

**Features:**
- **Auto-recall** — `context.assemble()` runs a parallel recall pipeline (memory + skill + knowledge) and injects `<relevant-memories>` into the system prompt
- **Session capture** — `afterTurn` buffers turns; auto-commits to BiBLE Atlas at configurable thresholds
- **Session lifecycle** — `on_session_start`, `on_session_end`, `before_reset` hooks manage per-session state
- **7 agent tools** — `bible_memory_search`, `bible_memory_save`, `bible_memory_get`, `bible_knowledge_search`, `bible_knowledge_list`, `bible_skill_search`, `bible_skill_get`
- **CLI** — `openclaw bible setup --base-url <url> [--write]` and `openclaw bible status`
- **Bypass patterns** — Regex patterns skip recall/capture for specific sessions

**Quick install:**
```bash
cd bible-oc-plugin
npm install && npm run build
openclaw plugins install . --force
openclaw gateway restart
openclaw bible setup --base-url http://127.0.0.1:5555 --write
openclaw bible status
```

See [TESTING_GUIDE.md](bible-oc-plugin/TESTING_GUIDE.md) for full setup and verification instructions.

### bible-hermes-plugin (Hermes Agent)

> **Location**: `bible-hermes-plugin/` | **Language**: Python ≥ 3.10 | **Platform**: [Hermes Agent](https://hermes-agent.nousresearch.com)

A feature-matched plugin for the Hermes Agent ecosystem — same recall, capture, and tool surface as the OpenClaw plugin.

**Features:**
- **Auto-recall** — `pre_llm_call` hook runs the BiBLE Atlas recall pipeline before each LLM turn
- **Session capture** — `post_llm_call` hook buffers turns; async flush at turn/character thresholds
- **Lifecycle hooks** — `on_session_start`, `on_session_end`, `on_session_reset`
- **7 agent tools** — identical tool surface: `bible_memory_*`, `bible_knowledge_*`, `bible_skill_*`
- **CLI** — `hermes bible setup --base-url <url> [--write]` and `hermes bible status`
- **Slash command** — `/bible status` in any Hermes session
- **Force injection** — `force_injection: true` runs recall on every user message regardless of domain flags
- **Force capture** — `force_capture: true` immediately flushes each turn instead of batching
- **Graceful degradation** — If unconfigured, only the CLI command registers; all hooks and tools skip until setup

**Quick install:**
```bash
./deploy.sh              # sync + install to ~/.hermes
./deploy.sh --restart    # also restart Hermes after
./deploy.sh --watch      # tail -f plugin logs after
hermes plugins enable bible-hermes-plugin
```

Configuration via `~/.hermes/config.yaml`:
```yaml
bible:
  base_url: "http://localhost:5555"
  enable_memory_recall: true
  enable_skill_recall: true
  recall_top_k: 10
  capture_enabled: true
  bypass_session_patterns:
    - "^scratch:"
    - "^test-"
```

See the [plugin README](bible-hermes-plugin/README.md) for full config schema, troubleshooting, and pip-based distribution.

---

## Quick Start

### 1. Start the BiBLE Atlas Server

```bash
# Clone and enter repo
cd BiBLE-Atlas

# Set up Python environment
uv sync --all-extras
source .venv/bin/activate

# Start the server (default: http://0.0.0.0:5555)
uv run python -m bible.main
```

### 2. Verify with CLI

```bash
cd bible_cli_go
go build -o ./target/bible ./cmd/bible-cli/
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555
./target/bible health
```

### 3. Connect an Agent Plugin

**OpenClaw:**
```bash
cd bible-oc-plugin && npm install && npm run build
openclaw plugins install . --force
openclaw bible setup --base-url http://127.0.0.1:5555 --write
```

**Hermes:**
```bash
cd bible-hermes-plugin && ./deploy.sh --restart
hermes bible setup --base-url http://127.0.0.1:5555 --write
```

---

## Environment Setup

```bash
uv sync --all-extras
source .venv/bin/activate
```

> **Note:** Python 3.10+ is required. Install optional extras for vector models (`vector`), MinIO (`minio`), or S3 (`s3`) as needed.

---

## Configuration

The server is configured via `bible-atlas.yaml` (YAML, supports hot-reload):

| Section | Purpose |
|---|---|
| `log` | Logging level, format, output target |
| `storage` | Workspace directory for data persistence |
| `file_system` | File storage backend: `local`, `minio`, or `s3` |
| `database` | Search backend: `opensearch`, `elasticsearch`, or `postgres` |
| `celery` | Async task broker (Redis) and worker config |
| `import_memory` | Import sandboxing, timeouts, workspace TTL |
| `vector` | Embedding models (BGE-M3, E5, MPNet, MiniLM) |
| `rerank` | Cross-encoder reranker models |
| `tag_to_index_mapping` | Knowledge base tag → index routing |
| `copilot_config` | AI-enhanced search integration |

Key env vars: `BIBLE_SERVER_HOST`, `BIBLE_SERVER_PORT`, `BIBLE_ATLAS_BASE_URL`, `BIBLE_ATLAS_TOKEN`.

---

## API Overview

### Import
| Endpoint | Description |
|---|---|
| `POST /api/import/knowledge-base` | Import knowledge base files (multipart) |
| `POST /api/import/skill` | Import skill packages |
| `POST /api/import/memory` | Import session memory |

All import endpoints return `202` with a `task_id` for async processing.

### Search
| Endpoint | Description |
|---|---|
| `POST /api/search/knowledge-base` | Semantic search across knowledge bases |
| `POST /api/search/memory` | Search session memories |
| `POST /api/search/skill` | Search skill packages |

### Download
| Endpoint | Description |
|---|---|
| `POST /api/download/{domain}/file` | Download single file by storage path |
| `POST /api/download/{domain}/batch` | Batch download as ZIP |
| `GET /api/download/{domain}/artifact/{id}` | Fetch a download artifact |

### Control
| Endpoint | Description |
|---|---|
| `GET /api/control/admin/tasks/{id}` | Query async task status |
| `DELETE /api/control/admin/tasks/{id}` | Cancel an async task |
| `GET /api/control/docs/list` | List knowledge base documents |
| `GET /health` | Health check |

---

## Documentation

### Architecture & Design
- [Server v4 Architecture](docs/designs/server_part/v4/01_架构总览.md) — Directory structure, layered responsibilities, core flows
- [Server v4 API Reference](docs/designs/server_part/v4/02_API接口文档.md) — Complete endpoint specification
- [Knowledge Base Parser Design](docs/designs/server_part/v4/03_KNOWLEDGE_BASE解析与安全执行设计.md) — Custom parser sandboxing
- [v3 → v4 Migration](docs/designs/server_part/v4/04_v3_to_v4迁移清单.md) — Migration checklist
- [Celery Async Task Design](docs/designs/server_part/v4/07_Celery通用异步任务机制设计与实现.md) — Async task architecture
- [Test Mode Design](docs/designs/server_part/v4/08_TestMode_Detail_Design.md) — Fixture-based integration testing
- [VSCode Extension Design](docs/designs/client_part/01-bible-vscode-extension-design.md) — Client architecture & boundary decisions

### Implementation Guides
- [Import Implementations](docs/designs/server_part/v4/import_implementations/) — Per-domain import details
- [Search Implementations](docs/designs/server_part/v4/search_implementations/) — Search pipeline implementation
- [Download Implementations](docs/designs/server_part/v4/download_implementations/) — Async download & artifact lifecycle
- [Infrastructure Implementations](docs/designs/server_part/v4/infrastructure_implementation/) — Database & file system adapters

### Manuals
- [Go CLI User Guide](docs/manual/go-cli-user-guide.md)
- [CLI Contract v1](docs/manual/cli-contract-v1.md) — JSON envelope contract
- [Test Mode User Guide](docs/manual/test-mode-user-guide.md)

### Design Notes (`meditation/`)
- [OC Plugin Design](meditation/oc-plugin/) — Architecture, auto-recall, capture, tools, implementation plan
- [Hermes Plugin Evolution](meditation/bible-hermes-plugin-evolution.md)
- [Test Mode Requirements](meditation/bible-test-mode-requirements.md)

---

## Development

### Before Submitting Code

```bash
# Format & lint Python code
uv run format path/to/file.py
uv run check --fix path/to/file.py
uv run mypy path/to/file.py

# Go CLI
cd bible_cli_go
go test ./... -race
go vet ./...
go build ./...

# Hermes plugin
cd bible-hermes-plugin
make check       # ruff lint + basedpyright typecheck
make test        # pytest with coverage

# OC plugin
cd bible-oc-plugin
npm run typecheck
npm test
npm run build
```

### Repository Layout

```
BiBLE-Atlas/
├── bible/                     # Python FastAPI server
│   ├── api/                   #   REST API routes (import, search, system)
│   ├── features/              #   Business logic (import, search, async_task)
│   ├── infrastructure/        #   Database, file system, vector tools
│   ├── config/                #   YAML config loader
│   ├── common/                #   Shared types, errors, logging
│   └── test_mode/             #   Fixture-based test server
├── bible_cli_go/              # Go CLI client
├── bible_vscode/              # VSCode extension (TypeScript)
├── bible-oc-plugin/           # OpenClaw context-engine plugin (TypeScript)
├── bible-hermes-plugin/       # Hermes Agent plugin (Python)
├── docs/                      # Architecture & design documentation
│   ├── designs/server_part/   #   Server v3/v4 designs
│   ├── designs/client_part/   #   Client extension designs
│   └── manual/                #   User guides
├── meditation/                # Design thinking & evolution notes
├── tests/                     # Server integration tests
├── bible-atlas.yaml           # Server configuration
└── pyproject.toml             # Python project metadata
```

---

## License

MIT — See [LICENSE](LICENSE).
