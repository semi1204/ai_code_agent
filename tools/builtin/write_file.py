"""write_file: create or overwrite a whole file."""

from agent import undo
from tools.base import tool
from ui import tui
from utils.paths import display_path_rel_to_cwd, resolve_path
from utils.text import unified_diff


@tool(
    "write_file",
    "Create or overwrite a file with content (parent directories are created). For partial changes use edit.",
    {"path": "string", "content": "string"},
    kind="write",
)
def write_file(args, s):
    path = resolve_path(s.config.cwd, args["path"])
    shown = display_path_rel_to_cwd(str(path), s.config.cwd)
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    undo.record(s, path)
    path.write_text(args["content"], encoding="utf-8")
    tui.print_diff(unified_diff(path, old, args["content"]))
    return f"{'Updated' if old is not None else 'Created'} {shown} ({len(args['content'].splitlines())} lines)"
