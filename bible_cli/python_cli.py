"""CLI entrypoint and parser tree for bible-cli."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from bible_cli.commands import CommandsManager, build_parser
from bible_cli.exceptions import BibleCLIError


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
