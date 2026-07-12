"""register_subcommands — wires the graph `load` and `seed` subcommands into eahelper's CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from dvm_eahelper.graph.fetch import DEFAULT_PROXY
from dvm_eahelper.graph.kuzu_backend import DEFAULT_DB_PATH
from dvm_eahelper.graph.loader import DEFAULT_DATA_DIR, DEFAULT_MAPPING_FILE


def _add_db_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--db",
        choices=["kuzu", "neo4j"],
        default=None,
        help="Graph database backend to use (default: EAHELPER_DB env var, "
             "interactive prompt if attached to a terminal, otherwise kuzu).",
    )
    p.add_argument(
        "--db-path",
        metavar="PATH",
        default=None,
        help=f"KuzuDB database directory (default: {DEFAULT_DB_PATH}, or EAHELPER_KUZU_PATH env var). "
             "Ignored for --db neo4j.",
    )


def _add_load_subcommand(subparsers: argparse._SubParsersAction) -> None:
    load = subparsers.add_parser(
        "load",
        help="Load downloaded LeanIX factsheet/relation JSON into a graph database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_db_args(load)
    load.add_argument(
        "--generate-mapping",
        action="store_true",
        help=f"Scan the live LeanIX workspace and write a mapping YAML "
             f"(default output: {DEFAULT_MAPPING_FILE}). "
             f"Requires the eahelper proxy to be running.",
    )
    load.add_argument(
        "--all-factsheets",
        action="store_true",
        help="Discover and import every FactSheet type from the live LeanIX workspace, "
             "ignoring the factsheet_types filter in the mapping file. "
             "Relationship mappings are still loaded from the mapping file (or defaults). "
             "Requires the eahelper proxy to be running.",
    )
    load.add_argument(
        "--mapping",
        default=None,
        metavar="PATH",
        help=f"Path to the metamodel mapping YAML file (default: {DEFAULT_MAPPING_FILE} if it "
             f"exists, otherwise the bundled default mapping).",
    )
    load.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        metavar="PATH",
        help=f"Directory containing downloaded factsheet/relation JSON (default: {DEFAULT_DATA_DIR})",
    )
    load.add_argument(
        "--proxy",
        default=DEFAULT_PROXY,
        metavar="URL",
        help=f"eahelper GraphQL proxy URL (default: {DEFAULT_PROXY})",
    )
    load.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL certificate verification (insecure; dev only)",
    )
    load.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip LeanIX download; load from previously saved JSON files in --data-dir",
    )
    load.add_argument(
        "--skip-db",
        "--skip-neo4j",
        action="store_true",
        dest="skip_db",
        help="Download only; do not write to the graph database",
    )
    load.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of records downloaded (or loaded from disk) per FactSheet type "
             "and per relationship type.",
    )
    load.set_defaults(func=_run_load)


def _add_seed_subcommand(subparsers: argparse._SubParsersAction) -> None:
    seed_p = subparsers.add_parser(
        "seed",
        help="Seed a demo Application Capability Map graph into the graph database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_db_args(seed_p)
    seed_p.set_defaults(func=_run_seed)


def register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    _add_load_subcommand(subparsers)
    _add_seed_subcommand(subparsers)


def _run_load(args: argparse.Namespace) -> None:
    import sys

    from dvm_eahelper.graph.fetch import download_factsheets, download_relations, make_ssl_context
    from dvm_eahelper.graph.loader import (
        DEFAULT_RELATIONS,
        load_mapping,
        load_saved_json,
        load_to_graph,
        resolve_mapping,
    )
    from dvm_eahelper.graph.select import resolve_backend

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    ssl_verify = False if args.no_verify_ssl else make_ssl_context()

    if args.generate_mapping:
        from dvm_eahelper.graph.discover import generate_mapping_file

        out = Path(args.mapping) if args.mapping else DEFAULT_MAPPING_FILE
        generate_mapping_file(args.proxy, ssl_verify, out)
        return

    if args.all_factsheets:
        from dvm_eahelper.graph.discover import discover_factsheet_types

        print(f"[mapping] --all-factsheets: discovering FactSheet types from {args.proxy} ...")
        try:
            discovered_types, schema_subtypes = discover_factsheet_types(args.proxy, ssl_verify)
        except Exception as exc:
            print(f"  ERROR: could not discover FactSheet types: {exc}")
            print("  Is the proxy running?  →  eahelper proxy")
            sys.exit(1)
        if not discovered_types:
            print("  No FactSheet types found. Is the proxy running?  →  eahelper proxy")
            sys.exit(1)
        print(f"  Found {len(discovered_types)} types: {', '.join(discovered_types)}")

        if args.mapping:
            _, rel_map, _ = load_mapping(Path(args.mapping))
        elif DEFAULT_MAPPING_FILE.exists():
            _, rel_map, _ = load_mapping(DEFAULT_MAPPING_FILE)
        else:
            rel_map = DEFAULT_RELATIONS

        factsheet_types = discovered_types
        subtype_map = schema_subtypes
    else:
        factsheet_types, rel_map, subtype_map = resolve_mapping(args.mapping)

    print(f"[mapping] FactSheet types: {', '.join(factsheet_types)}")
    if subtype_map:
        for t, sts in subtype_map.items():
            print(f"  {t} subtypes: {', '.join(sts)}")

    if args.skip_download:
        print(f"\n[load] Reading saved JSON from {data_dir} ...")
        factsheets, relations = load_saved_json(data_dir, factsheet_types, limit=args.limit)
    else:
        factsheets = download_factsheets(
            args.proxy, ssl_verify, factsheet_types, data_dir, subtype_map, limit=args.limit
        )
        relations = download_relations(args.proxy, ssl_verify, factsheet_types, data_dir, limit=args.limit)

    if args.skip_db:
        print("[graph] Skipped (--skip-db).")
        return

    backend = resolve_backend(args)
    load_to_graph(backend, factsheets, relations, rel_map)


def _run_seed(args: argparse.Namespace) -> None:
    from dvm_eahelper.graph.seed import seed
    from dvm_eahelper.graph.select import resolve_backend

    backend = resolve_backend(args)
    seed(backend)
