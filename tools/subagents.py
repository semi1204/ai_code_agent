"""Subagents: a restricted agent run as a tool (subagent_<name>)."""

import asyncio
import dataclasses
import textwrap

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
        from agent.agent import Agent  # lazy: agent imports the tool registry
        from agent.events import AgentEventType

        config = dataclasses.replace(s.config, max_turns=spec["max_turns"], allowed_tools=spec["tools"])
        prompt = textwrap.dedent(f"""\
            You are a specialized sub-agent with a specific task to complete.

            {spec["prompt"]}

            YOUR TASK:
            {args["goal"]}

            Focus only on this task, then give a concise final answer.""")
        tools_used, final, error = [], None, None
        deadline = asyncio.get_running_loop().time() + spec["timeout"]  # checked between events
        async with Agent(config) as agent:
            async for event in agent.run(prompt):
                if asyncio.get_running_loop().time() > deadline:
                    error = f"timed out after {spec['timeout']}s"
                    break
                if event.type == AgentEventType.TOOL_CALL_START:
                    tools_used.append(event.data["name"])
                elif event.type == AgentEventType.TEXT_COMPLETE:
                    final = event.data.get("content")
                elif event.type == AgentEventType.AGENT_ERROR:
                    error = event.data.get("error", "unknown error")
                    break
        summary = f"Sub-agent '{name}' used: {', '.join(tools_used) or 'no tools'}\n\n{final or 'No response'}"
        return f"error: {error}\n{summary}" if error else summary


for _name, _spec in SUBAGENTS.items():
    _register(_name, _spec)
