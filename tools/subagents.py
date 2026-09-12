"""Subagents: a restricted agent run as a tool (subagent_<name>)."""

import asyncio
import dataclasses
import textwrap
from collections import deque

from tools.base import tool

SUBAGENTS = {
    "codebase_investigator": {
        "description": "Investigates the codebase to answer questions about code structure, patterns, and implementations",
        "prompt": "You are a codebase investigation specialist. Explore and understand code to answer questions "
        "using read_file, grep, glob and list_dir. Do NOT modify any files.",
        "tools": ["read_file", "grep", "glob", "list_dir"],
        "max_turns": 20,
        "timeout": 600,
    },
    "code_reviewer": {
        "description": "Reviews code changes and provides feedback on quality, bugs, and improvements",
        "prompt": "You are a code review specialist. Look for bugs, code smells, security issues and improvement "
        "opportunities using read_file, list_dir and grep. Do NOT modify any files.",
        "tools": ["read_file", "grep", "list_dir"],
        "max_turns": 10,
        "timeout": 300,
    },
}


def _register(name: str, spec: dict) -> None:
    @tool(f"subagent_{name}", spec["description"], {"goal": "string"})
    async def run_subagent(args, s):
        from agent import agent  # lazy: agent imports the tool registry
        from prompts.system import get_system_prompt
        from tools import registry

        config = dataclasses.replace(s.config, max_turns=spec["max_turns"], allowed_tools=spec["tools"])
        # a fresh conversation that shares the parent's MCP connections, undo history and usage totals
        sub = dataclasses.replace(s, config=config, messages=[], last_usage={}, todos={}, pending=[], history=deque(maxlen=20), turns=0)
        sub.system_prompt = get_system_prompt(config, None, registry.names(sub))
        prompt = textwrap.dedent(f"""\
            You are a specialized sub-agent with a specific task to complete.

            {spec["prompt"]}

            YOUR TASK:
            {args["goal"]}

            Focus only on this task, then give a concise final answer.""")
        tools_used, final, error = [], None, None
        deadline = asyncio.get_running_loop().time() + spec["timeout"]  # checked between events
        async for event in agent.run(sub, prompt):
            if asyncio.get_running_loop().time() > deadline:
                error = f"timed out after {spec['timeout']}s"
                break
            if event[0] == "tool_start":
                tools_used.append(event[1])
                final = None
            elif event[0] == "text":
                final = (final or "") + event[1]
            elif event[0] == "error":
                error = event[1]
                break
        summary = f"Sub-agent '{name}' used: {', '.join(tools_used) or 'no tools'}\n\n{final or 'No response'}"
        return f"error: {error}\n{summary}" if error else summary


for _name, _spec in SUBAGENTS.items():
    _register(_name, _spec)
