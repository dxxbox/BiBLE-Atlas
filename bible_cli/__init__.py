"""Bible CLI package."""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Lazy-load CLI entrypoint to avoid import resolution issues."""
    from .python_cli import main as cli_main

    return cli_main(argv)
    