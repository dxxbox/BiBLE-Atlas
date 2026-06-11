# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BiBLE Atlas is an agent-native context management database. A Python FastAPI server (backed by OpenSearch) provides semantic search over three knowledge domains — **KNOWLEDGE_BASE**, **SKILL**, **MEMORY** — through a unified REST API. Agent plugins for OpenClaw, Hermes, and VSCode consume that API to auto-recall relevant context before each LLM turn, capture conversation turns as persistent memory, and expose domain tools to agents.

## Build, Test, and Lint Commands

### Server (`bible/`)

```bash
uv sync --all-extras          # install all deps including vector models
source .venv/bin/activate

# Run the server
uv run python -m bible.main

# Test mode server (fixture-driven, no real OpenSearch/Celery needed)
uv run python -m bible.test_mode.server --port 5555

# Tests
uv run pytest tests/ -v                          # all tests
uv run pytest tests/server/test_memory_search_service.py -v -k "test_search"  # single test
BIBLE_ATLAS_CONFIG=bible-atlas.yaml uv run pytest tests/ -v   # with real config

# Lint & type-check
uv run ruff check bible/
uv run ruff format bible/
uv run mypy bible/
```

### Go CLI (`bible_cli_go/`)

```bash
go build -o ./target/bible ./cmd/bible-cli/   # build
go test ./...                                  # all tests (self-contained, http mocks)
go test ./... -race                            # recommended for PRs
go test ./internal/cli/... -v -run TestRunHealth  # single test
go vet ./...
```

### Hermes Plugin (`bible-hermes-plugin/`)

```bash
make check       # ruff lint + basedpyright type-check
make fix         # auto-fix lint/format
make test        # pytest with coverage
make typecheck   # basedpyright only
# Single test:
uv run pytest tests/ -v -k "test_recall"
```

### OC Plugin (`bible-oc-plugin/`)

```bash
npm install
npm run typecheck    # tsc --noEmit
npm test             # vitest
npm run build        # tsc compile → dist/
```

### VSCode Extension (`bible_vscode/`)

```bash
npm install
npm run compile      # tsc check + esbuild
npm run watch        # dev mode
npm run vsix         # package .vsix for local install
```

## Architecture

### Three-Domain Model

All data belongs to one of three domains, each with its own import/search/download pipelines:

| Domain | Import endpoint | Search endpoint | Download |
|---|---|---|---|
| `KNOWLEDGE_BASE` | `POST /api/import/knowledge-base` | `POST /api/search/knowledge-base` | none |
| `SKILL` | `POST /api/import/skill` | `POST /api/search/skill` | `POST /api/download/skill/...` |
| `MEMORY` | `POST /api/import/memory` | `POST /api/search/memory` | `POST /api/download/memory/...` |

Knowledge bases are organized by `tag` → index mapping (configured in `bible-atlas.yaml`). Skills are `.skill` packages for agent invocation. Memory is conversation context persisted across sessions.

### Server Layering (`bible/`)

```
api/          → FastAPI route definitions (thin — delegates to features)
features/     → Business logic: import, search, async_task (Celery)
  import/       → memory_import/ (parser sandboxing + storage), parser_runtime/ (AST guard + sandbox runner)
  search/       → memory_search/, knowledge_base_search/, skill_search/ + common/ (hit mapping, query compilation)
  async_task/   → Celery app, dispatcher, worker, Redis repository
infrastructure/ → database/ (OpenSearch, Elasticsearch, Postgres), file_system/ (local, MinIO, S3), vector/ (embedding + rerank models)
config/        → YAML config loader (bible-atlas.yaml, hot-reload capable)
test_mode/     → Fixture-driven test server — replays recorded HTTP responses, no real backend needed
```

**Async import flow**: API returns `202 {task_id}` → Celery worker picks up task → parser runs in sandboxed subprocess (AST-checked first) → chunks written to OpenSearch + files to storage → task status queryable via `GET /api/control/admin/tasks/{id}`.

### Plugin Architecture

Both plugins (`bible-oc-plugin` and `bible-hermes-plugin`) are **feature-symmetric** — they provide the same capabilities on different agent platforms:

1. **Auto-recall pipeline**: Before each LLM turn, query BiBLE Atlas for relevant memories/skills/knowledge → deduplicate → score-filter → token-budget-truncate → inject as `<relevant-memories>` context block.
2. **Session capture**: After each turn, buffer the exchange. Flush to BiBLE Atlas memory import at configurable thresholds (turn count or character count).
3. **7 agent tools**: `bible_memory_search/save/get`, `bible_knowledge_search/list`, `bible_skill_search/get`.
4. **CLI**: `setup --base-url <url> [--write]` and `status` commands.
5. **Graceful degradation**: If unconfigured (no `base_url`), only the CLI command registers; all hooks and tools skip.

The OC plugin implements this as a `context-engine` kind (with `assemble`/`afterTurn`/`compact` lifecycle methods). The Hermes plugin uses hook-based registration (`pre_llm_call`, `post_llm_call`, `on_session_start/end/reset`).

### Configuration Resolution (Plugins)

Both plugins share the same config schema with different naming conventions:
- **Hermes**: `snake_case` in `~/.hermes/config.yaml` under `bible:` key
- **OC**: `camelCase` in `~/.openclaw/openclaw.json` under `plugins.entries.bible-oc-plugin.config`

Key settings: `baseUrl`/`base_url` (required), `enableMemoryRecall`, `enableSkillRecall`, `enableKnowledgeRecall`, `recallTopK`, `recallMinScore`, `injectionTokenBudget`, `captureEnabled`, `bypassSessionPatterns`. OC plugin adds `forceInjection`/`forceCapture`; Hermes adds `force_injection`/`force_capture`.

Priority: environment variables (`BIBLE_ATLAS_BASE_URL`) > config file.

## Key Conventions

### JSON Envelope (Go CLI — non-negotiable)

All Go CLI stdout output must use the envelope format:
```json
{"ok":true,"data":{...}}
{"ok":false,"error":{"code":"INVALID_ARGS","message":"..."}}
```
Use `protocol.PrintSuccess`/`protocol.PrintFailure`. Never `fmt.Println` to stdout. Exit codes: 0 = success, 1 = error, 3 = not implemented.

### Test Mode

The server has a built-in test mode (`bible/test_mode/`) that serves a fixture-driven HTTP API without OpenSearch, Celery, or real file storage. Fixtures define request→response mappings. Use it for integration tests and plugin development when the real server isn't available.

### Bypass Patterns

Both plugins support `bypassSessionPatterns` — regex patterns that match session IDs. Matching sessions skip recall and capture entirely. This is the standard way to exclude scratch/test sessions from memory pollution.

### Parser Sandboxing

Custom knowledge-base parsers run in sandboxed subprocesses. Before execution, the parser script is AST-checked (`ast_guard.py`) to block dangerous imports/operations. Timeout and resource limits are enforced by `sandbox_runner.py`.

## Cross-Cutting Patterns

- **Import is always async**: Import endpoints return `202` immediately. Check task status via `GET /api/control/admin/tasks/{id}`. CLI `--wait` flag polls until completion.
- **Plugin tools are HTTP wrappers**: Agent tools in both plugins are thin wrappers around BiBLE Atlas HTTP API calls — they don't contain search logic themselves.
- **Config is pushed to the edge**: Server config lives in `bible-atlas.yaml`. CLI config merges env vars + `~/.bible/config.json`. Plugin config merges env vars + host config file. Nothing reads config from multiple layers deep in business logic.
- **Go CLI error types**: `protocol.CLIError{Code, Message, ExitCode}` — used throughout. `protocol.NotImplemented("action")` for unimplemented commands. `protocol.WrapAsCLIError(err)` for wrapping unexpected errors.
- **Hermes plugin uses in-process Python**: The plugin is installed into Hermes Agent's venv (`~/.hermes/hermes-agent/venv/`). A local `.venv` in the plugin directory is invisible to Hermes.
