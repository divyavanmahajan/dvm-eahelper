"""
mcp_server — embedded MCP (Model Context Protocol) server exposing the eahelper
graph database (KuzuDB or Neo4j) to MCP-aware harnesses (Claude Code, VS Code
Copilot, etc.) via two tools: get_schema() and query(cypher).

Backend is opened per-call rather than held open for the process lifetime.
KuzuDB is single-writer/embedded: while another eahelper process (e.g.
`eahelper load`) holds the database open, a concurrent open from here will
raise a clear "database locked" error surfaced to the MCP caller.

Two transports:
  - Mounted at /mcp (streamable HTTP) inside the `eahelper server` supervisor app.
  - `eahelper mcp` — stdio transport, for harnesses that spawn a subprocess.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from dvm_eahelper.config import get_setting

_WRITE_KEYWORDS = (
    "CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP",
    "ALTER", "COPY", "LOAD", "INSTALL", "DETACH",
)


def _is_write_query(cypher: str) -> bool:
    upper = cypher.upper()
    return any(kw in upper for kw in _WRITE_KEYWORDS)


def _read_only_setting(cli_read_only: bool | None = None) -> bool:
    value = get_setting(
        "graph", "mcp_read_only",
        cli_value=cli_read_only,
        default=False,
    )
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def create_mcp_server(read_only: bool | None = None) -> FastMCP:
    """Build the FastMCP server instance with get_schema and query tools registered."""
    mcp = FastMCP(
        name="eahelper",
        instructions=(
            "Tools for querying the eahelper enterprise-architecture graph database "
            "(LeanIX factsheets/relationships loaded into KuzuDB or Neo4j)."
        ),
        json_response=True,
        stateless_http=True,
        streamable_http_path="/",
    )

    effective_read_only = _read_only_setting(read_only)

    def _open_backend():
        from dvm_eahelper.graph.select import resolve_backend_from_config

        return resolve_backend_from_config(read_only=effective_read_only)

    @mcp.tool()
    def get_schema() -> str:
        """Return the graph database schema: node tables/labels with properties,
        and relationship types, as JSON."""
        backend = _open_backend()
        try:
            with backend:
                schema = backend.get_schema()
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(schema, indent=2)

    @mcp.tool()
    def query(cypher: str) -> str:
        """Run a Cypher query against the graph database and return rows as JSON.

        Read-write by default. If the server is configured with mcp_read_only
        (config.toml [graph].mcp_read_only=true, or --mcp-read-only), write
        queries (CREATE/MERGE/DELETE/SET/...) are rejected."""
        if effective_read_only and _is_write_query(cypher):
            return json.dumps({
                "error": (
                    "This MCP server is read-only (mcp_read_only=true). "
                    "Write queries (CREATE/MERGE/DELETE/SET/...) are rejected."
                )
            })
        backend = _open_backend()
        try:
            with backend:
                rows = backend.run_query(cypher)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(rows, indent=2, default=str)

    return mcp


def run_stdio(read_only: bool | None = None) -> None:
    """Run the MCP server over stdio (for harnesses that spawn a subprocess)."""
    mcp = create_mcp_server(read_only=read_only)
    mcp.run(transport="stdio")
