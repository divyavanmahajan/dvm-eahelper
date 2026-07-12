"""
config — user configuration profile for eahelper.

Stored as TOML at ~/.eahelper/config.toml (read with stdlib tomllib, written
with a minimal hand-rolled emitter since values here are only strings/ints/bools).

Resolution order for every setting, implemented by get_setting():
  1. CLI flag (explicit value passed by the caller)
  2. Environment variable
  3. config.toml
  4. Interactive prompt (only if stdin is a TTY) — the answer is saved back to
     config.toml so the user is only asked once.
  5. Built-in default

No secrets (passwords, API keys) are stored here — those stay in env vars / .env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - py3.11 has tomllib in stdlib
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULTS: dict[str, dict[str, Any]] = {
    "leanix": {
        "workspace_url": "",
        "proxy_port": 8765,
    },
    "browser": {
        "browser": "",
        "cdp_port": 19222,
        "keep_open": False,
    },
    "graph": {
        "db": "",
        "kuzu_path": "",
        "mcp_read_only": False,
    },
    "neo4j": {
        "uri": "",
    },
}


def config_dir() -> Path:
    return Path.home() / ".eahelper"


def config_path() -> Path:
    return config_dir() / "config.toml"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f'"{_toml_escape(str(value))}"'


def _dump_toml(data: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for section in sorted(data):
        values = data[section]
        if not values:
            continue
        lines.append(f"[{section}]")
        for key in sorted(values):
            lines.append(f"{key} = {_toml_value(values[key])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_config() -> dict[str, dict[str, Any]]:
    """Read config.toml, returning {} if it does not exist or is unreadable."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def save_config(data: dict[str, dict[str, Any]]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(data), encoding="utf-8")


def _split_key(dotted_key: str) -> tuple[str, str]:
    if "." not in dotted_key:
        raise ValueError(f"Expected 'section.key', got {dotted_key!r}")
    section, key = dotted_key.split(".", 1)
    return section, key


def get_config_value(dotted_key: str) -> Any:
    section, key = _split_key(dotted_key)
    data = load_config()
    return data.get(section, {}).get(key)


def set_config_value(dotted_key: str, value: Any) -> None:
    section, key = _split_key(dotted_key)
    data = load_config()
    data.setdefault(section, {})[key] = value
    save_config(data)


def unset_config_value(dotted_key: str) -> None:
    section, key = _split_key(dotted_key)
    data = load_config()
    if section in data and key in data[section]:
        del data[section][key]
        if not data[section]:
            del data[section]
        save_config(data)


def effective_config() -> dict[str, dict[str, Any]]:
    """Merge built-in defaults with what's on disk, for display purposes."""
    merged: dict[str, dict[str, Any]] = {s: dict(v) for s, v in DEFAULTS.items()}
    for section, values in load_config().items():
        merged.setdefault(section, {}).update(values)
    return merged


def _coerce_like(default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    if isinstance(default, int):
        try:
            return int(raw.strip())
        except ValueError:
            return raw.strip()
    return raw.strip()


def get_setting(
    section: str,
    key: str,
    *,
    cli_value: Any = None,
    env_var: str | None = None,
    prompt: str | None = None,
    default: Any = None,
    save: bool = True,
) -> Any:
    """
    Resolve a single setting following the standard precedence:
    CLI flag > env var > config.toml > interactive prompt (TTY only) > default.

    When resolved via interactive prompt, the value is saved back to config.toml
    unless save=False.
    """
    if cli_value not in (None, ""):
        return cli_value

    if env_var:
        env_val = os.environ.get(env_var)
        if env_val not in (None, ""):
            return env_val

    on_disk = load_config().get(section, {}).get(key)
    if on_disk not in (None, ""):
        return on_disk

    builtin_default = DEFAULTS.get(section, {}).get(key, default)

    if prompt is not None and sys.stdin.isatty():
        try:
            raw = input(f"{prompt} [{builtin_default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ""
        value = _coerce_like(builtin_default if builtin_default != "" else default, raw) if raw else builtin_default
        if raw and save:
            set_config_value(f"{section}.{key}", value)
        return value

    return builtin_default
