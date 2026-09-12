"""Terminal output with ANSI escapes — no UI library."""

import os
import sys

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


def tool_end(name: str, success: bool, output: str, error: str | None, diff: str | None) -> None:
    if not success:
        print(f"  {RED}⎿  {(error or output or 'failed').splitlines()[0][:100]}{RESET}")
        return
    if diff:
        print_diff(diff)
        return
    lines = (output or "").splitlines() or ["(empty)"]
    preview = lines[0][:60] + ("..." if len(lines[0]) > 60 else "")
    if len(lines) > 1:
        preview += f" ... +{len(lines) - 1} lines"
    print(f"  {DIM}⎿  {preview}{RESET}")


# --- approval prompt ---


def confirm(c) -> bool:
    """Ask y/N for a ToolConfirmation; a non-interactive stdin rejects."""
    print(f"\n{YELLOW}⚠ Approval required{RESET}: {BOLD}{c.tool_name}{RESET} {DIM}{c.description}{RESET}")
    if c.command:
        print(f"  {YELLOW}$ {c.command}{RESET}")
    if c.diff:
        print_diff(c.diff.to_diff())
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
