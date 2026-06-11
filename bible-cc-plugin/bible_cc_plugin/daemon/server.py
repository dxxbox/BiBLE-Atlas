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
