from __future__ import annotations

import argparse
from collections.abc import Callable

from bible_cli.commands.parsers.health_parser import register_health_command
from bible_cli.commands.parsers.knowledge_parser import register_knowledge_command
from bible_cli.commands.parsers.memory_parser import register_memory_command
from bible_cli.commands.parsers.skills_parser import register_skills_command
from bible_cli.commands.parsers.system_parser import register_system_command

CommandRegistrar = Callable[[argparse._SubParsersAction], None]

COMMAND_REGISTRARS: tuple[CommandRegistrar, ...] = (
    register_health_command,
    register_system_command,
    register_knowledge_command,
    register_memory_command,
    register_skills_command,
)

