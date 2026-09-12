from datetime import datetime
from typing import Any
import uuid
from config.config import Config
from context.compaction import ChatCompactor
from context.loop_detector import LoopDetector
from context.manager import ContextManager
from hooks.hook_system import HookSystem
from tools import discovery
from tools.builtin import memory
from tools.mcp import mcp_manager
from tools.registry import create_default_registry


class Session:
    def __init__(self, config: Config):
        self.config = config
        self.tool_registry = create_default_registry(config)
        self.context_manager: ContextManager | None = None
        self.mcp: dict = {}  # server name -> MCPClient
        self.chat_compactor = ChatCompactor(config)
        self.loop_detector = LoopDetector()
        self.hook_system = HookSystem(config)
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
        self.context_manager = ContextManager(
            config=self.config,
            user_memory=self._load_memory(),
            tools=self.tool_registry.get_tools(),
        )

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
            "message_count": self.context_manager.message_count,
            "token_usage": self.context_manager.total_usage,
            "tools_count": len(self.tool_registry.get_tools()),
            "mcp_servers": sum(1 for c in self.mcp.values() if c.status == "connected"),
        }
