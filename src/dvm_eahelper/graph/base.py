"""
GraphBackend — abstract interface between the LeanIX loader and a graph database.

Both the Neo4j backend (dvm_eagraph.load_leanix, ported from an existing schemaless
Cypher loader) and the KuzuDB backend (embedded, statically-typed schema) implement
this interface so that loader.py and seed.py can drive either database identically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType


class GraphBackend(ABC):
    """Common operations the LeanIX loader needs from a graph database."""

    def __enter__(self) -> GraphBackend:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @abstractmethod
    def connect(self) -> None:
        """Open the connection/database. Must be called before any other method."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection/database and release resources."""

    @abstractmethod
    def ensure_schema(
        self,
        node_labels: list[str],
        relationship_types: list[tuple[str, str, str]] | None = None,
    ) -> None:
        """Ensure node/relationship schema exists for *node_labels*.

        *relationship_types* is an optional list of (rel_type, from_label, to_label)
        triples used by backends (e.g. Kuzu) that require rel tables to be declared
        with explicit endpoint labels before data can be inserted. Backends that do
        not need explicit relationship schema (e.g. Neo4j) may ignore it.
        """

    @abstractmethod
    def upsert_nodes(self, label: str, records: list[dict]) -> int:
        """Batch-upsert *records* as nodes with the given *label*, keyed on ``id``.

        Records without a truthy ``id`` key are skipped. Returns the number of
        records upserted.
        """

    @abstractmethod
    def upsert_relationships(self, rows: list[dict], rel_map: dict[str, str]) -> int:
        """Batch-upsert relationships described by *rows*.

        Each row has ``source_id``, ``relation`` (a LeanIX relation field name),
        and ``target_id`` keys. *rel_map* maps LeanIX relation field names to
        graph relationship type names; unmapped relation names fall back to the
        caller's naming convention. Returns the total number of relationships
        upserted.
        """

    @abstractmethod
    def query_stats(self) -> dict[str, int]:
        """Return {label: node_count, ..., '_relationships': relationship_count}."""

    @abstractmethod
    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        """Run a backend-native query and return a list of row dicts."""

    @abstractmethod
    def clear(self) -> None:
        """Delete all nodes and relationships in the database."""
