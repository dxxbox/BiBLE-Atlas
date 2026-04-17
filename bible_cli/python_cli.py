"""CLI entrypoint and parser tree for bible-cli."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bible_cli.commands import CommandsManager
from bible_cli.exceptions import BibleCLIError


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser with Phase-1 command tree."""
    parser = argparse.ArgumentParser(
        prog="bs",
        description="Bible CLI command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    _add_system_command(subparsers)
    _add_knowledge_command(subparsers)
    _add_memory_command(subparsers)
    _add_skills_command(subparsers)
    return parser


def _add_system_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("system", help="System related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("health", help="Check server health (planned)")


def _add_knowledge_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("knowledge", help="Knowledge related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("search", help="Search knowledge entries (planned)")


def _add_memory_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("memory", help="Memory related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("show", help="Display memory information (planned)")


def _add_skills_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("skills", help="Skills related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("list", help="List available skills (planned)")


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint used by script aliases."""
    parser = build_parser()
    parsed_args = parser.parse_args(list(argv) if argv is not None else None)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    manager = CommandsManager()
    try:
        return manager.dispatch(parsed_args)
    except BibleCLIError as error:
        print(f"Error[{error.code}]: {error.message}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
