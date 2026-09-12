"""Prompt suggestions: ask the model what the user will most likely type next."""

from client.llm_client import chat
from context import manager

INSTRUCTION = (
    "Reply with only the single most likely next message the user would type to you, given the conversation so far: "
    "one line, in the user's language, no quotes, no explanation. Reply with an empty line if nothing sensible follows."
)
MAX_LENGTH = 160


async def suggest(s) -> str | None:
    """One non-streaming call on the same conversation prefix, so the provider's prompt cache is reused."""
    if not s.messages:
        return None
    request = manager.messages_for_api(s) + [{"role": "user", "content": INSTRUCTION}]
    text = ""
    async for kind, payload in chat(s.config, request, stream=False):
        if kind == "text":
            text += payload
        elif kind == "error":
            return None
    return _clean(text)


def _clean(text: str) -> str | None:
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    line = line.strip("\"'`“”‘’ ")
    return line if 0 < len(line) <= MAX_LENGTH else None
