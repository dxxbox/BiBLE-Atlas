"""File classifier — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import os


def classify_files(files: list[dict]) -> tuple[dict, list[dict]]:
    """Classify uploaded files into skill package and other files.

    Returns (skill_package_file, other_files).

    Raises ValueError if != 1 .skill file found.
    Error codes embedded in exception message: SKILL_PACKAGE_MISSING or SKILL_PACKAGE_MULTIPLE
    """
    skill_files = [f for f in files if os.path.splitext(f.get("filename", ""))[1].lower() == ".skill"]
    other_files = [f for f in files if f not in skill_files]

    if len(skill_files) == 0:
        raise ValueError(
            "SKILL_PACKAGE_MISSING: No .skill package file found in upload. "
            "Exactly one .skill file is required."
        )
    if len(skill_files) > 1:
        names = ", ".join(f["filename"] for f in skill_files)
        raise ValueError(
            f"SKILL_PACKAGE_MULTIPLE: Multiple .skill package files found: {names}. "
            "Exactly one .skill file is required."
        )

    return skill_files[0], other_files
