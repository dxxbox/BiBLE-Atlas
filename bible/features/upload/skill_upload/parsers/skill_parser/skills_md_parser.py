"""SKILL.md parser — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations


def parse_standard_skills_md(md_path: str) -> dict:
    """Parse SKILL.md to extract name, description, and body.

    SKILL.md format convention:
    - First H1 heading (# ...) → name
    - First paragraph (non-heading, non-empty text after the H1) → description
    - Everything after the description paragraph → body (raw markdown)

    Returns {name: str, description: str, body: str}.

    Raises ValueError with code SKILL_MD_PARSE_INVALID or SKILL_MD_REQUIRED_FIELD_MISSING.
    """
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        raise ValueError(f"SKILL_MD_PARSE_INVALID: Cannot read SKILL.md: {exc}")

    if not content.strip():
        raise ValueError("SKILL_MD_PARSE_INVALID: SKILL.md is empty.")

    lines = content.splitlines()

    # Find the first H1 heading
    name: str | None = None
    h1_line_idx: int = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            name = stripped[2:].strip()
            h1_line_idx = i
            break

    if name is None:
        raise ValueError(
            "SKILL_MD_REQUIRED_FIELD_MISSING: SKILL.md must contain an H1 heading (# ...) "
            "for the skill name."
        )

    if not name:
        raise ValueError(
            "SKILL_MD_REQUIRED_FIELD_MISSING: SKILL.md H1 heading is empty — skill name is required."
        )

    # Find the first non-empty, non-heading paragraph after the H1
    description: str | None = None
    description_end_idx: int = -1

    i = h1_line_idx + 1
    while i < len(lines):
        line = lines[i].strip()
        if line and not line.startswith("#"):
            # Collect contiguous non-empty, non-heading lines as the description paragraph
            para_lines = []
            while i < len(lines):
                current = lines[i].strip()
                if not current or current.startswith("#"):
                    break
                para_lines.append(current)
                i += 1
            description = " ".join(para_lines).strip()
            description_end_idx = i
            break
        i += 1

    if not description:
        raise ValueError(
            "SKILL_MD_REQUIRED_FIELD_MISSING: SKILL.md must contain a description paragraph "
            "after the H1 heading."
        )

    # Everything after the description paragraph is the body
    if description_end_idx >= 0 and description_end_idx < len(lines):
        body = "\n".join(lines[description_end_idx:]).strip()
    else:
        body = ""

    return {
        "name": name,
        "description": description,
        "body": body,
    }
