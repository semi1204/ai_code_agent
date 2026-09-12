"""Undo for file writes: snapshot a file before writing it, restore on /undo."""

from pathlib import Path

MAX_HISTORY = 50


def record(s, path) -> None:
    """Call right before writing `path`; the old content is None for a new file."""
    path = Path(path)
    s.pending.append((path, path.read_text(encoding="utf-8") if path.exists() else None))


def commit(s, description: str) -> None:
    """Turn this turn's pending snapshots into one undo entry."""
    if s.pending:
        s.undo.append({"description": description, "changes": s.pending, "undone": False})
        s.pending = []
        del s.undo[:-MAX_HISTORY]


def undo(s, count: int = 1) -> list[dict]:
    """Restore the newest `count` entries that are not undone yet; returns them."""
    undone = []
    for entry in reversed(s.undo):
        if len(undone) == count:
            break
        if entry["undone"]:
            continue
        for path, old in reversed(entry["changes"]):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(old, encoding="utf-8")
        entry["undone"] = True
        undone.append(entry)
    return undone


def history(s, limit: int = 10) -> list[dict]:
    return list(reversed(s.undo[-limit:]))
