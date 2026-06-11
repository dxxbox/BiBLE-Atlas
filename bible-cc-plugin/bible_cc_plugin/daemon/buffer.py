"""SQLite buffer for sessions, turns, and key moments."""

from __future__ import annotations

import sqlite3
import json
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
