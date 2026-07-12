"""
autostart — ensure `eahelper server` is running before commands that need the
proxy (graph load, leanix download). If unreachable, spawns
`python -m dvm_eahelper server start` as a detached background process and
waits for /healthz.
"""

from __future__ import annotations

import subprocess
import sys
import time

from dvm_eahelper.server.daemon import is_server_healthy, resolve_port


def ensure_server_running(port: int | None = None, wait_timeout: float = 30.0) -> int:
    """Ensure the eahelper server is healthy on *port*, auto-starting it if not.

    Returns the resolved port. Raises RuntimeError if it cannot be started
    within wait_timeout.
    """
    resolved_port = resolve_port(port)

    if is_server_healthy(resolved_port):
        return resolved_port

    print(
        f"  eahelper server not reachable on port {resolved_port} — auto-starting "
        f"(python -m dvm_eahelper server start)..."
    )
    subprocess.run(
        [sys.executable, "-m", "dvm_eahelper", "server", "start"],
        check=False,
    )

    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if is_server_healthy(resolved_port):
            print(f"  eahelper server is up on http://127.0.0.1:{resolved_port}")
            return resolved_port
        time.sleep(0.5)

    raise RuntimeError(
        f"Could not auto-start eahelper server on port {resolved_port} within "
        f"{wait_timeout}s. Run 'eahelper server start' manually and check "
        f"~/.eahelper/server.log for details."
    )
