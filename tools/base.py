"""Tool infrastructure.

A tool is `def fn(args: dict, s) -> str` (sync or async), registered with
`@tool(name, description, params, kind)`. `params` is the compact schema
{"path": "string", "limit": "number?"} (trailing ? = optional) or a full JSON
schema object. Failures come back as "error: ..." strings, never exceptions.

"""

import inspect
from typing import Callable

KINDS = ("read", "write", "shell", "network", "memory", "mcp")
MUTATING = {"write", "shell", "network", "memory", "mcp"}
TOOLS: dict[str, tuple[str, dict, Callable, str]] = {}  # name -> (description, params, fn, kind)
JSON_TYPES = {"number": "integer"}  # compact type -> JSON schema type


def tool(name: str, description: str, params: dict, kind: str = "read"):
    def register(fn):
        TOOLS[name] = (description, params, fn, kind)
        return fn

    return register


def make_schema(name: str) -> dict:
    description, params, _, _ = TOOLS[name]
    if params.get("type") == "object":  # already a JSON schema (MCP servers send these)
        return {"name": name, "description": description, "parameters": params}
    properties, required = {}, []
    for pname, ptype in params.items():
        base = ptype.rstrip("?")
        properties[pname] = {"type": JSON_TYPES.get(base, base)}
        if not ptype.endswith("?"):
            required.append(pname)
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


async def run_tool(name: str, args: dict, s) -> str:
    _, params, fn, _ = TOOLS[name]
    if params.get("type") != "object":
        missing = [p for p, t in params.items() if not t.endswith("?") and p not in args]
        if missing:
            return f"error: missing parameters: {', '.join(missing)}"
    try:
        result = fn(args, s)
        return await result if inspect.isawaitable(result) else result
    except Exception as e:
        return f"error: {e}"
