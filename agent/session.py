"""Session: all per-conversation state in one dataclass."""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from config.config import Config
from context import loop_detector


@dataclass
class Session:
    config: Config
    system_prompt: str = ""  # built by agent.start() once the tools are known
    messages: list = field(default_factory=list)  # OpenAI chat messages
    usage: dict = field(default_factory=dict)  # cumulative token usage
    last_usage: dict = field(default_factory=dict)  # latest completion's usage (context-size estimate)
    undo: list = field(default_factory=list)  # committed undo entries
    pending: list = field(default_factory=list)  # (path, old_content) snapshots for the current turn
    todos: dict = field(default_factory=dict)
    mcp: dict = field(default_factory=dict)  # server name -> MCPClient
    history: deque = field(default_factory=lambda: deque(maxlen=loop_detector.WINDOW))  # for loop detection
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    turns: int = 0
