"""Tool lookup, plus the approval/hook wrapper around running one."""

from types import SimpleNamespace

import tools.builtin  # noqa: F401  (registers the builtin function tools)
import tools.subagents  # noqa: F401  (registers subagent_* tools)
from hooks.hook_system import run_hooks
from safety import approval
from tools.base import TOOLS, make_schema, run_tool


def names(s) -> list[str]:
    allowed = s.config.allowed_tools
    return [n for n in TOOLS if not allowed or n in allowed]


def info(name: str):
    """name/description/kind of a tool, for the prompt and the UI; None if unknown."""
    if name not in TOOLS:
        return None
    description, _, _, kind = TOOLS[name]
    return SimpleNamespace(name=name, description=description, kind=kind)


def schemas(s) -> list[dict]:
    return [make_schema(n) for n in names(s)]


async def invoke(s, name: str, args: dict) -> str:
    """Run one tool call through approval and hooks; failures come back as 'error: ...'."""
    if name not in names(s):
        output = f"error: unknown tool: {name}"
    else:
        await run_hooks(s, "before_tool", tool_name=name, tool_params=args)
        output = approval.check(s, name, args, TOOLS[name][3]) or await run_tool(name, args, s)
    await run_hooks(s, "after_tool", tool_name=name, tool_params=args, tool_result=output)
    return output
