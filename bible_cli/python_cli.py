"""CLI entrypoint and parser tree for bible-cli."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bible_cli.commands import CommandsManager, build_parser
from bible_cli.exceptions import BibleCLIError, CommandNotImplementedError


def _unknown_action_path(
    parser: argparse.ArgumentParser, argv: list[str]
) -> str | None:
    """Return 'command action' string when argv[1] is not a registered action for argv[0].

    Returns None when the command itself is unknown or when argv has fewer than 2 tokens,
    so ordinary argparse errors (missing required args for a *known* action) are not masked.
    """
    if len(argv) < 2:
        return None
    try:
        ns, _ = parser.parse_known_args([argv[0]])
    except SystemExit:
        return None
    if ns.command is None:
        return None
    for top_action in parser._actions:  # noqa: SLF001
        choices = getattr(top_action, "choices", None)
        if not isinstance(choices, dict) or ns.command not in choices:
            continue
        cmd_parser = choices[ns.command]
        for cmd_action in cmd_parser._actions:  # noqa: SLF001
            sub_choices = getattr(cmd_action, "choices", None)
            if isinstance(sub_choices, dict) and argv[1] not in sub_choices:
                return f"{argv[0]} {argv[1]}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint used by script aliases."""
    parser = build_parser()
    args_list = list(argv) if argv is not None else None
    _argv = args_list if args_list is not None else sys.argv[1:]

    try:
        parsed_args = parser.parse_args(args_list)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        command_path = _unknown_action_path(parser, _argv)
        if command_path is not None:
            error = CommandNotImplementedError(command_path)
            print(f"Error[{error.code}]: {error.message}", file=sys.stderr)
            return error.exit_code
        return int(exc.code) if isinstance(exc.code, int) else 1

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
