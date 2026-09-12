"""Decides whether a tool call may run under the session's approval policy."""

import re

from tools.base import MUTATING
from ui import tui
from utils.paths import resolve_path

DANGEROUS_PATTERNS = [
    # File system destruction
    r"rm\s+(-rf?|--recursive)\s+[/~]",
    r"rm\s+-rf?\s+\*",
    r"rmdir\s+[/~]",
    # Disk operations
    r"dd\s+if=",
    r"mkfs",
    r"fdisk",
    r"parted",
    # System control
    r"shutdown",
    r"reboot",
    r"halt",
    r"poweroff",
    r"init\s+[06]",
    # Permission changes on root
    r"chmod\s+(-R\s+)?777\s+[/~]",
    r"chown\s+-R\s+.*\s+[/~]",
    # Network exposure
    r"nc\s+-l",
    r"netcat\s+-l",
    # Code execution from network
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
    # Fork bomb
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
]

# Patterns for safe commands (auto-approved)
SAFE_PATTERNS = [
    # Information commands
    r"^(ls|dir|pwd|cd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(find|locate|which|whereis|file|stat)(\s|$)",
    # Development tools (read-only)
    r"^git\s+(status|log|diff|show|branch|remote|tag)(\s|$)",
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated)(\s|$)",
    r"^pip\s+(list|show|freeze)(\s|$)",
    r"^cargo\s+(tree|search)(\s|$)",
    # Text processing (usually safe)
    r"^(grep|awk|sed|cut|sort|uniq|tr|diff|comm)(\s|$)",
    # System info
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname)(\s|$)",
    r"^(env|printenv|set)$",
    # Process info
    r"^(ps|top|htop|pgrep)(\s|$)",
]


def _matches(patterns: list[str], command: str) -> bool:
    return any(re.search(p, command, re.IGNORECASE) for p in patterns)


def decide(s, name: str, args: dict, kind: str) -> str:
    """'approve' | 'reject' | 'ask'. The policy is read live, so /approval applies at once."""
    policy = s.config.approval
    if kind not in MUTATING or policy == "yolo":
        return "approve"
    if kind == "shell":
        command = str(args.get("command", ""))
        if _matches(DANGEROUS_PATTERNS, command):
            return "reject"
        if _matches(SAFE_PATTERNS, command) or policy in ("auto", "on-failure"):
            return "approve"
        return "reject" if policy == "never" else "ask"
    path = resolve_path(s.config.cwd, args["path"]) if args.get("path") else None
    if path and not path.is_relative_to(s.config.cwd):
        return "ask"  # touches a file outside the working directory
    if name == "write_file" and path and path.exists():
        return "ask"  # overwrites an existing file
    return "approve"


def check(s, name: str, args: dict, kind: str, diff: str | None = None) -> str | None:
    """Returns an 'error: ...' string when the call must not run, else None."""
    decision = decide(s, name, args, kind)
    if decision == "reject":
        return "error: rejected by safety policy"
    if decision == "ask" and not tui.confirm(name, args, diff):
        return "error: rejected by user"
    return None
