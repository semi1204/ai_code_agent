"""Plugin tools: every *.py in <cwd>/.ai-agent/tools and ~/.ai-agent/tools registers itself with @tool."""

import importlib.util
import sys

from config.loader import DATA_DIR


def load_plugins(config) -> None:
    for directory in (config.cwd / ".ai-agent" / "tools", DATA_DIR / "tools"):
        for path in sorted(directory.glob("*.py")) if directory.is_dir() else []:
            if path.name.startswith("__"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                print(f"warning: plugin {path}: {e}", file=sys.stderr)
