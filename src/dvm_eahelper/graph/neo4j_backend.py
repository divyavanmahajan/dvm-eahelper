"""Neo4jBackend — GraphBackend implementation backed by the neo4j Python driver."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from dvm_eahelper.graph.base import GraphBackend

load_dotenv()


def _is_primitive(v) -> bool:
    if isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, list):
        return all(isinstance(i, (str, int, float, bool)) for i in v)
    return False


def _coerce_value(v):
    """Coerce a value to a Neo4j-compatible type.

    Primitives and lists of primitives are returned as-is. Objects (dicts) and
    lists of objects are serialised to a JSON string so that structured LeanIX
    fields like ``externalId`` are preserved rather than dropped. None is
    returned for values that cannot be meaningfully stored.
    """
    if v is None:
        return None
    if _is_primitive(v):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return None


def clean_props(record: dict) -> dict:
    """Convert a record to a dict of Neo4j-compatible property values."""
    result = {}
    for k, v in record.items():
        coerced = _coerce_value(v)
        if coerced is not None:
            result[k] = coerced
    return result


def _merge_nodes(tx, label: str, rows: list[dict]) -> None:
    tx.run(
        f"""
        UNWIND $rows AS row
        MERGE (n:{label} {{id: row.id}})
        SET n += row
        """,
        rows=rows,
    )


def _merge_relationships(tx, rel_type: str, rows: list[dict]) -> None:
    tx.run(
        f"""
        UNWIND $rows AS row
        MATCH (src {{id: row.source_id}})
        MATCH (tgt {{id: row.target_id}})
        MERGE (src)-[:{rel_type}]->(tgt)
        """,
        rows=rows,
    )


class Neo4jBackend(GraphBackend):
    """Loads LeanIX factsheets/relationships into Neo4j using MERGE semantics."""

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.uri = uri or os.environ["NEO4J_URI"]
        self.username = username or os.environ["NEO4J_USERNAME"]
        self.password = password or os.environ["NEO4J_PASSWORD"]
        self.driver = None

    def connect(self) -> None:
        self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
        self.driver.verify_connectivity()

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def ensure_schema(
        self,
        node_labels: list[str],
        relationship_types: list[tuple[str, str, str]] | None = None,
    ) -> None:
        with self.driver.session() as session:
            for label in node_labels:
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    def upsert_nodes(self, label: str, records: list[dict]) -> int:
        rows = [clean_props(r) for r in records if r.get("id")]
        if not rows:
            return 0
        with self.driver.session() as session:
            session.execute_write(_merge_nodes, label, rows)
        print(f"[neo4j] Merged {len(rows)} {label} nodes.")
        return len(rows)

    def upsert_relationships(self, rows: list[dict], rel_map: dict[str, str]) -> int:
        from dvm_eahelper.graph.loader import rel_name_to_graph_type

        by_rel: dict[str, list[dict]] = {}
        for row in rows:
            lx_rel = row["relation"]
            rel_type = rel_map.get(lx_rel) or rel_name_to_graph_type(lx_rel)
            by_rel.setdefault(rel_type, []).append(row)

        total = 0
        with self.driver.session() as session:
            for rel_type, rel_rows in by_rel.items():
                session.execute_write(_merge_relationships, rel_type, rel_rows)
                print(f"[neo4j] Merged {len(rel_rows)} :{rel_type} relationships.")
                total += len(rel_rows)

        print(f"[neo4j] {total} relationships merged across {len(by_rel)} types.")
        return total

    def query_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        with self.driver.session() as session:
            result = session.run("MATCH (n) UNWIND labels(n) AS lbl RETURN lbl, count(n) AS c ORDER BY lbl")
            for row in result:
                stats[row["lbl"]] = row["c"]
            stats["_relationships"] = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return stats

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def clear(self) -> None:
        with self.driver.session() as session:
            session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))

    def get_schema(self) -> dict:
        node_tables: dict[str, list[str]] = {}
        rel_types: set[str] = set()
        with self.driver.session() as session:
            result = session.run(
                "CALL db.schema.nodeTypeProperties() "
                "YIELD nodeLabels, propertyName "
                "RETURN nodeLabels, collect(DISTINCT propertyName) AS props"
            )
            for row in result:
                for label in row["nodeLabels"]:
                    node_tables.setdefault(label, [])
                    node_tables[label] = sorted(set(node_tables[label]) | set(row["props"] or []))
            rel_result = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
            for row in rel_result:
                rel_types.add(row["relationshipType"])
        return {"node_tables": node_tables, "relationship_types": sorted(rel_types)}
