"""Decides whether a tool call may run under the session's approval policy."""

import asyncio
import re

from tools.base import MUTATING
from ui import tui
from utils.paths import resolve_path

# Rejected under every policy except yolo.
DANGEROUS_PATTERNS = [
    # wiping the root or home directory
    r"\brm\s+(-\w*r\w*|--recursive)(\s+\S+)*\s+(/|~/?|/\*|~/\*)(\s|$)",
    r"\brm\s+-\w*r\w*\s+\*(\s|$)",
    r"\brmdir\s+(/|~/?)(\s|$)",
    # disks and system state
    r"\bdd\s+if=",
    r"\b(mkfs|fdisk|parted)\b",
    r"(^|[;&|]\s*)(sudo\s+)?(shutdown|reboot|halt|poweroff|init\s+[06])\b",
    # permissions on the root or home directory
    r"\bchmod\s+(-R\s+)?777\s+(/|~/?)(\s|$)",
    r"\bchown\s+-R\s+\S+\s+(/|~/?)(\s|$)",
    # network exposure and piping downloads into a shell
    r"\b(nc|netcat)\s+-l",
    r"\b(curl|wget)\s+.*\|\s*(bash|sh|zsh)\b",
    # fork bomb
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
]

# Refused by the shell tool even under yolo.
BLOCKED_PATTERNS = [
    DANGEROUS_PATTERNS[0],
    r"\bdd\s+if=/dev/(zero|u?random)\b",
    r"\b(mkfs|fdisk|parted)\b",
    r"(^|[;&|]\s*)(sudo\s+)?(shutdown|reboot|halt|poweroff|init\s+[06])\b",
    r"\bchmod\s+(-R\s+)?777\s+(/|~/?)(\s|$)",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
]

# Auto-approved when they are the whole command (no chaining, pipes, redirection or substitution).
SAFE_PATTERNS = [
    r"^(ls|dir|pwd|cd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(find|locate|which|whereis|file|stat)(\s|$)",
    r"^git\s+(status|log|diff|show|branch|remote|tag)(\s|$)",
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated)(\s|$)",
    r"^pip\s+(list|show|freeze)(\s|$)",
    r"^cargo\s+(tree|search)(\s|$)",
    r"^(grep|rg|cut|sort|uniq|tr|diff|comm)(\s|$)",
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname)(\s|$)",
    r"^(env|printenv|set)$",
    r"^(ps|top|htop|pgrep)(\s|$)",
]
SHELL_METACHARS = re.compile(r"[;&|<>`\n]|\$\(")  # a safe command followed by `&& anything` is not safe
FIND_MUTATORS = re.compile(r"^find\b.*\s-(delete|exec|execdir|ok|okdir)\b")


def matches(patterns: list[str], command: str) -> bool:
    return any(re.search(p, command, re.IGNORECASE) for p in patterns)


def safe_command(command: str) -> bool:
    """A single read-only command from SAFE_PATTERNS with no shell metacharacters."""
    command = command.strip()
    return matches(SAFE_PATTERNS, command) and not SHELL_METACHARS.search(command) and not FIND_MUTATORS.search(command)


def decide(s, name: str, args: dict, kind: str) -> str:
    """'approve' | 'reject' | 'ask' for one tool call. The policy is read live, so /approval applies at once.

    read/memory: always approved (memory only touches the agent's own notes and todos).
    shell: dangerous -> reject; simple safe command -> approve; otherwise by policy.
    write: inside the working directory -> approve (overwriting an existing file asks); outside -> ask.
    network/mcp: side effects we cannot inspect -> by policy.
    """
    policy = s.config.approval
    if kind not in MUTATING or kind == "memory" or policy == "yolo":
        return "approve"
    if kind == "shell":
        command = str(args.get("command", ""))
        if matches(DANGEROUS_PATTERNS, command):
            return "reject"
        if safe_command(command):
            return "approve"
    elif kind == "write":
        cwd = s.config.cwd.resolve()
        path = resolve_path(cwd, args["path"]) if args.get("path") else None
        if path and not path.is_relative_to(cwd):
            return "ask"
        if name == "write_file" and path and path.exists():
            return "ask"
        return "approve"
    if policy in ("auto", "on-failure"):
        return "approve"
    return "reject" if policy == "never" else "ask"


async def check(s, name: str, args: dict, kind: str) -> str | None:
    """Returns an 'error: ...' string when the call must not run, else None."""
    decision = decide(s, name, args, kind)
    if decision == "reject":
        return "error: rejected by safety policy"
    if decision == "ask" and not await asyncio.to_thread(tui.confirm, name, args):
        return "error: rejected by user"
    return None
