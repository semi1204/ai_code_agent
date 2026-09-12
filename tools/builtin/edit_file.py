"""edit: replace an exact string in a file."""

from agent import undo
from tools.base import tool
from ui import tui
from utils.paths import display_path_rel_to_cwd, resolve_path
from utils.text import unified_diff


@tool(
    "edit",
    "Replace old_string with new_string in a file. old_string must match exactly and be unique "
    "unless replace_all=true; an empty old_string creates a new file.",
    {"path": "string", "old_string": "string?", "new_string": "string", "replace_all": "boolean?"},
    kind="write",
)
def edit(args, s):
    path = resolve_path(s.config.cwd, args["path"])
    shown = display_path_rel_to_cwd(str(path), s.config.cwd)
    old_string, new_string = args.get("old_string") or "", args["new_string"]
    if not path.is_file():
        if old_string:
            return f"error: file does not exist: {path} (use an empty old_string to create it)"
        path.parent.mkdir(parents=True, exist_ok=True)
        undo.record(s, path)
        path.write_text(new_string, encoding="utf-8")
        tui.print_diff(unified_diff(path, None, new_string))
        return f"Created {shown} ({len(new_string.splitlines())} lines)"
    if not old_string:
        return "error: old_string is empty but the file exists (use write_file to overwrite)"
    content = path.read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        return _no_match(old_string, content, path)
    if count > 1 and not args.get("replace_all"):
        return f"error: old_string appears {count} times in {path}; add context to make it unique or set replace_all=true"
    new_content = content.replace(old_string, new_string, -1 if args.get("replace_all") else 1)
    if new_content == content:
        return "error: no change — old_string equals new_string"
    undo.record(s, path)
    path.write_text(new_content, encoding="utf-8")
    tui.print_diff(unified_diff(path, content, new_content))
    return f"Edited {shown}: replaced {count if args.get('replace_all') else 1} occurrence(s)"


def _no_match(old_string: str, content: str, path) -> str:
    first = old_string.split()[:1]
    hints = [f"  line {i}: {line.strip()[:80]}" for i, line in enumerate(content.splitlines(), 1) if first and first[0] in line][:3]
    message = f"error: old_string not found in {path}."
    if hints:
        return message + " Similar lines:\n" + "\n".join(hints) + "\nMake sure old_string matches exactly (whitespace and indentation)."
    return message + " Re-read the file with read_file and match the text exactly (whitespace, indentation, line breaks)."
