"""Hermes directory-plugin shim.

When Hermes discovers this directory as a plugin (via ~/.hermes/plugins/bible-hermes-plugin/),
it imports this file. We forward the register() call to the actual package.

For pip-installed distribution, Hermes uses the entry point declared in
pyproject.toml → [project.entry-points."hermes_agent.plugins"] and imports
bible_hermes_plugin directly — this shim is not needed in that case.
"""

from bible_hermes_plugin import register  # noqa: F401

__all__ = ["register"]
