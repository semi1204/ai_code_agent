"""Wraps one MCP server tool as the function tool <server>__<tool>."""

from tools.base import tool


def register(server: str, info: dict) -> None:
    schema = dict(info["input_schema"] or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})

    @tool(f"{server}__{info['name']}", info["description"], schema, kind="mcp")
    async def call(args, s):  # the client is looked up per session, so sessions never share connections
        return await s.mcp[server].call_tool(info["name"], args)
