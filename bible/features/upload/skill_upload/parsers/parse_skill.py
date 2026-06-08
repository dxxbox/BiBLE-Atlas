#!/usr/bin/env python3
"""parse_skill.py — SKILL import parser entry point.

Invocation (by SandboxRunner):
    python parse_skill.py --manifest <manifest_path> [--context <json_string>]

Prints a single JSON object to stdout:
    { "chunks": [...], "search_profile": {...}, "local_file_storage_plan": {...} }

Exit codes:
    0  success
    1  validation or runtime error (error message on stderr)

This file runs in a subprocess sandbox and MUST use stdlib only.
No `bible.` imports allowed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _setup_path() -> None:
    """Add this script's directory to sys.path so the skill_parser package is importable."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)


def main() -> None:
    _setup_path()

    parser = argparse.ArgumentParser(description="SKILL import parser")
    parser.add_argument("--manifest", required=True, help="Path to skill_request_manifest.json")
    parser.add_argument("--context", default=None, help="Optional JSON parser context string")
    args = parser.parse_args()

    parser_context: dict = {}
    if args.context:
        try:
            parser_context = json.loads(args.context)
        except json.JSONDecodeError as exc:
            print(f"Invalid --context JSON: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        from skill_parser.orchestrator import parse_skill_manifest  # type: ignore[import]
        result = parse_skill_manifest(manifest_path=args.manifest, parser_context=parser_context)
    except Exception as exc:  # noqa: BLE001
        print(f"Parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
