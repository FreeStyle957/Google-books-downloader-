"""
Google Books Downloader - single entry point.

Double-clicking the built .exe (or running `python app.py`) does everything:

  1. starts the local web service on 127.0.0.1:8733
  2. opens the UI in the default browser
  3. stays alive until the tab is closed, then exits with no leftovers

Works both from source and from a PyInstaller bundle.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Must precede selenium: a global http_proxy hijacks the localhost channel
# between Python and the browser driver.
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def fix_missing_streams() -> None:
    """Give sys.stdout/stderr a sink when there is no console.

    PyInstaller's --windowed build (and pythonw.exe) leaves both as None, and
    uvicorn's log formatter calls sys.stderr.isatty() at startup, which then
    raises and kills the service before it ever binds its port.
    """
    sink = None
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            if sink is None:
                sink = open(os.devnull, "w", encoding="utf-8", errors="replace")
            setattr(sys, name, sink)


def app_dir() -> Path:
    """Folder user data belongs in: next to the exe, or next to app.py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return HERE


def log_path() -> Path:
    return app_dir() / "gbd.log"


def _log(msg: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def port_open(port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def service_healthy(url: str) -> bool:
    """Port answers OUR api - rules out a squatter."""
    try:
        with urllib.request.urlopen(url + "api/ping", data=b"{}", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    fix_missing_streams()
    import server  # imported late: it pulls in selenium/uvicorn

    port = int(os.environ.get("GBD_PORT", "8733"))
    url = f"http://127.0.0.1:{port}/"

    try:
        log_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    _log(f"start (frozen={getattr(sys, 'frozen', False)}) app_dir={app_dir()}")

    if service_healthy(url):
        # Already running (e.g. a second double-click): just show the UI.
        webbrowser.open(url)
        return 0
    if port_open(port):
        _log(f"port {port} busy, not ours - refusing to start")
        return 1

    failure: list[str] = []

    def run_server() -> None:
        try:
            server.main()
        except BaseException as exc:  # noqa: BLE001 - surfaced in gbd.log
            failure.append(f"{type(exc).__name__}: {exc}")
            _log(f"service crashed: {failure[-1]}")
            import traceback

            _log(traceback.format_exc())

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    deadline = time.time() + 120
    ready = False
    while time.time() < deadline:
        if failure:
            return 1
        if service_healthy(url):
            ready = True
            break
        # Keep the idle watchdog patient while we are still booting, otherwise a
        # slow cold start gets killed (and its real cause never surfaces).
        server._state["last_ping"] = time.time()
        time.sleep(0.4)
    if not ready:
        _log("service never became ready - see gbd.log")
        return 1

    # The idle watchdog counts from the last ping; there has not been one yet,
    # so restart the clock now or a slow cold start would shut us right back down.
    server._state["last_ping"] = time.time()

    if os.environ.get("GBD_NO_BROWSER"):
        # Headless/CI mode: run the service without popping a tab open.
        _log("service ready (GBD_NO_BROWSER set, not opening a tab)")
    else:
        _log("service ready, opening browser")
        webbrowser.open(url)

    # Idle here. The service's watchdog calls os._exit() once the tab stops
    # pinging, which ends this process too - nothing is left behind.
    while not server._state["shutdown"].is_set():
        if failure or not t.is_alive():
            _log("service thread ended unexpectedly")
            return 1
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        _log(f"FATAL: {type(exc).__name__}: {exc}")
        raise
