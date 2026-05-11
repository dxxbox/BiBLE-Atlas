from __future__ import annotations

import argparse
from pathlib import Path


def register_memory_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the `bible memory` command tree."""
    memory = subparsers.add_parser("memory", help="Memory management commands (v4)")
    action_parser = memory.add_subparsers(dest="action", metavar="action")

    _register_upload(action_parser)
    _register_upload_all(action_parser)
    _register_build_meta(action_parser)
    _register_status(action_parser)
    _register_search(action_parser)


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

def _register_upload(action_parser: argparse._SubParsersAction) -> None:
    p = action_parser.add_parser(
        "upload",
        help="Upload a session directory to MEMORY index (v4).",
    )
    p.add_argument(
        "session_dir",
        type=Path,
        help="Session directory containing meta.json (and optionally message.json).",
    )
    p.add_argument(
        "--kb-index",
        dest="kb_index",
        default=None,
        help=(
            "Knowledge base index name (required; fallback: BIBLE_MEMORY_KB_INDEX env var "
            "or config memory.upload.kb_index)."
        ),
    )
    p.add_argument(
        "--skip-if-exists",
        dest="skip_if_exists",
        action="store_true",
        default=True,
        help="Skip upload if session was already uploaded with same meta content (default: true).",
    )
    p.add_argument(
        "--no-skip",
        dest="skip_if_exists",
        action="store_false",
        help="Force re-upload even if meta_hash matches.",
    )
    p.add_argument(
        "--vector-model",
        dest="vector_model",
        default=None,
        help="Optional vector model name for embedding (e.g. 'bge-m3').",
    )
    p.add_argument(
        "--task-id",
        dest="task_ids",
        action="append",
        default=[],
        metavar="TASK_ID",
        help="Append a task ID tag to meta.json (may be repeated).",
    )
    p.add_argument(
        "--feature-tag",
        dest="feature_tags",
        action="append",
        default=[],
        metavar="TAG",
        help="Append a feature tag to meta.json (may be repeated).",
    )
    p.add_argument(
        "--title",
        dest="title",
        default=None,
        help="Override the title field in meta.json.",
    )
    p.add_argument(
        "--abstract",
        dest="abstract",
        default=None,
        help="Override the abstract field in meta.json.",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        default=False,
        help="Wait for the import task to complete and print final status.",
    )


# ---------------------------------------------------------------------------
# upload-all
# ---------------------------------------------------------------------------

def _register_upload_all(action_parser: argparse._SubParsersAction) -> None:
    p = action_parser.add_parser(
        "upload-all",
        help="Upload all session directories found under a base directory.",
    )
    p.add_argument(
        "base_dir",
        type=Path,
        help="Base directory whose immediate subdirectories are session directories.",
    )
    p.add_argument(
        "--kb-index",
        dest="kb_index",
        default=None,
        help="Knowledge base index name (required; fallback: BIBLE_MEMORY_KB_INDEX).",
    )
    p.add_argument(
        "--skip-if-exists",
        dest="skip_if_exists",
        action="store_true",
        default=True,
    )
    p.add_argument(
        "--no-skip",
        dest="skip_if_exists",
        action="store_false",
    )
    p.add_argument("--vector-model", dest="vector_model", default=None)
    p.add_argument(
        "--wait",
        action="store_true",
        default=False,
        help="Wait for each import task to complete before uploading next.",
    )


# ---------------------------------------------------------------------------
# build-meta
# ---------------------------------------------------------------------------

def _register_build_meta(action_parser: argparse._SubParsersAction) -> None:
    p = action_parser.add_parser(
        "build-meta",
        help="Build v4 format meta.json from message.json (idempotent).",
    )
    p.add_argument(
        "session_dir",
        type=Path,
        help="Session directory containing message.json.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing meta.json.",
    )
    p.add_argument(
        "--title",
        dest="title",
        default=None,
        help="Override the generated title.",
    )
    p.add_argument(
        "--abstract",
        dest="abstract",
        default=None,
        help="Override the generated abstract.",
    )
    p.add_argument(
        "--task-id",
        dest="task_ids",
        action="append",
        default=[],
        metavar="TASK_ID",
    )
    p.add_argument(
        "--feature-tag",
        dest="feature_tags",
        action="append",
        default=[],
        metavar="TAG",
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _register_status(action_parser: argparse._SubParsersAction) -> None:
    p = action_parser.add_parser(
        "status",
        help="Query upload task status for a session or a specific task ID.",
    )
    p.add_argument(
        "target",
        help="Session directory path (reads task_id from .bible-memory-cache.json) or bare task ID.",
    )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def _register_search(action_parser: argparse._SubParsersAction) -> None:
    p = action_parser.add_parser(
        "search",
        help="Search MEMORY index via /api/search/memory.",
    )
    p.add_argument("query", help="Search query string.")
    p.add_argument(
        "--kb-index",
        dest="kb_index",
        default=None,
        help="Knowledge base index name (required; fallback: BIBLE_MEMORY_KB_INDEX).",
    )
    p.add_argument(
        "--type",
        dest="search_type",
        default="hybrid",
        choices=["keyword", "title", "text", "vector", "hybrid"],
        help="Search strategy (default: hybrid).",
    )
    p.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=10,
        help="Max number of results to return (default: 10).",
    )
    p.add_argument(
        "--tag",
        dest="tag",
        default=None,
        help="Filter results by tag.",
    )
