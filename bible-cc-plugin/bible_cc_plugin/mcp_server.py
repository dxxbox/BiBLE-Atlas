"""BiBLE Atlas MCP server — exposes 5 tools via stdio transport."""

from __future__ import annotations

import json
import logging

from .config import resolve_config
from .client import BibleAtlasClient, error_details

logger = logging.getLogger("bible-cc-mcp")


def _make_server():
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    config = resolve_config()
    client = BibleAtlasClient(
        base_url=config.base_url,
        token=config.token,
        timeout_ms=config.timeout_ms,
        default_kb_index=config.default_kb_index,
        source_client=config.source_client,
    )

    server = Server("bible-atlas")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="bible_memory_search",
                description="Search BiBLE Atlas memory for relevant past context",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "description": "Max results (default 8)"},
                        "min_score": {"type": "number", "description": "Minimum relevance score 0-1 (default 0.35)"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="bible_memory_save",
                description="Save a memory to BiBLE Atlas",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array", "items": {"type": "object"}, "description": "Conversation messages to save"},
                        "title": {"type": "string", "description": "Memory title"},
                        "abstract": {"type": "string", "description": "Brief summary"},
                        "wait": {"type": "boolean", "description": "Wait for import to complete (default false)"},
                    },
                    "required": ["messages"],
                },
            ),
            Tool(
                name="bible_memory_get",
                description="Retrieve a specific memory from BiBLE Atlas by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID to retrieve"},
                    },
                    "required": ["memory_id"],
                },
            ),
            Tool(
                name="bible_knowledge_search",
                description="Search BiBLE Atlas knowledge base",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "tag": {"type": "string", "description": "Knowledge tag to search"},
                        "top_k": {"type": "integer", "description": "Max results (default 8)"},
                    },
                    "required": ["query", "tag"],
                },
            ),
            Tool(
                name="bible_knowledge_list",
                description="List available knowledge bases in BiBLE Atlas",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "description": "Filter by tag (optional)"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "bible_memory_search":
                result = client.search_memory(
                    query=arguments["query"],
                    top_k=arguments.get("top_k", 8),
                    min_score=arguments.get("min_score", 0.35),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_memory_save":
                result = client.save_memory(
                    messages=arguments["messages"],
                    title=arguments.get("title"),
                    abstract=arguments.get("abstract"),
                    wait=arguments.get("wait", False),
                )
                _notify_daemon(config)
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_memory_get":
                result = client.get_memory(arguments["memory_id"])
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_knowledge_search":
                result = client.search_knowledge(
                    query=arguments["query"],
                    tag=arguments.get("tag", ""),
                    top_k=arguments.get("top_k", 8),
                )
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "bible_knowledge_list":
                result = client.list_knowledge()
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps(error_details(exc), indent=2))]

    return server


def _notify_daemon(config) -> None:
    try:
        import httpx
        httpx.post(
            f"http://127.0.0.1:{config.daemon_port}/daemon/notify",
            json={"event": "memory_save"},
            timeout=2.0,
        )
    except Exception:
        pass


def main():
    import asyncio
    from mcp.server.stdio import stdio_server

    server = _make_server()

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
