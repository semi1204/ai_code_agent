# AI Coding Agent

A terminal-based AI assistant for pair programming. It can read, write, and execute code in your project.

> I saw [opencode](https://github.com/opencode-ai/opencode) and thought it looked cool, so I built this to learn how AI coding agents work under the hood.

Started from [RivaanRanawat/ai-coding-agent](https://github.com/RivaanRanawat/ai-coding-agent), then rewritten in the style of
[geohot/nanocode](https://github.com/geohot/nanocode): **zero dependencies** (standard library only), tools are plain
functions, state lives in one dataclass, errors are strings. The multi-file layout is kept so each concern stays readable.

## Getting Started

Python 3.11+ and an OpenAI-compatible chat completions endpoint. Nothing to install.

```bash
export API_KEY=your_key                      # or OPENAI_API_KEY
export BASE_URL=https://openrouter.ai/api/v1 # or OPENAI_API_BASE

python main.py                    # interactive mode
python main.py "do something"     # single prompt
python main.py --cwd path "..."   # run against another directory
```

## How It Works

```
main.py             REPL + slash commands; prints events with ANSI colours (ui/tui.py)
  └─ agent/agent.py run(s, message): async generator of
                      ("text", delta) | ("tool_start", name, args) | ("tool_end", name, output) | ("error", msg)
       ├─ client/llm_client.py   chat completions over urllib, streamed (SSE), retries on 429/5xx
       ├─ tools/registry.py      names/schemas/invoke: approval → hooks → run_tool
       │    ├─ tools/base.py     TOOLS registry, @tool decorator, compact schema → JSON schema
       │    ├─ tools/builtin/    read_file write_file edit shell grep glob list_dir todos memory web_fetch web_search
       │    ├─ tools/subagents.py subagent_* tools: a restricted agent on a copy of the session
       │    ├─ tools/mcp/        MCP servers (stdio JSON-RPC or streamable HTTP) registered as <server>__<tool>
       │    └─ tools/discovery.py plugins from .ai-agent/tools/*.py
       ├─ context/              manager (messages, usage, pruning), compaction (LLM summary), loop_detector
       ├─ safety/approval.py    approve / reject / ask, by tool kind, command patterns and paths
       ├─ hooks/hook_system.py  shell commands on before/after agent/tool and on_error
       ├─ agent/undo.py         file snapshots per turn for /undo
       └─ agent/persistence.py  sessions and checkpoints as JSON under ~/.ai-agent/
```

All per-conversation state is the `Session` dataclass in `agent/session.py` (config, messages, usage, undo, todos,
MCP clients, loop-detection history). Every module is a set of functions taking that session.

### The agent loop

```
run(s, message):
    compact if the context is over 80% of context_window, then append the user message
    repeat up to max_turns:
        stream one completion (text deltas + tool calls + usage)
        no tool calls -> done
        run the tool calls in order; consecutive read-only calls run concurrently
        commit undo snapshots, check for loops, prune old tool outputs
```

### Running a tool

```
registry.invoke(s, name, args)
    -> approval.check()      approve / reject / ask (y/N in the terminal)
    -> hooks before_tool
    -> run_tool()            missing required params or an exception -> "error: ..."
    -> hooks after_tool
```

## Tools

| Tool | What it does |
|------|--------------|
| `read_file` | Read a text file with line numbers (offset/limit) |
| `write_file` | Create or overwrite a file |
| `edit` | Exact-string replace; unique unless `replace_all`; empty `old_string` creates the file |
| `shell` | Run a command, output streamed live |
| `list_dir` | List a directory |
| `glob` | Find files by pattern |
| `grep` | Regex search, `file:line:text` |
| `web_search` | DuckDuckGo results |
| `web_fetch` | Fetch a URL as text |
| `memory` | Notes that persist across sessions (`~/.ai-agent/user_memory.json`) |
| `todos` | Task list for the session |
| `subagent_codebase_investigator`, `subagent_code_reviewer` | Read-only sub-agents |

## Configuration

`~/.ai-agent/config.toml`, overridden by `<cwd>/.ai-agent/config.toml`. Every key is optional:

```toml
approval = "on-request"    # on-request | on-failure | auto | auto-edit | never | yolo
max_turns = 100
parallel_tools = true
max_parallel_tools = 5
hooks_enabled = false

[model]
name = "anthropic/claude-sonnet-4"
temperature = 1
context_window = 200000

[shell_environment]
exclude_patterns = ["*KEY*", "*TOKEN*", "*SECRET*"]   # env vars hidden from shell commands and hooks

[[hooks]]
name = "log"
trigger = "before_tool"       # before_agent | after_agent | before_tool | after_tool | on_error
command = "python3 ./scripts/test_tool.py"   # or script = "..." for an inline bash script

[mcp_servers.filesystem]
command = "npx"               # stdio server
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
# url = "http://..."          # or a streamable-HTTP server
```

An `AGENTS.md` in the working directory is added to the system prompt as project instructions.

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/exit`, `/quit`, `/q` | Quit |
| `/clear`, `/c` | Clear the conversation |
| `/config` | Show current configuration |
| `/model <name>` | Change the model |
| `/approval <mode>` | Change the approval policy |
| `/stats` | Session statistics |
| `/tools` | List available tools |
| `/mcp` | MCP server status |
| `/save`, `/sessions`, `/resume <id>` | Save, list and resume sessions |
| `/checkpoint`, `/checkpoints`, `/restore <id>` | Same for checkpoints |
| `/undo [N]` | Undo the last N turns of file changes |
| `/history` | Undo history |

## Adding a Tool

A tool is a function taking the arguments dict and the session, returning a string (`"error: ..."` on failure).
The schema is the compact form `{"name": "type"}`; a trailing `?` marks an optional parameter.

```python
from tools.base import tool

@tool("word_count", "Count the words in a file", {"path": "string", "unique": "boolean?"})
def word_count(args, s):
    words = open(args["path"]).read().split()
    return str(len(set(words)) if args.get("unique") else len(words))
```

Put it in `tools/builtin/` (and import it from `tools/builtin/__init__.py`), or drop the file into
`.ai-agent/tools/` of a project or `~/.ai-agent/tools/` to load it as a plugin. Use `kind="write"`, `"shell"`,
`"network"` or `"memory"` for tools with side effects so the approval policy applies to them.

## License

MIT
