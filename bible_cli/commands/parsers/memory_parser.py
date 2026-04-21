from __future__ import annotations

import argparse


def register_memory_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("memory", help="Memory related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("show", help="Display memory information (planned)")

