"""Package structure validator — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import os


def validate_single_top_level_dir(extract_dir: str) -> str:
    """Validate that the extracted ZIP has exactly one top-level directory.

    Returns skill_name (the single top-level directory name).

    Raises ValueError if:
    - Root-level files exist (not allowed)
    - Zero or multiple top-level directories
    """
    entries = os.listdir(extract_dir)
    if not entries:
        raise ValueError(
            "SKILL_PACKAGE_INVALID_FORMAT: The .skill package is empty after extraction."
        )

    dirs = []
    files = []
    for entry in entries:
        full = os.path.join(extract_dir, entry)
        if os.path.isdir(full):
            dirs.append(entry)
        else:
            files.append(entry)

    if files:
        raise ValueError(
            f"SKILL_PACKAGE_INVALID_FORMAT: Root-level files found in .skill package: "
            f"{', '.join(files)}. All content must be under a single top-level directory."
        )

    if len(dirs) == 0:
        raise ValueError(
            "SKILL_PACKAGE_INVALID_FORMAT: No top-level directory found in .skill package."
        )

    if len(dirs) > 1:
        raise ValueError(
            f"SKILL_PACKAGE_INVALID_FORMAT: Multiple top-level directories found: "
            f"{', '.join(dirs)}. Exactly one is required."
        )

    return dirs[0]
