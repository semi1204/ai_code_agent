"""Looks tools up by name and runs them through approval and hooks."""

from types import SimpleNamespace

from safety import approval
from tools.base import TOOLS, Tool, ToolInvocation, ToolKind, ToolResult, make_schema, run_tool
from tools.builtin import get_all_builtin_tools
from tools.subagents import SubagentTool, get_default_subagent_definitions


class ToolRegistry:
    def __init__(self, config):
        self.config = config
        self._tools: dict[str, Tool] = {}  # legacy class-based tools; function tools live in TOOLS

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    register_mcp_tool = register

    def names(self) -> list[str]:
        names = list(self._tools) + [n for n in TOOLS if n not in self._tools]
        if self.config.allowed_tools:
            names = [n for n in names if n in self.config.allowed_tools]
        return names

    def get(self, name: str):
        if name in self._tools:
            return self._tools[name]
        if name in TOOLS:
            description, _, _, kind = TOOLS[name]
            return SimpleNamespace(name=name, description=description, kind=ToolKind(kind))
        return None

    def get_tools(self) -> list:
        return [self.get(n) for n in self.names()]

    def get_schemas(self) -> list[dict]:
        return [self._tools[n].to_openai_schema() if n in self._tools else make_schema(n) for n in self.names()]

    async def invoke(self, s, name: str, params: dict) -> ToolResult:
        if name not in self.names():
            result = ToolResult.error_result(f"Unknown tool: {name}")
        else:
            await s.hook_system.trigger_before_tool(name, params)
            result = await (self._invoke_class(s, name, params) if name in self._tools else self._invoke_function(s, name, params))
        await s.hook_system.trigger_after_tool(name, params, result)
        return result

    async def _invoke_class(self, s, name: str, params: dict) -> ToolResult:
        tool = self._tools[name]
        errors = tool.validate_params(params)
        if errors:
            return ToolResult.error_result(f"Invalid parameters: {'; '.join(errors)}")
        invocation = ToolInvocation(params=params, cwd=s.config.cwd, session=s)
        confirmation = await tool.get_confirmation(invocation)
        if confirmation:
            diff = confirmation.diff.to_diff() if confirmation.diff else None
            if error := approval.check(s, name, params, tool.kind.value, diff):
                return _fail(error)
        try:
            return await tool.execute(invocation)
        except Exception as e:
            return ToolResult.error_result(f"Internal error: {e}")

    async def _invoke_function(self, s, name: str, params: dict) -> ToolResult:
        if error := approval.check(s, name, params, TOOLS[name][3]):
            return _fail(error)
        output = await run_tool(name, params, s)
        return _fail(output) if output.startswith("error:") else ToolResult.success_result(output)


def _fail(message: str) -> ToolResult:
    return ToolResult(success=False, output=message, error=message)


def create_default_registry(config) -> ToolRegistry:
    registry = ToolRegistry(config)
    for tool_class in get_all_builtin_tools():
        registry.register(tool_class(config))
    for definition in get_default_subagent_definitions():
        registry.register(SubagentTool(config, definition))
    return registry
