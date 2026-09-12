from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any



@dataclass
class ToolDependency:
    tool_name: str
    call_id: str
    arguments: dict[str, Any]
    reads: set[Path] = field(default_factory=set)
    writes: set[Path] = field(default_factory=set)
    is_shell: bool = False


class DependencyAnalyzer:
    def analyze_tool_call(
        self,
        name: str,
        call_id: str,
        args: dict[str, Any],
        cwd: Path,
    ) -> ToolDependency:
        reads: set[Path] = set()
        writes: set[Path] = set()
        is_shell = False

        path_arg = args.get("path")
        if path_arg:
            resolved = self._resolve_path(path_arg, cwd)

            if name == "read_file":
                reads.add(resolved)
            elif name in ("write_file", "edit"):
                reads.add(resolved)
                writes.add(resolved)
            elif name in ("glob", "grep", "list_dir"):
                reads.add(resolved)

        if name == "shell":
            is_shell = True

        return ToolDependency(
            tool_name=name,
            call_id=call_id,
            arguments=args,
            reads=reads,
            writes=writes,
            is_shell=is_shell,
        )

    def _resolve_path(self, path_str: str, cwd: Path) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p.resolve()
        return (cwd / p).resolve()

    def has_conflict(self, a: ToolDependency, b: ToolDependency) -> bool:
        if a.is_shell or b.is_shell:
            return True

        if a.writes & b.writes:
            return True

        if a.reads & b.writes or a.writes & b.reads:
            return True

        return False

    def group_parallel_calls(
        self,
        tool_calls: list[tuple[str, str, dict[str, Any]]],
        cwd: Path,
    ) -> list[list[tuple[str, str, dict[str, Any]]]]:
        if not tool_calls:
            return []

        dependencies = [
            self.analyze_tool_call(name, call_id, args, cwd)
            for name, call_id, args in tool_calls
        ]

        batches: list[list[int]] = []
        assigned: set[int] = set()

        while len(assigned) < len(tool_calls):
            current_batch: list[int] = []
            batch_deps: list[ToolDependency] = []

            for i, dep in enumerate(dependencies):
                if i in assigned:
                    continue

                can_add = True
                for existing_dep in batch_deps:
                    if self.has_conflict(dep, existing_dep):
                        can_add = False
                        break

                if can_add:
                    current_batch.append(i)
                    batch_deps.append(dep)
                    assigned.add(i)

            if current_batch:
                batches.append(current_batch)

        return [[tool_calls[i] for i in batch] for batch in batches]
