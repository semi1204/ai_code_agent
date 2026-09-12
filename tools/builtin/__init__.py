"""Importing a builtin module registers its @tool functions."""

from tools.builtin import glob, list_dir, read_file  # noqa: F401  (registration side effect)
from tools.builtin.edit_file import EditTool
from tools.builtin.grep import GrepTool
from tools.builtin.memory import MemoryTool
from tools.builtin.shell import ShellTool
from tools.builtin.todo import TodosTool
from tools.builtin.web_fetch import WebFetchTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.write_file import WriteFileTool


def get_all_builtin_tools() -> list[type]:  # legacy class-based tools still to be converted
    return [WriteFileTool, EditTool, ShellTool, GrepTool, WebSearchTool, WebFetchTool, TodosTool, MemoryTool]
