"""Loop detection: notices when the agent repeats itself so the model can be nudged."""

WINDOW, REPEATS, MAX_CYCLE = 20, 3, 3  # s.history is a deque(maxlen=WINDOW)


def record(s, name: str, args: dict | None = None) -> None:
    """Remember one action: a tool call (name + args) or a text response (name='response', args={'text': ...})."""
    detail = "|".join(f"{k}={v}" for k, v in sorted((args or {}).items()))
    s.history.append(f"{name}|{detail}")


def check(s) -> str | None:
    """Describe a detected loop (and clear the history so it fires once), else None."""
    h = list(s.history)
    if len(h) >= REPEATS and len(set(h[-REPEATS:])) == 1:
        found = f"the same action was repeated {REPEATS} times"
    else:
        found = next(
            (f"a repeating cycle of {n} actions" for n in range(2, MAX_CYCLE + 1) if len(h) >= 2 * n and h[-2 * n : -n] == h[-n:]),
            None,
        )
    if found:
        s.history.clear()
    return found
