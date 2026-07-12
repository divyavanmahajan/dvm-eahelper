"""
loader — Load previously downloaded LeanIX factsheet/relation JSON into a GraphBackend.

Driven by the metamodel-mapping.yaml mapping file (factsheet_types + relationships),
same format used by the original dvm-eagraph Neo4j loader. Works against any
GraphBackend implementation (Neo4j or Kuzu) via the common interface in base.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from dvm_eahelper.graph.base import GraphBackend

_PACKAGE_DIR = Path(__file__).parent.parent

DEFAULT_DATA_DIR = Path("data/leanix")
DEFAULT_MAPPING_FILE = Path("metamodel-mapping.yaml")

_BUILTIN_FACTSHEET_TYPES = ["Application", "BusinessCapability", "Interface", "Organization"]

DEFAULT_RELATIONS: dict[str, str] = {
    "relApplicationToBusinessCapability": "SUPPORTS",
    "relApplicationToInterface": "PROVIDES",
    "relApplicationToDataObject": "CRUD",
    "relApplicationToITComponent": "RUNS_ON",
    "relApplicationToOrganization": "OWNED_BY",
    "relApplicationToProvider": "PROVIDED_BY",
    "relApplicationToInitiative": "AFFECTED_BY",
    "relApplicationToPlatform": "PART_OF",
    "relInterfaceToApplication": "CONSUMED_BY",
    "relInterfaceToDataObject": "TRANSFERS",
    "relInterfaceToITComponent": "RUNS_ON",
    "relBusinessCapabilityToApplication": "SUPPORTED_BY",
    "relBusinessCapabilityToBusinessContext": "ASSOCIATED_WITH",
    "relBusinessCapabilityToOrganization": "OWNED_BY",
    "relOrganizationToApplication": "OWNS",
    "relOrganizationToDataObject": "OWNS",
    "relOrganizationToObjective": "OWNS",
    "relOrganizationToPlatform": "OWNS",
    "relOrganizationToBusinessCapability": "SUPPORTS",
    "relITComponentToApplication": "HOSTS",
    "relITComponentToProvider": "OFFERED_BY",
    "relITComponentToTechCategory": "BELONGS_TO",
    "relITComponentToInterface": "HOSTS",
    "relProviderToITComponent": "OFFERS",
    "relInitiativeToApplication": "AFFECTS",
    "relInitiativeToBusinessCapability": "AFFECTS",
    "relInitiativeToInterface": "AFFECTS",
    "relInitiativeToITComponent": "AFFECTS",
    "relInitiativeToPlatform": "AFFECTS",
    "relInitiativeToObjective": "IMPROVES",
    "relInitiativeToProvider": "AFFECTS",
    "relPlatformToObjective": "SUPPORTS",
    "relPlatformToBusinessCapability": "SUPPORTS",
    "relDataObjectToApplication": "USED_BY",
    "relDataObjectToInterface": "CARRIED_BY",
    "relToParent": "CHILD_OF",
    "relToSuccessor": "SUCCEEDED_BY",
    "relToPredecessor": "PRECEDES",
}


def rel_name_to_graph_type(leanix_rel: str) -> str:
    """Convert a LeanIX relation field name to a graph relationship type string.

    Checks DEFAULT_RELATIONS first; falls back to stripping 'rel' and converting
    camelCase -> UPPER_SNAKE_CASE.
    """
    if leanix_rel in DEFAULT_RELATIONS:
        return DEFAULT_RELATIONS[leanix_rel]
    name = leanix_rel[3:] if leanix_rel.startswith("rel") else leanix_rel
    name = re.sub(r"([A-Z])", r"_\1", name).upper().strip("_")
    return name


def load_mapping(mapping_path: Path) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Load factsheet types, relationship label map, and subtype map from a YAML mapping file.

    Returns (factsheet_type_names, relation_type_map, subtype_map).
    Exits with a clear message if the file is missing.
    """
    if not mapping_path.exists():
        print(f"ERROR: Mapping file not found: {mapping_path}")
        print(
            "Run the following to generate it from your live LeanIX workspace:\n"
            "  eahelper load --generate-mapping"
        )
        sys.exit(1)

    with open(mapping_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    fs_cfg = data.get("factsheet_types") or {}
    fs_types = list(fs_cfg.keys())
    rel_map = {k: str(v) for k, v in (data.get("relationships") or {}).items()}

    subtype_map: dict[str, list[str]] = {}
    for type_name, cfg in fs_cfg.items():
        if isinstance(cfg, dict) and cfg.get("subtypes"):
            subtype_map[type_name] = list(cfg["subtypes"].keys())

    if not fs_types:
        print(f"ERROR: No factsheet_types found in {mapping_path}")
        sys.exit(1)

    return fs_types, rel_map, subtype_map


def _bundled_mapping() -> Path | None:
    """Return the path to the bundled default metamodel-mapping.yaml, or None."""
    p = _PACKAGE_DIR / "metamodel-mapping.yaml"
    return p if p.exists() else None


def resolve_mapping(mapping_arg: str | None) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Return (factsheet_types, relation_map, subtype_map) from a mapping file or built-in defaults.

    Resolution order:
      1. --mapping <path>  -> must exist (hard error if not)
      2. DEFAULT_MAPPING_FILE exists in CWD  -> load it
      3. Bundled package default mapping  -> load it
      4. Neither exist  -> warn and use built-in defaults
    """
    if mapping_arg:
        return load_mapping(Path(mapping_arg))

    if DEFAULT_MAPPING_FILE.exists():
        print(f"[mapping] Using {DEFAULT_MAPPING_FILE}")
        return load_mapping(DEFAULT_MAPPING_FILE)

    bundled = _bundled_mapping()
    if bundled is not None:
        print(f"[mapping] No local {DEFAULT_MAPPING_FILE} found — using bundled default mapping.")
        return load_mapping(bundled)

    print(
        f"[mapping] {DEFAULT_MAPPING_FILE} not found — using built-in defaults "
        f"({', '.join(_BUILTIN_FACTSHEET_TYPES)}).\n"
        f"  Tip: run  eahelper load --generate-mapping  to create a full mapping."
    )
    return _BUILTIN_FACTSHEET_TYPES, DEFAULT_RELATIONS, {}


def load_saved_json(
    data_dir: Path,
    types: list[str],
    limit: int | None = None,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Read factsheets and relations from previously saved JSON files."""
    factsheets: dict[str, list[dict]] = {}
    all_relations: list[dict] = []

    for type_name in types:
        fs_path = data_dir / f"{type_name}.json"
        if fs_path.exists():
            with open(fs_path, encoding="utf-8") as fh:
                records = json.load(fh)
            if limit is not None and len(records) > limit:
                print(f"  [limit] Capping {type_name} at {limit} of {len(records)} records.")
                records = records[:limit]
            factsheets[type_name] = records
            print(f"  Loaded {len(factsheets[type_name])} {type_name} records from {fs_path}")
        else:
            factsheets[type_name] = []
            print(f"  WARNING: {fs_path} not found — skipping {type_name}")

        rel_path = data_dir / f"{type_name}_relations.json"
        if rel_path.exists():
            with open(rel_path, encoding="utf-8") as fh:
                rows = json.load(fh)
            if limit is not None and len(rows) > limit:
                print(f"  [limit] Capping {type_name} relations at {limit} of {len(rows)} rows.")
                rows = rows[:limit]
            all_relations.extend(rows)
            print(f"  Loaded {len(rows)} {type_name} relation rows from {rel_path}")

    seen: set[tuple] = set()
    deduped = []
    for row in all_relations:
        key = (row["source_id"], row["relation"], row["target_id"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return factsheets, deduped


def print_stats_comparison(before: dict, after: dict, leanix: dict | None = None) -> None:
    """Print a before/after comparison table of node and relationship counts."""
    node_keys = sorted(k for k in set(before) | set(after) | set(leanix or {}) if k != "_relationships")
    col = max((len(k) for k in node_keys), default=10) + 2

    if leanix is not None:
        header = f"  {'Label':<{col}} {'LeanIX':>9} {'Before':>9} {'After':>9} {'Delta':>9}"
        sep_width = col + 39
    else:
        header = f"  {'Label':<{col}} {'Before':>9} {'After':>9} {'Delta':>9}"
        sep_width = col + 30

    print("\n" + header)
    print("  " + "-" * sep_width)

    for k in node_keys:
        b, a = before.get(k, 0), after.get(k, 0)
        delta = a - b
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        if leanix is not None:
            lx = leanix.get(k, 0)
            lx_str = f"{lx:,}" if lx else "-"
            print(f"  {k:<{col}} {lx_str:>9} {b:>9,} {a:>9,} {delta_str:>9}")
        else:
            print(f"  {k:<{col}} {b:>9,} {a:>9,} {delta_str:>9}")

    b, a = before.get("_relationships", 0), after.get("_relationships", 0)
    delta = a - b
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    print("  " + "-" * sep_width)
    if leanix is not None:
        lx = leanix.get("_relationships", 0)
        lx_str = f"{lx:,}" if lx else "-"
        print(f"  {'[Relationships]':<{col}} {lx_str:>9} {b:>9,} {a:>9,} {delta_str:>9}")
    else:
        print(f"  {'[Relationships]':<{col}} {b:>9,} {a:>9,} {delta_str:>9}")


def load_to_graph(
    backend: GraphBackend,
    factsheets: dict[str, list[dict]],
    relations: list[dict],
    rel_map: dict[str, str],
) -> None:
    types = list(factsheets.keys())

    leanix_counts: dict[str, int] = {label: len(records) for label, records in factsheets.items()}
    leanix_counts["_relationships"] = len(relations)

    relationship_types = _relationship_type_triples(factsheets, relations, rel_map)

    with backend:
        print(f"\n[{backend.__class__.__name__}] Connected.")

        print("[graph] Querying database state before load ...")
        before_stats = backend.query_stats()

        print("[graph] Ensuring schema ...")
        backend.ensure_schema(types, relationship_types)

        for label, records in factsheets.items():
            if records:
                backend.upsert_nodes(label, records)

        if relations:
            backend.upsert_relationships(relations, rel_map)

        after_stats = backend.query_stats()

        print("\n[graph] Load complete — before/after comparison:")
        print_stats_comparison(before_stats, after_stats, leanix=leanix_counts)


def _relationship_type_triples(
    factsheets: dict[str, list[dict]],
    relations: list[dict],
    rel_map: dict[str, str],
) -> list[tuple[str, str, str]]:
    """Best-effort (rel_type, from_label, to_label) triples for backends needing rel schema.

    Determines each relation's source/target node label from which factsheet type's id
    set the source_id/target_id belongs to. Falls back gracefully when unknown.
    """
    id_to_label: dict[str, str] = {}
    for label, records in factsheets.items():
        for r in records:
            rid = r.get("id")
            if rid:
                id_to_label[str(rid)] = label

    triples: set[tuple[str, str, str]] = set()
    for row in relations:
        lx_rel = row["relation"]
        rel_type = rel_map.get(lx_rel) or rel_name_to_graph_type(lx_rel)
        src_label = id_to_label.get(str(row.get("source_id")))
        tgt_label = id_to_label.get(str(row.get("target_id")))
        if src_label and tgt_label:
            triples.add((rel_type, src_label, tgt_label))

    return sorted(triples)
