"""Importing a builtin module registers its @tool functions."""

from tools.builtin import edit_file, glob, list_dir, read_file, write_file  # noqa: F401  (registration side effect)
from tools.builtin.grep import GrepTool
from tools.builtin.memory import MemoryTool
from tools.builtin.shell import ShellTool
from tools.builtin.todo import TodosTool
from tools.builtin.web_fetch import WebFetchTool
from tools.builtin.web_search import WebSearchTool


def get_all_builtin_tools() -> list[type]:  # legacy class-based tools still to be converted
    return [ShellTool, GrepTool, WebSearchTool, WebFetchTool, TodosTool, MemoryTool]
