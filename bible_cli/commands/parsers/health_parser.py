from __future__ import annotations

import argparse


def register_health_command(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser("health", help="Quick server heartbeat check")

