# Parser Runtime 通用实现指南（ASTGuard + SandboxRunner）

本文档定义 `app/features/import/parser_runtime/` 下通用运行时组件的实现细节。  
该组件与业务类型无关，统一服务于 `KNOWLEDGE_BASE/SKILL/MEMORY` 三类导入流程。

---

## 1. 目录与职责

```text
app/features/import/parser_runtime/
├── ast_guard.py
├── sandbox_runner.py
└── schemas.py                # 可选：ParseResult / ValidationError 类型定义
```

职责分工：

- `ASTGuard`：静态安全检查（语法树）
- `SandboxRunner`：受限执行脚本并返回结构化解析结果

---

## 2. 通用类型定义（建议）

```python
from dataclasses import dataclass, field
from typing import Any, Literal

ParserRuntimeErrorCode = Literal[
    "PARSER_SCRIPT_RISK",
    "PARSER_SCRIPT_TIMEOUT",
    "PARSER_SCRIPT_RUNTIME_ERROR",
    "PARSE_RESULT_SCHEMA_INVALID",
]

@dataclass
class GuardViolation:
    rule: str
    message: str
    line: int | None = None
    column: int | None = None

@dataclass
class GuardResult:
    ok: bool
    violations: list[GuardViolation]

@dataclass
class ParseResult:
    chunks: list[dict[str, Any]]
    search_profile: dict[str, Any]
    local_file_storage_plan: dict[str, Any] | None = None

@dataclass
class ParserRuntimeError(RuntimeError):
    code: ParserRuntimeErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
```

---

## 3. `ASTGuard` 完整实现

文件：`app/features/import/parser_runtime/ast_guard.py`

```python
from __future__ import annotations

import ast
import logging
from pathlib import Path

from .schemas import GuardResult, GuardViolation

DEFAULT_ALLOWED_IMPORTS: set[str] = {
    "__future__",
    "collections",
    "datetime",
    "itertools",
    "json",
    "math",
    "re",
    "typing",
}

DEFAULT_BANNED_CALLS: set[str] = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
    "os.popen",
    "os.system",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.run",
}

DEFAULT_BANNED_ATTR_SUFFIXES: set[str] = {
    ".chdir",
    ".environ",
    ".fork",
    ".putenv",
    ".popen",
    ".remove",
    ".removedirs",
    ".rename",
    ".replace",
    ".rmdir",
    ".spawn",
    ".system",
    ".unlink",
}

DEFAULT_BANNED_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Lambda,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Yield,
    ast.YieldFrom,
)


class ASTGuard:
    def __init__(
        self,
        allowed_imports: set[str] | None = None,
        banned_calls: set[str] | None = None,
        banned_attr_suffixes: set[str] | None = None,
        banned_ast_nodes: tuple[type[ast.AST], ...] | None = None,
        max_script_size_bytes: int = 256 * 1024,
        forbid_dunder_attr: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.allowed_imports = {
            item.strip().lower()
            for item in (allowed_imports or DEFAULT_ALLOWED_IMPORTS)
            if item.strip()
        }
        self.banned_calls = {
            item.strip().lower() for item in (banned_calls or DEFAULT_BANNED_CALLS) if item.strip()
        }
        self.banned_attr_suffixes = {
            item.strip().lower()
            for item in (banned_attr_suffixes or DEFAULT_BANNED_ATTR_SUFFIXES)
            if item.strip()
        }
        self.banned_ast_nodes = banned_ast_nodes or DEFAULT_BANNED_AST_NODES
        self.max_script_size_bytes = max_script_size_bytes
        self.forbid_dunder_attr = forbid_dunder_attr
        self.logger = logger or logging.getLogger(__name__)

    def validate(self, parser_script_path: str) -> GuardResult:
        violations: list[GuardViolation] = []
        script_path = Path(parser_script_path)

        source = self._read_source(script_path, violations)
        if source is None:
            return GuardResult(ok=False, violations=violations)

        tree = self._parse_source(script_path, source, violations)
        if tree is None:
            return GuardResult(ok=False, violations=violations)

        self._check_top_level(tree, violations)
        for node in ast.walk(tree):
            if self.banned_ast_nodes and isinstance(node, self.banned_ast_nodes):
                self._violate(
                    violations,
                    rule="BANNED_AST_NODE",
                    message=f"Node '{type(node).__name__}' is not allowed.",
                    node=node,
                )
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._check_import(node, violations)
            elif isinstance(node, ast.Call):
                self._check_call(node, violations)
            elif isinstance(node, ast.Attribute):
                self._check_attribute(node, violations)

        self.logger.debug("Parser script guard finished. violations=%d", len(violations))
        return GuardResult(ok=not violations, violations=violations)

    def _read_source(
        self,
        script_path: Path,
        violations: list[GuardViolation],
    ) -> str | None:
        if not script_path.exists() or not script_path.is_file():
            self._violate(
                violations,
                rule="SCRIPT_NOT_FOUND",
                message="Parser script not found.",
            )
            return None

        if script_path.suffix.lower() != ".py":
            self._violate(
                violations,
                rule="SCRIPT_EXTENSION_INVALID",
                message="Parser script must be a .py file.",
            )
            return None

        size = script_path.stat().st_size
        if size > self.max_script_size_bytes:
            self._violate(
                violations,
                rule="SCRIPT_TOO_LARGE",
                message=f"Script size exceeds {self.max_script_size_bytes} bytes.",
            )
            return None

        try:
            content = script_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            self._violate(
                violations,
                rule="SCRIPT_UTF8_INVALID",
                message="Parser script must be UTF-8 encoded.",
            )
            return None
        except OSError as exc:
            self._violate(
                violations,
                rule="SCRIPT_READ_FAILED",
                message=f"Failed to read parser script: {exc}.",
            )
            return None

        return content

    def _parse_source(
        self,
        script_path: Path,
        source: str,
        violations: list[GuardViolation],
    ) -> ast.Module | None:
        try:
            return ast.parse(source, filename=script_path.name, mode="exec")
        except SyntaxError as exc:
            self._violate(
                violations,
                rule="SCRIPT_SYNTAX_ERROR",
                message=exc.msg or "Parser script has syntax error.",
                line=exc.lineno,
                column=exc.offset,
            )
            return None

    def _check_top_level(self, tree: ast.Module, violations: list[GuardViolation]) -> None:
        parse_defs = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "parse"
        ]
        if len(parse_defs) == 0:
            self._violate(
                violations,
                rule="PARSE_FUNCTION_MISSING",
                message="Script must define top-level function parse(file_path, parser_context).",
            )
        elif len(parse_defs) > 1:
            self._violate(
                violations,
                rule="PARSE_FUNCTION_DUPLICATED",
                message="Only one top-level parse function is allowed.",
                node=parse_defs[1],
            )

        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                if isinstance(stmt.value.value, str):
                    continue
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "parse":
                continue
            self._violate(
                violations,
                rule="UNEXPECTED_TOP_LEVEL_STATEMENT",
                message=f"Top-level statement '{type(stmt).__name__}' is not allowed.",
                node=stmt,
            )

    def _check_import(
        self,
        node: ast.Import | ast.ImportFrom,
        violations: list[GuardViolation],
    ) -> None:
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            if node.level and node.level > 0:
                self._violate(
                    violations,
                    rule="IMPORT_RELATIVE_FORBIDDEN",
                    message="Relative import is not allowed in parser script.",
                    node=node,
                )
            modules = [node.module] if node.module else []

        for module_name in modules:
            root_module = module_name.split(".")[0].lower()
            if root_module not in self.allowed_imports:
                self._violate(
                    violations,
                    rule="IMPORT_NOT_ALLOWED",
                    message=f"Import '{module_name}' is not in allowed list.",
                    node=node,
                )

    def _check_call(self, node: ast.Call, violations: list[GuardViolation]) -> None:
        call_name = self._extract_qualified_name(node.func)
        if not call_name:
            return

        normalized = call_name.lower()
        root_name = normalized.split(".")[0]
        if normalized in self.banned_calls or root_name in self.banned_calls:
            self._violate(
                violations,
                rule="CALL_NOT_ALLOWED",
                message=f"Call '{call_name}' is forbidden.",
                node=node,
            )

    def _check_attribute(self, node: ast.Attribute, violations: list[GuardViolation]) -> None:
        if self.forbid_dunder_attr and node.attr.startswith("__") and node.attr.endswith("__"):
            self._violate(
                violations,
                rule="DUNDER_ATTR_FORBIDDEN",
                message=f"Dunder attribute '{node.attr}' is forbidden.",
                node=node,
            )

        qualified_name = self._extract_qualified_name(node) or node.attr
        normalized_name = f".{qualified_name.lower()}"
        for suffix in self.banned_attr_suffixes:
            normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
            if normalized_name.endswith(normalized_suffix):
                self._violate(
                    violations,
                    rule="ATTRIBUTE_NOT_ALLOWED",
                    message=f"Attribute '{qualified_name}' matches forbidden suffix '{normalized_suffix}'.",
                    node=node,
                )
                break

    def _extract_qualified_name(self, expr: ast.AST) -> str | None:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            parent = self._extract_qualified_name(expr.value)
            if parent:
                return f"{parent}.{expr.attr}"
            return expr.attr
        return None

    def _violate(
        self,
        violations: list[GuardViolation],
        rule: str,
        message: str,
        node: ast.AST | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        violations.append(
            GuardViolation(
                rule=rule,
                message=message,
                line=line if line is not None else getattr(node, "lineno", None),
                column=column if column is not None else getattr(node, "col_offset", None),
            )
        )
```

说明：

- 上述实现会收集全部违规项，避免用户反复修改。
- 规则均为可配置输入，服务层可按租户/环境注入不同策略。

---

## 4. `SandboxRunner` 完整实现

文件：`app/features/import/parser_runtime/sandbox_runner.py`

```python
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from .schemas import ParseResult, ParserRuntimeError


class SandboxRunner:
    def __init__(
        self,
        runtime_image: str,
        timeout_seconds: int = 10,
        cpu_limit: str = "1",
        memory_limit: str = "256m",
        pids_limit: int = 64,
        network_disabled: bool = True,
        read_only_rootfs: bool = True,
        work_dir: str = "/tmp/parser_runtime",
        docker_bin: str = "docker",
        logger: logging.Logger | None = None,
    ) -> None:
        self.runtime_image = runtime_image
        self.timeout_seconds = timeout_seconds
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.pids_limit = pids_limit
        self.network_disabled = network_disabled
        self.read_only_rootfs = read_only_rootfs
        self.work_dir = Path(work_dir)
        self.docker_bin = docker_bin
        self.logger = logger or logging.getLogger(__name__)

    def run_parse(
        self,
        parser_script_path: str,
        file_path: str,
        parser_context: dict[str, Any] | None = None,
    ) -> ParseResult:
        script_path = Path(parser_script_path).resolve()
        source_file = Path(file_path).resolve()
        context = parser_context or {}

        self._ensure_local_file(script_path, "parser script")
        self._ensure_local_file(source_file, "target file")

        request_id = str(context.get("request_id", "unknown"))
        script_sha256 = self._sha256_file(script_path)
        started_at = time.monotonic()

        self.work_dir.mkdir(parents=True, exist_ok=True)
        job_dir = Path(tempfile.mkdtemp(prefix="parser-runtime-", dir=self.work_dir))

        try:
            input_dir, output_dir = self._prepare_job_dir(job_dir, script_path, source_file, context)
            command = self._build_command(input_dir=input_dir, output_dir=output_dir)
            completed = self._run_command(command)
            result = self._load_and_validate_output(output_dir / "output.json")

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self.logger.info(
                "Sandbox parse succeeded",
                extra={
                    "request_id": request_id,
                    "script_sha256": script_sha256,
                    "elapsed_ms": elapsed_ms,
                    "exit_code": completed.returncode,
                },
            )
            return result
        except ParserRuntimeError as exc:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self.logger.warning(
                "Sandbox parse failed",
                extra={
                    "request_id": request_id,
                    "script_sha256": script_sha256,
                    "elapsed_ms": elapsed_ms,
                    "error_code": exc.code,
                    "error_message": exc.message,
                },
            )
            raise
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _prepare_job_dir(
        self,
        job_dir: Path,
        script_path: Path,
        source_file: Path,
        context: dict[str, Any],
    ) -> tuple[Path, Path]:
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        parser_target = input_dir / "parser.py"
        source_name = f"source{source_file.suffix}" if source_file.suffix else "source"
        source_target = input_dir / source_name

        shutil.copy2(script_path, parser_target)
        shutil.copy2(source_file, source_target)

        try:
            (input_dir / "context.json").write_text(
                json.dumps(context, ensure_ascii=False),
                encoding="utf-8",
            )
        except TypeError as exc:
            raise ParserRuntimeError(
                code="PARSER_SCRIPT_RUNTIME_ERROR",
                message="parser_context must be JSON serializable.",
            ) from exc

        runtime_manifest = {
            "input_file_path": f"/job/{source_name}",
            "timeout_seconds": self.timeout_seconds,
        }
        (input_dir / "runtime.json").write_text(
            json.dumps(runtime_manifest, ensure_ascii=False),
            encoding="utf-8",
        )
        (input_dir / "entrypoint.py").write_text(self._entrypoint_script(), encoding="utf-8")
        return input_dir, output_dir

    def _build_command(self, input_dir: Path, output_dir: Path) -> list[str]:
        command: list[str] = [
            self.docker_bin,
            "run",
            "--rm",
            "--user",
            "65534:65534",
            "--cpus",
            self.cpu_limit,
            "--memory",
            self.memory_limit,
            "--pids-limit",
            str(self.pids_limit),
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--volume",
            f"{input_dir.resolve()}:/job:ro",
            "--volume",
            f"{output_dir.resolve()}:/output:rw",
            "--workdir",
            "/job",
        ]
        if self.network_disabled:
            command.extend(["--network", "none"])
        if self.read_only_rootfs:
            command.append("--read-only")

        command.extend([self.runtime_image, "python", "/job/entrypoint.py"])
        return command

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 2,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParserRuntimeError(
                code="PARSER_SCRIPT_TIMEOUT",
                message=f"Parser script timed out after {self.timeout_seconds} seconds.",
            ) from exc
        except FileNotFoundError as exc:
            raise ParserRuntimeError(
                code="PARSER_SCRIPT_RUNTIME_ERROR",
                message=f"Sandbox runtime binary '{self.docker_bin}' is not installed.",
            ) from exc

        if completed.returncode != 0:
            stderr = completed.stderr or ""
            if "Parser function timed out" in stderr:
                raise ParserRuntimeError(
                    code="PARSER_SCRIPT_TIMEOUT",
                    message=f"Parser script timed out after {self.timeout_seconds} seconds.",
                    details={"stderr": self._clip(stderr)},
                )
            raise ParserRuntimeError(
                code="PARSER_SCRIPT_RUNTIME_ERROR",
                message="Parser script exited with non-zero status.",
                details={
                    "exit_code": completed.returncode,
                    "stdout": self._clip(completed.stdout),
                    "stderr": self._clip(completed.stderr),
                },
            )
        return completed

    def _load_and_validate_output(self, output_path: Path) -> ParseResult:
        if not output_path.exists():
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Sandbox output.json does not exist.",
            )
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Sandbox output.json is not valid JSON.",
            ) from exc

        if not isinstance(payload, dict):
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Parser result must be a JSON object.",
            )
        chunks = payload.get("chunks")
        search_profile = payload.get("search_profile")
        local_file_storage_plan = payload.get("local_file_storage_plan")

        if not isinstance(chunks, list) or not chunks:
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Field 'chunks' must be a non-empty list.",
            )
        if not all(isinstance(item, dict) for item in chunks):
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Each item in 'chunks' must be an object.",
            )
        if not isinstance(search_profile, dict):
            raise ParserRuntimeError(
                code="PARSE_RESULT_SCHEMA_INVALID",
                message="Field 'search_profile' must be an object.",
            )
        if local_file_storage_plan is not None:
            if not isinstance(local_file_storage_plan, dict):
                raise ParserRuntimeError(
                    code="PARSE_RESULT_SCHEMA_INVALID",
                    message="Field 'local_file_storage_plan' must be an object when provided.",
                )
            plan_files = local_file_storage_plan.get("files")
            if not isinstance(plan_files, list):
                raise ParserRuntimeError(
                    code="PARSE_RESULT_SCHEMA_INVALID",
                    message="Field 'local_file_storage_plan.files' must be a list.",
                )
            if not all(isinstance(item, dict) for item in plan_files):
                raise ParserRuntimeError(
                    code="PARSE_RESULT_SCHEMA_INVALID",
                    message="Each item in 'local_file_storage_plan.files' must be an object.",
                )
        return ParseResult(
            chunks=chunks,
            search_profile=search_profile,
            local_file_storage_plan=local_file_storage_plan,
        )

    def _ensure_local_file(self, path: Path, label: str) -> None:
        if not path.exists() or not path.is_file():
            raise ParserRuntimeError(
                code="PARSER_SCRIPT_RUNTIME_ERROR",
                message=f"{label} does not exist: {path}",
            )

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fp:
            while True:
                chunk = fp.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _clip(self, text: str | None, limit: int = 2000) -> str:
        if not text:
            return ""
        return text if len(text) <= limit else text[:limit] + "...<truncated>"

    def _entrypoint_script(self) -> str:
        return textwrap.dedent(
            """
            from __future__ import annotations

            import importlib.util
            import json
            import signal
            import traceback
            from pathlib import Path

            OUTPUT_FILE = Path("/output/output.json")
            RUNTIME_META = Path("/job/runtime.json")
            CONTEXT_FILE = Path("/job/context.json")
            PARSER_FILE = Path("/job/parser.py")

            class _ScriptTimeout(RuntimeError):
                pass

            def _on_timeout(signum, frame):
                raise _ScriptTimeout("Parser function timed out")

            def _load_parse():
                spec = importlib.util.spec_from_file_location("user_parser_module", PARSER_FILE)
                if spec is None or spec.loader is None:
                    raise RuntimeError("Failed to load parser module")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                parse_fn = getattr(module, "parse", None)
                if not callable(parse_fn):
                    raise RuntimeError("Missing callable parse(file_path, parser_context)")
                return parse_fn

            def main():
                runtime = json.loads(RUNTIME_META.read_text(encoding="utf-8"))
                parse_fn = _load_parse()
                parser_context = json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))
                timeout_seconds = int(runtime.get("timeout_seconds", 0))
                input_file_path = str(runtime["input_file_path"])

                if timeout_seconds > 0:
                    signal.signal(signal.SIGALRM, _on_timeout)
                    signal.alarm(timeout_seconds)
                try:
                    result = parse_fn(input_file_path, parser_context)
                finally:
                    if timeout_seconds > 0:
                        signal.alarm(0)

                OUTPUT_FILE.write_text(
                    json.dumps(result, ensure_ascii=False),
                    encoding="utf-8",
                )

            if __name__ == "__main__":
                try:
                    main()
                except Exception:
                    traceback.print_exc()
                    raise
            """
        ).strip() + "\n"
```

错误码映射（实现已覆盖）：

- 超时（外层 `subprocess timeout` 或内层 `signal.alarm`）-> `PARSER_SCRIPT_TIMEOUT`
- 容器/脚本非 0 退出 -> `PARSER_SCRIPT_RUNTIME_ERROR`
- 输出 JSON 不合法或字段缺失 -> `PARSE_RESULT_SCHEMA_INVALID`

---

## 5. 与服务层的集成约束

服务层固定调用顺序：

1. `ASTGuard.validate(script_path)`
2. `SandboxRunner.run_parse(script_path, file_path, parser_context)`
3. `validate_parse_result_schema(parse_result)`

不允许跳过 AST 检查直接运行脚本。

---

## 6. 单元测试与集成测试建议

### 6.1 ASTGuard

1. 合法脚本通过
2. 非白名单 import 拒绝
3. 黑名单调用拒绝
4. 禁止节点拒绝
5. dunder 访问拒绝
6. 多违规项完整返回

### 6.2 SandboxRunner

1. 正常脚本输出 `ParseResult`
2. 脚本超时 -> `PARSER_SCRIPT_TIMEOUT`
3. 脚本异常 -> `PARSER_SCRIPT_RUNTIME_ERROR`
4. 非法输出 -> `PARSE_RESULT_SCHEMA_INVALID`
5. 资源限制生效（超内存/超进程）
6. 执行后临时目录清理

