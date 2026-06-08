"""Manifest loader — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import json
import os


def load_manifest(manifest_path: str) -> list[dict]:
    """Read the manifest JSON written by StoreSkill.build_parse_manifest().

    Returns a list of dicts, each with keys:
        file_ref, filename, abs_path, size_bytes, content_type
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    files: list[dict] = manifest.get("files", [])
    result: list[dict] = []
    for entry in files:
        result.append(
            {
                "file_ref": entry.get("file_ref", ""),
                "filename": entry.get("filename", ""),
                "abs_path": entry.get("abs_path", ""),
                "size_bytes": entry.get("size_bytes", 0),
                "content_type": entry.get("content_type", "application/octet-stream"),
            }
        )
    return result
