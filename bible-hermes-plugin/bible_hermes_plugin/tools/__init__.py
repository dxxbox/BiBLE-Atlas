"""BiBLE Hermes Plugin — tools package.

Exports all 7 tool (schema, handler) pairs and register_tools() which wires
them into the Hermes plugin context.
"""

from __future__ import annotations

from ..http_client import BibleAtlasClient
from .knowledge import (
    KNOWLEDGE_LIST_SCHEMA,
    KNOWLEDGE_SEARCH_SCHEMA,
    make_knowledge_list_handler,
    make_knowledge_search_handler,
)
from .memory import (
    MEMORY_GET_SCHEMA,
    MEMORY_SAVE_SCHEMA,
    MEMORY_SEARCH_SCHEMA,
    make_memory_get_handler,
    make_memory_save_handler,
    make_memory_search_handler,
)
from .skill import (
    SKILL_GET_SCHEMA,
    SKILL_SEARCH_SCHEMA,
    make_skill_get_handler,
    make_skill_search_handler,
)

CORE_TOOL_NAMES: tuple[str, ...] = (
    "bible_memory_search",
    "bible_memory_save",
    "bible_memory_get",
    "bible_knowledge_search",
    "bible_knowledge_list",
    "bible_skill_search",
    "bible_skill_get",
)

_TOOLSET = "bible-hermes-plugin"


def register_tools(ctx, client: BibleAtlasClient) -> None:
    """Register all 7 BiBLE tools with the Hermes plugin context."""
    tools = [
        (MEMORY_SEARCH_SCHEMA, make_memory_search_handler(client)),
        (MEMORY_SAVE_SCHEMA, make_memory_save_handler(client)),
        (MEMORY_GET_SCHEMA, make_memory_get_handler(client)),
        (KNOWLEDGE_SEARCH_SCHEMA, make_knowledge_search_handler(client)),
        (KNOWLEDGE_LIST_SCHEMA, make_knowledge_list_handler(client)),
        (SKILL_SEARCH_SCHEMA, make_skill_search_handler(client)),
        (SKILL_GET_SCHEMA, make_skill_get_handler(client)),
    ]
    for schema, handler in tools:
        ctx.register_tool(
            name=schema["name"],
            toolset=_TOOLSET,
            schema=schema,
            handler=handler,
        )


__all__ = [
    "CORE_TOOL_NAMES",
    "register_tools",
]
