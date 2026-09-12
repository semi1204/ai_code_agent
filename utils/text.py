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
