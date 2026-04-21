from __future__ import annotations

import argparse


def register_skills_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("skills", help="Skills related commands")
    action_parser = parser.add_subparsers(dest="action", metavar="action")
    action_parser.add_parser("list", help="List available skills (planned)")

