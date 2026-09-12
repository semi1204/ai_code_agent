"""Saved sessions and checkpoints: JSON files under ~/.ai-agent/{sessions,checkpoints}/."""

import json
import os
from datetime import datetime

from config.loader import DATA_DIR


def save(s, kind: str = "sessions") -> str:
    """Write the conversation to DATA_DIR/<kind>/<name>.json; returns the name."""
    name = s.id if kind == "sessions" else f"{s.id}_{datetime.now():%Y%m%d_%H%M%S}"
    directory = DATA_DIR / kind
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / f"{name}.json"
    data = {
        "id": s.id, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
        "turns": s.turns, "messages": s.messages, "usage": s.usage,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, 0o600)
    return name


def load(name: str, kind: str = "sessions") -> dict | None:
    path = DATA_DIR / kind / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def restore(s, data: dict) -> None:
    """Replace the conversation in s with a saved one (MCP connections and tools stay)."""
    s.id, s.turns, s.usage = data["id"], data["turns"], data["usage"]
    s.created_at, s.updated_at = datetime.fromisoformat(data["created_at"]), datetime.fromisoformat(data["updated_at"])
    s.messages = [m for m in data["messages"] if m["role"] != "system"]
    s.undo, s.pending, s.todos, s.last_usage = [], [], {}, {}
    s.history.clear()


def saved(kind: str = "sessions") -> list[dict]:
    """Headers of the saved files, newest first; unreadable files are skipped."""
    directory = DATA_DIR / kind
    items = []
    for path in directory.glob("*.json") if directory.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({"name": path.stem, "updated_at": data["updated_at"], "turns": data["turns"]})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)
