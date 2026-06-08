"""Orchestrator — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import hashlib
import os
import tempfile

from .manifest_loader import load_manifest
from .file_classifier import classify_files
from .zip_safe_extractor import safe_extract
from .package_validator import validate_single_top_level_dir
from .skills_md_locator import locate_skills_md
from .skills_md_parser import parse_standard_skills_md
from .chunk_builder import build_chunks
from .storage_plan_builder import build_local_storage_plan
from .search_profile_builder import build_search_profile


def parse_skill_manifest(manifest_path: str, parser_context: dict) -> dict:
    """Orchestrate full SKILL parse.

    Returns {chunks, search_profile, local_file_storage_plan}.
    """
    files = load_manifest(manifest_path)
    skill_package, other_files = classify_files(files)

    # Extract to a temp dir alongside the manifest
    extract_dir = os.path.join(os.path.dirname(manifest_path), "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    safe_extract(skill_package["abs_path"], extract_dir)
    skill_name = validate_single_top_level_dir(extract_dir)

    skills_md_path = locate_skills_md(extract_dir, skill_name)
    skill_doc = parse_standard_skills_md(skills_md_path)

    with open(skill_package["abs_path"], "rb") as f:
        package_sha256 = hashlib.sha256(f.read()).hexdigest()
    package_info = {
        "filename": skill_package["filename"],
        "sha256": package_sha256,
        "path": skill_package["abs_path"],
    }

    search_profile = build_search_profile(skill_doc=skill_doc)
    local_file_storage_plan = build_local_storage_plan(skill_package, other_files)

    # Collect all file_refs from the storage plan so chunks can reference them;
    # store_skill.py will backfill related_storage_paths after files are persisted.
    all_file_refs = [f["file_ref"] for f in local_file_storage_plan.get("files", [])]

    chunks = build_chunks(
        skill_doc=skill_doc,
        package=package_info,
        parser_context=parser_context,
        file_refs=all_file_refs,
        skill_name=skill_name,
    )

    return {
        "chunks": chunks,
        "search_profile": search_profile,
        "local_file_storage_plan": local_file_storage_plan,
    }
