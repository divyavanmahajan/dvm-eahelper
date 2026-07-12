"""config_cli — `eahelper config` subcommand implementation."""

from __future__ import annotations

import argparse
import sys

from dvm_eahelper.config import (
    config_path,
    effective_config,
    set_config_value,
    unset_config_value,
)


def _add_config_subcommand(subparsers: argparse._SubParsersAction) -> None:
    cfg = subparsers.add_parser(
        "config",
        help="View or edit the eahelper user config (~/.eahelper/config.toml)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cfg_sub = cfg.add_subparsers(dest="config_command")

    cfg_sub.add_parser("path", help="Print the path to config.toml")

    set_p = cfg_sub.add_parser("set", help="Set a config value: eahelper config set <section.key> <value>")
    set_p.add_argument("dotted_key", metavar="section.key")
    set_p.add_argument("value")

    unset_p = cfg_sub.add_parser("unset", help="Remove a config value: eahelper config unset <section.key>")
    unset_p.add_argument("dotted_key", metavar="section.key")

    cfg.set_defaults(func=_run_config)


def _coerce_input(raw: str):
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        return raw


def _run_config(args: argparse.Namespace) -> None:
    sub = getattr(args, "config_command", None)

    if sub == "path":
        print(config_path())
        return

    if sub == "set":
        try:
            set_config_value(args.dotted_key, _coerce_input(args.value))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"  {args.dotted_key} = {args.value}")
        return

    if sub == "unset":
        try:
            unset_config_value(args.dotted_key)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"  Removed {args.dotted_key}")
        return

    data = effective_config()
    print(f"Config file: {config_path()}\n")
    for section in sorted(data):
        print(f"[{section}]")
        for key in sorted(data[section]):
            print(f"{key} = {data[section][key]!r}")
        print()


def register(subparsers: argparse._SubParsersAction) -> None:
    _add_config_subcommand(subparsers)
