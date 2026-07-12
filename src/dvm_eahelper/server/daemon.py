"""
daemon — background process management for `eahelper server start/stop/status`.

Pidfile: ~/.eahelper/server.pid
Log:     ~/.eahelper/server.log
"""

from __future__ import annotations

import subprocess
import sys
import time

import httpx

from dvm_eahelper.config import config_dir, get_setting


def pid_file():
    return config_dir() / "server.pid"


def log_file():
    return config_dir() / "server.log"


def _spawn_kwargs() -> dict:
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            "close_fds": True,
        }
    return {"start_new_session": True, "close_fds": True}


def _read_pid() -> int | None:
    f = pid_file()
    if not f.exists():
        return None
    try:
        return int(f.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in result.stdout
    try:
        import os

        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/healthz"


def is_server_healthy(port: int, timeout: float = 1.0) -> bool:
    try:
        resp = httpx.get(health_url(port), timeout=timeout)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def resolve_port(cli_port: int | None = None) -> int:
    return int(get_setting("leanix", "proxy_port", cli_value=cli_port, env_var="EAHELPER_PROXY_PORT", default=8765))


def start(
    port: int | None = None,
    keep_browser: bool = False,
    mcp_read_only: bool = False,
    wait_timeout: float = 30.0,
) -> None:
    resolved_port = resolve_port(port)

    if is_server_healthy(resolved_port):
        print(f"  eahelper server already running and healthy on port {resolved_port}.")
        return

    pid = _read_pid()
    if pid and _is_process_alive(pid):
        print(f"  eahelper server process (pid {pid}) is running but not yet healthy — waiting...")
    else:
        args = [sys.executable, "-m", "dvm_eahelper", "server", "--foreground"]
        if keep_browser:
            args.append("--keep-browser")
        if mcp_read_only:
            args.append("--mcp-read-only")
        if port:
            args += ["--port", str(port)]

        config_dir().mkdir(parents=True, exist_ok=True)
        log = log_file().open("a", encoding="utf-8")
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **_spawn_kwargs(),
        )
        pid_file().write_text(str(proc.pid), encoding="utf-8")
        print(f"  Starting eahelper server (pid {proc.pid}) on port {resolved_port}, logging to {log_file()}...")

    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if is_server_healthy(resolved_port):
            print(f"  eahelper server healthy on http://127.0.0.1:{resolved_port}")
            return
        time.sleep(0.5)

    raise RuntimeError(
        f"Timed out after {wait_timeout}s waiting for eahelper server to become healthy on "
        f"port {resolved_port}. Check the log at {log_file()}."
    )


def stop() -> None:
    pid = _read_pid()
    if pid is None:
        print("  No eahelper server pidfile found — nothing to stop.")
        return

    if not _is_process_alive(pid):
        print("  eahelper server process is not running (stale pidfile) — cleaning up.")
        pid_file().unlink(missing_ok=True)
        return

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        import os
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    pid_file().unlink(missing_ok=True)
    print(f"  Stopped eahelper server (pid {pid}).")


def status(port: int | None = None) -> None:
    resolved_port = resolve_port(port)
    pid = _read_pid()
    alive = pid is not None and _is_process_alive(pid)
    healthy = is_server_healthy(resolved_port)

    print(f"  pidfile          : {pid_file()}")
    print(f"  pid              : {pid if pid is not None else '(none)'}")
    print(f"  process alive    : {alive}")
    print(f"  health endpoint  : {health_url(resolved_port)}")
    print(f"  healthy          : {healthy}")

    if healthy:
        print("  status           : RUNNING")
    elif alive:
        print("  status           : STARTING or UNHEALTHY")
    else:
        print("  status           : STOPPED")
