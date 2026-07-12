"""
discover — Scan the live LeanIX workspace (via the eahelper proxy) to discover
FactSheet types and relation fields, and generate a metamodel mapping YAML.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

from dvm_eahelper.graph.loader import DEFAULT_RELATIONS, rel_name_to_graph_type
from dvm_eahelper.leanix.download import _gql, introspect_type, list_relation_fields

METAMODEL_MD = Path("leanix-metamodel.md")


def discover_factsheet_types(proxy: str, ssl_verify) -> tuple[list[str], dict[str, list[str]]]:
    """Return (main_types, subtype_map) discovered from the LeanIX GraphQL schema.

    main_types:   OBJECT types implementing BaseFactSheet / FactSheet.
    subtype_map:  {TypeName: [SubtypeName, ...]} for types whose subtypes are
                  exposed as separate OBJECT types implementing the parent type.
                  Empty dict when the workspace has no schema-level subtypes.
    """
    result = _gql(proxy, "{ __schema { types { name kind interfaces { name } } } }", {}, ssl_verify)
    types = result.get("data", {}).get("__schema", {}).get("types", [])

    main_types = sorted(
        t["name"] for t in types
        if t["kind"] == "OBJECT"
        and any(i["name"] in ("BaseFactSheet", "FactSheet") for i in (t["interfaces"] or []))
    )
    main_set = set(main_types)

    subtype_map: dict[str, list[str]] = {}
    for t in types:
        if t["kind"] != "OBJECT":
            continue
        for iface in (t["interfaces"] or []):
            if iface["name"] in main_set:
                subtype_map.setdefault(iface["name"], []).append(t["name"])
    for key in subtype_map:
        subtype_map[key].sort()

    return main_types, subtype_map


def parse_metamodel_md(md_path: Path) -> dict[str, str]:
    """Parse the Relationships table from a leanix-metamodel.md file.

    Each row (Source, Relationship, Target) is converted to:
      key  → relSourceTypeToTargetType   (spaces stripped from type names)
      value → RELATIONSHIP_LABEL         (label uppercased, spaces/slashes → underscores)

    Returns an empty dict if the file cannot be parsed.
    """
    relations: dict[str, str] = {}
    in_relationships = False

    with open(md_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()

            if stripped == "## Relationships":
                in_relationships = True
                continue

            if not in_relationships:
                continue

            if stripped.startswith("## "):
                break

            if not stripped.startswith("|"):
                continue

            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) < 6:
                continue

            if parts[1] in ("#", "---", "") or parts[1].startswith("---"):
                continue

            source = parts[2].replace(" ", "")
            rel_label = parts[3]
            target = parts[4].replace(" ", "")

            if not source or not rel_label or not target:
                continue

            lx_field = f"rel{source}To{target}"
            rel_type = re.sub(r"[^A-Z0-9]+", "_", rel_label.upper()).strip("_")

            if lx_field not in relations:
                relations[lx_field] = rel_type

    return relations


def parse_metamodel_md_subtypes(md_path: Path) -> dict[str, list[str]]:
    """Parse the Fact Sheet Types table from leanix-metamodel.md.

    Returns {TypeName: [SubtypeName, ...]} for types that declare subtypes.
    Type and subtype names are normalised to PascalCase (spaces removed,
    original capitalisation preserved — e.g. "AI Agent" → "AIAgent").
    Decoration characters (* † .) are stripped from subtype names.
    """
    subtypes: dict[str, list[str]] = {}
    in_table = False

    with open(md_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()

            if stripped == "## Fact Sheet Types":
                in_table = True
                continue

            if not in_table:
                continue

            if stripped.startswith("## "):
                break

            if not stripped.startswith("|"):
                continue

            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) < 5:
                continue

            if parts[1] in ("Layer", "---", "") or parts[1].startswith("---"):
                continue

            type_name_raw = parts[2]
            subtypes_raw = parts[4] if len(parts) > 4 else ""

            if not type_name_raw or subtypes_raw.strip() in ("—", "-", "", "Subtypes"):
                continue

            type_name = type_name_raw.replace(" ", "")

            subtype_list = []
            for st in re.split(r"[,;]", subtypes_raw):
                cleaned = re.sub(r"[*†.†‡]", "", st).strip()
                if cleaned and cleaned not in ("—", "-"):
                    subtype_list.append(cleaned.replace(" ", ""))

            if subtype_list:
                subtypes[type_name] = subtype_list

    return subtypes


def generate_mapping_file(proxy: str, ssl_verify, output_path: Path) -> None:
    """Scan the live LeanIX workspace and write a mapping YAML to *output_path*.

    Relationship defaults come from leanix-metamodel.md (if present), falling back
    to the hardcoded DEFAULT_RELATIONS dict. Any relation field not matched by either
    source is auto-converted from camelCase to UPPER_SNAKE_CASE.
    """
    if METAMODEL_MD.exists():
        md_defaults = parse_metamodel_md(METAMODEL_MD)
        print(f"[mapping] Loaded {len(md_defaults)} relationship defaults from {METAMODEL_MD}")
    else:
        md_defaults = {}
        print(f"[mapping] {METAMODEL_MD} not found — using built-in relationship defaults")

    defaults = {**DEFAULT_RELATIONS, **md_defaults}
    print(f"[mapping] Discovering FactSheet types from {proxy} ...")
    try:
        types, schema_subtypes = discover_factsheet_types(proxy, ssl_verify)
    except Exception as exc:
        print(f"  ERROR scanning LeanIX: {exc}")
        print("  Is the proxy running?  →  eahelper proxy")
        sys.exit(1)

    if not types:
        print("  No FactSheet types found. Is the proxy running?  →  eahelper proxy")
        sys.exit(1)

    print(f"  Found {len(types)} FactSheet types: {', '.join(types)}")

    md_subtypes = parse_metamodel_md_subtypes(METAMODEL_MD) if METAMODEL_MD.exists() else {}

    fs_section: dict[str, dict] = {}
    for t in types:
        entry: dict = {"node_label": t}

        raw_subtypes = schema_subtypes.get(t) or md_subtypes.get(t, [])
        if raw_subtypes:
            entry["subtypes"] = {st: {"node_label": t} for st in raw_subtypes}

        fs_section[t] = entry

    rel_section: dict[str, str] = {}

    all_types_to_introspect = list(types)
    for t in types:
        all_types_to_introspect.extend(schema_subtypes.get(t) or md_subtypes.get(t, []))

    for type_name in all_types_to_introspect:
        is_subtype = type_name not in set(types)
        label = f"  Inspecting {'subtype ' if is_subtype else ''}relations for {type_name} ..."
        print(label)
        try:
            type_fields = introspect_type(proxy, type_name, ssl_verify)
            for rf in list_relation_fields(type_fields):
                field_name = rf["name"] if isinstance(rf, dict) else rf
                if field_name not in rel_section:
                    rel_section[field_name] = defaults.get(field_name) or rel_name_to_graph_type(field_name)
        except Exception as exc:
            if is_subtype:
                pass
            else:
                print(f"    WARNING: could not introspect {type_name}: {exc}")

    for field_name, rel_type in defaults.items():
        if field_name not in rel_section:
            rel_section[field_name] = rel_type

    mapping: dict = {
        "factsheet_types": fs_section,
        "relationships": rel_section,
    }

    header = (
        f"# LeanIX → graph metamodel mapping\n"
        f"# Generated: {date.today()}\n"
        f"#\n"
        f"# factsheet_types: controls which FactSheet types are downloaded/loaded\n"
        f"#   and what graph node label is used for each.\n"
        f"# relationships: maps LeanIX relation field names to graph relationship types.\n"
        f"#\n"
        f"# Edit node_label and relationship values freely; re-run eahelper load to apply.\n\n"
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.dump(mapping, fh, default_flow_style=False, sort_keys=True, allow_unicode=True)

    print(f"\n[mapping] Written to {output_path}")
    print(f"  Review and edit the file, then run:  eahelper load --mapping {output_path}")
