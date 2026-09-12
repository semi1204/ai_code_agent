"""Which tool calls may run concurrently: read-only ones that arrive back to back."""

PARALLEL_SAFE = {"read_file", "grep", "glob", "list_dir", "web_fetch", "web_search"}


def batches(calls: list[dict], enabled: bool, limit: int) -> list[list[dict]]:
    """Split tool calls into ordered batches; only consecutive PARALLEL_SAFE calls share one."""
    result = []
    for call in calls:
        last = result[-1] if result else None
        if enabled and last and len(last) < limit and call["name"] in PARALLEL_SAFE and last[0]["name"] in PARALLEL_SAFE:
            last.append(call)
        else:
            result.append([call])
    return result
