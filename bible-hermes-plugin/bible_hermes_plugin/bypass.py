"""BiBLE Hermes Plugin — session bypass logic.

Sessions whose ID matches one of the configured regex patterns are skipped
for both recall and capture (e.g. scratch sessions, test sessions).
"""

from __future__ import annotations

import re


def is_bypassed_session(session_id: str, patterns: list[re.Pattern]) -> bool:
    """Return True if session_id matches any of the compiled bypass patterns."""
    if not patterns or not session_id:
        return False
    return any(p.search(session_id) for p in patterns)
