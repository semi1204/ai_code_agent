"""shell: run a command, streaming its output to the terminal."""

import asyncio
import fnmatch
import os
import signal
import sys
from asyncio.subprocess import DEVNULL, PIPE, STDOUT

from safety.approval import BLOCKED_PATTERNS, matches
from tools.base import tool
from ui.tui import DIM, RESET
from utils.paths import resolve_path

MAX_OUTPUT = 100 * 1024


@tool(
    "shell",
    "Run a shell command in the working directory (or cwd). Output is streamed; timeout defaults to 120s (max 600).",
    {"command": "string", "timeout": "number?", "cwd": "string?"},
    kind="shell",
)
async def shell(args, s):
    command = args["command"]
    if matches(BLOCKED_PATTERNS, command):  # refused even under yolo
        return f"error: command blocked for safety: {command}"
    cwd = resolve_path(s.config.cwd, args.get("cwd") or ".")
    if not cwd.is_dir():
        return f"error: working directory does not exist: {cwd}"
    timeout = min(max(int(args.get("timeout") or 120), 1), 600)
    argv = ["cmd.exe", "/c", command] if sys.platform == "win32" else ["/bin/bash", "-c", command]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT, cwd=cwd, env=scrubbed_env(s.config), start_new_session=True
    )
    chunks, size = [], 0
    try:
        async with asyncio.timeout(timeout):
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace")
                print(f"  {DIM}│ {line.rstrip()}{RESET}", flush=True)
                if size < MAX_OUTPUT:
                    chunks.append(line)
                    size += len(line)
            await proc.wait()
    except TimeoutError:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL) if sys.platform != "win32" else proc.kill()
        await proc.wait()
        return f"error: command timed out after {timeout}s\n" + "".join(chunks)
    output = "".join(chunks).rstrip() + ("\n... [output truncated]" if size >= MAX_OUTPUT else "")
    if proc.returncode != 0:
        return f"error: exit code {proc.returncode}\n{output}"
    return output or "(empty)"


def scrubbed_env(config) -> dict:
    """os.environ minus secrets (config.shell_environment.exclude_patterns), plus set_vars."""
    policy = config.shell_environment
    env = dict(os.environ)
    if not policy.ignore_default_excludes:
        for pattern in policy.exclude_patterns:
            for key in [k for k in env if fnmatch.fnmatch(k.upper(), pattern.upper())]:
                del env[key]
    env.update(policy.set_vars)
    return env
