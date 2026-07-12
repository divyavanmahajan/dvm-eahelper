"""
supervisor — the `eahelper server` runtime.

Runs the GraphQL proxy (proxy/server.py's FastAPI app) and mounts the embedded
MCP server (mcp_server.py) at /mcp, in a single uvicorn process on
[leanix].proxy_port.

Browser lifecycle: when a LeanIX token is needed (startup with no valid cached
token, or the proxy signals a 401/expired token), a managed browser is launched
on demand, the token is captured, then the browser is closed again (unless
[browser].keep_open or --keep-browser was requested). The browser is relaunched
automatically the next time a token is needed. A browser this process did not
launch itself is never closed (see server/browser.py's PID tracking).
"""

from __future__ import annotations

import contextlib

from dvm_eahelper.config import get_setting


def _capture_token_via_browser(leanix_url: str, keep_browser: bool) -> str | None:
    from dvm_eahelper.server.browser import ensure_browser, stop_browser

    try:
        cdp = ensure_browser()
    except RuntimeError as exc:
        print(f"  WARNING: could not launch managed browser: {exc}")
        return None

    try:
        from dvm_eahelper.proxy.token import get_token_sync

        token = get_token_sync(leanix_url, cdp)
        print("  Token captured from managed browser.")
        return token
    except RuntimeError as exc:
        print(f"  WARNING: token capture failed: {exc}")
        return None
    finally:
        if not keep_browser:
            stop_browser()


def build_supervisor_app(
    leanix_url: str | None,
    proxy_port: int,
    keep_browser: bool = False,
    mcp_read_only: bool | None = None,
    ssl_verify=True,
    api_key: str | None = None,
):
    """Build the combined FastAPI app: GraphQL proxy + mounted MCP server."""
    from dvm_eahelper.mcp_server import create_mcp_server
    from dvm_eahelper.proxy.persistence import load_token
    from dvm_eahelper.proxy.server import build_app
    from dvm_eahelper.server.browser import cdp_url

    initial_token: str | None = None
    if leanix_url:
        initial_token = load_token(leanix_url)

    mcp = create_mcp_server(read_only=mcp_read_only)
    mcp_asgi_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        import asyncio

        capture_task = None
        if leanix_url and not initial_token and not api_key:

            async def _bootstrap_token():
                print("  No cached LeanIX token — capturing in the background via managed browser.")
                token = await asyncio.to_thread(_capture_token_via_browser, leanix_url, keep_browser)
                if token:
                    from dvm_eahelper.proxy.persistence import save_token

                    save_token(leanix_url, token)
                    app.state.set_token(token)

            capture_task = asyncio.create_task(_bootstrap_token())

        async with mcp.session_manager.run():
            yield

        if capture_task and not capture_task.done():
            capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await capture_task

    app = build_app(
        leanix_url,
        initial_token,
        cdp_url=cdp_url() if leanix_url else None,
        ssl_verify=ssl_verify,
        api_key=api_key,
        lifespan=lifespan,
    )
    app.mount("/mcp", mcp_asgi_app)

    return app


def run_foreground(
    proxy_port: int | None = None,
    leanix_url: str | None = None,
    keep_browser: bool = False,
    mcp_read_only: bool | None = None,
) -> None:
    import uvicorn

    port = get_setting("leanix", "proxy_port", cli_value=proxy_port, env_var="EAHELPER_PROXY_PORT", default=8765)
    port = int(port)

    url = get_setting(
        "leanix", "workspace_url",
        cli_value=leanix_url,
        env_var="LEANIX_WORKSPACE_URL",
        prompt="LeanIX workspace URL (leave blank to configure later)",
        default="",
    )
    url = (url or "").rstrip("/") or None

    app = build_supervisor_app(
        url,
        port,
        keep_browser=keep_browser,
        mcp_read_only=mcp_read_only,
    )

    host = "127.0.0.1"
    print(
        f"\n  eahelper server running on http://{host}:{port}\n"
        f"    GraphQL proxy    → http://{host}:{port}/graphql\n"
        f"    Health check     → http://{host}:{port}/healthz\n"
        f"    MCP endpoint     → http://{host}:{port}/mcp\n"
        "\nPress Ctrl+C to stop.\n"
    )

    uvicorn.run(app, host=host, port=port, log_level="warning")
