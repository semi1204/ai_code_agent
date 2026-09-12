"""CLI entry point: `python main.py "prompt"` for one shot, no argument for the REPL."""

import asyncio
import sys
from pathlib import Path

from agent.agent import Agent
from agent.events import AgentEventType
from agent.persistence import PersistenceManager, SessionSnapshot
from agent.session import Session
from config.config import APPROVAL_POLICIES
from config.loader import load_config
from ui.tui import TUI, get_console

console = get_console()


class CLI:
    def __init__(self, config):
        self.config = config
        self.tui = TUI(config, console)
        self.agent = None

    async def run_single(self, message: str) -> str | None:
        async with Agent(self.config) as agent:
            self.agent = agent
            return await self.process(message)

    async def run_interactive(self) -> None:
        self.tui.print_welcome(
            "AI Agent",
            lines=[f"model: {self.config.model_name}", f"cwd: {self.config.cwd}", "commands: /help /config /approval /model /exit"],
        )
        async with Agent(self.config, confirmation_callback=self.tui.handle_confirmation) as agent:
            self.agent = agent
            while True:
                try:
                    line = console.input("\n[user]>[/user] ").strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    console.print("\n[dim]Use /exit to quit[/dim]")
                    continue
                if not line:
                    continue
                if line.startswith("/"):
                    if await self.command(line) is False:
                        break
                else:
                    await self.process(line)
        console.print("\n[dim]Goodbye![/dim]")

    def tool_kind(self, name: str) -> str | None:
        tool = self.agent.session.tool_registry.get(name)
        return tool.kind.value if tool else None

    async def process(self, message: str) -> str | None:
        streaming, final = False, None
        async for event in self.agent.run(message):
            d = event.data
            if event.type == AgentEventType.TEXT_DELTA:
                if not streaming:
                    self.tui.begin_assistant()
                    streaming = True
                self.tui.stream_assistant_delta(d.get("content", ""))
            elif event.type == AgentEventType.TEXT_COMPLETE:
                final = d.get("content")
                if streaming:
                    self.tui.end_assistant()
                    streaming = False
            elif event.type == AgentEventType.AGENT_ERROR:
                console.print(f"\n[error]Error: {d.get('error', 'Unknown error')}[/error]")
            elif event.type == AgentEventType.TOOL_CALL_START:
                self.tui.tool_call_start(d.get("call_id", ""), d["name"], self.tool_kind(d["name"]), d.get("arguments", {}))
            elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                self.tui.tool_call_complete(
                    d.get("call_id", ""), d["name"], self.tool_kind(d["name"]), d.get("success", False), d.get("output", ""),
                    d.get("error"), d.get("metadata"), d.get("diff"), d.get("truncated", False), d.get("exit_code"),
                )
        return final

    # --- slash commands: each takes the argument string; returning False quits ---

    async def command(self, line: str):
        name, _, args = line.partition(" ")
        handler = COMMANDS.get(name.lower())
        if not handler:
            console.print(f"[error]Unknown command: {name}[/error]")
            return True
        return await handler(self, args.strip())

    async def cmd_quit(self, args):
        return False

    async def cmd_help(self, args):
        self.tui.show_help()

    async def cmd_clear(self, args):
        self.agent.session.context_manager.clear()
        self.agent.session.loop_detector.clear()
        console.print("[success]Conversation cleared[/success]")

    async def cmd_config(self, args):
        c = self.config
        console.print("\n[bold]Current Configuration[/bold]")
        for key, value in [
            ("Model", c.model_name), ("Temperature", c.temperature), ("Approval", c.approval),
            ("Working Dir", c.cwd), ("Max Turns", c.max_turns), ("Hooks Enabled", c.hooks_enabled),
        ]:
            console.print(f"  {key}: {value}")

    async def cmd_model(self, args):
        if args:
            self.config.model_name = args
            console.print(f"[success]Model changed to: {args}[/success]")
        else:
            console.print(f"Current model: {self.config.model_name}")

    async def cmd_approval(self, args):
        if not args:
            console.print(f"Current approval policy: {self.config.approval}")
        elif args in APPROVAL_POLICIES:
            self.config.approval = args
            console.print(f"[success]Approval policy changed to: {args}[/success]")
        else:
            console.print(f"[error]Unknown approval policy: {args}. Valid: {', '.join(APPROVAL_POLICIES)}[/error]")

    async def cmd_stats(self, args):
        console.print("\n[bold]Session Statistics[/bold]")
        for key, value in self.agent.session.get_stats().items():
            console.print(f"   {key}: {value}")

    async def cmd_tools(self, args):
        tools = self.agent.session.tool_registry.get_tools()
        console.print(f"\n[bold]Available tools ({len(tools)})[/bold]")
        for tool in tools:
            console.print(f"  • {tool.name}")

    async def cmd_mcp(self, args):
        servers = self.agent.session.mcp_manager.get_all_servers()
        console.print(f"\n[bold]MCP Servers ({len(servers)})[/bold]")
        for s in servers:
            color = "green" if s["status"] == "connected" else "red"
            console.print(f"  • {s['name']}: [{color}]{s['status']}[/{color}] ({s['tools']} tools)")

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
        await self.agent.session.mcp_manager.shutdown()
        self.agent.session = session

    async def cmd_save(self, args):
        PersistenceManager().save_session(self.snapshot())
        console.print(f"[success]Session saved: {self.agent.session.session_id}[/success]")

    async def cmd_sessions(self, args):
        console.print("\n[bold]Saved Sessions[/bold]")
        for s in PersistenceManager().list_sessions():
            console.print(f"  • {s['session_id']} (turns: {s['turn_count']}, updated: {s['updated_at']})")

    async def cmd_resume(self, args):
        snap = PersistenceManager().load_session(args) if args else None
        if not snap:
            console.print("[error]Usage: /resume <session_id> (see /sessions)[/error]")
            return
        await self.restore(snap)
        console.print(f"[success]Resumed session: {snap.session_id}[/success]")

    async def cmd_checkpoint(self, args):
        checkpoint_id = PersistenceManager().save_checkpoint(self.snapshot())
        console.print(f"[success]Checkpoint created: {checkpoint_id}[/success]")

    async def cmd_checkpoints(self, args):
        console.print("\n[bold]Checkpoints[/bold]")
        for path in sorted(PersistenceManager().checkpoints_dir.glob("*.json"), reverse=True):
            console.print(f"  • {path.stem}")

    async def cmd_restore(self, args):
        snap = PersistenceManager().load_checkpoint(args) if args else None
        if not snap:
            console.print("[error]Usage: /restore <checkpoint_id> (see /checkpoints)[/error]")
            return
        await self.restore(snap)
        console.print(f"[success]Restored checkpoint: {args}[/success]")

    async def cmd_undo(self, args):
        try:
            count = int(args or 1)
        except ValueError:
            console.print("[error]Usage: /undo [count][/error]")
            return
        undone = self.agent.session.undo_manager.undo(count)
        if not undone:
            console.print("[warning]Nothing to undo[/warning]")
        for entry in undone:
            console.print(f"[success]Undone: {entry.description}[/success]")
            for change in entry.changes:
                console.print(f"  - {'Deleted' if change.is_new_file else 'Restored'}: {change.path}")

    async def cmd_history(self, args):
        history = self.agent.session.undo_manager.get_history()
        if not history:
            console.print("[dim]No undo history[/dim]")
            return
        console.print("\n[bold]Undo History[/bold]")
        for e in history:
            console.print(f"  {e.entry_id} - {e.description} ({len(e.changes)} file(s)) {'[dim](undone)[/dim]' if e.is_undone else ''}")


COMMANDS = {
    "/help": CLI.cmd_help,
    "/exit": CLI.cmd_quit, "/quit": CLI.cmd_quit, "/q": CLI.cmd_quit,
    "/clear": CLI.cmd_clear, "/c": CLI.cmd_clear,
    "/config": CLI.cmd_config,
    "/model": CLI.cmd_model,
    "/approval": CLI.cmd_approval,
    "/stats": CLI.cmd_stats,
    "/tools": CLI.cmd_tools,
    "/mcp": CLI.cmd_mcp,
    "/save": CLI.cmd_save, "/sessions": CLI.cmd_sessions, "/resume": CLI.cmd_resume,
    "/checkpoint": CLI.cmd_checkpoint, "/checkpoints": CLI.cmd_checkpoints, "/restore": CLI.cmd_restore,
    "/undo": CLI.cmd_undo, "/history": CLI.cmd_history,
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
        console.print(f"[error]{error}[/error]")
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
