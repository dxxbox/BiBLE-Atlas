"""Central command dispatcher."""

from __future__ import annotations

from argparse import Namespace

from bible_cli.commands.handlers import (
    HealthCommands,
    KnowledgeCommands,
    MemoryCommands,
    SkillsCommands,
    SystemCommands,
)


class CommandsManager:
    """Dispatch parsed args to dedicated command group handlers."""

    def __init__(self) -> None:
        self._handlers = {
            "health": HealthCommands(),
            "system": SystemCommands(),
            "knowledge": KnowledgeCommands(),
            "memory": MemoryCommands(),
            "skills": SkillsCommands(),
        }

    def dispatch(self, args: Namespace) -> int:
        command = getattr(args, "command", None)
        if command is None:
            return 0
        handler = self._handlers[command]
        return handler.execute(args)
