"""Looks tools up by name and runs them through approval and hooks."""

from types import SimpleNamespace

from safety.approval import ApprovalContext, ApprovalDecision
from tools.base import MUTATING, TOOLS, Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult, make_schema, run_tool
from tools.builtin import get_all_builtin_tools
from tools.subagents import SubagentTool, get_default_subagent_definitions
from utils.paths import resolve_path


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
        invocation = ToolInvocation(params=params, cwd=s.config.cwd, undo_manager=s.undo_manager)
        confirmation = await tool.get_confirmation(invocation)
        if confirmation:
            context = ApprovalContext(
                name, params, tool.is_mutating(params), confirmation.affected_paths, confirmation.command, confirmation.is_dangerous
            )
            if rejected := await self._approve(s, context, confirmation):
                return rejected
        try:
            return await tool.execute(invocation)
        except Exception as e:
            return ToolResult.error_result(f"Internal error: {e}")

    async def _invoke_function(self, s, name: str, params: dict) -> ToolResult:
        if TOOLS[name][3] in MUTATING:
            paths = [resolve_path(s.config.cwd, params["path"])] if "path" in params else []
            confirmation = ToolConfirmation(name, params, f"Execute {name}", affected_paths=paths, command=params.get("command"))
            if rejected := await self._approve(s, ApprovalContext(name, params, True, paths, confirmation.command), confirmation):
                return rejected
        output = await run_tool(name, params, s)
        if output.startswith("error:"):
            return ToolResult(success=False, output=output, error=output)
        return ToolResult.success_result(output)

    async def _approve(self, s, context: ApprovalContext, confirmation: ToolConfirmation) -> ToolResult | None:
        decision = await s.approval_manager.check_approval(context)
        if decision == ApprovalDecision.REJECTED:
            return ToolResult.error_result("Operation rejected by safety policy")
        if decision == ApprovalDecision.NEEDS_CONFIRMATION and not s.approval_manager.request_confirmation(confirmation):
            return ToolResult.error_result("User rejected the operation")
        return None


def create_default_registry(config) -> ToolRegistry:
    registry = ToolRegistry(config)
    for tool_class in get_all_builtin_tools():
        registry.register(tool_class(config))
    for definition in get_default_subagent_definitions():
        registry.register(SubagentTool(config, definition))
    return registry
