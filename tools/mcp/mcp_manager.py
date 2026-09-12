"""Connects the configured MCP servers for a session and registers their tools."""

import asyncio
import sys

from tools.builtin.shell import scrubbed_env
from tools.mcp import mcp_tool
from tools.mcp.client import MCPClient


async def connect_all(s) -> None:
    """Fill s.mcp with one client per enabled server; a failed server keeps status 'error'."""
    for name, cfg in s.config.mcp_servers.items():
        if cfg.enabled:
            s.mcp[name] = MCPClient(name, cfg, s.config.cwd, scrubbed_env(s.config))  # secrets hidden unless set in cfg.env
    outcomes = await asyncio.gather(
        *(asyncio.wait_for(c.connect(), c.config.startup_timeout_sec) for c in s.mcp.values()), return_exceptions=True
    )
    for client, outcome in zip(s.mcp.values(), outcomes):
        if isinstance(outcome, BaseException):
            client.status = "error"
            print(f"warning: MCP server '{client.name}': {outcome or type(outcome).__name__}", file=sys.stderr)
        for info in client.tools:
            mcp_tool.register(client.name, info)


async def shutdown(s) -> None:
    await asyncio.gather(*(c.disconnect() for c in s.mcp.values()), return_exceptions=True)
    s.mcp.clear()


def status(s) -> list[dict]:
    return [{"name": c.name, "status": c.status, "tools": len(c.tools)} for c in s.mcp.values()]
