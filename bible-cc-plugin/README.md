# bible-cc-plugin

BiBLE Atlas plugin for [Claude Code](https://claude.ai/code) — memory + knowledge broker, automatic session capture with smart moment detection, and MCP tools.

## What it does

- **Auto-recall** — Before each session, searches BiBLE Atlas for relevant past memories and injects them as context so Claude remembers your project history across sessions.
- **Smart session capture** — Buffers conversation turns and uses an LLM (Claude API) to detect *key moments* (session topic, decisions, accomplishments), then saves them to BiBLE Atlas. No more saving noise — only what matters.
- **MCP tools** — Five agent-callable tools for explicit memory and knowledge operations: `bible_memory_search`, `bible_memory_save`, `bible_memory_get`, `bible_knowledge_search`, `bible_knowledge_list`.
- **Graceful degradation** — If BiBLE Atlas is unreachable or unconfigured, tools and hooks degrade gracefully. Run `bible-cc setup` to get started.

## Requirements

- Python ≥ 3.10
- A running [BiBLE Atlas](https://github.com/NousResearch/bible-atlas) server
- [Claude Code](https://claude.ai/code) installed
- [uv](https://docs.astral.sh/uv/) (for install)

## Quick start

```bash
cd bible-cc-plugin

# 1. Deploy
./deploy.sh --setup

# 2. Follow the setup wizard (or answer with defaults)
#    BiBLE Atlas base URL [http://localhost:5555]:
#    BiBLE Atlas token (optional):

# 3. Start Claude Code — the daemon auto-starts via Setup hook
```

After setup, BiBLE Atlas integration is active. Open any Claude Code session — relevant memories from past sessions will be injected automatically.

## Installation

### Via deploy script (recommended)

```bash
cd bible-cc-plugin
./deploy.sh
```

This syncs source files to `~/.claude/plugins/bible-cc-plugin/`, installs with `uv`, and enables the plugin.

| Flag | What it does |
|---|---|
| `--setup` | Run `bible-cc setup` wizard after install |
| `--restart` | Restart the daemon after install |
| `--watch` | Tail the plugin log after install |
| `--help` | Show usage |

### Manual install

```bash
cd bible-cc-plugin
uv pip install .
```

Then add to `~/.claude/settings.json`:

```json
{
  "bible-cc-plugin": true
}
```

## Configuration

Configuration lives at `~/.bible-cc/config.yaml`. Environment variables override YAML values.

### Minimal config

```yaml
bible:
  base_url: "http://localhost:5555"
```

### Full config with defaults

```yaml
# ── BiBLE Atlas connection ──
bible:
  base_url: "http://localhost:5555"    # BIBLE_ATLAS_BASE_URL
  token: null                          # BIBLE_ATLAS_TOKEN (optional bearer token)
  timeout_ms: 30000

# ── Daemon ──
daemon:
  port: 9777
  db_path: "~/.bible-cc/daemon.db"

# ── Context recall ──
recall:
  enable_memory: true                   # search memory before each session
  enable_knowledge: false               # also search knowledge bases
  knowledge_tags: []                    # which knowledge tags to search
  top_k: 8                              # max results per domain
  min_score: 0.35                       # minimum relevance (0–1)
  injection_token_budget: 1200          # token budget for injected context
  force_injection: false                # recall all domains regardless of flags

# ── Session capture ──
capture:
  enabled: true
  mode: "key_moments"                   # key_moments | full | off
  commit_threshold_turns: 8             # detect moments every N turns
  commit_threshold_chars: 16000         # detect moments after N chars
  tool_result_max_chars: 250            # truncate tool results for detection

# ── Moment detection ──
detection:
  model: "claude-sonnet-4-5"            # LLM for classifying moments
  max_tokens: 512
  temperature: 0.0

# ── Bypass ──
bypass:
  session_patterns: []                  # regex patterns — matching sessions skip capture + recall
```

### Environment variables

| Variable | Overrides |
|---|---|
| `BIBLE_ATLAS_BASE_URL` | `bible.base_url` |
| `BIBLE_ATLAS_TOKEN` | `bible.token` |
| `BIBLE_CC_CONFIG_PATH` | Config file location |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | LLM API key (for moment detection) |

The daemon inherits `ANTHROPIC_API_KEY` from Claude Code's own environment — no separate API key config needed.

## How it works

### Architecture

```
Claude Code hooks  ──→  Daemon (HTTP :9777, SQLite)  ──→  BiBLE Atlas
       │                       │
       └─── MCP Server ────────┘
```

Three components work together:

| Component | What it does | Runs |
|---|---|---|
| **Daemon** (`bible-cc-daemon`) | Buffers turns to SQLite, detects key moments via LLM, flushes to BiBLE Atlas, serves context for injection | Persistent, managed by hooks |
| **MCP Server** (`bible-cc-mcp`) | 5 tools Claude can call directly: `bible_memory_*`, `bible_knowledge_*` | Per session, stdio transport |
| **Hooks** | Glue — start daemon on Setup, inject context on SessionStart, feed turns on UserPromptSubmit/PostToolUse, flush on Stop | Event-driven shell commands |

### Hook lifecycle

| Hook | What happens |
|---|---|
| **Setup** | `bible-cc-daemon --start` — daemon starts (no-op if already running) |
| **SessionStart** | Daemon registers session + queries BiBLE Atlas for relevant past memories → injected as context |
| **UserPromptSubmit** | User message buffered to daemon |
| **PostToolUse** | Tool call buffered (truncated to 250 chars) |
| **Stop** | Daemon runs moment detection on buffered turns → detected key moments flushed to BiBLE Atlas |

### Key moment detection

The daemon buffers conversation turns in local SQLite. When a session ends (or a threshold is hit), it calls Claude API with a structured prompt to identify:

- **Session start** — the user defined a topic or scope
- **Decision** — the user confirmed a choice or approach
- **Accomplishment** — something was completed, verified, and accepted

Intermediate bug fixes and unconfirmed discoveries are intentionally NOT captured. Only moments the user confirmed or that changed the session direction are saved.

## CLI reference

```
bible-cc setup                  # interactive config wizard
bible-cc status                 # show connection, recall, capture, daemon status

bible-cc-daemon --start         # start daemon (idempotent)
bible-cc-daemon --stop          # stop daemon
bible-cc-daemon --status        # check if daemon is running

bible-cc-hook session-start --session-id <id> --message <msg>
bible-cc-hook session-end   --session-id <id>
bible-cc-hook turn-user     --session-id <id> --message <msg>
bible-cc-hook turn-tool     --session-id <id> --tool <name> --message <summary>
```

## MCP tools

These are available to Claude during any session (configured via `.mcp.json`):

| Tool | Parameters | What it does |
|---|---|---|
| `bible_memory_search` | `query`, `top_k?`, `min_score?` | Search past memories by relevance |
| `bible_memory_save` | `messages[]`, `title?`, `abstract?`, `wait?` | Save a memory explicitly |
| `bible_memory_get` | `memory_id` | Retrieve a specific memory |
| `bible_knowledge_search` | `query`, `tag`, `top_k?` | Search knowledge bases |
| `bible_knowledge_list` | `tag?` | List available knowledge bases |

When `bible_memory_save` is called, the daemon is notified so it won't re-inject the same content as context.

## Troubleshooting

### "BIBLE_ATLAS_BASE_URL is required"

Run `bible-cc setup` or set the `BIBLE_ATLAS_BASE_URL` environment variable.

### Daemon not running

```bash
bible-cc-daemon --status
bible-cc-daemon --start
```

The daemon also auto-starts on next Claude Code session via the Setup hook. Check `~/.bible-cc/logs/bible-cc-plugin.log` for errors.

### No memories recalled

- Check `bible-cc status` — is `recall: memory=on`?
- Is the BiBLE Atlas server reachable? `curl <base_url>/health`
- Adjust `recall.min_score` lower (e.g. `0.2`) for more results
- Set `recall.force_injection: true` to recall regardless of domain flags

### Moment detection not working

- Verify `ANTHROPIC_API_KEY` is set in your environment
- Check `~/.bible-cc/logs/bible-cc-plugin.log` for detection errors
- Try a cheaper/faster model: set `detection.model: "claude-haiku-4-5"`

### Claude Code doesn't see MCP tools

Make sure `.mcp.json` is present in the plugin directory and the plugin is enabled. Restart Claude Code after enabling.

### Port 9777 already in use

Set `daemon.port` in `~/.bible-cc/config.yaml` to a different port.

## Files and directories

| Path | Purpose |
|---|---|
| `~/.bible-cc/config.yaml` | Plugin configuration |
| `~/.bible-cc/daemon.db` | SQLite buffer (sessions, turns, moments) |
| `~/.bible-cc/daemon.pid` | Daemon PID file |
| `~/.bible-cc/logs/bible-cc-plugin.log` | Plugin log |
| `~/.claude/plugins/bible-cc-plugin/` | Installed plugin files |
