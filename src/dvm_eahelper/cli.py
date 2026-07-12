"""
eahelper – LeanIX enterprise-architecture helper CLI

Usage
-----
    eahelper <command> [OPTIONS]

Commands
--------
    server      Run the integrated server: GraphQL proxy + MCP endpoint (+ start|stop|status)
    proxy       Start the standalone GraphQL proxy server (legacy; prefer 'server')
    diagnose    Test SSL/TLS connectivity to LeanIX and recommend fixes
    download    Download all FactSheets of a type from LeanIX via the proxy
    load        Load downloaded data into the graph database
    seed        Seed the graph database
    mcp         Run the MCP server over stdio
    mcp-config  Print/install MCP client config for Claude Code / VS Code
    config      View or edit ~/.eahelper/config.toml

Agent skill
-----------
An installable Agent Skill (Claude Code, GitHub Copilot, and other
agentskills.io-compatible agents) that walks you through setup and usage:

    git clone https://github.com/divyavanmahajan/dvm-eahelper-skills
    # Claude Code:      cp -R dvm-eahelper-skills/skills/eahelper ~/.claude/skills/eahelper
    # GitHub Copilot:   cp -R dvm-eahelper-skills/skills/eahelper ~/.copilot/skills/eahelper

Then restart your agent so it picks up the skill.
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

DEFAULT_URL = "https://eu-10.leanix.net/YourInstance"
DEFAULT_PORT = 8765
DEFAULT_CDP = "http://localhost:19222"


def _prompt(prompt_text: str, default: str) -> str:
    """Prompt the user for a value, showing the default."""
    try:
        value = input(f"{prompt_text} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return value if value else default


def _add_shared(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--url",
        metavar="URL",
        default=None,
        help=f"LeanIX workspace base URL (default: {DEFAULT_URL})",
    )
    ssl_group = p.add_mutually_exclusive_group()
    ssl_group.add_argument(
        "--ca-bundle",
        metavar="PATH",
        default=None,
        help=(
            "Path to a PEM CA bundle for SSL verification. "
            "Use when behind a corporate SSL inspection proxy. "
            "Run 'eahelper diagnose' to auto-detect and export the right bundle."
        ),
    )
    ssl_group.add_argument(
        "--no-verify-ssl",
        action="store_true",
        default=False,
        help="Disable SSL certificate verification entirely (insecure).",
    )
    p.add_argument(
        "--legacy-ssl",
        action="store_true",
        default=True,
        help=(
            "Relax Python 3.13+ strict X.509 certificate validation. "
            "Fixes 'Missing Authority Key Identifier' errors from corporate SSL proxies. "
            "(default: enabled)"
        ),
    )
    p.add_argument(
        "--no-legacy-ssl",
        action="store_false",
        dest="legacy_ssl",
        help="Disable legacy SSL mode and use strict X.509 validation.",
    )


def _add_proxy_subcommand(subparsers: argparse._SubParsersAction) -> None:
    proxy = subparsers.add_parser(
        "proxy",
        help="Start the GraphQL proxy server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_shared(proxy)
    proxy.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for the proxy server (default: {DEFAULT_PORT})",
    )
    proxy.add_argument(
        "--connect",
        metavar="CDP_URL",
        default=DEFAULT_CDP,
        dest="cdp_url",
        help=(
            "Connect to an existing browser via Chrome DevTools Protocol. "
            f"(default: {DEFAULT_CDP})"
        ),
    )
    proxy.add_argument(
        "--token",
        metavar="TOKEN",
        default=None,
        help="Use this Bearer token directly (skips browser extraction)",
    )
    proxy.add_argument(
        "--api-token",
        metavar="API_KEY",
        default=None,
        dest="api_key",
        help=(
            "LeanIX Technical User API key. Exchanges the key for a Bearer token "
            "via OAuth2 (no browser needed). Also reads from env var LEANIX_API_TOKEN."
        ),
    )
    proxy.add_argument(
        "--no-save",
        action="store_true",
        default=False,
        help="Do not save the token to ~/.eahelper/tokens.json",
    )
    proxy.set_defaults(func=_run_proxy)


def _add_diagnose_subcommand(subparsers: argparse._SubParsersAction) -> None:
    diag = subparsers.add_parser(
        "diagnose",
        help="Test SSL/TLS connectivity to LeanIX and recommend fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_shared(diag)
    diag.set_defaults(func=_run_diagnose)


def _add_download_subcommand(subparsers: argparse._SubParsersAction) -> None:
    dl = subparsers.add_parser(
        "download",
        help="Download all FactSheets of a type from LeanIX via the proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Introspects the GraphQL schema, builds a query with all scalar fields\n"
            "for the requested FactSheet type, paginates through all results, and\n"
            "writes them as JSON (default) or CSV.\n\n"
            "Docs: https://help.sap.com/docs/leanix/ea/graphql-api"
        ),
    )
    _add_shared(dl)
    dl.add_argument(
        "--type", "-t",
        metavar="TYPE",
        default=None,
        dest="fs_type",
        help="FactSheet type to download (e.g. Application, ITComponent). "
             "Use --list-types to see all available types.",
    )
    dl.add_argument(
        "--subtype", "-s",
        metavar="SUBTYPE",
        nargs="+",
        default=[],
        dest="subtypes",
        help="Filter by category (subtype). Case-insensitive. "
             "Use --list-subtypes to see available values for a type.",
    )
    dl.add_argument(
        "--proxy",
        metavar="URL",
        default="http://localhost:8765/graphql",
        help="GraphQL proxy URL (default: http://localhost:8765/graphql)",
    )
    dl.add_argument(
        "--output", "-o",
        metavar="FILE",
        default=None,
        help="Write output to FILE (default: {Type}.json)",
    )
    dl.add_argument(
        "--format", "-f",
        choices=["json", "csv"],
        default="json",
        dest="fmt",
        help="Output format: json (default) or csv",
    )
    dl.add_argument(
        "--list-types",
        action="store_true",
        default=False,
        help="List all available FactSheet types from the schema and exit",
    )
    dl.add_argument(
        "--list-subtypes",
        action="store_true",
        default=False,
        help="List all distinct category (subtype) values for --type and exit",
    )
    dl.add_argument(
        "--relations",
        action="store_true",
        default=False,
        help=(
            "Download relationships between FactSheets instead of field data. "
            "If --type is omitted, an interactive type selector is shown. "
            "Output is CSV with columns: source_id, source_displayName, relation, "
            "target_id, target_displayName. Default file: {Type}_relations.csv"
        ),
    )
    dl.add_argument(
        "--list-relations",
        action="store_true",
        default=False,
        help="List all available relationship fields for --type and exit",
    )
    dl.add_argument(
        "--limit", "-n",
        type=int,
        metavar="N",
        default=None,
        help="Stop after downloading N records (useful for testing)",
    )
    dl.set_defaults(func=_run_download)


def _add_mcp_subcommand(subparsers: argparse._SubParsersAction) -> None:
    mcp_p = subparsers.add_parser(
        "mcp",
        help="Run the MCP server over stdio (for harnesses that spawn a subprocess)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_p.add_argument(
        "--read-only",
        action="store_true",
        default=None,
        help="Reject write Cypher queries via the query tool",
    )
    mcp_p.set_defaults(func=_run_mcp)


def _add_mcp_config_subcommand(subparsers: argparse._SubParsersAction) -> None:
    mcp_cfg = subparsers.add_parser(
        "mcp-config",
        help="Print (or install) MCP config snippets for Claude Code / VS Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_cfg.add_argument(
        "--install",
        action="store_true",
        default=False,
        help="Write/merge .mcp.json and .vscode/mcp.json in the current directory",
    )
    mcp_cfg.set_defaults(func=_run_mcp_config)


def _stub_graph_subcommands(subparsers: argparse._SubParsersAction) -> None:
    def _missing(_args: argparse.Namespace) -> None:
        print(
            "Error: the 'load'/'seed' commands are not available yet — "
            "the dvm_eahelper.graph package has not been implemented.",
            file=sys.stderr,
        )
        sys.exit(1)

    for name, help_text in (
        ("load", "Load downloaded data into the graph database (unavailable)"),
        ("seed", "Seed the graph database (unavailable)"),
    ):
        p = subparsers.add_parser(name, help=help_text)
        p.set_defaults(func=_missing)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eahelper",
        description="LeanIX enterprise-architecture helper: GraphQL proxy, factsheet download, and graph loading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version
    try:
        _version = _pkg_version("dvm-eahelper")
    except PackageNotFoundError:
        _version = "dev"

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {_version}",
    )
    parser.add_argument(
        "--help-library",
        action="store_true",
        default=False,
        help="Print Markdown documentation for using dvm_eahelper.leanix as a Python library and exit",
    )

    subparsers = parser.add_subparsers(dest="command")

    _add_proxy_subcommand(subparsers)
    _add_diagnose_subcommand(subparsers)
    _add_download_subcommand(subparsers)
    _add_mcp_subcommand(subparsers)
    _add_mcp_config_subcommand(subparsers)

    from dvm_eahelper.config_cli import register as register_config
    register_config(subparsers)

    from dvm_eahelper.server_cli import register as register_server
    register_server(subparsers)

    try:
        from dvm_eahelper.graph.cli import register_subcommands
        register_subcommands(subparsers)
    except ImportError:
        _stub_graph_subcommands(subparsers)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _resolve_ssl(args: argparse.Namespace) -> bool | str | ssl.SSLContext:
    """
    Determine the ssl_verify value to pass to build_app.

    Priority:
      1. --no-verify-ssl  → False              (skip all verification)
      2. --legacy-ssl     → SSLContext          (relaxed X.509 strict mode)
      3. --ca-bundle PATH → str                 (custom CA file, optionally + legacy)
      4. default          → True or SSLContext  (system/certifi bundle)
    """
    import ssl as _ssl

    if args.no_verify_ssl:
        print("  SSL verify       : DISABLED (--no-verify-ssl)")
        return False

    legacy = getattr(args, "legacy_ssl", False)

    def _make_ctx(ca_file: str | None = None) -> _ssl.SSLContext:
        ctx = _ssl.create_default_context()
        if ca_file:
            ctx.load_verify_locations(cafile=ca_file)
        try:
            ctx.verify_flags &= ~_ssl.VERIFY_X509_STRICT
        except AttributeError:
            pass
        return ctx

    if args.ca_bundle:
        path = Path(args.ca_bundle)
        if not path.is_file():
            print(f"Error: --ca-bundle path not found: {path}", file=sys.stderr)
            sys.exit(1)
        if legacy:
            print(f"  SSL verify       : custom CA bundle + legacy mode ({path})")
            return _make_ctx(str(path))
        print(f"  SSL verify       : custom CA bundle ({path})")
        return str(path)

    if legacy:
        print("  SSL verify       : legacy mode (relaxed X.509 strict checking)")
        return _make_ctx()

    # Check env var as a convenience (mirrors requests/httpx convention)
    env_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if env_bundle and Path(env_bundle).is_file():
        print(f"  SSL verify       : CA bundle from env ({env_bundle})")
        return env_bundle

    print("  SSL verify       : system CA bundle")
    return True


def _extract_from_browser(leanix_url: str, cdp_url: str) -> str:
    """Extract Bearer token from browser; print guidance and exit on failure."""
    print(f"  CDP endpoint     : {cdp_url}")
    print(
        "\nConnecting to browser to extract Bearer token…\n"
        "  Make sure Chrome/Edge is running with:\n"
        "    chrome.exe --remote-debugging-port=19222 --user-data-dir=C:\\Temp\\chrome-debug\n"
        "  and that you are already logged in to LeanIX.\n"
    )
    from dvm_eahelper.proxy.token import get_token_sync
    try:
        return get_token_sync(leanix_url, cdp_url)
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)


def _run_diagnose(args: argparse.Namespace) -> None:
    url = args.url or DEFAULT_URL
    from dvm_eahelper.proxy.diagnose import run_diagnostics
    run_diagnostics(url.rstrip("/"), ca_bundle=args.ca_bundle)


def _run_mcp(args: argparse.Namespace) -> None:
    from dvm_eahelper.mcp_server import run_stdio
    run_stdio(read_only=args.read_only)


def _run_mcp_config(args: argparse.Namespace) -> None:
    from dvm_eahelper.mcp_config import run_mcp_config
    run_mcp_config(install=args.install)


def _run_download(args: argparse.Namespace) -> None:
    from dvm_eahelper.server.autostart import ensure_server_running

    try:
        ensure_server_running()
    except RuntimeError as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    ssl_verify = _resolve_ssl(args)
    limit = getattr(args, "limit", None)
    if getattr(args, "relations", False) or getattr(args, "list_relations", False):
        from dvm_eahelper.leanix.download import run_download_relations
        run_download_relations(
            proxy_url=args.proxy,
            type_name=args.fs_type,
            output_path=args.output,
            list_relations=getattr(args, "list_relations", False),
            ssl_verify=ssl_verify,
            limit=limit,
        )
    else:
        from dvm_eahelper.leanix.download import run_download
        run_download(
            proxy_url=args.proxy,
            type_name=args.fs_type,
            subtypes=args.subtypes,
            output_path=args.output,
            fmt=args.fmt,
            list_subtypes=args.list_subtypes,
            list_types=args.list_types,
            ssl_verify=ssl_verify,
            limit=limit,
        )


def _run_proxy(args: argparse.Namespace) -> None:
    import uvicorn

    # ------------------------------------------------------------------ #
    # Resolve LeanIX URL                                                   #
    # ------------------------------------------------------------------ #
    leanix_url = args.url
    if not leanix_url:
        leanix_url = _prompt("LeanIX workspace URL", DEFAULT_URL)
    leanix_url = leanix_url.rstrip("/")

    print(f"\n  LeanIX workspace : {leanix_url}")

    # ------------------------------------------------------------------ #
    # Resolve SSL verification                                             #
    # ------------------------------------------------------------------ #
    ssl_verify = _resolve_ssl(args)

    # ------------------------------------------------------------------ #
    # Obtain Bearer token                                                  #
    # ------------------------------------------------------------------ #
    from dvm_eahelper.proxy.persistence import load_token, save_token

    token: str | None = None

    # Resolve API key: CLI flag takes priority, then env var
    api_key: str | None = getattr(args, "api_key", None) or os.environ.get("LEANIX_API_TOKEN")

    if args.token:
        # Explicit Bearer token provided via CLI — use it directly
        token = args.token
        print("  Token            : provided via --token flag")

    elif api_key:
        # Technical User API key — exchange for a Bearer token via OAuth2
        print("  Token source     : Technical User API key (OAuth2)")
        from dvm_eahelper.proxy.token import get_token_from_api_key
        try:
            ssl_for_oauth: bool | str = (
                False if ssl_verify is False
                else ssl_verify if isinstance(ssl_verify, str)
                else True
            )
            token = get_token_from_api_key(api_key, leanix_url, ssl_for_oauth)
            print("  Token            : obtained via OAuth2 client-credentials")
        except RuntimeError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        # Try loading a previously saved token
        saved = load_token(leanix_url)
        if saved:
            print("  Token            : loaded from ~/.eahelper/tokens.json")
            token = saved
        else:
            # No saved token — extract from browser
            token = _extract_from_browser(leanix_url, args.cdp_url)

    # Persist (unless --no-save or --token was used, where we still save)
    if not args.no_save:
        save_token(leanix_url, token)

    # ------------------------------------------------------------------ #
    # Build and start server                                               #
    # ------------------------------------------------------------------ #
    from dvm_eahelper.proxy.server import build_app

    app = build_app(leanix_url, token, cdp_url=args.cdp_url, ssl_verify=ssl_verify, api_key=api_key)

    host = "127.0.0.1"
    refresh_note = (
        f"    Token refresh    → POST http://{host}:{args.port}/token/refresh\n"
    )
    print(
        f"\n  ✓ Starting LeanIX GraphQL proxy on http://{host}:{args.port}\n"
        f"    GraphiQL UI      → http://{host}:{args.port}/graphql\n"
        f"    API endpoint     → POST http://{host}:{args.port}/graphql\n"
        f"    Upstream         → {leanix_url}/services/pathfinder/v1/graphql\n"
        + refresh_note +
        "\n  LeanIX GraphQL API docs:\n"
        "    https://help.sap.com/docs/leanix/ea/graphql-api\n"
        "\nPress Ctrl+C to stop.\n"
    )

    uvicorn.run(app, host=host, port=args.port, log_level="warning")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "help_library", False):
        from dvm_eahelper.leanix._library_help import LIBRARY_HELP
        print(LIBRARY_HELP)
        return

    if getattr(args, "func", None):
        args.func(args)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
