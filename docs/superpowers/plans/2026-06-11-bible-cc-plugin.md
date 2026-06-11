# BiBLE Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that integrates BiBLE Atlas as a memory + knowledge broker — persistent Python daemon with SQLite buffer + LLM moment detection + MCP server for 5 tools + lifecycle hooks.

**Architecture:** Three components: (1) `bible-cc-daemon` HTTP server on :9777 that buffers turns to SQLite, detects key moments via Claude API, and injects context via BiBLE recall; (2) `bible-cc-mcp` MCP stdio server wrapping BibleAtlasClient for 5 tools; (3) `hooks/hooks.json` shell glue wiring Claude Code lifecycle events to daemon endpoints.

**Tech Stack:** Python 3.10+, SQLite (stdlib), http.server (stdlib), httpx, anthropic SDK, mcp SDK, PyYAML

**Reused from bible-hermes-plugin:** `http_client.py`, `ranking.py`, `injection.py`, `logging_utils.py`, `bypass.py`, `recall.py` (adapted for CC config)

---

## File Structure

```
bible-cc-plugin/                        ← new top-level dir alongside bible-hermes-plugin
├── pyproject.toml
├── plugin.json
├── .mcp.json
├── hooks/
│   └── hooks.json
├── bible_cc_plugin/
│   ├── __init__.py
│   ├── client.py                       ← copied + adapted from hermes http_client.py
│   ├── config.py                       ← adapted from hermes config.py
│   ├── logging_utils.py                ← copied from hermes
│   ├── ranking.py                      ← copied from hermes (no changes)
│   ├── injection.py                    ← copied from hermes (no changes)
│   ├── recall.py                       ← adapted from hermes (CC config, memory+knowledge only)
│   ├── bypass.py                       ← adapted from hermes
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── server.py                   ← HTTP server (:9777) using stdlib http.server
│   │   ├── buffer.py                   ← SQLite schema + CRUD for sessions/turns/moments
│   │   ├── detector.py                 ← LLM moment detection via Anthropic API
│   │   └── injector.py                 ← context injection via BiBLE recall pipeline
│   ├── mcp_server.py                   ← MCP stdio server with 5 tools
│   └── cli.py                          ← bible-cc-daemon + bible-cc-hook CLI entry points
└── tests/
    ├── test_buffer.py
    ├── test_detector.py
    ├── test_config.py
    ├── test_injector.py
    └── test_mcp_server.py
```

---

### Task 1: Package skeleton + config

**Files:**
- Create: `bible-cc-plugin/pyproject.toml`
- Create: `bible-cc-plugin/bible_cc_plugin/__init__.py`
- Create: `bible-cc-plugin/bible_cc_plugin/logging_utils.py`
- Create: `bible-cc-plugin/bible_cc_plugin/config.py`
- Create: `bible-cc-plugin/tests/test_config.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "bible-cc-plugin"
version = "0.1.0"
description = "BiBLE Atlas Claude Code plugin — memory + knowledge broker daemon, MCP tools, and lifecycle hooks"
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.27.0",
    "anthropic>=0.30.0",
    "mcp>=1.0.0",
    "pyyaml>=6.0",
]

[project.scripts]
bible-cc-daemon = "bible_cc_plugin.cli:daemon_main"
bible-cc-hook = "bible_cc_plugin.cli:hook_main"
bible-cc = "bible_cc_plugin.cli:setup_main"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Create `bible_cc_plugin/__init__.py`**

```python
"""BiBLE Claude Code Plugin — memory + knowledge broker for Claude Code."""
```

- [ ] **Step 3: Copy `logging_utils.py` from hermes plugin verbatim**

Copy `/bible-hermes-plugin/bible_hermes_plugin/logging_utils.py` → `bible-cc-plugin/bible_cc_plugin/logging_utils.py` (no changes)

- [ ] **Step 4: Create `bible_cc_plugin/config.py`**

```python
"""BiBLE CC Plugin — configuration resolution.

Reads from ~/.bible-cc/config.yaml with env var overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BibleCCConfig:
    # BiBLE Atlas connection
    base_url: str
    token: str | None = None
    timeout_ms: int = 30_000
    default_kb_index: str = "kb_memory_main"
    source_client: str = "claude-code"

    # Daemon
    daemon_port: int = 9777
    db_path: str = "~/.bible-cc/daemon.db"

    # Context recall
    enable_memory_recall: bool = True
    enable_knowledge_recall: bool = False
    knowledge_tags: list[str] = field(default_factory=list)
    recall_top_k: int = 8
    recall_min_score: float = 0.35
    injection_token_budget: int = 1200
    force_injection: bool = False

    # Session capture
    capture_enabled: bool = True
    capture_mode: str = "key_moments"
    commit_threshold_turns: int = 8
    commit_threshold_chars: int = 16_000
    tool_result_max_chars: int = 250

    # Moment detection
    detection_model: str = "claude-sonnet-4-5"
    detection_max_tokens: int = 512
    detection_temperature: float = 0.0

    # Bypass
    bypass_session_patterns: list[str] = field(default_factory=list)
    compiled_bypass_patterns: list[re.Pattern[str]] = field(default_factory=list, repr=False)


class BibleConfigError(ValueError):
    pass


def resolve_config() -> BibleCCConfig:
    file_cfg = _load_yaml_config()
    return _build_config(file_cfg)


def _config_path() -> Path:
    return Path(os.environ.get("BIBLE_CC_CONFIG_PATH", Path.home() / ".bible-cc" / "config.yaml"))


def _load_yaml_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_config(file_cfg: dict) -> BibleCCConfig:
    bible = file_cfg.get("bible", {}) if isinstance(file_cfg.get("bible"), dict) else {}
    daemon = file_cfg.get("daemon", {}) if isinstance(file_cfg.get("daemon"), dict) else {}
    recall = file_cfg.get("recall", {}) if isinstance(file_cfg.get("recall"), dict) else {}
    capture = file_cfg.get("capture", {}) if isinstance(file_cfg.get("capture"), dict) else {}
    detection = file_cfg.get("detection", {}) if isinstance(file_cfg.get("detection"), dict) else {}
    bypass = file_cfg.get("bypass", {}) if isinstance(file_cfg.get("bypass"), dict) else {}

    base_url = os.environ.get("BIBLE_ATLAS_BASE_URL") or bible.get("base_url", "")
    if not base_url:
        raise BibleConfigError(
            "BIBLE_ATLAS_BASE_URL is required. Run 'bible-cc setup' or set the env var."
        )

    cfg = BibleCCConfig(
        base_url=base_url.rstrip("/"),
        token=os.environ.get("BIBLE_ATLAS_TOKEN") or bible.get("token"),
        timeout_ms=_int(bible, "timeout_ms", 1000, None, 30_000),
        default_kb_index=bible.get("default_kb_index", "kb_memory_main"),
        source_client=bible.get("source_client", "claude-code"),
        daemon_port=_int(daemon, "port", 1024, 65535, 9777),
        db_path=daemon.get("db_path", "~/.bible-cc/daemon.db"),
        enable_memory_recall=_bool(recall, "enable_memory", True),
        enable_knowledge_recall=_bool(recall, "enable_knowledge", False),
        knowledge_tags=_str_list(recall, "knowledge_tags"),
        recall_top_k=_int(recall, "top_k", 1, 50, 8),
        recall_min_score=_float(recall, "min_score", 0.0, 1.0, 0.35),
        injection_token_budget=_int(recall, "injection_token_budget", 128, None, 1200),
        force_injection=_bool(recall, "force_injection", False),
        capture_enabled=_bool(capture, "enabled", True),
        capture_mode=capture.get("mode", "key_moments"),
        commit_threshold_turns=_int(capture, "commit_threshold_turns", 1, None, 8),
        commit_threshold_chars=_int(capture, "commit_threshold_chars", 1000, None, 16_000),
        tool_result_max_chars=_int(capture, "tool_result_max_chars", 50, 2000, 250),
        detection_model=detection.get("model", "claude-sonnet-4-5"),
        detection_max_tokens=_int(detection, "max_tokens", 64, 4096, 512),
        detection_temperature=_float(detection, "temperature", 0.0, 2.0, 0.0),
        bypass_session_patterns=_str_list(bypass, "session_patterns"),
    )
    cfg.compiled_bypass_patterns = _compile_patterns(cfg.bypass_session_patterns)
    return cfg


def _bool(section: dict, key: str, fallback: bool) -> bool:
    val = section.get(key)
    return fallback if val is None else bool(val)


def _int(section: dict, key: str, lo: int, hi: int | None, fallback: int) -> int:
    val = section.get(key)
    if val is None:
        return fallback
    if not isinstance(val, int) or isinstance(val, bool):
        return fallback
    if val < lo:
        return fallback
    if hi is not None and val > hi:
        return fallback
    return val


def _float(section: dict, key: str, lo: float, hi: float, fallback: float) -> float:
    val = section.get(key)
    if val is None:
        return fallback
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return fallback
    if val < lo or val > hi:
        return fallback
    return float(val)


def _str_list(section: dict, key: str) -> list[str]:
    val = section.get(key)
    if not isinstance(val, list):
        return []
    return [str(item).strip() for item in val if isinstance(item, str) and item.strip()]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    compiled: list[re.Pattern] = []
    for p in patterns:
        try:
            compiled.append(re.compile(p))
        except re.error:
            pass
    return compiled
```

- [ ] **Step 5: Create `tests/test_config.py`**

```python
import os
import tempfile
from pathlib import Path
import yaml
from bible_cc_plugin.config import resolve_config, BibleConfigError


def test_resolve_config_from_env():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
            "daemon": {"port": 9777},
            "capture": {"mode": "key_moments", "tool_result_max_chars": 200},
            "detection": {"model": "claude-sonnet-4-5"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.base_url == "http://localhost:5555"
            assert cfg.daemon_port == 9777
            assert cfg.capture_mode == "key_moments"
            assert cfg.tool_result_max_chars == 200
            assert cfg.detection_model == "claude-sonnet-4-5"
            assert cfg.source_client == "claude-code"
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_missing_base_url_raises():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text("daemon:\n  port: 9777\n")
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            resolve_config()
            assert False, "should have raised"
        except BibleConfigError:
            pass
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_env_var_overrides_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://yaml.example.com:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        os.environ["BIBLE_ATLAS_BASE_URL"] = "http://env.example.com:5555"
        try:
            cfg = resolve_config()
            assert cfg.base_url == "http://env.example.com:5555"
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
            os.environ.pop("BIBLE_ATLAS_BASE_URL", None)


def test_defaults_when_empty_config():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.daemon_port == 9777
            assert cfg.capture_mode == "key_moments"
            assert cfg.tool_result_max_chars == 250
            assert cfg.recall_top_k == 8
            assert cfg.recall_min_score == 0.35
            assert cfg.enable_memory_recall is True
            assert cfg.enable_knowledge_recall is False
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
```

- [ ] **Step 6: Run tests**

```bash
cd bible-cc-plugin && python -m pytest tests/test_config.py -v
```
Expected: 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add bible-cc-plugin/
git commit -m "feat: add bible-cc-plugin package skeleton + config system"
```

---

### Task 2: Copy reusable modules from hermes plugin

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/client.py`
- Create: `bible-cc-plugin/bible_cc_plugin/ranking.py`
- Create: `bible-cc-plugin/bible_cc_plugin/injection.py`
- Create: `bible-cc-plugin/bible_cc_plugin/bypass.py`
- Create: `bible-cc-plugin/bible_cc_plugin/recall.py`

- [ ] **Step 1: Copy `client.py` from hermes `http_client.py`**

```bash
cp bible-hermes-plugin/bible_hermes_plugin/http_client.py bible-cc-plugin/bible_cc_plugin/client.py
```
Then edit line 127: change `source_client: str = "hermes"` → `source_client: str = "claude-code"`

- [ ] **Step 2: Copy `ranking.py` verbatim**

```bash
cp bible-hermes-plugin/bible_hermes_plugin/ranking.py bible-cc-plugin/bible_cc_plugin/ranking.py
```

- [ ] **Step 3: Copy `injection.py` verbatim**

```bash
cp bible-hermes-plugin/bible_hermes_plugin/injection.py bible-cc-plugin/bible_cc_plugin/injection.py
```

- [ ] **Step 4: Copy `bypass.py`**

```bash
cp bible-hermes-plugin/bible_hermes_plugin/bypass.py bible-cc-plugin/bible_cc_plugin/bypass.py
```

- [ ] **Step 5: Create `recall.py` — adapted, memory + knowledge only**

```python
"""BiBLE CC Plugin — recall pipeline.

Runs parallel searches across memory / knowledge domains and returns
ranked hits ready for context injection.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import re

from .config import BibleCCConfig
from .client import BibleAtlasClient
from .injection import render_relevant_memories
from .logging_utils import action_logger, log
from .ranking import RecallHit, filter_rank_and_trim, normalize_hits


def run_recall_pipeline(
    user_message: str,
    conversation_history: list[dict],
    config: BibleCCConfig,
    client: BibleAtlasClient,
) -> tuple[str, list[str]]:
    query = _build_recall_query(user_message, conversation_history)
    if not query:
        return "", []

    warnings: list[str] = []
    tasks: list[tuple[str, str | None]] = []

    if config.enable_memory_recall:
        tasks.append(("memory", None))
    if config.enable_knowledge_recall:
        for tag in config.knowledge_tags:
            tasks.append(("knowledge", tag))

    if not tasks:
        return "", warnings

    hits = _run_parallel_searches(tasks, query, config, client, warnings)
    ranked = filter_rank_and_trim(hits, query, config.recall_min_score, config.recall_top_k)
    rendered = render_relevant_memories(ranked, config.injection_token_budget)
    return rendered, warnings


def build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    return _build_recall_query(user_message, conversation_history)


def _build_recall_query(user_message: str, conversation_history: list[dict]) -> str:
    recent_text = "\n".join(
        _text_from_message(m)
        for m in conversation_history[-6:]
        if _text_from_message(m)
    )
    raw = "\n".join(filter(None, [recent_text, user_message]))
    return _clean_for_query(raw)[:2000].strip()


def _run_parallel_searches(
    tasks: list[tuple[str, str | None]],
    query: str,
    config: BibleCCConfig,
    client: BibleAtlasClient,
    warnings: list[str],
) -> list[RecallHit]:
    all_hits: list[RecallHit] = []

    def search_one(domain: str, tag: str | None) -> list[RecallHit]:
        try:
            if domain == "memory":
                payload = client.search_memory(query, config.recall_top_k, config.recall_min_score)
            else:
                payload = client.search_knowledge(query, tag or "", config.recall_top_k, config.recall_min_score)
            return normalize_hits(domain, payload, tag)
        except Exception as exc:
            warnings.append(f"{domain} recall failed: {exc}")
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {pool.submit(search_one, domain, tag): (domain, tag) for domain, tag in tasks}
        for future in concurrent.futures.as_completed(futures):
            with contextlib.suppress(Exception):
                all_hits.extend(future.result())

    return all_hits


def _text_from_message(message: dict) -> str:
    content = message.get("content") or message.get("text") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text") or item.get("content") or ""
            for item in content
            if isinstance(item, dict)
        )
    return ""


def _clean_for_query(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", lambda m: " [code block omitted] " if len(m.group()) > 500 else m.group(), text)
    text = re.sub(r"[A-Za-z0-9+/=]{120,}", " [encoded blob omitted] ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

- [ ] **Step 6: Verify imports**

```bash
cd bible-cc-plugin && python -c "from bible_cc_plugin.client import BibleAtlasClient; from bible_cc_plugin.recall import run_recall_pipeline; from bible_cc_plugin.config import resolve_config; print('OK')"
```
Expected: "OK"

- [ ] **Step 7: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/client.py bible-cc-plugin/bible_cc_plugin/ranking.py bible-cc-plugin/bible_cc_plugin/injection.py bible-cc-plugin/bible_cc_plugin/bypass.py bible-cc-plugin/bible_cc_plugin/recall.py
git commit -m "feat: copy and adapt reusable modules from hermes plugin"
```

---

### Task 3: SQLite buffer

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/daemon/__init__.py`
- Create: `bible-cc-plugin/bible_cc_plugin/daemon/buffer.py`
- Create: `bible-cc-plugin/tests/test_buffer.py`

- [ ] **Step 1: Create `daemon/__init__.py`**

```python
"""BiBLE CC Plugin — daemon components."""
```

- [ ] **Step 2: Create `daemon/buffer.py`**

```python
"""SQLite buffer for sessions, turns, and key moments."""

from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class Buffer:
    """Thread-safe SQLite store for daemon state."""

    def __init__(self, db_path: str) -> None:
        expanded = Path(db_path).expanduser()
        expanded.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(expanded)
        self._lock = Lock()
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        with self._lock:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def create_session(self, session_id: str) -> dict:
        return self._execute(
            "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
            (session_id, _iso_now()),
        )

    def get_session(self, session_id: str) -> dict | None:
        return self._fetchone("SELECT * FROM sessions WHERE session_id=?", (session_id,))

    def update_session_status(self, session_id: str, status: str) -> None:
        self._execute("UPDATE sessions SET status=? WHERE session_id=?", (status, session_id))

    def add_turn(self, session_id: str, role: str, content: str, tool_calls: list[dict] | None = None) -> int:
        seq = self._get_turn_count(session_id) + 1
        self._execute(
            "INSERT INTO turns (session_id, seq, role, content, tool_calls, timestamp) VALUES (?,?,?,?,?,?)",
            (session_id, seq, role, content, json.dumps(tool_calls or []), _iso_now()),
        )
        chars = len(content) + len(json.dumps(tool_calls or []))
        self._execute(
            "UPDATE sessions SET turn_count=turn_count+1, buffered_chars=buffered_chars+? WHERE session_id=?",
            (chars, session_id),
        )
        return seq

    def get_turns(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self._fetchall(
            "SELECT * FROM turns WHERE session_id=? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(rows))

    def get_turn_count(self, session_id: str) -> int:
        row = self._fetchone("SELECT turn_count FROM sessions WHERE session_id=?", (session_id,))
        return row["turn_count"] if row else 0

    def get_buffered_chars(self, session_id: str) -> int:
        row = self._fetchone("SELECT buffered_chars FROM sessions WHERE session_id=?", (session_id,))
        return row["buffered_chars"] if row else 0

    def add_moment(self, session_id: str, moment_type: str, title: str, narrative: str, turn_range: str | None = None) -> int:
        return self._execute(
            "INSERT INTO moments (session_id, moment_type, title, narrative, turn_range, detected_at) VALUES (?,?,?,?,?,?)",
            (session_id, moment_type, title, narrative, turn_range, _iso_now()),
        )

    def get_pending_moments(self, session_id: str) -> list[dict]:
        return self._fetchall(
            "SELECT * FROM moments WHERE session_id=? AND flushed=0",
            (session_id,),
        )

    def mark_moment_flushed(self, moment_id: int) -> None:
        self._execute("UPDATE moments SET flushed=1 WHERE id=?", (moment_id,))

    def _get_turn_count(self, session_id: str) -> int:
        row = self._fetchone("SELECT MAX(seq) as max_seq FROM turns WHERE session_id=?", (session_id,))
        return (row and row["max_seq"]) or 0

    def _migrate(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id     TEXT PRIMARY KEY,
                started_at     TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'active',
                topic_scope    TEXT,
                turn_count     INTEGER DEFAULT 0,
                buffered_chars INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS turns (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT NOT NULL REFERENCES sessions(session_id),
                seq           INTEGER NOT NULL,
                role          TEXT NOT NULL,
                content       TEXT NOT NULL,
                tool_calls    TEXT,
                timestamp     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS moments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT NOT NULL REFERENCES sessions(session_id),
                moment_type   TEXT NOT NULL,
                title         TEXT NOT NULL,
                narrative     TEXT NOT NULL,
                turn_range    TEXT,
                detected_at   TEXT NOT NULL,
                flushed       INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
            CREATE INDEX IF NOT EXISTS idx_moments_session ON moments(session_id);
            CREATE INDEX IF NOT EXISTS idx_moments_pending ON moments(session_id) WHERE flushed=0;
        """)

    def _execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([d[0] for d in cur.description], row))

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 3: Create `tests/test_buffer.py`**

```python
import tempfile
from pathlib import Path
from bible_cc_plugin.daemon.buffer import Buffer


def test_create_session():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            session = buf.get_session("sess-1")
            assert session["session_id"] == "sess-1"
            assert session["status"] == "active"
            assert session["turn_count"] == 0
        finally:
            buf.close()


def test_add_turn_and_get_turns():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            buf.add_turn("sess-1", "user", "Hello")
            buf.add_turn("sess-1", "assistant", "Hi there", [{"name": "read", "content": "file contents"}])

            turns = buf.get_turns("sess-1")
            assert len(turns) == 2
            assert turns[0]["role"] == "user"
            assert turns[0]["content"] == "Hello"
            assert turns[1]["role"] == "assistant"
            assert buf.get_turn_count("sess-1") == 2
            assert buf.get_buffered_chars("sess-1") > 0
        finally:
            buf.close()


def test_add_and_get_pending_moments():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            buf.add_moment("sess-1", "decision", "Chose Python", "Decided to use Python.", "3-5")
            buf.add_moment("sess-1", "accomplishment", "Config done", "Config system complete.", "6-8")

            pending = buf.get_pending_moments("sess-1")
            assert len(pending) == 2
            assert pending[0]["flushed"] == 0

            buf.mark_moment_flushed(pending[0]["id"])
            still_pending = buf.get_pending_moments("sess-1")
            assert len(still_pending) == 1
        finally:
            buf.close()
```

- [ ] **Step 4: Run tests**

```bash
cd bible-cc-plugin && python -m pytest tests/test_buffer.py -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/daemon/ bible-cc-plugin/tests/test_buffer.py
git commit -m "feat: add SQLite buffer for sessions, turns, and moments"
```

---

### Task 4: Context injector + daemon HTTP server

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/daemon/injector.py`
- Create: `bible-cc-plugin/bible_cc_plugin/daemon/server.py`
- Create: `bible-cc-plugin/tests/test_injector.py`

- [ ] **Step 1: Create `daemon/injector.py`**

```python
"""Context injection — queries BiBLE Atlas and returns formatted context string."""

from __future__ import annotations

import logging

from ..config import BibleCCConfig
from ..client import BibleAtlasClient
from ..recall import run_recall_pipeline
from .buffer import Buffer

logger = logging.getLogger(__name__)


class ContextInjector:
    def __init__(self, config: BibleCCConfig, client: BibleAtlasClient, buffer: Buffer) -> None:
        self.config = config
        self.client = client
        self.buffer = buffer
        self._manual_saves: set[str] = set()

    def notify_manual_save(self, session_id: str) -> None:
        self._manual_saves.add(session_id)

    def inject(self, session_id: str, user_message: str) -> str:
        if not self.config.enable_memory_recall and not self.config.enable_knowledge_recall:
            return ""

        recall_config = self.config
        if self.config.force_injection:
            from copy import copy
            recall_config = copy(self.config)
            recall_config.enable_memory_recall = True
            recall_config.enable_knowledge_recall = True

        turns = self.buffer.get_turns(session_id, limit=12)
        history = [
            {"role": t["role"], "content": t["content"]}
            for t in turns[:-1] if t["role"] == "user"
        ]

        try:
            rendered, warnings = run_recall_pipeline(
                user_message=user_message,
                conversation_history=history,
                config=recall_config,
                client=self.client,
            )
            for w in warnings:
                logger.debug("recall warning: %s", w)
            return rendered
        except Exception as exc:
            logger.warning("inject failed (non-fatal): %s", exc)
            return ""
```

- [ ] **Step 2: Create `tests/test_injector.py`**

```python
from bible_cc_plugin.config import BibleCCConfig
from bible_cc_plugin.client import BibleAtlasClient
from bible_cc_plugin.daemon.buffer import Buffer
from bible_cc_plugin.daemon.injector import ContextInjector


def test_inject_when_recall_disabled_returns_empty():
    buf = Buffer(":memory:")
    buf.open()
    try:
        cfg = BibleCCConfig(
            base_url="http://localhost:5555",
            enable_memory_recall=False,
            enable_knowledge_recall=False,
        )
        client = BibleAtlasClient(base_url="http://localhost:5555")
        injector = ContextInjector(cfg, client, buf)
        result = injector.inject("sess-1", "hello")
        assert result == ""
    finally:
        buf.close()


def test_notify_manual_save():
    buf = Buffer(":memory:")
    buf.open()
    try:
        cfg = BibleCCConfig(base_url="http://localhost:5555")
        client = BibleAtlasClient(base_url="http://localhost:5555")
        injector = ContextInjector(cfg, client, buf)
        injector.notify_manual_save("sess-1")
        assert "sess-1" in injector._manual_saves
    finally:
        buf.close()
```

- [ ] **Step 3: Create `daemon/server.py`**

```python
"""BiBLE CC Daemon — lightweight HTTP server on :9777 using stdlib http.server."""

from __future__ import annotations

import json
import logging
import os
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from ..config import resolve_config
from ..client import BibleAtlasClient
from .buffer import Buffer
from .detector import MomentDetector
from .injector import ContextInjector

logger = logging.getLogger("bible-cc-daemon")
_PID_FILE = Path.home() / ".bible-cc" / "daemon.pid"


class _Handler(BaseHTTPRequestHandler):
    buffer: Buffer = None
    injector: ContextInjector = None
    detector: MomentDetector = None

    def log_message(self, fmt, *args):
        logger.debug("daemon.http %s", fmt % args)

    def do_POST(self):
        body = self._read_body()
        try:
            result = self._route(self.path, body)
            self._respond(200, result)
        except ValueError as exc:
            self._respond(400, {"error": str(exc)})
        except Exception as exc:
            logger.exception("daemon error handling %s", self.path)
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        try:
            result = self._route(self.path, {})
            self._respond(200, result)
        except ValueError as exc:
            self._respond(400, {"error": str(exc)})

    def _route(self, path: str, body: dict) -> dict:
        routes = {
            "/daemon/health": lambda: {"status": "ok", "pid": os.getpid()},
            "/session/start": lambda: self._session_start(body),
            "/session/end": lambda: self._session_end(body),
            "/turn/user": lambda: self._turn(body, "user"),
            "/turn/assistant": lambda: self._turn(body, "assistant"),
            "/turn/tool": lambda: self._turn_tool(body),
            "/context/inject": lambda: self._inject(body),
            "/daemon/notify": lambda: {"ok": True},
        }
        handler = routes.get(path)
        if handler is None:
            raise ValueError(f"unknown endpoint: {path}")
        return handler()

    def _session_start(self, body: dict) -> dict:
        session_id = body.get("session_id", "")
        if not session_id:
            raise ValueError("session_id required")
        self.buffer.create_session(session_id)
        logger.info("session.start session_id=%s", session_id)
        return {"ok": True, "session_id": session_id}

    def _session_end(self, body: dict) -> dict:
        session_id = body.get("session_id", "")
        if not session_id:
            raise ValueError("session_id required")
        turns = self.buffer.get_turns(session_id, limit=100)
        moments = self.detector.detect(session_id, turns)
        for m in moments:
            self.buffer.add_moment(session_id, m["type"], m["title"], m["narrative"], m.get("turn_range"))
        pending = self.buffer.get_pending_moments(session_id)
        flushed = 0
        for pm in pending:
            try:
                self.injector.client.save_memory(
                    messages=[{"role": "system", "content": f"[{pm['moment_type']}] {pm['title']}: {pm['narrative']}"}],
                    title=pm["title"],
                    abstract=pm["narrative"][:500],
                    metadata={
                        "source": "claude-code",
                        "plugin_id": "bible-cc-plugin",
                        "session_id": session_id,
                        "moment_type": pm["moment_type"],
                    },
                    wait=False,
                )
                self.buffer.mark_moment_flushed(pm["id"])
                flushed += 1
            except Exception as exc:
                logger.warning("flush moment %s failed: %s", pm["id"], exc)
        self.buffer.update_session_status(session_id, "ended")
        logger.info("session.end session_id=%s moments=%d flushed=%d", session_id, len(pending), flushed)
        return {"ok": True, "moments_detected": len(pending), "moments_flushed": flushed}

    def _turn(self, body: dict, role: str) -> dict:
        session_id = body.get("session_id", "")
        message = body.get("message", "")
        if not session_id or not message:
            raise ValueError("session_id and message required")
        tool_calls = body.get("tool_calls")
        seq = self.buffer.add_turn(session_id, role, message, tool_calls)
        return {"ok": True, "seq": seq}

    def _turn_tool(self, body: dict) -> dict:
        session_id = body.get("session_id", "")
        tool_name = body.get("tool_name", "unknown")
        result_summary = (body.get("result_summary") or "")[:self.injector.config.tool_result_max_chars]
        message = f"[tool:{tool_name}] {result_summary}"
        seq = self.buffer.add_turn(session_id, "assistant", message)
        return {"ok": True, "seq": seq}

    def _inject(self, body: dict) -> dict:
        session_id = body.get("session_id", "")
        user_message = body.get("user_message", "")
        context = self.injector.inject(session_id, user_message)
        return {"context": context}

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _respond(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Daemon:
    def __init__(self) -> None:
        self.config = resolve_config()
        self.buffer = Buffer(self.config.db_path)
        self.client = BibleAtlasClient(
            base_url=self.config.base_url,
            token=self.config.token,
            timeout_ms=self.config.timeout_ms,
            default_kb_index=self.config.default_kb_index,
            source_client=self.config.source_client,
        )
        self.injector = ContextInjector(self.config, self.client, self.buffer)
        self.detector = MomentDetector(self.config)

    def start(self) -> None:
        self.buffer.open()
        _Handler.buffer = self.buffer
        _Handler.injector = self.injector
        _Handler.detector = self.detector
        _write_pid()
        server = HTTPServer(("127.0.0.1", self.config.daemon_port), _Handler)
        logger.info("daemon listening on :%d", self.config.daemon_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            self.buffer.close()
            _remove_pid()

    @staticmethod
    def is_running() -> bool:
        if not _PID_FILE.exists():
            return False
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False


def _write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    _PID_FILE.unlink(missing_ok=True)
```

- [ ] **Step 4: Run unit tests**

```bash
cd bible-cc-plugin && python -m pytest tests/test_injector.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/daemon/server.py bible-cc-plugin/bible_cc_plugin/daemon/injector.py bible-cc-plugin/tests/test_injector.py
git commit -m "feat: add daemon HTTP server and context injector"
```

---

### Task 5: Moment detector

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/daemon/detector.py`
- Create: `bible-cc-plugin/tests/test_detector.py`

- [ ] **Step 1: Create `daemon/detector.py`**

```python
"""LLM-based key moment detection using Anthropic API."""

from __future__ import annotations

import json
import logging

from ..config import BibleCCConfig

logger = logging.getLogger(__name__)

_DETECTION_PROMPT = """You are analyzing a conversation between a user and an AI agent.
Identify if any KEY MOMENTS occurred in these recent turns.

Key moment types:
- SESSION_START: the user defines the topic or scope of work
- DECISION: the user confirms a choice, approach, or design direction
- ACCOMPLISHMENT: something was completed, verified, and accepted by the user

Do NOT flag:
- Intermediate bug fixes or error corrections
- Exploratory discoveries (unless user explicitly confirms importance)

Respond with a JSON array. If no key moments found, return an empty array [].
Each moment: {"type": "<type>", "title": "<one-line summary>", "narrative": "<2-4 sentences>", "turn_range": "<e.g. 3-7>"}

Conversation turns:
{turns_text}
"""


class MomentDetector:
    def __init__(self, config: BibleCCConfig) -> None:
        self._model = config.detection_model
        self._max_tokens = config.detection_max_tokens
        self._temperature = config.detection_temperature

    def detect(self, session_id: str, turns: list[dict]) -> list[dict]:
        if not turns:
            return []

        turns_text = _format_turns(turns)
        prompt = _DETECTION_PROMPT.replace("{turns_text}", turns_text)

        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system="You are a conversation analyst. Return only valid JSON arrays.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            return _parse_moments(text)
        except Exception as exc:
            logger.warning("moment detection failed for %s: %s", session_id, exc)
            return []


def _format_turns(turns: list[dict]) -> str:
    lines = []
    for i, t in enumerate(turns):
        role = t.get("role", "unknown")
        content = t.get("content", "")[:800]
        lines.append(f"[{i + 1}] {role}: {content}")
    return "\n".join(lines)


def _parse_moments(text: str) -> list[dict]:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [m for m in result if isinstance(m, dict) and "type" in m and "title" in m and "narrative" in m]
    except json.JSONDecodeError:
        pass
    return []
```

- [ ] **Step 2: Create `tests/test_detector.py`**

```python
from bible_cc_plugin.daemon.detector import _format_turns, _parse_moments


def test_format_turns():
    turns = [
        {"role": "user", "content": "I want to build a web app."},
        {"role": "assistant", "content": "What framework?"},
        {"role": "user", "content": "Let's use Flask."},
    ]
    formatted = _format_turns(turns)
    assert "[1] user: I want to build a web app." in formatted
    assert "[3] user: Let's use Flask." in formatted


def test_parse_moments_valid_json():
    text = '[{"type": "decision", "title": "Chose Flask", "narrative": "User decided on Flask.", "turn_range": "2-3"}]'
    moments = _parse_moments(text)
    assert len(moments) == 1
    assert moments[0]["type"] == "decision"
    assert moments[0]["title"] == "Chose Flask"


def test_parse_moments_markdown_fenced():
    text = '```json\n[{"type": "accomplishment", "title": "Done", "narrative": "Feature complete.", "turn_range": "4-6"}]\n```'
    moments = _parse_moments(text)
    assert len(moments) == 1
    assert moments[0]["type"] == "accomplishment"


def test_parse_moments_empty():
    assert _parse_moments("[]") == []


def test_parse_moments_invalid():
    assert _parse_moments("not json") == []
    assert _parse_moments('{"not": "array"}') == []
```

- [ ] **Step 3: Run tests**

```bash
cd bible-cc-plugin && python -m pytest tests/test_detector.py -v
```
Expected: 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/daemon/detector.py bible-cc-plugin/tests/test_detector.py
git commit -m "feat: add LLM moment detector for key moment classification"
```

---

### Task 6: MCP server

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/mcp_server.py`
- Create: `bible-cc-plugin/tests/test_mcp_server.py`

- [ ] **Step 1: Create `mcp_server.py`**

```python
"""BiBLE Atlas MCP server — exposes 5 tools via stdio transport."""

from __future__ import annotations

import json
import logging

from .config import resolve_config
from .client import BibleAtlasClient, error_details

logger = logging.getLogger("bible-cc-mcp")


def _make_server():
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    config = resolve_config()
    client = BibleAtlasClient(
        base_url=config.base_url,
        token=config.token,
        timeout_ms=config.timeout_ms,
        default_kb_index=config.default_kb_index,
        source_client=config.source_client,
    )

    server = Server("bible-atlas")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="bible_memory_search",
                description="Search BiBLE Atlas memory for relevant past context",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "description": "Max results (default 8)"},
                        "min_score": {"type": "number", "description": "Minimum relevance score 0-1 (default 0.35)"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="bible_memory_save",
                description="Save a memory to BiBLE Atlas",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array", "items": {"type": "object"}, "description": "Conversation messages to save"},
                        "title": {"type": "string", "description": "Memory title"},
                        "abstract": {"type": "string", "description": "Brief summary"},
                        "wait": {"type": "boolean", "description": "Wait for import to complete (default false)"},
                    },
                    "required": ["messages"],
                },
            ),
            Tool(
                name="bible_memory_get",
                description="Retrieve a specific memory from BiBLE Atlas by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID to retrieve"},
                    },
                    "required": ["memory_id"],
                },
            ),
            Tool(
                name="bible_knowledge_search",
                description="Search BiBLE Atlas knowledge base",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "tag": {"type": "string", "description": "Knowledge tag to search"},
                        "top_k": {"type": "integer", "description": "Max results (default 8)"},
                    },
                    "required": ["query", "tag"],
                },
            ),
            Tool(
                name="bible_knowledge_list",
                description="List available knowledge bases in BiBLE Atlas",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "description": "Filter by tag (optional)"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "bible_memory_search":
                result = client.search_memory(
                    query=arguments["query"],
                    top_k=arguments.get("top_k", 8),
                    min_score=arguments.get("min_score", 0.35),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_memory_save":
                result = client.save_memory(
                    messages=arguments["messages"],
                    title=arguments.get("title"),
                    abstract=arguments.get("abstract"),
                    wait=arguments.get("wait", False),
                )
                _notify_daemon(config)
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_memory_get":
                result = client.get_memory(arguments["memory_id"])
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_knowledge_search":
                result = client.search_knowledge(
                    query=arguments["query"],
                    tag=arguments.get("tag", ""),
                    top_k=arguments.get("top_k", 8),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_knowledge_list":
                result = client.list_knowledge()
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps(error_details(exc), indent=2))]

    return server


def _notify_daemon(config) -> None:
    try:
        import httpx
        httpx.post(
            f"http://127.0.0.1:{config.daemon_port}/daemon/notify",
            json={"event": "memory_save"},
            timeout=2.0,
        )
    except Exception:
        pass


def main():
    import asyncio
    from mcp.server.stdio import stdio_server

    server = _make_server()

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `tests/test_mcp_server.py`** — config validation only

```python
import os
import tempfile
from pathlib import Path
import yaml
from bible_cc_plugin.mcp_server import _make_server


def test_server_creation():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            server = _make_server()
            assert server is not None
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
```

- [ ] **Step 3: Run tests**

```bash
cd bible-cc-plugin && python -m pytest tests/test_mcp_server.py -v
```
Expected: 1 test PASS (or SKIP if mcp package unavailable)

- [ ] **Step 4: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/mcp_server.py bible-cc-plugin/tests/test_mcp_server.py
git commit -m "feat: add MCP server with 5 BiBLE Atlas tools"
```

---

### Task 7: CLI + plugin manifests

**Files:**
- Create: `bible-cc-plugin/bible_cc_plugin/cli.py`
- Create: `bible-cc-plugin/plugin.json`
- Create: `bible-cc-plugin/.mcp.json`
- Create: `bible-cc-plugin/hooks/hooks.json`

- [ ] **Step 1: Create `cli.py`**

```python
"""BiBLE CC Plugin — CLI entry points.

bible-cc-daemon --start|--stop|--status    daemon lifecycle
bible-cc-hook session-start|turn-user|...  hook glue → HTTP calls
bible-cc setup                              config wizard
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

import httpx
import yaml


def daemon_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc-daemon")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.start:
        _start_daemon()
    elif args.stop:
        _stop_daemon()
    elif args.status:
        _status_daemon()
    else:
        parser.print_help()


def _start_daemon() -> None:
    from .daemon.server import Daemon
    if Daemon.is_running():
        print("Daemon already running.")
        return
    daemon = Daemon()
    daemon.start()


def _stop_daemon() -> None:
    pid_file = Path.home() / ".bible-cc" / "daemon.pid"
    if not pid_file.exists():
        print("Daemon not running.")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        print(f"Daemon (pid={pid}) stopped.")
    except OSError as exc:
        print(f"Failed to stop daemon: {exc}")


def _status_daemon() -> None:
    from .daemon.server import Daemon
    print("Daemon:", "running" if Daemon.is_running() else "not running")


def hook_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc-hook")
    parser.add_argument("action", choices=["session-start", "session-end", "turn-user", "turn-tool"])
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--message", default="")
    parser.add_argument("--tool", default="")
    parser.add_argument("--port", type=int, default=9777)
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}"

    if args.action == "session-start":
        r = httpx.post(f"{base}/session/start", json={"session_id": args.session_id}, timeout=5)
        r.raise_for_status()
        r2 = httpx.post(f"{base}/context/inject", json={
            "session_id": args.session_id,
            "user_message": args.message,
        }, timeout=10)
        r2.raise_for_status()
        context = r2.json().get("context", "")
        if context:
            print(context)
    elif args.action == "session-end":
        httpx.post(f"{base}/session/end", json={"session_id": args.session_id}, timeout=30)
    elif args.action == "turn-user":
        httpx.post(f"{base}/turn/user", json={
            "session_id": args.session_id,
            "message": args.message,
        }, timeout=5)
    elif args.action == "turn-tool":
        httpx.post(f"{base}/turn/tool", json={
            "session_id": args.session_id,
            "tool_name": args.tool,
            "result_summary": args.message[:250],
        }, timeout=5)


def setup_main() -> None:
    parser = argparse.ArgumentParser(prog="bible-cc")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.cmd == "setup":
        _setup_wizard()
    elif args.cmd == "status":
        _print_status()
    else:
        parser.print_help()


def _setup_wizard() -> None:
    print("BiBLE Claude Code Plugin — Setup\n")
    base_url = input("BiBLE Atlas base URL [http://localhost:5555]: ").strip() or "http://localhost:5555"
    token = input("BiBLE Atlas token (optional): ").strip() or None

    config_dir = Path.home() / ".bible-cc"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    config = {"bible": {"base_url": base_url}}
    if token:
        config["bible"]["token"] = token

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    print(f"Config saved to {config_path}\n")

    try:
        r = httpx.get(f"{base_url.rstrip('/')}/health", timeout=5)
        if r.is_success:
            print("✓ Connected to BiBLE Atlas successfully.")
        else:
            print(f"⚠ BiBLE Atlas returned status {r.status_code}")
    except Exception as exc:
        print(f"⚠ Could not connect to BiBLE Atlas: {exc}")

    print("\nSetup complete. Add the plugin to Claude Code to enable it.")


def _print_status() -> None:
    from .config import resolve_config, BibleConfigError
    from .daemon.server import Daemon

    try:
        cfg = resolve_config()
        print(f"Config: {Path.home() / '.bible-cc' / 'config.yaml'}")
        print(f"BiBLE URL: {cfg.base_url}")
        print(f"Recall: memory={'on' if cfg.enable_memory_recall else 'off'} knowledge={'on' if cfg.enable_knowledge_recall else 'off'}")
        print(f"Capture: {cfg.capture_mode}")
        print(f"Daemon port: {cfg.daemon_port}")
        print(f"Daemon: {'running' if Daemon.is_running() else 'not running'}")
    except BibleConfigError as exc:
        print(f"Not configured: {exc}")
        print("Run 'bible-cc setup' to configure.")


if __name__ == "__main__":
    daemon_main()
```

- [ ] **Step 2: Create `plugin.json`**

```json
{
  "name": "bible-cc-plugin",
  "version": "0.1.0",
  "description": "BiBLE Atlas memory + knowledge broker for Claude Code",
  "author": { "name": "BiBLE Atlas Team" },
  "repository": "https://github.com/NousResearch/bible-atlas",
  "license": "MIT"
}
```

- [ ] **Step 3: Create `.mcp.json`**

```json
{
  "mcpServers": {
    "bible-atlas": {
      "command": "python",
      "args": ["-m", "bible_cc_plugin.mcp_server"],
      "env": {
        "BIBLE_ATLAS_BASE_URL": "${BIBLE_ATLAS_BASE_URL:-http://localhost:5555}"
      }
    }
  }
}
```

- [ ] **Step 4: Create `hooks/hooks.json`**

```json
{
  "hooks": {
    "Setup": [{
      "command": "bible-cc-daemon --start",
      "timeout": 10000
    }],
    "SessionStart": [{
      "command": "bible-cc-hook session-start --session-id \"$CLAUDE_SESSION_ID\" --message \"$USER_PROMPT\"",
      "timeout": 15000
    }],
    "UserPromptSubmit": [{
      "command": "bible-cc-hook turn-user --session-id \"$CLAUDE_SESSION_ID\" --message \"$USER_PROMPT\"",
      "timeout": 5000
    }],
    "PostToolUse": [{
      "command": "bible-cc-hook turn-tool --session-id \"$CLAUDE_SESSION_ID\" --tool \"$TOOL_NAME\" --message \"$TOOL_RESULT\"",
      "timeout": 5000
    }],
    "Stop": [{
      "command": "bible-cc-hook session-end --session-id \"$CLAUDE_SESSION_ID\"",
      "timeout": 30000
    }]
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add bible-cc-plugin/bible_cc_plugin/cli.py bible-cc-plugin/plugin.json bible-cc-plugin/.mcp.json bible-cc-plugin/hooks/
git commit -m "feat: add CLI entry points + plugin manifest files"
```

---

## Summary

| Task | Component | Est. Lines | Tests |
|---|---|---|---|
| 1 | Package skeleton + config | ~150 | 4 |
| 2 | Reusable modules (copy + adapt) | ~500 | — |
| 3 | SQLite buffer | ~120 | 3 |
| 4 | Daemon HTTP server + injector | ~230 | 2 |
| 5 | Moment detector | ~80 | 5 |
| 6 | MCP server | ~120 | 1 |
| 7 | CLI + plugin manifests | ~180 + 3 files | — |

**Total:** ~1,380 lines Python + 3 manifest files + 15 tests
