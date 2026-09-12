"""list_dir: directory listing, directories first."""

from tools.base import tool
from utils.paths import resolve_path


@tool(
    "list_dir",
    "List a directory (directories end with /). Hidden entries are skipped unless include_hidden=true.",
    {"path": "string?", "include_hidden": "boolean?"},
)
def list_dir(args, s):
    path = resolve_path(s.config.cwd, args.get("path") or ".")
    if not path.is_dir():
        return f"error: directory does not exist: {path}"
    items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not args.get("include_hidden"):
        items = [p for p in items if not p.name.startswith(".")]
    return "\n".join(p.name + "/" if p.is_dir() else p.name for p in items) or "Directory is empty"
