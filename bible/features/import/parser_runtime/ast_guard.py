from __future__ import annotations

import ast

from bible.common.errors import DomainError, ErrorCode

FORBIDDEN_MODULES = {"os", "sys", "subprocess", "socket", "shutil", "importlib", "ctypes", "builtins"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open"}


class _ASTVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in FORBIDDEN_MODULES:
                self.violations.append(f"Forbidden import: {alias.name} (line {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        root = module.split(".")[0]
        if root in FORBIDDEN_MODULES:
            self.violations.append(f"Forbidden from-import: {module} (line {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name and name in FORBIDDEN_CALLS:
            self.violations.append(f"Forbidden call: {name}() (line {node.lineno})")
        self.generic_visit(node)


class ASTGuard:
    def validate(self, script_path: str) -> None:
        with open(script_path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=script_path)
        except SyntaxError as exc:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                f"Parser script has syntax error: {exc}",
                details={"code": "PARSER_SCRIPT_RISK"},
            )

        visitor = _ASTVisitor()
        visitor.visit(tree)

        if visitor.violations:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Parser script contains forbidden patterns: " + "; ".join(visitor.violations),
                details={"code": "PARSER_SCRIPT_RISK", "violations": visitor.violations},
            )
