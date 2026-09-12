def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def truncate_text(text: str, max_tokens: int, suffix: str = "\n... [truncated]") -> str:
    if count_tokens(text) <= max_tokens:
        return text
    budget = (max_tokens - count_tokens(suffix)) * 4
    if budget <= 0:
        return suffix.strip()
    cut = text.rfind("\n", 0, budget)
    return text[: cut if cut > 0 else budget] + suffix


def unified_diff(path, old: str | None, new: str) -> str:
    """Diff of old -> new for `path`; old=None means the file is new."""
    import difflib

    a = (old or "").splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    for lines in (a, b):
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
    return "".join(difflib.unified_diff(a, b, fromfile="/dev/null" if old is None else str(path), tofile=str(path)))
