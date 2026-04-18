"""CLI parser composition for command tree."""

from __future__ import annotations

import argparse

from bible_cli.commands.parsers.registry import COMMAND_REGISTRARS


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser with current command tree."""
    parser = argparse.ArgumentParser(
        prog="bs",
        description="Bible CLI command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for registrar in COMMAND_REGISTRARS:
        registrar(subparsers)

    return parser
