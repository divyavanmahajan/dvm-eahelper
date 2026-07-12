"""
fetch — Download LeanIX factsheets and relationships via the eahelper proxy
and save them as `{Type}.json` / `{Type}_relations.json` in a data directory,
ready for loading into a graph database.
"""

from __future__ import annotations

import json
import ssl
from pathlib import Path

from dvm_eahelper.leanix.download import (
    _BASE_SUBSELECT,
    _SAFE_BASE_FIELDS,
    _collect_object_subfields,
    build_query,
    build_relations_query,
    fetch_all,
    fetch_all_relations,
    introspect_type,
    list_relation_fields,
    write_json,
)

DEFAULT_PROXY = "http://localhost:8765/graphql"


def make_ssl_context() -> ssl.SSLContext:
    """Legacy SSL context that tolerates corporate SSL-inspection proxies."""
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def download_factsheets(
    proxy: str,
    ssl_verify,
    types: list[str],
    data_dir: Path,
    subtype_map: dict[str, list[str]] | None = None,
    limit: int | None = None,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}

    for type_name in types:
        subtypes = (subtype_map or {}).get(type_name, [])
        subtype_label = f" (subtypes: {', '.join(subtypes)})" if subtypes else ""
        print(f"\n[download] {type_name} factsheets{subtype_label} ...")
        try:
            type_fields = introspect_type(proxy, type_name, ssl_verify)
            base_fields_raw = introspect_type(proxy, "BaseFactSheet", ssl_verify)
            base_field_names = {f["name"] for f in base_fields_raw}

            base_fields = [
                f for f in _SAFE_BASE_FIELDS
                if f in base_field_names or f in _BASE_SUBSELECT
            ]
            if "completion" in base_field_names:
                base_fields.append("completion")

            base_names = set(base_fields) | {"id", "name", "type", "category"}
            object_subfields = _collect_object_subfields(proxy, type_fields, base_names, ssl_verify)

            query = build_query(type_name, type_fields, base_fields, object_subfields)
            records = fetch_all(
                proxy_url=proxy,
                query=query,
                type_name=type_name,
                subtypes=[],
                ssl_verify=ssl_verify,
                verbose=True,
                type_fields=type_fields,
                base_fields=base_fields,
                object_subfields=object_subfields,
                limit=limit,
            )

            if limit is not None and len(records) >= limit:
                print(f"  [limit] Stopped at {limit} records (limit reached).")

            out_path = data_dir / f"{type_name}.json"
            with open(out_path, "w", encoding="utf-8") as fh:
                write_json(records, fh)

            print(f"  → {len(records)} records  →  {out_path}")
            results[type_name] = records

        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: could not download {type_name}: {exc}")
            results[type_name] = []

    return results


def download_relations(
    proxy: str,
    ssl_verify,
    types: list[str],
    data_dir: Path,
    limit: int | None = None,
) -> list[dict]:
    seen: set[tuple] = set()
    all_rows: list[dict] = []

    for type_name in types:
        print(f"\n[download] {type_name} relations ...")
        try:
            type_fields = introspect_type(proxy, type_name, ssl_verify)
            relation_fields = list_relation_fields(type_fields)

            if not relation_fields:
                print(f"  No relation fields for {type_name}")
                continue

            query = build_relations_query(type_name, relation_fields)
            rows = fetch_all_relations(
                proxy_url=proxy,
                query=query,
                type_name=type_name,
                relation_fields=relation_fields,
                ssl_verify=ssl_verify,
                verbose=True,
                limit=limit,
            )

            unique_rows = []
            for row in rows:
                key = (row["source_id"], row["relation"], row["target_id"])
                if key not in seen:
                    seen.add(key)
                    unique_rows.append(row)

            if limit is not None and len(rows) >= limit:
                print(f"  [limit] Stopped at {limit} relation rows (limit reached).")

            out_path = data_dir / f"{type_name}_relations.json"
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(unique_rows, fh, indent=2, ensure_ascii=False)

            all_rows.extend(unique_rows)
            print(f"  → {len(unique_rows)} unique relation rows  →  {out_path}")

        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: could not download {type_name} relations: {exc}")

    return all_rows
