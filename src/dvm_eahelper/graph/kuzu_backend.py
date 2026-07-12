"""KuzuBackend — GraphBackend implementation backed by embedded KuzuDB.

Kuzu requires an explicit schema: node/rel tables and their columns must be
declared with ``CREATE NODE TABLE`` / ``CREATE REL TABLE`` before any data can
be inserted, and there is no ``SET n += map`` dynamic-property form like
Neo4j's Cypher. To keep this backend a drop-in replacement for the Neo4j one
(which stores arbitrary LeanIX record fields as node properties), every
property is declared as ``STRING`` and node tables are grown on demand via
``ALTER TABLE ... ADD IF NOT EXISTS <col> STRING`` as new property keys are
encountered. Non-primitive values (dicts / lists of objects) are JSON-encoded
before storage, matching the Neo4j backend's ``clean_props`` behaviour.

Relationship tables are named after the graph relationship type (e.g.
``SUPPORTS``). Kuzu rel tables must declare their FROM/TO node-label pairs up
front; since the same relationship type can connect different label pairs
(e.g. both ``Application`` and ``Interface`` can ``SUPPORT`` a
``BusinessCapability``), each new pair is added to the rel table with
``ALTER TABLE ... ADD FROM ... TO ...`` the first time it is seen.
"""

from __future__ import annotations

import json
from pathlib import Path

import kuzu

from dvm_eahelper.graph.base import GraphBackend

DEFAULT_DB_PATH = Path("./eahelper-kuzu-db")


def _is_primitive(v) -> bool:
    if isinstance(v, (str, int, float, bool)):
        return True
    if isinstance(v, list):
        return all(isinstance(i, (str, int, float, bool)) for i in v)
    return False


def _coerce_value(v):
    """Coerce a value to a Kuzu STRING-compatible value (mirrors the Neo4j backend)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list) and _is_primitive(v):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return None


def clean_props(record: dict) -> dict:
    """Convert a record to a dict of Kuzu-compatible (all-STRING) property values."""
    result = {}
    for k, v in record.items():
        if k == "id":
            continue
        coerced = _coerce_value(v)
        if coerced is not None:
            result[k] = coerced
    return result


class KuzuBackend(GraphBackend):
    """Loads LeanIX factsheets/relationships into an embedded KuzuDB database."""

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.read_only = read_only
        self.db: kuzu.Database | None = None
        self.conn: kuzu.Connection | None = None
        self._node_columns: dict[str, set[str]] = {}
        self._rel_pairs: dict[str, set[tuple[str, str]]] = {}

    def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db = kuzu.Database(str(self.db_path), read_only=self.read_only)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Could not open KuzuDB at {self.db_path}: {exc}. "
                "KuzuDB is single-writer/embedded — this usually means another "
                "eahelper process (server, load, or mcp) already has this database "
                "open. Stop it first, or point --db-path at a different directory."
            ) from exc
        self.conn = kuzu.Connection(self.db)
        self._load_existing_schema()

    def close(self) -> None:
        self.conn = None
        self.db = None

    def _load_existing_schema(self) -> None:
        res = self.conn.execute("CALL show_tables() RETURN *")
        tables = []
        while res.has_next():
            row = res.get_next()
            tables.append((row[1], row[2]))

        for name, kind in tables:
            if kind == "NODE":
                info = self.conn.execute(f'CALL TABLE_INFO("{name}") RETURN *')
                cols: set[str] = set()
                while info.has_next():
                    cols.add(info.get_next()[1])
                self._node_columns[name] = cols
            elif kind == "REL":
                info = self.conn.execute(f'CALL SHOW_CONNECTION("{name}") RETURN *')
                pairs: set[tuple[str, str]] = set()
                while info.has_next():
                    row = info.get_next()
                    pairs.add((row[0], row[1]))
                self._rel_pairs[name] = pairs

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #

    def ensure_schema(
        self,
        node_labels: list[str],
        relationship_types: list[tuple[str, str, str]] | None = None,
    ) -> None:
        for label in node_labels:
            self._ensure_node_table(label)

        for rel_type, from_label, to_label in relationship_types or []:
            self._ensure_node_table(from_label)
            self._ensure_node_table(to_label)
            self._ensure_rel_pair(rel_type, from_label, to_label)

    def _ensure_node_table(self, label: str) -> None:
        if label in self._node_columns:
            return
        self.conn.execute(f"CREATE NODE TABLE IF NOT EXISTS {label}(id STRING, PRIMARY KEY(id))")
        self._node_columns[label] = {"id"}

    def _ensure_node_columns(self, label: str, columns: set[str]) -> None:
        self._ensure_node_table(label)
        existing = self._node_columns[label]
        missing = columns - existing
        for col in sorted(missing):
            self.conn.execute(f"ALTER TABLE {label} ADD IF NOT EXISTS {col} STRING")
            existing.add(col)

    def _ensure_rel_pair(self, rel_type: str, from_label: str, to_label: str) -> None:
        pairs = self._rel_pairs.get(rel_type)
        if pairs is None:
            self.conn.execute(f"CREATE REL TABLE IF NOT EXISTS {rel_type}(FROM {from_label} TO {to_label})")
            self._rel_pairs[rel_type] = {(from_label, to_label)}
            return
        if (from_label, to_label) not in pairs:
            self.conn.execute(f"ALTER TABLE {rel_type} ADD FROM {from_label} TO {to_label}")
            pairs.add((from_label, to_label))

    # ------------------------------------------------------------------ #
    # Node / relationship upserts
    # ------------------------------------------------------------------ #

    def upsert_nodes(self, label: str, records: list[dict]) -> int:
        rows = []
        for r in records:
            rid = r.get("id")
            if not rid:
                continue
            props = clean_props(r)
            rows.append({"id": str(rid), **props})
        if not rows:
            return 0

        all_cols: set[str] = set()
        for row in rows:
            all_cols.update(row.keys())
        all_cols.discard("id")
        self._ensure_node_columns(label, all_cols)

        for row in rows:
            for col in all_cols:
                row.setdefault(col, None)

        set_clause = ", ".join(f"n.{c} = row.{c}" for c in sorted(all_cols))
        query = f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}})"
        if set_clause:
            query += f" SET {set_clause}"
        self.conn.execute(query, {"rows": rows})

        print(f"[kuzu] Merged {len(rows)} {label} nodes.")
        return len(rows)

    def upsert_relationships(self, rows: list[dict], rel_map: dict[str, str]) -> int:
        from dvm_eahelper.graph.loader import rel_name_to_graph_type

        label_of = self._id_label_map()

        by_rel: dict[str, list[dict]] = {}
        for row in rows:
            lx_rel = row["relation"]
            rel_type = rel_map.get(lx_rel) or rel_name_to_graph_type(lx_rel)
            by_rel.setdefault(rel_type, []).append(row)

        total = 0
        for rel_type, rel_rows in by_rel.items():
            by_pair: dict[tuple[str, str], list[dict]] = {}
            for row in rel_rows:
                src_label = label_of.get(row["source_id"])
                tgt_label = label_of.get(row["target_id"])
                if not src_label or not tgt_label:
                    continue
                by_pair.setdefault((src_label, tgt_label), []).append(row)

            for (src_label, tgt_label), pair_rows in by_pair.items():
                self._ensure_rel_pair(rel_type, src_label, tgt_label)
                self.conn.execute(
                    f"""
                    UNWIND $rows AS row
                    MATCH (src:{src_label} {{id: row.source_id}}), (tgt:{tgt_label} {{id: row.target_id}})
                    MERGE (src)-[:{rel_type}]->(tgt)
                    """,
                    {"rows": [{"source_id": str(r["source_id"]), "target_id": str(r["target_id"])} for r in pair_rows]},
                )
                total += len(pair_rows)

            print(f"[kuzu] Merged {len(rel_rows)} :{rel_type} relationships.")

        print(f"[kuzu] {total} relationships merged across {len(by_rel)} types.")
        return total

    def _id_label_map(self) -> dict[str, str]:
        """Return {node_id: label} for every node currently in the database."""
        mapping: dict[str, str] = {}
        for label in self._node_columns:
            res = self.conn.execute(f"MATCH (n:{label}) RETURN n.id")
            while res.has_next():
                mapping[res.get_next()[0]] = label
        return mapping

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def query_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for label in self._node_columns:
            res = self.conn.execute(f"MATCH (n:{label}) RETURN count(n)")
            stats[label] = res.get_next()[0] if res.has_next() else 0

        total_rels = 0
        for rel_type in self._rel_pairs:
            res = self.conn.execute(f"MATCH ()-[r:{rel_type}]->() RETURN count(r)")
            total_rels += res.get_next()[0] if res.has_next() else 0
        stats["_relationships"] = total_rels
        return stats

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        res = self.conn.execute(query, parameters or {})
        columns = res.get_column_names()
        rows = []
        while res.has_next():
            rows.append(dict(zip(columns, res.get_next())))
        return rows

    def clear(self) -> None:
        for rel_type in list(self._rel_pairs):
            self.conn.execute(f"MATCH ()-[r:{rel_type}]->() DELETE r")
        for label in list(self._node_columns):
            self.conn.execute(f"MATCH (n:{label}) DELETE n")

    def get_schema(self) -> dict:
        return {
            "node_tables": {label: sorted(cols) for label, cols in self._node_columns.items()},
            "relationship_types": sorted(self._rel_pairs.keys()),
        }
