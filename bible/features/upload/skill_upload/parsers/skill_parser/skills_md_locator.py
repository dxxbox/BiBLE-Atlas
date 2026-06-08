"""SKILLS.md locator — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations

import os


def locate_skills_md(extract_dir: str, skill_name: str) -> str:
    """Return absolute path to <skill-name>/SKILLS.md.

    Case-sensitive match for SKILLS.md.

    Raises ValueError with code SKILL_MD_NOT_FOUND or SKILL_MD_MULTIPLE.
    """
    skill_dir = os.path.join(extract_dir, skill_name)
    if not os.path.isdir(skill_dir):
        raise ValueError(
            f"SKILL_MD_NOT_FOUND: Skill directory '{skill_name}' not found under extract dir."
        )

    matches = [
        entry for entry in os.listdir(skill_dir)
        if entry == "SKILLS.md" and os.path.isfile(os.path.join(skill_dir, entry))
    ]

    if len(matches) == 0:
        raise ValueError(
            f"SKILL_MD_NOT_FOUND: SKILLS.md not found in '{skill_name}/'. "
            "The .skill package must contain a SKILLS.md file."
        )

    if len(matches) > 1:
        raise ValueError(
            f"SKILL_MD_MULTIPLE: Multiple SKILLS.md files found in '{skill_name}/'."
        )

    return os.path.join(skill_dir, matches[0])
