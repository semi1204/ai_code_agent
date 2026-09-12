"""Example plugin: any *.py in .ai-agent/tools/ can register tools with @tool."""

from tools.base import tool


@tool("test_tool", "Echo a message back (example plugin loaded from .ai-agent/tools/test_tool.py)", {"message": "string"})
def test_tool(args, s):
    return f"Test tool received: {args['message']}"
