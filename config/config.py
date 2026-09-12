import os
from dataclasses import dataclass, field
from pathlib import Path

APPROVAL_POLICIES = ("on-request", "on-failure", "auto", "auto-edit", "never", "yolo")
HOOK_TRIGGERS = ("before_agent", "after_agent", "before_tool", "after_tool", "on_error")


@dataclass
class ModelConfig:
    name: str = "mistralai/devstral-2512:free"
    temperature: float = 1
    context_window: int = 256_000


@dataclass
class ShellEnvironmentPolicy:
    ignore_default_excludes: bool = False
    exclude_patterns: list = field(default_factory=lambda: ["*KEY*", "*TOKEN*", "*SECRET*"])
    set_vars: dict = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    enabled: bool = True
    startup_timeout_sec: float = 10
    command: str | None = None  # stdio transport
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None  # streamable http transport

    def __post_init__(self):
        if bool(self.command) == bool(self.url):
            raise ValueError("MCP server needs exactly one of 'command' (stdio) or 'url' (http)")


@dataclass
class HookConfig:
    name: str
    trigger: str
    command: str | None = None
    script: str | None = None
    timeout_sec: float = 30
    enabled: bool = True

    def __post_init__(self):
        if self.trigger not in HOOK_TRIGGERS:
            raise ValueError(f"hook '{self.name}': trigger must be one of {HOOK_TRIGGERS}")
        if not (self.command or self.script):
            raise ValueError(f"hook '{self.name}': needs 'command' or 'script'")


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    cwd: Path = field(default_factory=Path.cwd)
    shell_environment: ShellEnvironmentPolicy = field(default_factory=ShellEnvironmentPolicy)
    hooks_enabled: bool = False
    hooks: list = field(default_factory=list)
    approval: str = "on-request"
    max_turns: int = 100
    mcp_servers: dict = field(default_factory=dict)
    allowed_tools: list | None = None  # if set, only these tools are offered
    developer_instructions: str | None = None
    user_instructions: str | None = None
    parallel_tools: bool = True
    max_parallel_tools: int = 5

    def __post_init__(self):
        if self.approval not in APPROVAL_POLICIES:
            raise ValueError(f"approval must be one of {APPROVAL_POLICIES}")

    @property
    def api_key(self) -> str | None:
        return os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")

    @property
    def base_url(self) -> str | None:
        return os.environ.get("BASE_URL") or os.environ.get("OPENAI_API_BASE")

    @property
    def model_name(self) -> str:
        return self.model.name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model.name = value

    @property
    def temperature(self) -> float:
        return self.model.temperature

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("No API key found. Set API_KEY (or OPENAI_API_KEY)")
        if not self.cwd.exists():
            errors.append(f"Working directory does not exist: {self.cwd}")
        return errors


def from_dict(d: dict) -> Config:
    d = dict(d)
    d["model"] = ModelConfig(**d.get("model", {}))
    d["shell_environment"] = ShellEnvironmentPolicy(**d.get("shell_environment", {}))
    d["hooks"] = [HookConfig(**h) for h in d.get("hooks", [])]
    d["mcp_servers"] = {k: MCPServerConfig(**v) for k, v in d.get("mcp_servers", {}).items()}
    d["cwd"] = Path(d.get("cwd", Path.cwd()))
    return Config(**d)
