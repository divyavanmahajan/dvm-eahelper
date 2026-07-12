"""
mcp_config — print/install MCP configuration snippets for Claude Code (.mcp.json)
and VS Code / GitHub Copilot (.vscode/mcp.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dvm_eahelper.config import get_setting


def _proxy_port() -> int:
    return int(get_setting("leanix", "proxy_port", default=8765))


def claude_code_config() -> dict:
    port = _proxy_port()
    return {
        "mcpServers": {
            "eahelper-http": {
                "type": "http",
                "url": f"http://localhost:{port}/mcp",
            },
            "eahelper-stdio": {
                "command": "eahelper",
                "args": ["mcp"],
            },
        }
    }


def vscode_config() -> dict:
    port = _proxy_port()
    return {
        "servers": {
            "eahelper-http": {
                "type": "http",
                "url": f"http://localhost:{port}/mcp",
            },
            "eahelper-stdio": {
                "type": "stdio",
                "command": "eahelper",
                "args": ["mcp"],
            },
        }
    }


def _merge_json(existing: dict, new: dict, top_key: str) -> dict:
    merged = dict(existing)
    merged.setdefault(top_key, {})
    merged[top_key].update(new.get(top_key, {}))
    return merged


def _write_merged(path: Path, new_config: dict, top_key: str) -> None:
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    merged = _merge_json(existing, new_config, top_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def print_config() -> None:
    print("Claude Code (.mcp.json):")
    print(json.dumps(claude_code_config(), indent=2))
    print("\nVS Code / GitHub Copilot (.vscode/mcp.json):")
    print(json.dumps(vscode_config(), indent=2))


def install_config(cwd: Path | None = None) -> None:
    base = cwd or Path.cwd()
    claude_path = base / ".mcp.json"
    vscode_path = base / ".vscode" / "mcp.json"

    _write_merged(claude_path, claude_code_config(), "mcpServers")
    print(f"  Wrote/merged {claude_path}")

    _write_merged(vscode_path, vscode_config(), "servers")
    print(f"  Wrote/merged {vscode_path}")


def run_mcp_config(install: bool) -> None:
    if install:
        install_config()
    else:
        print_config()
        print("\nRun with --install to write these into the current directory.", file=sys.stderr)
