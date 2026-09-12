"""glob: find files by pattern."""

from tools.base import tool
from utils.paths import resolve_path


@tool(
    "glob",
    "Find files matching a glob pattern (** recurses) under path (default: working directory).",
    {"pattern": "string", "path": "string?"},
)
def glob(args, s):
    root = resolve_path(s.config.cwd, args.get("path") or ".")
    if not root.is_dir():
        return f"error: directory does not exist: {root}"
    cwd = s.config.cwd.resolve()
    matches = [p for p in root.glob(args["pattern"]) if p.is_file()]
    lines = [str(p.relative_to(cwd) if p.is_relative_to(cwd) else p) for p in matches[:1000]]
    if len(matches) > 1000:
        lines.append("... (limited to 1000 results)")
    return "\n".join(lines) or "No files matched"
