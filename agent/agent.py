"""The agent loop: a user message in, streamed events out, tools run until the model stops calling them."""

import asyncio
import json
from datetime import datetime

from agent import undo
from agent.session import Session
from client.llm_client import chat
from context import compaction, loop_detector, manager
from hooks.hook_system import run_hooks
from prompts.system import LOOP_BREAKER, get_system_prompt
from tools import discovery, registry
from tools.builtin import memory
from tools.mcp import mcp_manager
from tools.parallel import batches


async def start(config) -> Session:
    """Connect MCP servers, load plugins and build the system prompt."""
    s = Session(config)
    await mcp_manager.connect_all(s)
    discovery.load_plugins(config)
    entries = memory.load()
    notes = "User preferences and notes:\n" + "\n".join(f"- {k}: {v}" for k, v in entries.items()) if entries else None
    s.system_prompt = get_system_prompt(config, notes, registry.names(s))
    return s


async def close(s: Session) -> None:
    await mcp_manager.shutdown(s)


async def run(s: Session, message: str):
    """Yield ("text", delta) | ("tool_start", name, args) | ("tool_end", name, output) | ("error", message)."""
    await run_hooks(s, "before_agent", user_message=message)
    if manager.needs_compaction(s):  # before appending, so the new message reaches the model verbatim
        await compaction.compact(s)
    manager.add_user(s, message)
    final = None
    for _ in range(s.config.max_turns):
        s.turns += 1
        s.updated_at = datetime.now()
        text, calls, usage, failed = "", [], None, False
        async for kind, payload in chat(s.config, manager.messages_for_api(s), tools=registry.schemas(s) or None):
            if kind == "text":
                text += payload
                yield ("text", payload)
            elif kind == "tool_call":
                calls.append(payload)
            elif kind == "usage":
                usage = payload
            elif kind == "error":
                failed = True
                await run_hooks(s, "on_error", error=payload)
                yield ("error", payload)
        if failed:
            break  # record nothing for this turn; the user can retry
        tool_calls = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in calls]
        manager.add_assistant(s, text or None, tool_calls or None)
        if usage:
            manager.add_usage(s, usage)
        if text:
            final = text
            loop_detector.record(s, "response", {"text": text})
        if not calls:
            manager.prune_tool_outputs(s)
            break
        for batch in batches(calls, s.config.parallel_tools, s.config.max_parallel_tools):
            for call in batch:
                yield ("tool_start", call["name"], call["arguments"])
                loop_detector.record(s, call["name"], call["arguments"])
            outputs = await asyncio.gather(*(registry.invoke(s, c["name"], c["arguments"]) for c in batch))
            for call, output in zip(batch, outputs):
                yield ("tool_end", call["name"], output)
                manager.add_tool(s, call["id"], output)
        undo.commit(s, f"Turn {s.turns}: {', '.join(c['name'] for c in calls)}")
        if found := loop_detector.check(s):
            manager.add_user(s, LOOP_BREAKER.format(reason=found))
        manager.prune_tool_outputs(s)
        if manager.needs_compaction(s):
            await compaction.compact(s)
    else:
        error = f"Maximum turns ({s.config.max_turns}) reached"
        await run_hooks(s, "on_error", error=error)
        yield ("error", error)
    await run_hooks(s, "after_agent", user_message=message, response=final)
