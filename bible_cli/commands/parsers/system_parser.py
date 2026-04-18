from __future__ import annotations

import argparse


def register_system_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("system", help="System related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("status", help="Get server runtime status")
    action_parser.add_parser("info", help="Fetch server info")

