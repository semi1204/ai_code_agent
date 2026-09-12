"""Hooks: shell commands from config.toml that run on agent/tool events.

Context reaches the hook through AI_AGENT_* environment variables
(TRIGGER, CWD, and one per keyword passed to run_hooks, dicts as JSON).
"""

import asyncio
import json
import os
import signal
import sys
import tempfile
from asyncio.subprocess import DEVNULL, PIPE

from tools.builtin.shell import scrubbed_env


async def run_hooks(s, trigger: str, **context) -> None:
    if not s.config.hooks_enabled:
        return
    env = {**scrubbed_env(s.config), "AI_AGENT_TRIGGER": trigger, "AI_AGENT_CWD": str(s.config.cwd)}
    for key, value in context.items():
        if value is not None:
            env[f"AI_AGENT_{key.upper()}"] = value if isinstance(value, str) else json.dumps(value)
    for hook in s.config.hooks:
        if hook.enabled and hook.trigger == trigger:
            await _run(hook, env, s.config.cwd)


async def _run(hook, env: dict, cwd) -> None:
    script = None
    command = hook.command
    if not command:  # inline script: write it to a temp file
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\n" + hook.script)
            script = command = f.name
        os.chmod(script, 0o755)
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE, cwd=cwd, env=env, start_new_session=True
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), hook.timeout_sec)
            if proc.returncode:
                print(f"warning: hook '{hook.name}' exited {proc.returncode}: {stderr.decode(errors='replace').strip()[:200]}", file=sys.stderr)
        except TimeoutError:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL) if sys.platform != "win32" else proc.kill()
            await proc.wait()
            print(f"warning: hook '{hook.name}' timed out after {hook.timeout_sec}s", file=sys.stderr)
    except OSError as e:
        print(f"warning: hook '{hook.name}': {e}", file=sys.stderr)
    finally:
        if script:
            os.unlink(script)
