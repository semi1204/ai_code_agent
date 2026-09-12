"""Importing a builtin module registers its @tool functions."""

from tools.builtin import (  # noqa: F401  (registration side effect)
    edit_file, glob, grep, list_dir, memory, read_file, shell, todo, web_fetch, web_search, write_file,
)


def get_all_builtin_tools() -> list[type]:  # legacy class-based tools: none left
    return []
