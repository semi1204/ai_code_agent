from datetime import datetime
from typing import Any
import uuid
from config.config import Config
from collections import deque
from context import loop_detector
from prompts.system import get_system_prompt
from tools import discovery
from tools.builtin import memory
from tools.mcp import mcp_manager
from tools import registry


class Session:
    def __init__(self, config: Config):
        self.config = config
        self.system_prompt: str | None = None  # built in initialize() once tools are known
        self.messages: list[dict] = []
        self.usage: dict = {}  # cumulative token usage
        self.last_usage: dict = {}  # usage of the latest completion (context size estimate)
        self.mcp: dict = {}  # server name -> MCPClient
        self.history: deque = deque(maxlen=loop_detector.WINDOW)  # recent actions for loop detection
        self.session_id = str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.todos: dict[str, str] = {}
        self.undo: list[dict] = []  # committed undo entries
        self.pending: list[tuple] = []  # (path, old_content) snapshots for the current turn

        self.turn_count = 0

    async def initialize(self) -> None:
        await mcp_manager.connect_all(self)
        discovery.load_plugins(self.config)
        self.system_prompt = get_system_prompt(self.config, self._load_memory(), [registry.info(n) for n in registry.names(self)])

    def _load_memory(self) -> str | None:
        entries = memory.load()
        return "User preferences and notes:\n" + "\n".join(f"- {k}: {v}" for k, v in entries.items()) if entries else None

    def increment_turn(self) -> int:
        self.turn_count += 1
        self.updated_at = datetime.now()

        return self.turn_count

    def get_stats(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "turn_count": self.turn_count,
            "message_count": len(self.messages),
            "token_usage": self.usage,
            "tools_count": len(registry.names(self)),
            "mcp_servers": sum(1 for c in self.mcp.values() if c.status == "connected"),
        }
