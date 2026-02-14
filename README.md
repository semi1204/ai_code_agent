# AI Coding Agent

A terminal-based AI assistant for pair programming. It can read, write, and execute code in your project.

> I saw [opencode](https://github.com/opencode-ai/opencode) and thought it looked cool, so I built this to learn how AI coding agents work under the hood.

## Getting Started

```bash
export API_KEY=your_openrouter_key
export BASE_URL=https://openrouter.ai/api/v1

python main.py                    # interactive mode
python main.py "do something"     # single prompt
```

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                         main.py (CLI)                        │
│            Entry point, command handling, user I/O           │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                      agent/agent.py                          │
│         Core agentic loop - orchestrates everything          │
│    • Streams LLM responses                                   │
│    • Dispatches tool calls (sequential or parallel)          │
│    • Manages turn count and loop detection                   │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                     agent/session.py                         │
│              Per-conversation state container                │
│    • LLM client, tool registry, context manager              │
│    • Undo manager, loop detector, hook system                │
└──────────────────────────┬───────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ client/       │  │ context/      │  │ tools/        │
│ LLM API       │  │ History &     │  │ File, Shell,  │
│ (OpenRouter)  │  │ Compression   │  │ Web, MCP...   │
└───────────────┘  └───────────────┘  └───────────────┘
```

## Directory Structure

### `agent/`
The brain of the system.

- **agent.py** - Main loop. Calls LLM, gets response, executes tools, repeats until done. Handles parallel execution when multiple independent tools are called.
- **session.py** - Holds all the state for one conversation: client, tools, context, undo history.
- **undo.py** - Tracks file changes so users can `/undo` mistakes.
- **events.py** - Event types for streaming UI updates (text deltas, tool starts/completions).
- **persistence.py** - Save/load sessions to disk.

### `client/`
Talks to the LLM.

- **llm_client.py** - Async OpenAI-compatible client with streaming. Handles retries for rate limits.
- **response.py** - Data classes for streaming events, tool calls, token usage.

### `context/`
Manages conversation history.

- **manager.py** - Stores messages, generates system prompts, tracks token usage.
- **compaction.py** - When context gets too long, summarizes older messages to free up space.
- **loop_detector.py** - Detects when the agent is stuck repeating the same action.

### `tools/`
Everything the agent can do.

- **base.py** - Base `Tool` class. Every tool inherits from this. Defines `execute()`, `get_confirmation()`, etc.
- **registry.py** - Central registry. Tools register here, agent looks them up by name.
- **parallel.py** - Dependency analyzer for parallel execution. Figures out which tools can run at the same time.

#### `tools/builtin/`
Built-in tools:

| Tool | What it does |
|------|--------------|
| `read_file.py` | Read file contents |
| `write_file.py` | Create or overwrite files |
| `edit_file.py` | Surgical find-and-replace edits |
| `shell.py` | Run shell commands |
| `list_dir.py` | List directory contents |
| `glob.py` | Find files by pattern |
| `grep.py` | Search file contents |
| `web_search.py` | Search the web |
| `web_fetch.py` | Fetch a URL |
| `memory.py` | Persistent key-value storage |
| `todos.py` | Task list management |

#### `tools/mcp/`
Model Context Protocol integration.

- **mcp_manager.py** - Starts and manages MCP server processes.
- **mcp_client.py** - Communicates with MCP servers via stdio or HTTP.
- **mcp_tool.py** - Wraps MCP tools so they look like regular tools.

#### `tools/subagents.py`
Spawn mini-agents for specific tasks (code review, codebase investigation).

### `config/`
Configuration loading.

- **config.py** - Pydantic models for all config options.
- **loader.py** - Loads from `~/.config/ai-agent/config.toml` and `.ai-agent/config.toml`.

### `safety/`
Keeps things safe.

- **approval.py** - Decides what needs user confirmation. Blocks dangerous commands like `rm -rf /`.

### `hooks/`
Extensibility.

- **hook_system.py** - Run scripts before/after agent runs or tool calls.

### `prompts/`
System prompt generation.

- **system.py** - Builds the system prompt with environment info, tool descriptions, user instructions.

### `ui/`
Terminal interface.

- **tui.py** - Rich-based terminal UI. Formats tool calls, diffs, streaming text.

## Key Flows

### 1. User sends a message

```
User input
    → agent.run(message)
    → context_manager.add_user_message()
    → _agentic_loop() starts
```

### 2. Agentic loop

```
while turns < max_turns:
    1. Check if context needs compression
    2. Call LLM with messages + tool schemas
    3. Stream response text to UI
    4. If tool calls returned:
       - Group independent calls into parallel batches
       - Execute each batch (parallel or sequential)
       - Record changes for undo
       - Add results to context
       - Check for loops
    5. If no tool calls, we're done
```

### 3. Tool execution

```
tool_registry.invoke(name, params)
    → tool.validate_params()
    → approval_manager.check_approval()
    → hook_system.trigger_before_tool()
    → tool.execute()
    → undo_manager.record_change() (if file modified)
    → hook_system.trigger_after_tool()
```

### 4. Parallel execution

When the LLM requests multiple tools at once:

```
DependencyAnalyzer.group_parallel_calls()
    → Analyze each tool's file reads/writes
    → Group non-conflicting tools together
    → Shell commands always run alone

For each batch:
    → asyncio.gather(*[invoke(tool) for tool in batch])
```

## Configuration

Create `.ai-agent/config.toml` in your project:

```toml
[model]
name = "anthropic/claude-3.5-sonnet"
temperature = 0.7
context_window = 128000

[agent]
max_turns = 100
approval = "on-request"    # on-request | auto | yolo
parallel_tools = true
max_parallel_tools = 5

[mcp_servers.example]
command = "npx"
args = ["-y", "@anthropic/mcp-server"]
```

Or create `AGENT.md` in your project root for custom instructions.

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/undo [N]` | Undo last N file changes |
| `/history` | Show undo history |
| `/config` | Show current config |
| `/tools` | List available tools |
| `/mcp` | MCP server status |
| `/stats` | Session statistics |
| `/save` | Save session |
| `/resume <id>` | Resume saved session |
| `/exit` | Quit |

## Adding a New Tool

1. Create a file in `tools/builtin/`:

```python
from tools.base import Tool, ToolInvocation, ToolResult, ToolKind
from pydantic import BaseModel, Field

class MyToolParams(BaseModel):
    arg1: str = Field(..., description="What this arg does")

class MyTool(Tool):
    name = "my_tool"
    description = "What this tool does"
    kind = ToolKind.READ  # or WRITE, SHELL, NETWORK
    schema = MyToolParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = MyToolParams(**invocation.params)
        # do stuff
        return ToolResult.success_result("output")
```

2. Register it in `tools/builtin/__init__.py`:

```python
def get_all_builtin_tools():
    return [
        # ... existing tools
        MyTool,
    ]
```

## Requirements

- Python 3.11+
- API key from OpenRouter or compatible provider

## License

MIT
