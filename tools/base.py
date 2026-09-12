"""Tool infrastructure.

A tool is `def fn(args: dict, s) -> str` (sync or async), registered with
`@tool(name, description, params, kind)`. `params` is the compact schema
{"path": "string", "limit": "number?"} (trailing ? = optional) or a full JSON
schema object. Failures come back as "error: ..." strings, never exceptions.

The Tool class further down is the legacy class-based API, kept only until
every builtin is converted.
"""

from __future__ import annotations
import abc
import inspect
from pathlib import Path
from pydantic import BaseModel, ValidationError
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass, field
from pydantic.json_schema import model_json_schema

from config.config import Config

KINDS = ("read", "write", "shell", "network", "memory", "mcp")
MUTATING = {"write", "shell", "network", "memory", "mcp"}
TOOLS: dict[str, tuple[str, dict, Callable, str]] = {}  # name -> (description, params, fn, kind)
JSON_TYPES = {"number": "integer"}  # compact type -> JSON schema type


def tool(name: str, description: str, params: dict, kind: str = "read"):
    def register(fn):
        TOOLS[name] = (description, params, fn, kind)
        return fn

    return register


def make_schema(name: str) -> dict:
    description, params, _, _ = TOOLS[name]
    if params.get("type") == "object":  # already a JSON schema (MCP servers send these)
        return {"name": name, "description": description, "parameters": params}
    properties, required = {}, []
    for pname, ptype in params.items():
        base = ptype.rstrip("?")
        properties[pname] = {"type": JSON_TYPES.get(base, base)}
        if not ptype.endswith("?"):
            required.append(pname)
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


async def run_tool(name: str, args: dict, s) -> str:
    _, params, fn, _ = TOOLS[name]
    if params.get("type") != "object":
        missing = [p for p, t in params.items() if not t.endswith("?") and p not in args]
        if missing:
            return f"error: missing parameters: {', '.join(missing)}"
    try:
        result = fn(args, s)
        return await result if inspect.isawaitable(result) else result
    except Exception as e:
        return f"error: {e}"


# --- legacy class-based API ---


class ToolKind(str, Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    NETWORK = "network"
    MEMORY = "memory"
    MCP = "mcp"


@dataclass
class FileDiff:
    path: Path
    old_content: str
    new_content: str

    is_new_file: bool = False
    is_deletion: bool = False

    def to_diff(self) -> str:
        import difflib

        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        old_name = "/dev/null" if self.is_new_file else str(self.path)
        new_name = "/dev/null" if self.is_deletion else str(self.path)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
        )

        return "".join(diff)


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    truncated: bool = False
    diff: FileDiff | None = None
    exit_code: int | None = None

    @classmethod
    def error_result(cls, error: str, output: str = "", **kwargs: Any):
        return cls(
            success=False,
            output=output,
            error=error,
            **kwargs,
        )

    @classmethod
    def success_result(cls, output: str, **kwargs: Any):
        return cls(
            success=True,
            output=output,
            error=None,
            **kwargs,
        )

    def to_model_output(self) -> str:
        if self.success or self.output == self.error:
            return self.output
        return f"Error: {self.error}" + (f"\n\nOutput:\n{self.output}" if self.output else "")


@dataclass
class ToolInvocation:
    params: dict[str, Any]
    cwd: Path
    session: Any = None


@dataclass
class ToolConfirmation:
    tool_name: str
    params: dict[str, Any]
    description: str

    diff: FileDiff | None = None
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class Tool(abc.ABC):
    name: str = "base_tool"
    description: str = "Base tool"
    kind: ToolKind = ToolKind.READ

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    def schema(self) -> dict[str, Any] | type["BaseModel"]:
        raise NotImplementedError("Tool must define schema property or class attribute")

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**params)
            except ValidationError as e:
                errors = []
                for error in e.errors():
                    field = ".".join(str(x) for x in error.get("loc", []))
                    msg = error.get("msg", "Validation error")
                    errors.append(f"Parameter '{field}': {msg}")

                return errors
            except Exception as e:
                return [str(e)]

        return []

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return self.kind in {
            ToolKind.WRITE,
            ToolKind.SHELL,
            ToolKind.NETWORK,
            ToolKind.MEMORY,
        }

    async def get_confirmation(
        self, invocation: ToolInvocation
    ) -> ToolConfirmation | None:
        if not self.is_mutating(invocation.params):
            return None

        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Execute {self.name}",
        )

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.schema

        if isinstance(schema, type) and issubclass(schema, BaseModel):

            json_schema = model_json_schema(schema, mode="serialization")

            return {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": json_schema.get("properties", {}),
                    "required": json_schema.get("required", []),
                },
            }

        if isinstance(schema, dict):
            result = {
                "name": self.name,
                "description": self.description,
            }

            if "parameters" in schema:
                result["parameters"] = schema["parameters"]
            else:
                result["parameters"] = schema

            return result

        raise ValueError(f"Invalid schema type for tool {self.name}: {type(schema)}")
