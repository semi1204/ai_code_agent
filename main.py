"""CLI entry point: `python main.py "prompt"` for one shot, no argument for the REPL."""

import asyncio
import sys
from pathlib import Path

from agent import agent, undo
from agent.persistence import PersistenceManager, SessionSnapshot
from config.config import APPROVAL_POLICIES
from config.loader import load_config
from tools import registry
from tools.mcp import mcp_manager
from ui import tui
from ui.tui import BLUE, BOLD, DIM, GREEN, RED, RESET, YELLOW


class CLI:
    def __init__(self, config):
        self.config = config
        self.session = None

    async def run_single(self, message: str) -> str | None:
        self.session = await agent.start(self.config)
        try:
            return await self.process(message)
        finally:
            await agent.close(self.session)

    async def run_interactive(self) -> None:
        tui.welcome(self.config)
        self.session = await agent.start(self.config)
        try:
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
        finally:
            await agent.close(self.session)
        print(f"\n{DIM}Goodbye!{RESET}")

    def tool_kind(self, name: str) -> str | None:
        tool = registry.info(name)
        return tool.kind if tool else None

    async def process(self, message: str) -> str | None:
        streaming, final = False, None
        async for event in agent.run(self.session, message):
            if streaming and event[0] != "text":
                tui.end_text()
                streaming = False
            if event[0] == "text":
                if not streaming:
                    tui.begin_text()
                    streaming, final = True, ""
                tui.text(event[1])
                final += event[1]
            elif event[0] == "tool_start":
                tui.tool_start(event[1], self.tool_kind(event[1]), event[2], self.config.cwd)
            elif event[0] == "tool_end":
                tui.tool_end(event[1], event[2])
            elif event[0] == "error":
                print(f"\n{RED}⏺ Error: {event[1]}{RESET}")
        if streaming:
            tui.end_text()
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
        self.session.messages.clear()
        self.session.history.clear()
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
        s = self.session
        print(f"\n{BOLD}Session Statistics{RESET}")
        for key, value in [
            ("session_id", s.id), ("created_at", s.created_at.isoformat()), ("turns", s.turns), ("messages", len(s.messages)),
            ("token_usage", s.usage), ("tools", len(registry.names(s))), ("mcp_servers", sum(c.status == "connected" for c in s.mcp.values())),
        ]:
            print(f"   {key}: {value}")

    async def cmd_tools(self, args):
        names = registry.names(self.session)
        print(f"\n{BOLD}Available tools ({len(names)}){RESET}")
        for name in names:
            print(f"  • {name}")

    async def cmd_mcp(self, args):
        servers = mcp_manager.status(self.session)
        print(f"\n{BOLD}MCP Servers ({len(servers)}){RESET}")
        for s in servers:
            color = GREEN if s["status"] == "connected" else RED
            print(f"  • {s['name']}: {color}{s['status']}{RESET} ({s['tools']} tools)")

    # sessions and checkpoints share one snapshot/restore path

    def snapshot(self) -> SessionSnapshot:
        s = self.session
        return SessionSnapshot(s.id, s.created_at, s.updated_at, s.turns, s.messages, s.usage)

    async def restore(self, snap: SessionSnapshot) -> None:
        await agent.close(self.session)
        s = self.session = await agent.start(self.config)
        s.id, s.created_at, s.updated_at, s.turns, s.usage = snap.session_id, snap.created_at, snap.updated_at, snap.turn_count, snap.total_usage
        s.messages = [m for m in snap.messages if m["role"] != "system"]

    async def cmd_save(self, args):
        PersistenceManager().save_session(self.snapshot())
        print(f"{GREEN}Session saved: {self.session.id}{RESET}")

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
        undone = undo.undo(self.session, count)
        if not undone:
            print(f"{YELLOW}Nothing to undo{RESET}")
        for entry in undone:
            print(f"{GREEN}Undone: {entry['description']}{RESET}")
            for path, old in entry["changes"]:
                print(f"  - {'Deleted' if old is None else 'Restored'}: {path}")

    async def cmd_history(self, args):
        history = undo.history(self.session)
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
