# bible-hermes-plugin

BiBLE Atlas plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — memory recall, session capture, knowledge/skill tools, and CLI integration.

## Features

- **Auto-recall** — Before each LLM turn, searches BiBLE Atlas memory (and optionally skills/knowledge) and injects `<relevant-memories>` context via the `pre_llm_call` hook.
- **Session capture** — Buffers conversation turns in a thread-safe store and asynchronously commits them to BiBLE Atlas memory at configurable turn/character thresholds via `post_llm_call`.
- **Session lifecycle** — `on_session_start`, `on_session_end`, and `on_session_reset` hooks flush pending turns and manage per-session state.
- **Bypass patterns** — Regex patterns skip recall/capture for specific session IDs (e.g. `^scratch:`).
- **7 agent tools** — `bible_memory_search`, `bible_memory_save`, `bible_memory_get`, `bible_knowledge_search`, `bible_knowledge_list`, `bible_skill_search`, `bible_skill_get`.
- **CLI** — `hermes bible setup --base-url <url> [--write]` and `hermes bible status`.
- **Slash command** — `/bible status` inside any Hermes session.
- **Graceful degradation** — If `BIBLE_ATLAS_BASE_URL` is not set, only the CLI command is registered; all hooks and tools are skipped until setup completes.

## Requirements

- Python ≥ 3.10
- [httpx](https://www.python-httpx.org/) ≥ 0.27.0
- A running [BiBLE Atlas](https://github.com/NousResearch/bible-atlas) HTTP service

## Installation

### Directory plugin (recommended for personal use)

```bash
# Clone or copy this directory to your Hermes plugins folder
# while at bible folder.
cd ~/.hermes
source .venv/bin/activate
cp -r bible-hermes-plugin ~/.hermes/plugins/

# Install the plugin into Hermes Agent's Python environment.
# ⚠️  Do NOT create a .venv inside the plugin directory — Hermes runs from
# its own venv at ~/.hermes/hermes-agent/venv/, so packages installed in a
# local .venv are invisible to it.

cd ~/.hermes/plugins/bible-hermes-plugin
uv pip install .

uv pip install --python ~/.hermes/hermes-agent/venv/bin/python \
  ~/.hermes/plugins/bible-hermes-plugin/

# Enable
hermes plugins enable bible-hermes-plugin
```

> **Note:** `hermes plugins enable` only toggles the plugin on in config.
> It does NOT install the Python package. The `uv pip install` step above
> is required for Hermes to find the `bible_hermes_plugin` module.

### Pip / entry-point plugin (recommended for team distribution)

```bash
pip install bible-hermes-plugin   # or: uv pip install bible-hermes-plugin
# Hermes auto-discovers it via the hermes_agent.plugins entry point.
```

## Configuration

Set environment variables or add a `bible:` section to `~/.hermes/config.yaml`:

| Env var | config.yaml key | Default | Description |
|---|---|---|---|
| `BIBLE_ATLAS_BASE_URL` | `bible.base_url` | *(required)* | BiBLE Atlas HTTP base URL |
| `BIBLE_ATLAS_TOKEN` | `bible.token` | `null` | Optional bearer token |
| — | `bible.enable_memory_recall` | `true` | Recall memories before each turn |
| — | `bible.enable_skill_recall` | `false` | Recall skills before each turn |
| — | `bible.enable_knowledge_recall` | `false` | Recall knowledge before each turn |
| — | `bible.recall_top_k` | `8` | Max hits per domain |
| — | `bible.recall_min_score` | `0.35` | Minimum relevance score (0–1) |
| — | `bible.injection_token_budget` | `1200` | Token budget for injected context |
| — | `bible.capture_enabled` | `true` | Enable session capture |
| — | `bible.capture_commit_threshold_turns` | `8` | Auto-flush after N turns |
| — | `bible.capture_commit_threshold_chars` | `16000` | Auto-flush after N buffered chars |
| — | `bible.bypass_session_patterns` | `[]` | Regex patterns to skip |

Example `~/.hermes/config.yaml`:

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

## Development

```bash
cd bible-hermes-plugin
uv sync          # install deps into .venv
uv run python -c "from bible_hermes_plugin import register; print('OK')"
```

## Troubleshooting

### `No module named 'bible_hermes_plugin'`

Hermes logs:
```
WARNING hermes_cli.plugins: Failed to load plugin 'bible-hermes-plugin': No module named 'bible_hermes_plugin'
```

**Root cause:** The plugin's Python package is not installed into Hermes Agent's
venv (`~/.hermes/hermes-agent/venv/`). A `.venv` inside the plugin directory
itself is invisible to the Hermes process — Hermes runs from its own
interpreter, not the plugin's.

**Fix:**
```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python \
  ~/.hermes/plugins/bible-hermes-plugin/
```

Then restart Hermes (`/reset` in session, or relaunch the CLI).
