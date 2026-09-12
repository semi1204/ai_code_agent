"""read_file: file contents with line numbers."""

from tools.base import tool
from utils.paths import is_binary_file, resolve_path
from utils.text import truncate_text

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_OUTPUT_TOKENS = 25_000


@tool(
    "read_file",
    "Read a text file with line numbers. Use offset (1-based line) and limit for large files. Cannot read binary files.",
    {"path": "string", "offset": "number?", "limit": "number?"},
)
def read_file(args, s):
    path = resolve_path(s.config.cwd, args["path"])
    if not path.is_file():
        return f"error: file not found: {path}"
    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        return f"error: file too large ({size / 1024 / 1024:.1f}MB, max 10MB)"
    if is_binary_file(path):
        return f"error: cannot read binary file: {path.name}"
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")
    lines = content.splitlines()
    if not lines:
        return "File is empty."
    start = max(0, int(args.get("offset") or 1) - 1)
    end = min(start + int(args["limit"]), len(lines)) if args.get("limit") else len(lines)
    output = "\n".join(f"{i:6}|{line}" for i, line in enumerate(lines[start:end], start + 1))
    if start > 0 or end < len(lines):
        output = f"Showing lines {start + 1}-{end} of {len(lines)}\n\n" + output
    return truncate_text(output, MAX_OUTPUT_TOKENS, f"\n... [truncated, {len(lines)} total lines]")
