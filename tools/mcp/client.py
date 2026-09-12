"""Minimal MCP client: stdio (newline-delimited JSON-RPC) or streamable HTTP."""

import asyncio
import itertools
import json
import os
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path
from urllib.request import Request, urlopen

from config.config import MCPServerConfig

PROTOCOL_VERSION = "2025-03-26"


class MCPClient:
    def __init__(self, name: str, config: MCPServerConfig, cwd: Path, env: dict | None = None) -> None:
        self.name = name
        self.env = dict(os.environ) if env is None else env  # base environment for a stdio server
        self.config = config
        self.cwd = cwd
        self.status = "disconnected"  # disconnected | connected | error
        self.tools: list[dict] = []  # {"name", "description", "input_schema"}
        self._proc = None
        self._session_id = None
        self._ids = itertools.count(1)

    async def connect(self) -> None:
        try:
            if self.config.command:
                self._proc = await asyncio.create_subprocess_exec(
                    self.config.command,
                    *self.config.args,
                    stdin=PIPE,
                    stdout=PIPE,
                    stderr=DEVNULL,
                    env={**self.env, **self.config.env},
                    cwd=self.config.cwd or self.cwd,
                )
            await self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ai-agent", "version": "0"},
                },
            )
            await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            listed = await self._request("tools/list")
            self.tools = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("inputSchema", {})}
                for t in listed.get("tools", [])
            ]
            self.status = "connected"
        except Exception:
            self.status = "error"
            raise

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(c.get("text", json.dumps(c)) for c in result.get("content", []))
        return f"error: {text}" if result.get("isError") else text

    async def disconnect(self) -> None:
        if self._proc:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), 3)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None
        self.tools = []
        self.status = "disconnected"

    # --- JSON-RPC plumbing ---

    async def _request(self, method: str, params: dict | None = None) -> dict:
        msg_id = next(self._ids)
        reply = await self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}, msg_id)
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error'].get('message', reply['error'])}")
        return reply.get("result", {})

    async def _send(self, msg: dict, wait_for: int | None = None) -> dict | None:
        """Send one message; if wait_for is an id, return the reply with that id."""
        if self._proc:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode())
            await self._proc.stdin.drain()
            while wait_for is not None:
                line = await self._proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"MCP server '{self.name}' exited")
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue  # non-JSON noise on stdout
                if reply.get("id") == wait_for:
                    return reply
            return None

        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = Request(self.config.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        resp = await asyncio.to_thread(urlopen, req, timeout=self.config.startup_timeout_sec)
        with resp:
            self._session_id = resp.headers.get("Mcp-Session-Id", self._session_id)
            body = (await asyncio.to_thread(resp.read)).decode("utf-8", "replace")
        if wait_for is None:
            return None
        if resp.headers.get_content_type() == "text/event-stream":
            for line in body.splitlines():
                if line.startswith("data:"):
                    reply = json.loads(line[5:])
                    if reply.get("id") == wait_for:
                        return reply
            raise RuntimeError(f"MCP server '{self.name}': no response in event stream")
        return json.loads(body)
