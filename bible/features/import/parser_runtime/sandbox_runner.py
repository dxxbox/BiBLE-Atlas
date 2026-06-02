from __future__ import annotations

import json
import subprocess
import sys

from bible.common.errors import DomainError, ErrorCode


class SandboxRunner:
    def __init__(self, timeout_seconds: int = 60) -> None:
        self._timeout_seconds = timeout_seconds

    def run_parse(
        self,
        parser_script_path: str,
        manifest_path: str,
        parser_context: dict | None = None,
    ) -> dict:
        cmd = [sys.executable, parser_script_path, "--manifest", manifest_path]
        if parser_context:
            cmd += ["--context", json.dumps(parser_context)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise DomainError(
                ErrorCode.DEADLINE_EXCEEDED,
                f"Parser script timed out after {self._timeout_seconds}s",
                details={"code": "PARSER_SCRIPT_TIMEOUT"},
            )

        if proc.returncode != 0:
            raise DomainError(
                ErrorCode.INTERNAL,
                f"Parser script exited with code {proc.returncode}: {proc.stderr[:500]}",
                details={"code": "PARSER_SCRIPT_RUNTIME_ERROR", "stderr": proc.stderr[:2000]},
            )

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise DomainError(
                ErrorCode.INTERNAL,
                f"Parser script produced invalid JSON: {exc}",
                details={"code": "PARSER_SCRIPT_RUNTIME_ERROR", "stdout": proc.stdout[:500]},
            )

        return result
