from __future__ import annotations

import argparse


def register_knowledge_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("knowledge", help="Knowledge related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("list", help="List knowledge entries")
    search_parser = action_parser.add_parser("search", help="Search knowledge entries")
    search_parser.add_argument("query", nargs="?", default=None, help="Optional search keyword")

