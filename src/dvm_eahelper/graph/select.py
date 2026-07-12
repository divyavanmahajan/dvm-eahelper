"""resolve_backend — decide which GraphBackend implementation to use.

Precedence:
  1. --db flag (explicit CLI choice)
  2. EAHELPER_DB environment variable
  3. Interactive prompt (only when stdin is a TTY) — default "kuzu" on empty input
  4. "kuzu" (final fallback for non-interactive/unattended runs)
"""

from __future__ import annotations

import argparse
import os
import sys

from dvm_eahelper.graph.base import GraphBackend

_VALID_BACKENDS = ("kuzu", "neo4j")


def _build_backend(name: str, args: argparse.Namespace) -> GraphBackend:
    if name == "neo4j":
        from dvm_eahelper.graph.neo4j_backend import Neo4jBackend

        return Neo4jBackend()

    from dvm_eahelper.graph.kuzu_backend import KuzuBackend

    db_path = getattr(args, "db_path", None) or os.environ.get("EAHELPER_KUZU_PATH")
    return KuzuBackend(db_path=db_path)


def resolve_backend(args: argparse.Namespace) -> GraphBackend:
    """Resolve and instantiate the GraphBackend to use for this run."""
    choice = getattr(args, "db", None)

    if not choice:
        choice = os.environ.get("EAHELPER_DB")

    if not choice and sys.stdin.isatty():
        answer = input("Which graph database? [kuzu]/neo4j: ").strip().lower()
        choice = answer or "kuzu"

    if not choice:
        choice = "kuzu"

    if choice not in _VALID_BACKENDS:
        print(f"ERROR: unknown graph database {choice!r}; expected one of {_VALID_BACKENDS}", file=sys.stderr)
        sys.exit(1)

    return _build_backend(choice, args)
