"""URI helper placeholder."""

from __future__ import annotations


class BibleURI:
    """Minimal URI value object; full validation arrives in later phases."""

    def __init__(self, raw: str) -> None:
        self.raw = raw

    def __str__(self) -> str:
        return self.raw
