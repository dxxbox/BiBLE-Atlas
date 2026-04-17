"""Command handlers for top-level command groups."""

from __future__ import annotations

from argparse import Namespace

from bible_cli.exceptions import CommandNotImplementedError


class _BaseCommands:
    group_name: str

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class SystemCommands(_BaseCommands):
    group_name = "system"


class KnowledgeCommands(_BaseCommands):
    group_name = "knowledge"


class MemoryCommands(_BaseCommands):
    group_name = "memory"


class SkillsCommands(_BaseCommands):
    group_name = "skills"
