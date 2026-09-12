"""Conversation history: OpenAI chat messages on s.messages, usage accounting, pruning."""

from utils.text import count_tokens

PRUNE_PROTECT_TOKENS = 40_000  # newest tool outputs kept intact
PRUNE_MINIMUM_TOKENS = 20_000  # prune only when at least this much would be freed
PRUNED = "[Old tool result content cleared]"


def add_user(s, content: str) -> None:
    s.messages.append({"role": "user", "content": content})


def add_assistant(s, content: str | None, tool_calls: list | None = None) -> None:
    message = {"role": "assistant"}
    if content:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = tool_calls
    s.messages.append(message)


def add_tool(s, call_id: str, content: str) -> None:
    s.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})


def messages_for_api(s) -> list[dict]:
    return [{"role": "system", "content": s.system_prompt}] + s.messages


def add_usage(s, usage: dict) -> None:
    s.last_usage = usage
    s.usage = {k: s.usage.get(k, 0) + v for k, v in usage.items()}


def needs_compaction(s) -> bool:
    used = s.last_usage.get("total_tokens") or sum(count_tokens(m.get("content") or "") for m in messages_for_api(s))
    return used > s.config.model.context_window * 0.8


def prune_tool_outputs(s) -> int:
    """Clear tool outputs older than the newest PRUNE_PROTECT_TOKENS worth, if that frees PRUNE_MINIMUM_TOKENS."""
    if sum(m["role"] == "user" for m in s.messages) < 2:
        return 0
    kept, to_prune = 0, []
    for m in reversed(s.messages):
        if m["role"] != "tool" or m["content"] == PRUNED:
            continue
        kept += count_tokens(m["content"])
        if kept > PRUNE_PROTECT_TOKENS:
            to_prune.append(m)
    if sum(count_tokens(m["content"]) for m in to_prune) < PRUNE_MINIMUM_TOKENS:
        return 0
    for m in to_prune:
        m["content"] = PRUNED
    return len(to_prune)
