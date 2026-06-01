from __future__ import annotations
from typing import Any

from .chunk_builder import build_single_memory_chunk
from .file_classifier import split_meta_and_attachments
from .manifest_loader import load_manifest
from .meta_parser import parse_meta
from .search_profile_builder import build_search_profile
from .storage_plan_builder import build_local_storage_plan


def parse_manifest(file_path: str, parser_context: dict[str, Any]) -> dict[str, Any]:
    """Full parse pipeline for a single memory import manifest.

    Returns a dict with keys: chunks, search_profile, local_file_storage_plan.
    """
    del parser_context  # reserved for future use

    files = load_manifest(file_path)
    meta_file, attachments = split_meta_and_attachments(files)
    meta = parse_meta(meta_file.abs_path)

    chunks = build_single_memory_chunk(meta, attachments)
    search_profile = build_search_profile()
    local_file_storage_plan = build_local_storage_plan(attachments)

    return {
        "chunks": chunks,
        "search_profile": search_profile,
        "local_file_storage_plan": local_file_storage_plan,
    }