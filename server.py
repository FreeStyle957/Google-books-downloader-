"""
Local web service for Google Books Downloader.

Provides a small HTTP + SSE API that the single-page UI in static/index.html
drives. Exits by itself shortly after the browser tab stops sending heartbeats,
so no stray Edge/uvicorn processes are left behind.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import core  # noqa: E402

def _fix_missing_streams() -> None:
    """No console (pythonw / --windowed) leaves sys.stdout/stderr as None, which
    crashes uvicorn's log formatter. Point them at the null device instead."""
    sink = None
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            if sink is None:
                sink = open(os.devnull, "w", encoding="utf-8", errors="replace")
            setattr(sys, name, sink)


_fix_missing_streams()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _res_dir() -> Path:
    """Where bundled read-only assets (static/) live.

    PyInstaller unpacks them into a temp dir exposed as sys._MEIPASS; when
    running from source that is simply the project folder.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent


def _app_dir() -> Path:
    """Where user data goes (downloads/, logs). Always next to the executable."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = _res_dir()
APP_DIR = _app_dir()
STATIC = BASE / "static"
OUTROOT = APP_DIR / "downloads"

try:
    OUTROOT.mkdir(exist_ok=True)
except OSError:
    # Read-only location (e.g. Program Files): fall back to the user's Desktop
    # so downloads are still reachable and never silently lost.
    OUTROOT = Path.home() / "Desktop" / "GoogleBooksDownloads"
    OUTROOT.mkdir(parents=True, exist_ok=True)

# After the tab stops pinging, wait this long then shut everything down.
IDLE_TIMEOUT = float(os.environ.get("GBD_IDLE_TIMEOUT", "30"))

app = FastAPI(title="Google Books Downloader")

_state: dict[str, Any] = {
    "browser": None,
    "scan": None,          # core.ScanResult
    "last_out": None,
    "busy": False,
    "cancel": threading.Event(),
    "last_ping": time.time(),
    "lock": threading.Lock(),
    "shutdown": threading.Event(),
}

_prog_lock = threading.Lock()
_progress: list[str] = []


def push(msg: str) -> None:
    with _prog_lock:
        _progress.append(msg)
        if len(_progress) > 400:
            del _progress[:-200]


def drain_progress() -> list[str]:
    with _prog_lock:
        out = list(_progress)
        _progress.clear()
    return out


def ensure_browser() -> core.Browser:
    b = _state["browser"]
    if b is None or b.driver is None:
        b = core.Browser(headless=True)
        b.start()
        _state["browser"] = b
    return b


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.post("/api/ping")
def ping() -> dict:
    _state["last_ping"] = time.time()
    return {"ok": True, "edge": bool(_state["browser"])}


class ScanReq(BaseModel):
    url: str


@app.post("/api/scan")
def scan(req: ScanReq) -> dict:
    if _state["busy"]:
        raise HTTPException(409, "Another job is running.")
    _state["busy"] = True
    _state["cancel"] = threading.Event()
    try:
        browser = ensure_browser()
        push("Browser ready.")
        res = core.scan_book(
            req.url,
            browser,
            progress=push,
            max_rounds=int(os.environ.get("GBD_SCAN_ROUNDS", "260")),
            stop=_state["cancel"],
        )
        _state["scan"] = res
        numbers = sorted(res.pages)
        return {
            "ok": True,
            "title": res.title,
            "book_id": res.book_id,
            "count": res.count,
            "pages": numbers,
        }
    except core.GBDError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500)
    finally:
        _state["busy"] = False


class DownloadReq(BaseModel):
    selection: str = "all"
    make_pdf: bool = True
    folder: str = ""


@app.post("/api/download")
def download(req: DownloadReq) -> dict:
    if _state["busy"]:
        raise HTTPException(409, "Another job is running.")
    res: core.ScanResult | None = _state["scan"]
    if res is None:
        raise HTTPException(400, "Scan a book first.")

    _state["busy"] = True
    _state["cancel"] = threading.Event()
    try:
        chosen = core.select_pages(req.selection, res.pages)
        push(f"Selected {len(chosen)} page(s).")

        parent = Path(req.folder) if req.folder.strip() else OUTROOT
        slug = core._safe(res.title)
        outdir = parent / slug
        outdir.mkdir(parents=True, exist_ok=True)

        def prog(i: int, total: int, label: str) -> None:
            push(f"[{i}/{total}] {label}")

        # Download through the browser when we still have it: Python's requests
        # goes through the machine proxy, which often 502s on books.google.com.
        fetcher = None
        br = _state.get("browser")
        if br is not None and br.driver is not None:
            try:
                fetcher = core.make_browser_fetcher(br.driver)
            except Exception:  # noqa: BLE001
                fetcher = None
        push("Downloading via browser." if fetcher else "Downloading via requests.")

        files = core.download_pages(
            chosen, outdir, progress=prog, stop=_state["cancel"], fetcher=fetcher
        )
        pdf = None
        if req.make_pdf and files:
            push("Building PDF ...")
            try:
                pdf = core.make_pdf(files, core._fit_path(outdir, slug, ".pdf"))
            except Exception as exc:  # noqa: BLE001 - pages are already saved
                push(f"PDF skipped: {exc}")
                pdf = None
            if not pdf:
                push("PDF could not be built; page images were still saved.")

        _state["last_out"] = str(outdir)
        return {
            "ok": True,
            "files": len(files),
            "dir": str(outdir),
            "pdf": str(pdf) if pdf else None,
        }
    except core.GBDError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500)
    finally:
        _state["busy"] = False


@app.post("/api/cancel")
def cancel() -> dict:
    _state["cancel"].set()
    push("Cancel requested.")
    return {"ok": True}


@app.get("/api/progress")
def progress():
    def gen():
        while True:
            msgs = drain_progress()
            for m in msgs:
                yield f"data: {json.dumps({'msg': m}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'busy': _state['busy']}, ensure_ascii=False)}\n\n"
            time.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream")


class OpenReq(BaseModel):
    path: str = ""


@app.post("/api/open")
def open_folder(req: OpenReq) -> dict:
    target = req.path or _state.get("last_out") or str(OUTROOT)
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", target])
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/quit")
def quit_server() -> dict:
    _state["shutdown"].set()
    return {"ok": True}


def _log(msg: str) -> None:
    """Optional trace file (GBD_DEBUG=1) next to the exe, for field support."""
    if not os.environ.get("GBD_DEBUG"):
        return
    try:
        with open(APP_DIR / "gbd.log", "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _idle_watchdog() -> None:
    while not _state["shutdown"].is_set():
        time.sleep(3)
        if _state["busy"]:
            continue
        idle = time.time() - _state["last_ping"]
        if idle > IDLE_TIMEOUT:
            _log(f"idle {idle:.0f}s > {IDLE_TIMEOUT}s -> shutting down")
            _shutdown()
            return


def _shutdown() -> None:
    _log("shutdown: closing browser")
    # Hard bail-out: even if Edge/driver teardown hangs, the process must die.
    threading.Timer(10.0, lambda: os._exit(0)).start()
    try:
        b = _state.get("browser")
        if b:
            b.close()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.3)
    os._exit(0)


def main() -> None:
    port = int(os.environ.get("GBD_PORT", "8733"))
    threading.Thread(target=_idle_watchdog, daemon=True).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
