"""Chunk builder — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import hashlib


def build_chunks(
    skill_doc: dict,
    package: dict,
    parser_context: dict,
    file_refs: list[str] | None = None,
    skill_name: str = "",
) -> list[dict]:
    """Build chunk list from parsed SKILLS.md doc."""
    name: str = skill_doc["name"]
    description: str = skill_doc["description"]
    body: str = skill_doc.get("body", "")

    content = f"{name}\n{description}"
    if body:
        content = f"{content}\n\n{body}"

    package_filename: str = package.get("filename", "")
    package_sha256: str = package.get("sha256", "")

    doc_id_src = f"{package_sha256}::{name}"
    doc_id = hashlib.sha256(doc_id_src.encode("utf-8")).hexdigest()

    # source_file points to the canonical SKILLS.md location inside the package
    source_file = f"{skill_name}/SKILLS.md" if skill_name else package_filename

    chunk: dict = {
        "doc_id": doc_id,
        "title": name,
        "name": name,
        "description": description,
        "body": body,
        "content": content,
        "metadata": {
            "source_file": source_file,
            "skill_name": name,
            "related_file_refs": list(file_refs) if file_refs else [],
            "related_storage_paths": [],
            "package_filename": package_filename,
            "package_sha256": package_sha256,
            "parser_version": "v4-skill-package-1",
        },
    }

    return [chunk]
