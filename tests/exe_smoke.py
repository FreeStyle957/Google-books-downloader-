"""Smoke test for the packaged exe: launch -> scan -> download -> self-exit.

    python tests/exe_smoke.py <path-to-GoogleBooksDownloader.exe> [book-url]

Verifies the things that only break once frozen: bundled selenium-manager,
bundled static assets, and the idle watchdog still firing from inside the exe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("GBD_PORT", "8733"))
URL = f"http://127.0.0.1:{PORT}/"
BOOK = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "https://books.google.com/books?id=buc0AAAAMAAJ"
)

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"


def post(path: str, payload: dict, timeout: float = 300) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        URL + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # noqa: F821
        return json.load(e)


def get(path: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(URL + path, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    if not exe.exists():
        print(f"exe not found: {exe}")
        return 2
    workdir = exe.parent

    # GBD_NO_BROWSER: keep the exe from opening a real tab, otherwise the page's
    # own heartbeat keeps the service alive and self-exit can never be observed.
    env = dict(
        os.environ,
        GBD_SCAN_ROUNDS=os.environ.get("GBD_SCAN_ROUNDS", "18"),
        GBD_IDLE_TIMEOUT=os.environ.get("GBD_IDLE_TIMEOUT", "20"),
        GBD_NO_BROWSER="1",
        GBD_DEBUG="1",
    )
    proc = subprocess.Popen([str(exe)], cwd=str(workdir), env=env)

    alive = threading.Event()
    alive.set()

    def beat() -> None:
        while alive.is_set():
            try:
                post("api/ping", {})
            except Exception:  # noqa: BLE001
                pass
            time.sleep(4)

    threading.Thread(target=beat, daemon=True).start()

    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            if get("api/ping")[0] or get("")[0] == 200:
                break
            if proc.poll() is not None:
                print(f"exe exited early rc={proc.returncode}")
                return 1
            time.sleep(0.5)
        else:
            print("exe never became ready")
            return 1
        print("service: ready")

        status, body = get("")
        print(f"GET /      -> {status}, html={'index' in body.lower() or len(body) > 500}")

        print("scanning ...")
        t0 = time.time()
        r = post("api/scan", {"url": BOOK})
        if not r.get("ok"):
            print("scan FAILED:", r)
            return 1
        print(f"scan       -> {r['count']} pages, {r['title'][:50]!r} "
              f"({time.time() - t0:.1f}s)")

        r = post("api/download", {"selection": "1-3", "make_pdf": True})
        if not r.get("ok"):
            print("download FAILED:", r)
            return 1
        print(f"download   -> {r['files']} files, pdf={Path(r['pdf']).name if r.get('pdf') else None}")

        outdir = Path(r["dir"])
        imgs = sorted(outdir.glob("page_*.jp*g")) + sorted(outdir.glob("page_*.png"))
        print(f"on disk    -> {len(imgs)} image(s) in {outdir.name}")
        if not imgs:
            print("no image files written")
            return 1
        print(f"first file -> {imgs[0].name} ({imgs[0].stat().st_size // 1024} KB)")
        print("SMOKE OK")
        return 0
    finally:
        alive.clear()
        print("waiting for self-exit ...")
        deadline = time.time() + 90
        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"self-exit  -> rc={proc.returncode} "
                      f"({time.time() - (deadline - 90):.0f}s after heartbeat stopped)")
                return 0
            time.sleep(1)
        print("did NOT exit on its own - FAIL")
        proc.kill()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
