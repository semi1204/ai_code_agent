"""memory: key/value notes that persist across sessions in ~/.ai-agent/user_memory.json."""

import json

from config.loader import DATA_DIR
from tools.base import tool

PATH = DATA_DIR / "user_memory.json"


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8")).get("entries", {})
    except (OSError, ValueError):
        return {}


def save(entries: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")


@tool(
    "memory",
    "Remember user preferences and notes across sessions. action: set (key, value) | get (key) | delete (key) | list | clear.",
    {"action": "string", "key": "string?", "value": "string?"},
    kind="memory",
)
def memory(args, s):
    action, key = args["action"].lower(), args.get("key")
    entries = load()
    if action == "set":
        if not key or not args.get("value"):
            return "error: key and value are required for set"
        entries[key] = args["value"]
        save(entries)
        return f"Set memory: {key}"
    if action == "get":
        if not key:
            return "error: key is required for get"
        return f"{key}: {entries[key]}" if key in entries else f"Memory not found: {key}"
    if action == "delete":
        if key not in entries:
            return f"Memory not found: {key}"
        del entries[key]
        save(entries)
        return f"Deleted memory: {key}"
    if action == "list":
        return "\n".join(f"{k}: {v}" for k, v in sorted(entries.items())) or "No memories stored"
    if action == "clear":
        count = len(entries)
        save({})
        return f"Cleared {count} memory entries"
    return f"error: unknown action: {args['action']}"
