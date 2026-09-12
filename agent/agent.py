from __future__ import annotations
import asyncio
from typing import AsyncGenerator
from agent.events import AgentEvent, AgentEventType
from agent import undo
from agent.session import Session
from tools.mcp import mcp_manager
import json
from client.llm_client import chat
from config.config import Config
from prompts.system import create_loop_breaker_prompt
from tools.base import ToolResult
from tools.parallel import DependencyAnalyzer


class Agent:
    def __init__(self, config: Config):
        self.config = config
        self.session: Session | None = Session(self.config)
        self._dependency_analyzer = DependencyAnalyzer()

    async def run(self, message: str):
        await self.session.hook_system.trigger_before_agent(message)
        yield AgentEvent.agent_start(message)
        self.session.context_manager.add_user_message(message)

        final_response: str | None = None

        async for event in self._agentic_loop():
            yield event

            if event.type == AgentEventType.TEXT_COMPLETE:
                final_response = event.data.get("content")

        await self.session.hook_system.trigger_after_agent(message, final_response)
        yield AgentEvent.agent_end(final_response)

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:
        max_turns = self.config.max_turns

        for turn_num in range(max_turns):
            self.session.increment_turn()
            response_text = ""

            # check for context overflow
            if self.session.context_manager.needs_compression():
                summary, usage = await self.session.chat_compactor.compress(
                    self.session.context_manager
                )

                if summary:
                    self.session.context_manager.replace_with_summary(summary)
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)

            tool_schemas = self.session.tool_registry.get_schemas()

            tool_calls: list[dict] = []
            usage: dict | None = None

            async for kind, payload in chat(
                self.config,
                self.session.context_manager.get_messages(),
                tools=tool_schemas or None,
            ):
                if kind == "text":
                    response_text += payload
                    yield AgentEvent.text_delta(payload)
                elif kind == "tool_call":
                    tool_calls.append(payload)
                elif kind == "error":
                    yield AgentEvent.agent_error(payload)
                elif kind == "usage":
                    usage = payload

            self.session.context_manager.add_assistant_message(
                response_text or None,
                (
                    [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in tool_calls
                    ]
                    if tool_calls
                    else None
                ),
            )
            if response_text:
                yield AgentEvent.text_complete(response_text)
                self.session.loop_detector.record_action(
                    "response",
                    text=response_text,
                )

            if not tool_calls:
                if usage:
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)

                self.session.context_manager.prune_tool_outputs()
                return

            tool_call_results: list[tuple[str, str]] = []

            if self.config.parallel_tools and len(tool_calls) > 1:
                prepared_calls = [
                    (tc["name"], tc["id"], tc["arguments"]) for tc in tool_calls
                ]
                batches = self._dependency_analyzer.group_parallel_calls(
                    prepared_calls, self.config.cwd
                )

                for batch in batches:
                    for name, call_id, args in batch:
                        yield AgentEvent.tool_call_start(call_id, name, args)
                        self.session.loop_detector.record_action(
                            "tool_call", tool_name=name, args=args
                        )

                    async def invoke_tool(
                        name: str, call_id: str, args: dict
                    ) -> tuple[str, str, ToolResult]:
                        result = await self.session.tool_registry.invoke(self.session, name, args)
                        return (name, call_id, result)

                    semaphore = asyncio.Semaphore(self.config.max_parallel_tools)

                    async def invoke_with_semaphore(
                        name: str, call_id: str, args: dict
                    ) -> tuple[str, str, ToolResult]:
                        async with semaphore:
                            return await invoke_tool(name, call_id, args)

                    tasks = [
                        invoke_with_semaphore(name, call_id, args)
                        for name, call_id, args in batch
                    ]
                    results = await asyncio.gather(*tasks)

                    for name, call_id, result in results:
                        yield AgentEvent.tool_call_complete(call_id, name, result)
                        tool_call_results.append(
                            (call_id, result.to_model_output())
                        )
            else:
                for tool_call in tool_calls:
                    yield AgentEvent.tool_call_start(
                        tool_call["id"],
                        tool_call["name"],
                        tool_call["arguments"],
                    )

                    self.session.loop_detector.record_action(
                        "tool_call",
                        tool_name=tool_call["name"],
                        args=tool_call["arguments"],
                    )

                    result = await self.session.tool_registry.invoke(self.session, tool_call["name"], tool_call["arguments"])

                    yield AgentEvent.tool_call_complete(
                        tool_call["id"],
                        tool_call["name"],
                        result,
                    )

                    tool_call_results.append(
                        (tool_call["id"], result.to_model_output())
                    )

            for call_id, content in tool_call_results:
                self.session.context_manager.add_tool_result(call_id, content)

            undo.commit(self.session, f"Turn {self.session.turn_count}: {', '.join(tc['name'] for tc in tool_calls)}")

            loop_detection_error = self.session.loop_detector.check_for_loop()
            if loop_detection_error:
                loop_prompt = create_loop_breaker_prompt(loop_detection_error)
                self.session.context_manager.add_user_message(loop_prompt)

            if usage:
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

            self.session.context_manager.prune_tool_outputs()
        yield AgentEvent.agent_error(f"Maximum turns ({max_turns}) reached")

    async def __aenter__(self) -> Agent:
        await self.session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ) -> None:
        if self.session:
            await mcp_manager.shutdown(self.session)
            self.session = None
