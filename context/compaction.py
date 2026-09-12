"""Compaction: replace a long history with a model-written summary."""

import sys

from client.llm_client import chat
from context import manager
from prompts.system import get_compression_prompt
from ui.tui import DIM, RESET

LIMITS = {"tool": 2000, "assistant": 3000, "user": 1500}  # chars of each message shown to the summariser
CONTINUATION = """# Context Restoration (Previous Session Compacted)

The previous conversation was compacted due to context length limits. Below is a detailed summary of the work done so far.

**CRITICAL: Actions listed under "COMPLETED ACTIONS" are already done. DO NOT repeat them.**

---

{summary}

---

Resume work from where we left off. Focus ONLY on the remaining tasks."""
ACK = """I've reviewed the context from the previous session. I understand:
- The original goal and what was requested
- Which actions are ALREADY COMPLETED (I will NOT repeat these)
- The current state of the project
- What still needs to be done

I'll continue with the REMAINING tasks only, starting from where we left off."""
CONTINUE = "Continue with the REMAINING work only. Do NOT repeat any completed actions. Proceed with the next step as described in the context above."


def _transcript(messages: list[dict]) -> str:
    parts = ["Here is the conversation that needs to be continued:"]
    for m in messages:
        role, content = m["role"], m.get("content") or ""
        if role == "assistant" and m.get("tool_calls"):
            calls = "\n".join(f"  - {tc['function']['name']}({tc['function']['arguments'][:500]})" for tc in m["tool_calls"])
            parts.append(f"Assistant called tools:\n{calls}")
        if content:
            limit = LIMITS[role]
            label = f"Tool result ({m.get('tool_call_id', '?')})" if role == "tool" else role.capitalize()
            parts.append(f"{label}:\n{content[:limit]}" + ("\n... [truncated]" if len(content) > limit else ""))
    return "\n\n---\n\n".join(parts)


async def compact(s) -> bool:
    """Summarise s.messages into three synthetic messages. Returns False (with a warning) if that failed."""
    if len(s.messages) < 3:
        return False
    request = [{"role": "system", "content": get_compression_prompt()}, {"role": "user", "content": _transcript(s.messages)}]
    summary, usage = "", None
    async for kind, payload in chat(s.config, request, stream=False):
        if kind == "text":
            summary += payload
        elif kind == "usage":
            usage = payload
        elif kind == "error":
            print(f"warning: compaction failed: {payload}", file=sys.stderr)
            return False
    if not summary:
        print("warning: compaction returned no summary", file=sys.stderr)
        return False
    print(f"\n{DIM}⏺ context compacted: {len(s.messages)} messages → summary{RESET}")
    s.messages = [
        {"role": "user", "content": CONTINUATION.format(summary=summary)},
        {"role": "assistant", "content": ACK},
        {"role": "user", "content": CONTINUE},
    ]
    if usage:
        manager.add_usage(s, usage)
    return True
