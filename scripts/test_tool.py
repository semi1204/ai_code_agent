#!/usr/bin/env python3
"""Example hook: appends one JSON line per event to ./hook.log (wired up in .ai-agent/config.toml)."""

import json
import os
from datetime import datetime

KEYS = ("TRIGGER", "TOOL_NAME", "TOOL_PARAMS", "TOOL_RESULT", "USER_MESSAGE", "RESPONSE", "ERROR")
entry = {"timestamp": datetime.now().isoformat()}
entry.update({key.lower(): os.environ[f"AI_AGENT_{key}"] for key in KEYS if f"AI_AGENT_{key}" in os.environ})
with open(os.path.join(os.environ.get("AI_AGENT_CWD", "."), "hook.log"), "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
