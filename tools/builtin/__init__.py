"""Importing a builtin module registers its @tool functions."""

from tools.builtin import edit_file, glob, grep, list_dir, memory, read_file, shell, todo, write_file  # noqa: F401  (registration side effect)
from tools.builtin.web_fetch import WebFetchTool
from tools.builtin.web_search import WebSearchTool


def get_all_builtin_tools() -> list[type]:  # legacy class-based tools still to be converted
    return [WebSearchTool, WebFetchTool]
