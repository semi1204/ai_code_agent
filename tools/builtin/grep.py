"""grep: regex search over files."""

import os
import re
from pathlib import Path

from tools.base import tool
from utils.paths import display_path_rel_to_cwd, is_binary_file, resolve_path
from utils.text import truncate_text

IGNORED_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv"}
MAX_FILES = 500
MAX_OUTPUT_TOKENS = 25_000


@tool(
    "grep",
    "Search files for a regex; returns file:line:text. path may be a file or directory (default: working directory).",
    {"pattern": "string", "path": "string?", "case_insensitive": "boolean?"},
)
def grep(args, s):
    root = resolve_path(s.config.cwd, args.get("path") or ".")
    if not root.exists():
        return f"error: path does not exist: {root}"
    try:
        pattern = re.compile(args["pattern"], re.IGNORECASE if args.get("case_insensitive") else 0)
    except re.error as e:
        return f"error: invalid regex: {e}"
    files = [root] if root.is_file() else _walk(root)
    hits = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        shown = display_path_rel_to_cwd(str(path), s.config.cwd)
        hits += [f"{shown}:{i}:{line}" for i, line in enumerate(lines, 1) if pattern.search(line)]
    if not hits:
        return f"No matches for '{args['pattern']}' ({len(files)} files searched)"
    return truncate_text("\n".join(hits), MAX_OUTPUT_TOKENS, "\n... [truncated]")


def _walk(root: Path) -> list[Path]:
    """Text files under root, skipping hidden files, IGNORED_DIRS and binaries; at most MAX_FILES."""
    files = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in names:
            path = Path(dirpath) / name
            if not name.startswith(".") and not is_binary_file(path):
                files.append(path)
                if len(files) >= MAX_FILES:
                    return files
    return files
