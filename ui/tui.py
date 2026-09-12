"""Terminal output with ANSI escapes — no UI library."""

import os
import shutil
import sys
import threading
import unicodedata

try:
    import readline
except ImportError:  # e.g. Windows: no Tab completion, the hint is still shown
    readline = None

from utils.paths import display_path_rel_to_cwd
from utils.text import truncate_text

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
BLUE, CYAN, GREEN, YELLOW, RED, MAGENTA = "\033[34m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[35m"
KIND_COLOR = {"read": CYAN, "write": YELLOW, "shell": MAGENTA, "network": BLUE, "memory": GREEN, "mcp": GREEN}
MAX_BLOCK_TOKENS = 2500


def separator() -> str:
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        cols = 80
    return f"{DIM}{'─' * min(cols, 80)}{RESET}"


def welcome(config) -> None:
    print(f"{BOLD}AI Agent{RESET} | {DIM}{config.model_name} | {config.cwd} | /help{RESET}\n")


# --- assistant text, streamed ---


def begin_text() -> None:
    print(f"\n{CYAN}⏺{RESET} ", end="", flush=True)


def text(delta: str) -> None:
    print(delta, end="", flush=True)


def end_text() -> None:
    print()


# --- tool calls ---


def tool_start(name: str, kind: str | None, args: dict, cwd) -> None:
    key, value = next(iter(args.items()), ("", ""))
    if key in ("path", "cwd"):
        value = display_path_rel_to_cwd(str(value), cwd)
    preview = str(value).replace("\n", "\\n")[:60]
    print(f"\n{KIND_COLOR.get(kind, GREEN)}⏺ {name}{RESET}({DIM}{preview}{RESET})")


def print_diff(diff: str) -> None:
    for line in truncate_text(diff, MAX_BLOCK_TOKENS).splitlines():
        color = GREEN if line.startswith("+") else RED if line.startswith("-") else CYAN if line.startswith("@@") else DIM
        print(f"  {color}{line}{RESET}")


def tool_end(name: str, output: str) -> None:
    if output.startswith("error:"):
        print(f"  {RED}⎿  {output.splitlines()[0][:100]}{RESET}")
        return
    lines = output.splitlines() or ["(empty)"]
    preview = lines[0][:60] + ("..." if len(lines[0]) > 60 else "")
    if len(lines) > 1:
        preview += f" ... +{len(lines) - 1} lines"
    print(f"  {DIM}⎿  {preview}{RESET}")


# --- approval prompt ---


def confirm(name: str, args: dict) -> bool:
    """Ask y/N before running a tool; a non-interactive stdin rejects."""
    print(f"\n{YELLOW}⚠ Approval required{RESET}: {BOLD}{name}{RESET}")
    for key, value in args.items():
        lines = str(value).splitlines() or [""]
        shown = "\n    ".join(lines[:8]) + (f"\n    … (+{len(lines) - 8} lines)" if len(lines) > 8 else "")
        print(f"  {YELLOW if key == 'command' else DIM}{key}: {shown}{RESET}")
    if not sys.stdin.isatty():
        print(f"  {RED}⎿  rejected (stdin is not a terminal){RESET}")
        return False
    try:
        return input(f"{BOLD}Approve? [y/N]{RESET} ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def show_help(commands: dict) -> None:
    print(f"\n{BOLD}Commands{RESET}")
    for name, (_, description) in commands.items():
        print(f"  {CYAN}{name:<14}{RESET}{description}")
    print(f"\n{DIM}Type a message to chat. The agent can read, write and run code; some actions ask for approval.{RESET}")


# --- input line, with an optional background prompt suggestion (Tab fills it in) ---

PROMPT = "\n\001" + BOLD + BLUE + "\002❯\001" + RESET + "\002 "  # \001..\002 hide the escapes from readline's cursor math


def read_line(fetch=None) -> str:
    """Prompt for a line. `fetch` runs in a background thread and may return a suggested prompt: it is drawn
    dimly on the blank line above the prompt, and Tab completes it (when the typed text is a prefix of it)."""
    state = {"suggestion": None, "done": False}

    def typed() -> str:
        buffer = readline.get_line_buffer() if readline else ""
        return "" if "\n" in buffer else buffer  # libedit keeps the previous line (newline included) until new input arrives

    def completer(text, index):
        suggestion, current = state["suggestion"], typed()
        return text + suggestion[len(current):] if index == 0 and suggestion and suggestion.startswith(current) else None

    def worker():
        try:
            suggestion = fetch()
        except Exception as e:
            if not state["done"]:  # a failure after the user moved on (or quit) is not worth a line
                print(f"warning: prompt suggestion failed: {e}", file=sys.stderr)
            return
        if state["done"] or not suggestion or not suggestion.startswith(typed()):
            return
        state["suggestion"] = suggestion
        sys.stdout.write(f"\0337\033[A\r  {DIM}⇥ {_fit(suggestion, shutil.get_terminal_size().columns - 5)}{RESET}\0338")
        sys.stdout.flush()

    if readline:
        readline.set_completer(completer)
        readline.set_completer_delims("")
        libedit = getattr(readline, "backend", "") == "editline" or "libedit" in (readline.__doc__ or "")
        readline.parse_and_bind("bind ^I rl_complete" if libedit else "tab: complete")
    if fetch:
        threading.Thread(target=worker, daemon=True).start()
    try:
        return input(PROMPT)
    finally:
        state["done"] = True


def _fit(text: str, columns: int) -> str:
    """Cut text so its display width (CJK counts double) fits in columns."""
    out, width = "", 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if width > columns:
            return out + "…"
        out += ch
    return out
