"""Exception model for bible-cli."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COMMAND_NOT_IMPLEMENTED_EXIT_CODE = 3


@dataclass(slots=True)
class BibleCLIError(Exception):
    """Base error with stable code/details fields for CLI output."""

    message: str
    code: str = "CLI_ERROR"
    exit_code: int = 1
    details: dict[str, Any] | None = None


class CommandNotImplementedError(BibleCLIError):
    """Raised when a command path is declared but not implemented yet."""

    def __init__(self, command_path: str) -> None:
        super().__init__(
            message=f"Command '{command_path}' is not implemented yet.",
            code="CLI_NOT_IMPLEMENTED",
            exit_code=COMMAND_NOT_IMPLEMENTED_EXIT_CODE,
            details={"command_path": command_path},
        )
