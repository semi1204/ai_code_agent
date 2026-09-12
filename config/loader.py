import sys
import tomllib
from pathlib import Path

from config.config import Config, from_dict

DATA_DIR = Path.home() / ".ai-agent"  # config.toml, user_memory.json, tools/, sessions/, checkpoints/


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"warning: skipping config {path}: {e}", file=sys.stderr)
        return {}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(cwd: Path | None = None) -> Config:
    cwd = Path(cwd or Path.cwd())
    d = _merge(_load_toml(DATA_DIR / "config.toml"), _load_toml(cwd / ".ai-agent" / "config.toml"))
    d.setdefault("cwd", cwd)
    agents_md = cwd / "AGENTS.md"
    if "developer_instructions" not in d and agents_md.is_file():
        d["developer_instructions"] = agents_md.read_text(encoding="utf-8")
    try:
        return from_dict(d)
    except (TypeError, ValueError) as e:
        raise SystemExit(f"Invalid configuration: {e}")
