"""resolve_backend — decide which GraphBackend implementation to use.

Precedence (via dvm_eahelper.config.get_setting):
  1. --db flag (explicit CLI choice)
  2. EAHELPER_DB environment variable
  3. config.toml [graph].db
  4. Interactive prompt (only when stdin is a TTY) — default "kuzu" on empty input;
     the choice is saved to config.toml so later runs don't prompt again.
  5. "kuzu" (final fallback for non-interactive/unattended runs)
"""

from __future__ import annotations

import argparse
import sys

from dvm_eahelper.config import get_setting
from dvm_eahelper.graph.base import GraphBackend

_VALID_BACKENDS = ("kuzu", "neo4j")


def _build_backend(name: str, db_path: str | None = None, read_only: bool = False) -> GraphBackend:
    if name == "neo4j":
        from dvm_eahelper.graph.neo4j_backend import Neo4jBackend

        return Neo4jBackend()

    from dvm_eahelper.graph.kuzu_backend import KuzuBackend

    resolved_path = db_path or get_setting(
        "graph", "kuzu_path",
        env_var="EAHELPER_KUZU_PATH",
        default="",
    )
    return KuzuBackend(db_path=resolved_path or None, read_only=read_only)


def resolve_backend_name(cli_db: str | None = None) -> str:
    """Resolve just the backend name ("kuzu"/"neo4j") using standard precedence."""
    choice = get_setting(
        "graph", "db",
        cli_value=cli_db,
        env_var="EAHELPER_DB",
        prompt="Which graph database? kuzu/neo4j",
        default="kuzu",
    )
    choice = (choice or "kuzu").lower()
    if choice not in _VALID_BACKENDS:
        print(f"ERROR: unknown graph database {choice!r}; expected one of {_VALID_BACKENDS}", file=sys.stderr)
        sys.exit(1)
    return choice


def resolve_backend(args: argparse.Namespace) -> GraphBackend:
    """Resolve and instantiate the GraphBackend to use for this run."""
    choice = resolve_backend_name(getattr(args, "db", None))
    db_path = getattr(args, "db_path", None)
    return _build_backend(choice, db_path=db_path)


def resolve_backend_from_config(read_only: bool = False) -> GraphBackend:
    """Resolve and instantiate the GraphBackend purely from config/env (no argparse args)."""
    choice = resolve_backend_name(None)
    return _build_backend(choice, read_only=read_only)
