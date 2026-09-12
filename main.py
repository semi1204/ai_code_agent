"""CLI entry point: `python main.py "prompt"` for one shot, no argument for the REPL."""

import asyncio
import sys
from pathlib import Path

from agent import undo
from agent.agent import Agent
from agent.events import AgentEventType
from agent.persistence import PersistenceManager, SessionSnapshot
from agent.session import Session
from config.config import APPROVAL_POLICIES
from config.loader import load_config
from tools.mcp import mcp_manager
from ui import tui
from ui.tui import BLUE, BOLD, DIM, GREEN, RED, RESET, YELLOW


class CLI:
    def __init__(self, config):
        self.config = config
        self.agent = None

    async def run_single(self, message: str) -> str | None:
        async with Agent(self.config) as agent:
            self.agent = agent
            return await self.process(message)

    async def run_interactive(self) -> None:
        tui.welcome(self.config)
        async with Agent(self.config) as agent:
            self.agent = agent
            while True:
                try:
                    line = input(f"\n{BOLD}{BLUE}❯{RESET} ").strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print(f"\n{DIM}Use /exit to quit{RESET}")
                    continue
                if not line:
                    continue
                if line.startswith("/"):
                    if await self.command(line) is False:
                        break
                else:
                    await self.process(line)
        print(f"\n{DIM}Goodbye!{RESET}")

    def tool_kind(self, name: str) -> str | None:
        tool = self.agent.session.tool_registry.get(name)
        return tool.kind.value if tool else None

    async def process(self, message: str) -> str | None:
        streaming, final = False, None
        async for event in self.agent.run(message):
            d = event.data
            if event.type == AgentEventType.TEXT_DELTA:
                if not streaming:
                    tui.begin_text()
                    streaming = True
                tui.text(d.get("content", ""))
            elif event.type == AgentEventType.TEXT_COMPLETE:
                final = d.get("content")
                if streaming:
                    tui.end_text()
                    streaming = False
            elif event.type == AgentEventType.AGENT_ERROR:
                print(f"\n{RED}⏺ Error: {d.get('error', 'Unknown error')}{RESET}")
            elif event.type == AgentEventType.TOOL_CALL_START:
                tui.tool_start(d["name"], self.tool_kind(d["name"]), d.get("arguments", {}), self.config.cwd)
            elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                tui.tool_end(d["name"], d.get("success", False), d.get("output", ""), d.get("error"), d.get("diff"))
        return final

    # --- slash commands: each takes the argument string; returning False quits ---

    async def command(self, line: str):
        name, _, args = line.partition(" ")
        if name.lower() not in COMMANDS:
            print(f"{RED}Unknown command: {name}{RESET}")
            return True
        handler, _ = COMMANDS[name.lower()]
        return await handler(self, args.strip())

    async def cmd_quit(self, args):
        return False

    async def cmd_help(self, args):
        tui.show_help(COMMANDS)

    async def cmd_clear(self, args):
        self.agent.session.context_manager.clear()
        self.agent.session.loop_detector.clear()
        print(f"{GREEN}Conversation cleared{RESET}")

    async def cmd_config(self, args):
        c = self.config
        print(f"\n{BOLD}Current Configuration{RESET}")
        for key, value in [
            ("Model", c.model_name), ("Temperature", c.temperature), ("Approval", c.approval),
            ("Working Dir", c.cwd), ("Max Turns", c.max_turns), ("Hooks Enabled", c.hooks_enabled),
        ]:
            print(f"  {key}: {value}")

    async def cmd_model(self, args):
        if args:
            self.config.model_name = args
            print(f"{GREEN}Model changed to: {args}{RESET}")
        else:
            print(f"Current model: {self.config.model_name}")

    async def cmd_approval(self, args):
        if not args:
            print(f"Current approval policy: {self.config.approval}")
        elif args in APPROVAL_POLICIES:
            self.config.approval = args
            print(f"{GREEN}Approval policy changed to: {args}{RESET}")
        else:
            print(f"{RED}Unknown approval policy: {args}. Valid: {', '.join(APPROVAL_POLICIES)}{RESET}")

    async def cmd_stats(self, args):
        print(f"\n{BOLD}Session Statistics{RESET}")
        for key, value in self.agent.session.get_stats().items():
            print(f"   {key}: {value}")

    async def cmd_tools(self, args):
        tools = self.agent.session.tool_registry.get_tools()
        print(f"\n{BOLD}Available tools ({len(tools)}){RESET}")
        for tool in tools:
            print(f"  • {tool.name}")

    async def cmd_mcp(self, args):
        servers = mcp_manager.status(self.agent.session)
        print(f"\n{BOLD}MCP Servers ({len(servers)}){RESET}")
        for s in servers:
            color = GREEN if s["status"] == "connected" else RED
            print(f"  • {s['name']}: {color}{s['status']}{RESET} ({s['tools']} tools)")

    # sessions and checkpoints share one snapshot/restore path

    def snapshot(self) -> SessionSnapshot:
        s = self.agent.session
        return SessionSnapshot(
            s.session_id, s.created_at, s.updated_at, s.turn_count, s.context_manager.get_messages(), s.context_manager.total_usage
        )

    async def restore(self, snap: SessionSnapshot) -> None:
        session = Session(self.config)
        await session.initialize()
        session.session_id, session.created_at, session.updated_at, session.turn_count = (
            snap.session_id, snap.created_at, snap.updated_at, snap.turn_count
        )
        cm = session.context_manager
        cm.total_usage = snap.total_usage
        for m in snap.messages:
            if m["role"] == "user":
                cm.add_user_message(m.get("content", ""))
            elif m["role"] == "assistant":
                cm.add_assistant_message(m.get("content", ""), m.get("tool_calls"))
            elif m["role"] == "tool":
                cm.add_tool_result(m.get("tool_call_id", ""), m.get("content", ""))
        await mcp_manager.shutdown(self.agent.session)
        self.agent.session = session

    async def cmd_save(self, args):
        PersistenceManager().save_session(self.snapshot())
        print(f"{GREEN}Session saved: {self.agent.session.session_id}{RESET}")

    async def cmd_sessions(self, args):
        print(f"\n{BOLD}Saved Sessions{RESET}")
        for s in PersistenceManager().list_sessions():
            print(f"  • {s['session_id']} (turns: {s['turn_count']}, updated: {s['updated_at']})")

    async def cmd_resume(self, args):
        snap = PersistenceManager().load_session(args) if args else None
        if not snap:
            print(f"{RED}Usage: /resume <session_id> (see /sessions){RESET}")
            return
        await self.restore(snap)
        print(f"{GREEN}Resumed session: {snap.session_id}{RESET}")

    async def cmd_checkpoint(self, args):
        checkpoint_id = PersistenceManager().save_checkpoint(self.snapshot())
        print(f"{GREEN}Checkpoint created: {checkpoint_id}{RESET}")

    async def cmd_checkpoints(self, args):
        print(f"\n{BOLD}Checkpoints{RESET}")
        for path in sorted(PersistenceManager().checkpoints_dir.glob("*.json"), reverse=True):
            print(f"  • {path.stem}")

    async def cmd_restore(self, args):
        snap = PersistenceManager().load_checkpoint(args) if args else None
        if not snap:
            print(f"{RED}Usage: /restore <checkpoint_id> (see /checkpoints){RESET}")
            return
        await self.restore(snap)
        print(f"{GREEN}Restored checkpoint: {args}{RESET}")

    async def cmd_undo(self, args):
        try:
            count = int(args or 1)
        except ValueError:
            print(f"{RED}Usage: /undo [count]{RESET}")
            return
        undone = undo.undo(self.agent.session, count)
        if not undone:
            print(f"{YELLOW}Nothing to undo{RESET}")
        for entry in undone:
            print(f"{GREEN}Undone: {entry['description']}{RESET}")
            for path, old in entry["changes"]:
                print(f"  - {'Deleted' if old is None else 'Restored'}: {path}")

    async def cmd_history(self, args):
        history = undo.history(self.agent.session)
        if not history:
            print(f"{DIM}No undo history{RESET}")
            return
        print(f"\n{BOLD}Undo History{RESET}")
        for e in history:
            print(f"  {e['description']} ({len(e['changes'])} file(s)) {DIM + '(undone)' + RESET if e['undone'] else ''}")


COMMANDS = {  # name -> (handler, help)
    "/help": (CLI.cmd_help, "Show this help"),
    "/exit": (CLI.cmd_quit, "Exit the agent"),
    "/quit": (CLI.cmd_quit, "Exit the agent"),
    "/q": (CLI.cmd_quit, "Exit the agent"),
    "/clear": (CLI.cmd_clear, "Clear conversation history"),
    "/c": (CLI.cmd_clear, "Clear conversation history"),
    "/config": (CLI.cmd_config, "Show current configuration"),
    "/model": (CLI.cmd_model, "/model <name> — change the model"),
    "/approval": (CLI.cmd_approval, "/approval <mode> — change approval mode"),
    "/stats": (CLI.cmd_stats, "Show session statistics"),
    "/tools": (CLI.cmd_tools, "List available tools"),
    "/mcp": (CLI.cmd_mcp, "Show MCP server status"),
    "/save": (CLI.cmd_save, "Save current session"),
    "/sessions": (CLI.cmd_sessions, "List saved sessions"),
    "/resume": (CLI.cmd_resume, "/resume <session_id> — resume a saved session"),
    "/checkpoint": (CLI.cmd_checkpoint, "Create a checkpoint"),
    "/checkpoints": (CLI.cmd_checkpoints, "List checkpoints"),
    "/restore": (CLI.cmd_restore, "/restore <checkpoint_id> — restore a checkpoint"),
    "/undo": (CLI.cmd_undo, "/undo [N] — undo last N file operations"),
    "/history": (CLI.cmd_history, "Show undo history"),
}


def main(argv: list[str]) -> None:
    args = list(argv)
    cwd = None
    for flag in ("--cwd", "-c"):
        if flag in args:
            i = args.index(flag)
            cwd = Path(args[i + 1])
            del args[i : i + 2]
    prompt = " ".join(args)

    config = load_config(cwd=cwd)
    errors = config.validate()
    for error in errors:
        print(f"{RED}{error}{RESET}")
    if errors:
        sys.exit(1)

    cli = CLI(config)
    if prompt:
        if asyncio.run(cli.run_single(prompt)) is None:
            sys.exit(1)
    else:
        asyncio.run(cli.run_interactive())


if __name__ == "__main__":
    main(sys.argv[1:])
