"""server_cli — `eahelper server` subcommand: start/stop/status/foreground."""

from __future__ import annotations

import argparse
import sys


def _add_server_subcommand(subparsers: argparse._SubParsersAction) -> None:
    srv = subparsers.add_parser(
        "server",
        help="Run the eahelper server: GraphQL proxy + embedded MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Runs the LeanIX GraphQL proxy and the embedded MCP server (mounted at /mcp) "
            "in one process. Manages a debug browser automatically when a LeanIX token "
            "is needed.\n\n"
            "  eahelper server            run in the foreground\n"
            "  eahelper server start       run detached in the background\n"
            "  eahelper server stop        stop the background server\n"
            "  eahelper server status      check whether it is running"
        ),
    )
    srv.add_argument(
        "action",
        nargs="?",
        choices=["start", "stop", "status"],
        default=None,
        help="Background daemon action. Omit to run in the foreground.",
    )
    srv.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    srv.add_argument("--port", type=int, default=None, help="Proxy/MCP port (default: config leanix.proxy_port)")
    srv.add_argument("--url", metavar="URL", default=None, help="LeanIX workspace base URL")
    srv.add_argument(
        "--keep-browser",
        action="store_true",
        default=False,
        help="Keep the managed browser open after token capture (default: close it)",
    )
    srv.add_argument(
        "--mcp-read-only",
        action="store_true",
        default=False,
        help="Reject write Cypher queries via the MCP query tool",
    )
    srv.set_defaults(func=_run_server)


def _run_server(args: argparse.Namespace) -> None:
    action = args.action

    if action == "start":
        from dvm_eahelper.server.daemon import start

        try:
            start(port=args.port, keep_browser=args.keep_browser, mcp_read_only=args.mcp_read_only)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if action == "stop":
        from dvm_eahelper.server.daemon import stop

        stop()
        return

    if action == "status":
        from dvm_eahelper.server.daemon import status

        status(port=args.port)
        return

    from dvm_eahelper.server.supervisor import run_foreground

    run_foreground(
        proxy_port=args.port,
        leanix_url=args.url,
        keep_browser=args.keep_browser,
        mcp_read_only=args.mcp_read_only,
    )


def register(subparsers: argparse._SubParsersAction) -> None:
    _add_server_subcommand(subparsers)
