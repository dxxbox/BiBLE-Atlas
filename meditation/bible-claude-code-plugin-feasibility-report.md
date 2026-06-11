# BiBLE Claude Code Plugin — Architecture Design

> Status: draft | Date: 2026-06-11

## Overview

A Claude Code plugin that integrates BiBLE Atlas as a memory + knowledge broker.
Three components: a persistent daemon, an MCP server, and lifecycle hooks.

## Design Journey

This section captures the Q&A flow that shaped the architecture — why each decision was made and what alternatives were considered.

### Q1: Primary motivation?

**Chosen: Full integration (C)** — Context recall/injection + session capture + agent tools. Not just tools-only or memory-only. The plugin should mirror what bible-hermes-plugin does for Hermes Agent.

### Q2: What can we learn from claude-mem?

Before choosing an approach, we analyzed the `claude-mem` plugin (v13.4.1, by thedotmack) which is already running in this session. Key findings:

- **Architecture**: Hook system (Setup, SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop) → Worker daemon (HTTP :37777, SQLite) → MCP server (stdio) → Skills (slash commands)
- **claude-mem built everything from scratch** because no external memory server existed: own SQLite, own ChromaDB vector store, own LLM observation pipeline, own schema migrations
- **BiBLE Atlas already provides all of that**: OpenSearch for search, Celery for async tasks, full HTTP API, file storage. The plugin is a *bridge*, not a replacement.

### Q3: Language?

**Chosen: Python** — Reuses bible-hermes-plugin's HTTP client, recall pipeline, ranking, and config modules directly. The hermes plugin is ~1,200 lines of Python total because it delegates everything to the server.

### Q4: Who are the users?

**Chosen: Both individual + team (C)** — Developers, but also writers, reporters, teachers. Not code-only. BiBLE serves as a general knowledge/memory broker, not a code-specific tool.

### Q5: Where does BiBLE Atlas live?

**Chosen: Doesn't matter (D)** — The plugin just needs a base URL. Local, team server, cloud — all opaque to the plugin.

### Q6: What gets captured as memory?

**Chosen: Key moments, configurable (C)** — Not full transcripts, not summary-only. Three moment types matter:
- **Session start** — defines topic scope
- **Decision moment** — user confirms a choice/approach (MUST have)
- **Accomplishment moment** — something verified and accepted; session focus shifts

Explicitly NOT captured: intermediate bug fixes (model/user mistakes), unconfirmed discoveries (side notes).

### Q7: How does context recall work?

**Chosen: Auto-inject + explicit tools (D)** — BiBLE plays the role of a *broker/summoner* of knowledge and memory. Claude Code already manages skills well natively. So the tool surface excludes skill tools — only memory + knowledge tools remain.

### Q8: Who detects key moments?

**Chosen: Plugin-side LLM (C)** — The daemon has its own LLM call (configurable model) to classify moments. Not heuristic regex, not delegated to BiBLE server's AI pipeline. This implies the daemon needs: buffering, prompt construction, LLM API integration, and structured output parsing.

### Q9: Hook-based capture or daemon-based?

**Chosen: Worker daemon, claude-mem style (C)** — Given plugin-side LLM detection, multi-user/team scenarios, and Claude Code sessions that can end abruptly or run in parallel, a persistent daemon with durable SQLite buffer is the only architecture that won't lose moments.

### Why Not The Alternatives

| Alternative | Why Rejected |
|---|---|
| **Thin scripts + server-side LLM** | User wants plugin-side moment detection (Q8) |
| **In-memory MCP server only** | Buffer lost on crash/restart; can't survive session boundaries |
| **Full transcript capture** | Too noisy; user explicitly wants key moments only (Q6) |
| **Include skill tools** | Claude Code manages skills natively; BiBLE focuses on memory + knowledge (Q7) |

---

## Scenario Summary

| Dimension | Decision |
|---|---|
| **Users** | Individuals + teams; developers, writers, reporters, teachers |
| **BiBLE location** | Opaque to plugin — just a base URL |
| **Primary domains** | Memory + Knowledge brokerage (skills are Claude Code's domain) |
| **Capture content** | Key moments: session-start topics, decisions, accomplishments |
| **Capture mode** | Configurable; key-moments by default |
| **Context recall** | Auto-inject + explicit tools both available |
| **Moment detection** | Plugin-side LLM call (worker daemon) |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Claude Code                             │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │  Setup   │  │SessionSt │  │UserPrompt │  │   Stop    │  │
│  │  Hook    │  │   art    │  │  Submit   │  │   Hook    │  │
│  │          │  │  Hook    │  │   Hook    │  │           │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
│       │             │              │               │        │
│       │    ┌────────┼──────────────┼───────────────┘        │
│       │    │        │              │                         │
│       │    │   ┌────▼──────────────▼──────┐                  │
│       │    │   │  MCP Server (stdio)      │                  │
│       │    │   │  bible_memory_search     │                  │
│       │    │   │  bible_memory_save       │                  │
│       │    │   │  bible_knowledge_search  │                  │
│       │    │   │  ...                     │                  │
│       │    │   └────────────┬─────────────┘                  │
│       │    │                │                                │
└───────┼────┼────────────────┼────────────────────────────────┘
        │    │                │
        ▼    ▼                ▼
┌──────────────────────────────────────────────┐
│         Bible CC Daemon (HTTP :9777)          │
│                                               │
│  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │  Session │  │  Moment  │  │   Context    │ │
│  │  Buffer  │  │ Detector │  │   Injector   │ │
│  │ (SQLite) │  │  (LLM)   │  │              │ │
│  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │             │               │        │
└───────┼─────────────┼───────────────┼────────┘
        │             │               │
        ▼             ▼               ▼
┌──────────────────────────────────────────────┐
│            BiBLE Atlas Server                 │
│  (memory / knowledge search, save, import)    │
└──────────────────────────────────────────────┘
```

### Three Components

| Component | Role | Transport | Lifetime |
|---|---|---|---|
| **Daemon** (`bible-cc-daemon`) | Buffer turns, detect key moments via LLM, flush to BiBLE, serve context for injection | HTTP on `localhost:9777` | Persistent (managed by hooks) |
| **MCP Server** (`bible-cc-mcp`) | 6 BiBLE tools (memory search/save/get, knowledge search/list) + daemon status tool | Stdio (MCP protocol) | Per Claude Code session |
| **Hooks** | Glue — start daemon, inject context, feed turns to daemon | Shell → HTTP calls to daemon | Event-driven |

### Key Design Decisions

- Daemon port `9777` (non-standard, avoid conflicts)
- SQLite at `~/.bible-cc/daemon.db` (per-user)
- BiBLE Atlas URL configured once, shared by all components
- Skill tools excluded — Claude Code manages skills natively
- Tools: `bible_memory_search`, `bible_memory_save`, `bible_memory_get`, `bible_knowledge_search`, `bible_knowledge_list`

### Capture Taxonomy (Key Moments)

- **Session start** — defines topic scope
- **Decision moment** — user confirms a choice or approach
- **Accomplishment moment** — something verified and accepted by user; session focus shifts

Non-key (not captured):
- Intermediate bug fixes (model/user mistakes)
- Discoveries (side notes, unless user confirms as significant)

### Hook → Daemon Flow

| Hook | Daemon Endpoint | Purpose |
|---|---|---|
| Setup | `POST /daemon/start` | Start daemon if not running |
| SessionStart | `POST /session/start` + `POST /context/inject` | Register session, get context injection string |
| UserPromptSubmit | `POST /turn/user` | Feed user message to buffer |
| PostToolUse | `POST /turn/tool` | Feed tool call to buffer |
| Stop | `POST /session/end` | Trigger moment detection + flush to BiBLE |

---

## Daemon Design

### HTTP API

```
POST /daemon/start       — idempotent, returns {pid, port, status}
POST /daemon/stop        — graceful shutdown
GET  /daemon/health      — {status: "ok", uptime: 1234, sessions: 3}

POST /session/start      — {session_id} → creates session row
POST /session/end        — {session_id} → triggers flush + moment detection

POST /turn/user          — {session_id, message} → buffer turn
POST /turn/assistant     — {session_id, message, tool_calls[]} → buffer turn

POST /context/inject     — {session_id, user_message}
                           → returns "<relevant-memories>..." string
```

### SQLite Schema

```sql
-- Active sessions
CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY,
    started_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    topic_scope    TEXT,
    turn_count     INTEGER DEFAULT 0,
    buffered_chars INTEGER DEFAULT 0
);

-- Buffered turns (raw conversation)
CREATE TABLE turns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    seq           INTEGER NOT NULL,
    role          TEXT NOT NULL,      -- user | assistant
    content       TEXT NOT NULL,
    tool_calls    TEXT,               -- JSON array of {name, arguments}
    timestamp     TEXT NOT NULL
);

-- Detected key moments
CREATE TABLE moments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    moment_type   TEXT NOT NULL,      -- session_start | decision | accomplishment
    title         TEXT NOT NULL,
    narrative     TEXT NOT NULL,
    turn_range    TEXT,               -- e.g. "3-7"
    detected_at   TEXT NOT NULL,
    flushed       INTEGER DEFAULT 0  -- 0=pending, 1=sent to BiBLE
);
```

### Moment Detection Flow

```
UserPromptSubmit ─→ buffer turn ─→ check threshold
                                      │
                    ┌─────────────────┘ (every N turns or N chars)
                    ▼
              ┌──────────────┐
              │ Build prompt │  ← last K turns + session context
              └──────┬───────┘
                     ▼
              ┌──────────────┐
              │   LLM Call   │  ← Claude API (configurable model)
              └──────┬───────┘
                     ▼
              ┌──────────────┐
              │ Parse result │  → structured moments or "none"
              └──────┬───────┘
                     ▼
              ┌──────────────┐
              │ Save to      │
              │ moments table│  ← pending flush
              └──────────────┘
```

### Moment Detection Prompt (sketch)

```
You are analyzing a conversation between a user and an AI agent.
Identify if any KEY MOMENTS occurred in these recent turns.

Key moment types:
- SESSION_START: the user defines the topic/scope of work
- DECISION: the user confirms a choice, approach, or design direction
- ACCOMPLISHMENT: something was completed, verified, and accepted

Do NOT flag:
- Intermediate bug fixes or error corrections
- Exploratory discoveries (unless user explicitly confirms importance)

For each key moment found, provide:
- type: one of the above
- title: one-line summary
- narrative: 2-4 sentences describing what happened and why it matters
```

### BiBLE HTTP Client

Reused from bible-hermes-plugin: `http_client.py` (BibleAtlasClient class) —
`search_memory()`, `search_knowledge()`, `save_memory()`, `get_memory()`.
The daemon imports this module directly; no code duplication.

---

## MCP Server Design

A thin wrapper around `BibleAtlasClient` (reused from bible-hermes-plugin).
Stdio transport, launched per Claude Code session.

### Tools

| Tool | Parameters | Returns |
|---|---|---|
| `bible_memory_search` | query, top_k, min_score | hits[] |
| `bible_memory_save` | messages[], title, abstract | {memory_id, task_id} |
| `bible_memory_get` | memory_id | {title, overview, ...} |
| `bible_knowledge_search` | query, tag, top_k | hits[] |
| `bible_knowledge_list` | tag | [{name, description}] |

### Discovery (`.mcp.json`)

```json
{
  "mcpServers": {
    "bible-atlas": {
      "command": "python",
      "args": ["-m", "bible_cc_plugin.mcp_server"],
      "env": {
        "BIBLE_ATLAS_BASE_URL": "http://localhost:5555"
      }
    }
  }
}
```

## Hooks Design

Glue between Claude Code lifecycle events and the daemon. Two small CLI entry points
under the `bible-cc` namespace: `bible-cc-daemon` (lifecycle) and `bible-cc-hook` (thin
wrappers that curl the daemon).

### Hook → Daemon Mapping

```
Setup ──────────────────────────────────────────────────────────────
  → bible-cc-daemon --start          (idempotent, no-op if running)
  → ensures config exists (prompt setup if missing)

SessionStart ───────────────────────────────────────────────────────
  → POST /session/start  {session_id}
  → POST /context/inject {session_id, user_message}
  → returns context string → injected into Claude's system prompt

UserPromptSubmit ───────────────────────────────────────────────────
  → POST /turn/user  {session_id, message}

PostToolUse ────────────────────────────────────────────────────────
  → POST /turn/tool  {session_id, tool_name, arguments, result_summary}

Stop ───────────────────────────────────────────────────────────────
  → POST /session/end  {session_id}
  → daemon runs moment detection → flushes key moments to BiBLE
```

### hooks/hooks.json (sketch)

```json
{
  "hooks": {
    "Setup": [{
      "command": "bible-cc-daemon --start",
      "timeout": 10000
    }],
    "SessionStart": [{
      "command": "bible-cc-hook session-start --session-id \"$CLAUDE_SESSION_ID\"",
      "timeout": 15000,
      "inject": true
    }],
    "UserPromptSubmit": [{
      "command": "bible-cc-hook turn-user --session-id \"$CLAUDE_SESSION_ID\" --message \"$USER_PROMPT\"",
      "timeout": 5000
    }],
    "PostToolUse": [{
      "command": "bible-cc-hook turn-tool --session-id \"$CLAUDE_SESSION_ID\" --tool \"$TOOL_NAME\"",
      "timeout": 5000
    }],
    "Stop": [{
      "command": "bible-cc-hook session-end --session-id \"$CLAUDE_SESSION_ID\"",
      "timeout": 30000
    }]
  }
}
```

- `bible_memory_save` (MCP tool) also calls `POST /daemon/notify` so the daemon
  knows a manual memory was saved and can skip re-injecting it as context.
- `PostToolUse` truncates tool result content to 250 chars by default
  (configurable via `tool_result_max_chars`) — enough for moment detection,
  not full file contents.

---

## Config System

Single YAML file at `~/.bible-cc/config.yaml`. Environment variable overrides
take precedence (matching the hermes plugin pattern).

### Schema

```yaml
# ── BiBLE Atlas connection ──
bible:
  base_url: "http://localhost:5555"    # BIBLE_ATLAS_BASE_URL
  token: null                          # BIBLE_ATLAS_TOKEN (optional)

# ── Daemon ──
daemon:
  port: 9777                           # BIBLE_CC_DAEMON_PORT
  db_path: "~/.bible-cc/daemon.db"    # BIBLE_CC_DB_PATH

# ── Context recall ──
recall:
  enable_memory: true
  enable_knowledge: false
  knowledge_tags: []
  top_k: 8
  min_score: 0.35
  injection_token_budget: 1200
  force_injection: false               # ignore enable flags, always recall

# ── Session capture ──
capture:
  enabled: true
  mode: "key_moments"                  # key_moments | full | off
  commit_threshold_turns: 8            # trigger detection every N turns
  commit_threshold_chars: 16000        # trigger detection after N chars
  tool_result_max_chars: 250           # truncate tool results in hook

# ── Moment detection ──
detection:
  model: "claude-sonnet-4-5"           # LLM for moment classification
  max_tokens: 512
  temperature: 0.0

# ── Bypass ──
bypass:
  session_patterns: []                 # regex patterns to skip
```

### Setup flow

```
bible-cc setup
  → prompts for BiBLE base URL
  → writes ~/.bible-cc/config.yaml
  → starts daemon
  → verifies connectivity to BiBLE Atlas
```

### Credentials

- **BiBLE Atlas**: `BIBLE_ATLAS_TOKEN` env var or `bible.token` in config.yaml
- **LLM (moment detection)**: Daemon inherits `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_API_KEY` from Claude Code's environment — no separate config needed.
  The Anthropic Python SDK auto-detects these.

---

## Package Structure

```
bible-cc-plugin/
├── pyproject.toml
├── plugin.json                     ← .claude-plugin manifest
├── .mcp.json                       ← MCP server discovery
├── hooks/
│   └── hooks.json                  ← hook definitions
├── bible_cc_plugin/
│   ├── __init__.py
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── server.py               ← HTTP server (:9777)
│   │   ├── buffer.py               ← SQLite session/turn/moment store
│   │   ├── detector.py             ← LLM moment detection
│   │   └── injector.py             ← context injection (calls BiBLE recall)
│   ├── mcp_server.py               ← MCP stdio server
│   ├── cli.py                      ← bible-cc CLI entry points
│   ├── config.py                   ← config loading (adapted from hermes)
│   └── client.py                   ← BiBLE HTTP client (reused from hermes)
└── tests/
    ├── test_daemon.py
    ├── test_detector.py
    ├── test_buffer.py
    └── test_mcp_server.py
```

**Distribution:** `pip install bible-cc-plugin` — single command. User then adds it
to Claude Code's plugin registry. Configuration via `bible-cc setup` wizard.
