from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.base import FileDiff


@dataclass
class UndoEntry:
    entry_id: str
    timestamp: datetime
    changes: list[FileDiff]
    description: str
    is_undone: bool = False


class UndoManager:
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, session_id: str, max_history: int = 50):
        self.session_id = session_id
        self.max_history = max_history
        self._history: list[UndoEntry] = []
        self._pending_changes: list[FileDiff] = []
        self._lock = asyncio.Lock()

    def create_backup(self, path: Path) -> str | None:
        if not path.exists():
            return None

        try:
            if path.stat().st_size > self.MAX_FILE_SIZE:
                return None

            return path.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            return None

    def record_change(self, diff: FileDiff) -> None:
        self._pending_changes.append(diff)

    def commit_entry(self, description: str) -> str | None:
        if not self._pending_changes:
            return None

        entry_id = str(uuid.uuid4())[:8]
        entry = UndoEntry(
            entry_id=entry_id,
            timestamp=datetime.now(),
            changes=self._pending_changes.copy(),
            description=description,
        )

        self._history.append(entry)
        self._pending_changes.clear()

        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history :]

        return entry_id

    def undo(self, count: int = 1) -> list[UndoEntry]:
        undone_entries: list[UndoEntry] = []

        for _ in range(count):
            entry = self._find_next_undoable()
            if not entry:
                break

            for change in reversed(entry.changes):
                self._restore_file(change)

            entry.is_undone = True
            undone_entries.append(entry)

        return undone_entries

    def _find_next_undoable(self) -> UndoEntry | None:
        for entry in reversed(self._history):
            if not entry.is_undone:
                return entry
        return None

    def _restore_file(self, diff: FileDiff) -> bool:
        try:
            if diff.is_new_file:
                if diff.path.exists():
                    diff.path.unlink()
            elif diff.is_deletion:
                diff.path.parent.mkdir(parents=True, exist_ok=True)
                diff.path.write_text(diff.old_content, encoding="utf-8")
            else:
                diff.path.write_text(diff.old_content, encoding="utf-8")
            return True
        except IOError:
            return False

    def get_history(self, limit: int = 10) -> list[UndoEntry]:
        return list(reversed(self._history[-limit:]))

    def clear_pending(self) -> None:
        self._pending_changes.clear()

    def has_pending_changes(self) -> bool:
        return len(self._pending_changes) > 0
