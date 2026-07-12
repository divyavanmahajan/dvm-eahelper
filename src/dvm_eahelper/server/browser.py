"""
browser — launch/stop a managed debug browser (Chrome or Edge) for CDP access.

Uses a persistent user-data-dir at ~/.eahelper/browser-profile so the user's
LeanIX login survives across launches. Tracks the PID of a browser process we
launched ourselves in ~/.eahelper/browser.pid so we never kill a browser we
didn't start.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

from dvm_eahelper.config import config_dir, get_setting, set_config_value

DEFAULT_CDP_PORT = 19222


def browser_profile_dir() -> Path:
    path = config_dir() / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_pid_file() -> Path:
    return config_dir() / "browser.pid"


def _candidate_executables() -> dict[str, list[Path]]:
    if sys.platform == "darwin":
        return {
            "chrome": [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ],
            "edge": [
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ],
        }
    if sys.platform == "win32":
        import os

        program_files = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        chrome_paths = [
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"
            for pf in program_files if pf
        ]
        edge_paths = [
            Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            for pf in program_files if pf
        ]
        return {"chrome": chrome_paths, "edge": edge_paths}
    # Linux / other POSIX — best effort, rarely used for this tool
    return {
        "chrome": [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium-browser")],
        "edge": [Path("/usr/bin/microsoft-edge")],
    }


def discover_browsers() -> dict[str, Path]:
    """Return {"chrome": path, "edge": path} for browsers found on this machine."""
    found: dict[str, Path] = {}
    for name, candidates in _candidate_executables().items():
        for path in candidates:
            if path.exists():
                found[name] = path
                break
    return found


def choose_browser(cli_browser: str | None = None) -> tuple[str, Path]:
    """
    Decide which browser to launch, following config resolution + platform rules.

    On Windows, Edge's CDP support requires the user to close ALL Edge windows
    first (a well-known limitation), so Chrome is preferred when both are
    available. If only Edge is available on Windows, warn and (TTY) confirm.
    """
    found = discover_browsers()
    if not found:
        raise RuntimeError(
            "No supported browser found (Chrome or Edge). Install Google Chrome "
            "or Microsoft Edge, or start one manually with --remote-debugging-port "
            f"={DEFAULT_CDP_PORT} and pass --connect."
        )

    choice = get_setting(
        "browser", "browser",
        cli_value=cli_browser,
        env_var="EAHELPER_BROWSER",
        default="",
    )

    if choice and choice in found:
        return choice, found[choice]

    if sys.platform == "win32":
        if "chrome" in found:
            chosen = "chrome"
        else:
            chosen = "edge"
            print(
                "  WARNING: only Microsoft Edge was found. Edge's remote-debugging "
                "support requires ALL Edge windows to be closed first, or it will "
                "silently ignore --remote-debugging-port and CDP capture will fail."
            )
            if sys.stdin.isatty():
                answer = input("  Continue with Edge anyway? [y/N]: ").strip().lower()
                if answer not in ("y", "yes"):
                    raise RuntimeError(
                        "Aborted. Install Google Chrome for a smoother experience, "
                        "or close all Edge windows and retry."
                    )
    else:
        chosen = "chrome" if "chrome" in found else next(iter(found))

    set_config_value("browser.browser", chosen)
    return chosen, found[chosen]


def cdp_url(port: int | None = None) -> str:
    p = port or get_setting("browser", "cdp_port", env_var="EAHELPER_CDP_PORT", default=DEFAULT_CDP_PORT)
    return f"http://127.0.0.1:{p}"


def is_browser_ready(port: int, timeout: float = 1.0) -> bool:
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _spawn_kwargs() -> dict:
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            "close_fds": True,
        }
    return {"start_new_session": True, "close_fds": True}


def launch_browser(
    port: int | None = None,
    browser: str | None = None,
    wait_timeout: float = 20.0,
) -> str:
    """
    Launch a managed debug browser with CDP enabled, waiting until it is ready.
    Returns the CDP URL. Raises RuntimeError on failure or timeout.
    """
    port = port or get_setting("browser", "cdp_port", env_var="EAHELPER_CDP_PORT", default=DEFAULT_CDP_PORT)

    if is_browser_ready(port):
        return cdp_url(port)

    name, exe = choose_browser(browser)
    profile_dir = browser_profile_dir()

    args = [
        str(exe),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    print(f"  Launching managed {name} (CDP port {port})...")
    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_spawn_kwargs(),
    )

    browser_pid_file().parent.mkdir(parents=True, exist_ok=True)
    browser_pid_file().write_text(str(proc.pid), encoding="utf-8")

    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if is_browser_ready(port):
            return cdp_url(port)
        time.sleep(0.5)

    raise RuntimeError(
        f"Timed out waiting for {name} to expose CDP on port {port} "
        f"after {wait_timeout}s."
    )


def _read_managed_pid() -> int | None:
    f = browser_pid_file()
    if not f.exists():
        return None
    try:
        return int(f.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def stop_browser() -> bool:
    """
    Stop the browser we launched (by PID from browser.pid), if any.
    Never touches a browser we didn't launch. Returns True if a process was stopped.
    """
    pid = _read_managed_pid()
    if pid is None:
        return False

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            import os
            import signal

            os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    finally:
        try:
            browser_pid_file().unlink()
        except OSError:
            pass
    return True


def ensure_browser(port: int | None = None, browser: str | None = None) -> str:
    """Ensure a CDP-enabled browser is running, launching one if necessary."""
    port = port or get_setting("browser", "cdp_port", env_var="EAHELPER_CDP_PORT", default=DEFAULT_CDP_PORT)
    if is_browser_ready(port):
        return cdp_url(port)
    return launch_browser(port=port, browser=browser)
