"""
Google Books Downloader - core engine (Windows / Microsoft Edge).

Rewritten from aprikyan/google-books-downloader (gbd.py, 2020) because the
original stack no longer works:

  * bundled chromedriver.exe is v83 and cannot drive any modern browser
  * selenium-wire's request interception is not usable on Edge 154
  * Edge 154 dropped the "performance" log type, so `driver.get_log` is dead

The page-image URLs are instead captured straight from the DevTools protocol
websocket, which is what selenium-wire was doing under the hood anyway.

Network access to books.google.com needs no cookie - the `sig` token embedded
in each captured URL is enough, and `&w=69420` still yields the highest
resolution Google is willing to serve.
"""

from __future__ import annotations

import json
import base64
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse
from pathlib import Path
from typing import Callable

# The sandbox/global http_proxy would otherwise hijack the localhost channel
# between Python and msedgedriver. Must be set before selenium is imported.
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import requests  # noqa: E402
import websocket  # noqa: E402
from selenium import webdriver  # noqa: E402
from selenium.common.exceptions import WebDriverException  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.edge.options import Options  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Ask for the widest image Google will render for a page.
HIRES_WIDTH = 69420

# Windows MAX_PATH is 260; leave headroom for separators and long parent dirs.
PATH_BUDGET = 240
NAME_MAX = 80

# Any Chromium-based browser works. Tried in this order; the first one that
# exists on disk wins. Override with GBD_BROWSER_PATH=/path/to/browser.exe.
BROWSER_CANDIDATES: list[tuple[str, str]] = [
    ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ("edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ("edge", r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ("brave", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ("brave", r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"),
]

# Google Books URL shapes we accept:
#   legacy : books.google.com/books?id=buc0AAAAMAAJ&pg=1
#   current: google.com.sg/books/edition/<title-slug>/PqFUCwAAQBAJ?hl=zh-CN
#   current: ... /books/edition/_/PqFUCwAAQBAJ  (empty slug)
ID_RE = re.compile(r"[?&]id=([A-Za-z0-9_\-]{8,})")
EDITION_RE = re.compile(r"/books/edition/[^/?#]*/([A-Za-z0-9_\-]{8,})")
TAIL_RE = re.compile(r"/books/[^/?#]+/([A-Za-z0-9_\-]{10,})(?=[/?#]|$)")
HL_RE = re.compile(r"[?&]hl=([A-Za-z\-]{2,})")

# Captures e.g.
#   https://books.google.com/books/content?id=X&pg=PP1&img=1&zoom=3&sig=..&w=1280
#   https://books.google.com/books/publisher/content?id=X&pg=PA14&...   (publisher-hosted)
# The `publisher/` segment is optional: volumes supplied by a publisher use it,
# and missing it meant those books scanned zero pages.
# The trailing run must be GREEDY: a lazy match stops right after the digits and
# drops the `sig` token, and Google then answers 404 for the image.
# group(0)=full url, group(1)=page prefix (PP/PA/PT...), group(2)=page number
URL_RE = re.compile(
    r"https://[^\s'\"]*?/books/(?:publisher/)?content\?"
    r"[^\s'\"]*?\bpg=([A-Z]{1,3})(\d+)[^\s'\"]*"
)
CONTENT_MARK_RE = re.compile(r"/books/(?:publisher/)?content\?")


class GBDError(Exception):
    """User-facing failure."""


def _registry_browser() -> tuple[str, str] | None:
    """Ask the registry where the default Edge/Chrome lives (Windows)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg

        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe", "edge"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", "chrome"),
        ]
        for root, sub, kind in keys:
            try:
                with winreg.OpenKey(root, sub) as k:
                    path = winreg.QueryValue(k, None)
                    if path and os.path.exists(path):
                        return kind, path
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def find_browser() -> tuple[str, str]:
    """Return (kind, path) for an installed Chromium browser.

    `kind` is one of edge / chrome / brave and decides which Selenium driver and
    options class we use. Honours GBD_BROWSER_PATH (and the legacy
    GBD_EDGE_PATH) so a portable browser can be pointed at explicitly.
    """
    override = os.environ.get("GBD_BROWSER_PATH") or os.environ.get("GBD_EDGE_PATH")
    if override:
        if not os.path.exists(override):
            raise GBDError(f"GBD_BROWSER_PATH points at a missing file: {override}")
        low = override.lower()
        kind = "chrome" if "chrome" in low else "brave" if "brave" in low else "edge"
        return kind, override

    for kind, raw in BROWSER_CANDIDATES:
        path = os.path.expandvars(raw)
        if path and os.path.exists(path):
            return kind, path

    found = _registry_browser()
    if found:
        return found

    for exe, kind in (("msedge", "edge"), ("chrome", "chrome"),
                      ("google-chrome", "chrome"), ("chromium", "chrome")):
        hit = shutil.which(exe)
        if hit:
            return kind, hit

    raise GBDError(
        "No Chromium browser found. Install Microsoft Edge or Google Chrome "
        "(Brave works too), or set GBD_BROWSER_PATH to the browser executable."
    )


def normalize_book_url(url: str) -> tuple[str, str, str]:
    """Return (book_id, data_url, embed_url) from any Google Books URL."""
    url = (url or "").strip()
    if not url:
        raise GBDError("No URL given.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    m = ID_RE.search(url) or EDITION_RE.search(url) or TAIL_RE.search(url)
    if not m:
        raise GBDError(
            "Cannot find a book id in that URL. Expected either "
            "'...?id=XXXX' or '.../books/edition/<title>/XXXX'."
        )
    book_id = m.group(1)

    # Honour the language the user was browsing in; helps non-English volumes.
    hm = HL_RE.search(url)
    hl = hm.group(1) if hm else "en"

    # Always start from books.google.com (no "www.") and let Google pick the
    # regional site. Measured: books.google.com -> books.google.com.sg renders the
    # reader fine, while www.google.com.sg redirects to books.google.cn, which
    # serves no preview at all.
    host = "books.google.com"

    data_url = (
        f"https://{host}/books?id={book_id}&pg=1&hl={hl}#v=onepage&q&f=false"
    )
    embed_url = (
        f"https://{host}/books?id={book_id}&pg=1&hl={hl}"
        "&f=false&output=embed&source=gbs_embed"
    )
    return book_id, data_url, embed_url


# --------------------------------------------------------------------------- #


@dataclass
class Page:
    number: int
    label: str          # raw Google page marker, e.g. "PP1", "PA42"
    url: str
    hires_url: str = ""

    def __post_init__(self) -> None:
        if not self.hires_url:
            self.hires_url = re.sub(r"([&?])w=\d+", r"\1w=" + str(HIRES_WIDTH), self.url)
            if f"w={HIRES_WIDTH}" not in self.hires_url:
                sep = "&" if "?" in self.hires_url else "?"
                self.hires_url = f"{self.hires_url}{sep}w={HIRES_WIDTH}"


@dataclass
class ScanResult:
    title: str
    book_id: str
    pages: dict[int, Page] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.pages)


def _driver_classes(kind: str):
    """(Options, WebDriver) for a browser kind."""
    if kind == "chrome":
        from selenium.webdriver.chrome.options import Options as _Opts

        return _Opts, webdriver.Chrome
    if kind == "brave":
        from selenium.webdriver.chrome.options import Options as _Opts

        return _Opts, webdriver.Chrome
    from selenium.webdriver.edge.options import Options as _Opts

    return _Opts, webdriver.Edge


class Browser:
    """Owns a Chromium instance (Edge / Chrome / Brave).

    The browser is launched by us with a remote-debugging port so that we can
    attach both Selenium (for interaction) and a raw CDP socket (for network
    events). Selenium Manager fetches the matching driver automatically.
    """

    def __init__(self, port: int | None = None, headless: bool = True) -> None:
        self.kind, self.edge = find_browser()
        self.port = port or _free_port()
        self.headless = headless
        self.profile = tempfile.mkdtemp(prefix="gbd-browser-")
        self.proc: subprocess.Popen | None = None
        self.ws: websocket.WebSocket | None = None
        self.driver = None
        self._events: queue.Queue = queue.Queue()
        self._reader_stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        args = [
            self.edge,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-gpu",
            "--log-level=3",
            "--window-size=1400,1000",
        ]
        if self.headless:
            args.append("--headless=new")
        args.append("about:blank")

        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        ws_url = self._wait_page_endpoint()
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self._send(1, "Network.enable")
        threading.Thread(target=self._pump, daemon=True).start()

        opts_cls, driver_cls = _driver_classes(self.kind)
        opts = opts_cls()
        opts.debugger_address = f"127.0.0.1:{self.port}"
        opts.add_argument("--disable-gpu")
        try:
            self.driver = driver_cls(options=opts)
        except WebDriverException as exc:
            raise GBDError(
                f"Could not attach to {self.kind}: {exc}\n"
                "Selenium Manager downloads the matching driver on first use, so "
                "this usually means it could not reach the network."
            ) from exc

    def close(self) -> None:
        self._reader_stop.set()
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except Exception:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)
        self.driver = None
        self.ws = None
        self.proc = None

    # -- CDP plumbing ------------------------------------------------------- #

    def _wait_page_endpoint(self, timeout: float = 30.0) -> str:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=2
                ) as r:
                    for e in json.load(r):
                        if e.get("type") == "page":
                            return e["webSocketDebuggerUrl"]
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            if self.proc and self.proc.poll() is not None:
                raise GBDError(
                    f"{self.kind} exited during startup (rc={self.proc.returncode})"
                )
            time.sleep(0.4)
        raise GBDError(
            f"{self.kind} debug endpoint never became ready. Last error: {last}"
        )

    def enable_network(self) -> None:
        """Re-arm CDP network capture (a navigation can silently drop it)."""
        try:
            self._send(900, "Network.enable")
        except Exception:  # noqa: BLE001
            pass

    def _send(self, mid: int, method: str, params: dict | None = None) -> None:
        assert self.ws is not None
        payload = {"id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        self.ws.send(json.dumps(payload))

    def _pump(self) -> None:
        """Background reader: push every CDP frame onto a queue."""
        assert self.ws is not None
        ws = self.ws
        ws.settimeout(0.5)
        while not self._reader_stop.is_set():
            try:
                raw = ws.recv()
            except Exception:  # noqa: BLE001
                continue
            if not raw:
                continue
            try:
                self._events.put(json.loads(raw))
            except Exception:  # noqa: BLE001
                continue

    def drain_content_urls(self) -> list[str]:
        urls: list[str] = []
        while True:
            try:
                msg = self._events.get_nowait()
            except queue.Empty:
                break
            if msg.get("method") != "Network.requestWillBeSent":
                continue
            u = msg.get("params", {}).get("request", {}).get("url", "")
            if CONTENT_MARK_RE.search(u):
                urls.append(u)
        return urls

    def drain_all_urls(self) -> list[str]:
        """Every request URL seen so far (diagnostics)."""
        urls: list[str] = []
        while True:
            try:
                msg = self._events.get_nowait()
            except queue.Empty:
                break
            if msg.get("method") != "Network.requestWillBeSent":
                continue
            u = msg.get("params", {}).get("request", {}).get("url", "")
            if u:
                urls.append(u)
        return urls


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #


def get_book_meta(driver: webdriver.Edge, data_url: str) -> str:
    """Best-effort title/author for the download folder name."""
    title, author = "", ""
    try:
        driver.get(data_url)
        time.sleep(2)
    except WebDriverException:
        return ""
    for cls in ("gb-volume-title", "title", "h1"):
        try:
            title = driver.find_element(By.CLASS_NAME, cls).text.strip()
            if title:
                break
        except Exception:  # noqa: BLE001
            continue
    try:
        author = driver.find_element(By.CLASS_NAME, "addmd").text.strip()
    except Exception:  # noqa: BLE001
        pass
    if not title:
        try:
            title = (driver.title or "").split(" - ")[0].strip()
        except Exception:  # noqa: BLE001
            title = ""
    author = author.lstrip("(").strip()
    out = title or "google-books"
    if author:
        out = f"{out} ({author})"
    return _safe(out, NAME_MAX)


def _safe(name: str, maxlen: int = NAME_MAX) -> str:
    """Filesystem-safe component, capped so the full path stays under MAX_PATH.

    Windows cannot create a path longer than 260 characters. A long book title
    used for both the folder and the PDF name (as the original script did) blows
    past that limit, so every component is truncated.
    """
    out = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "")
    out = re.sub(r"\s+", " ", out).strip().strip(".")
    if len(out) > maxlen:
        out = out[:maxlen].rstrip(" .")
    return out or "book"


def _fit_path(parent: str | Path, stem: str, suffix: str, budget: int = PATH_BUDGET) -> Path:
    """Join parent/stem+suffix, shortening the stem so the result fits in budget."""
    parent = Path(parent)
    base = _safe(stem)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    full = parent / f"{base}{ext}"
    if len(str(full)) <= budget:
        return full
    overhead = len(str(parent)) + len(ext) + 1
    room = budget - overhead
    if room < 12:
        return parent / f"book{ext}"
    return parent / f"{_safe(stem, room)}{ext}"


def _wait_reader(driver: webdriver.Edge, timeout: float = 18.0) -> bool:
    """Poll until the old-style reader renders its page container."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if driver.find_elements(By.CLASS_NAME, "pageImageDisplay"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.7)
    return False


def scan_book(
    url: str,
    browser: Browser,
    progress: Callable[[str], None] | None = None,
    max_rounds: int = 260,
    idle_limit: int = 6,
    stop: threading.Event | None = None,
) -> ScanResult:
    """Load the book, scroll through it, and collect every page image URL."""
    emit = progress or (lambda _m: None)
    book_id, data_url, embed_url = normalize_book_url(url)

    # Reader FIRST, metadata after. Measured: navigating to the plain book page
    # before the embed page kills the CDP network feed (zero events thereafter),
    # so the scan would find no pages. Metadata is cosmetic - fetch it last.
    emit("Opening book page ...")
    browser.driver.get(embed_url)
    # Re-arm the listener in case an earlier navigation dropped it.
    browser.enable_network()
    if not _wait_reader(browser.driver, timeout=18):
        emit("Reader not ready yet, reloading once ...")
        try:
            browser.driver.refresh()
        except WebDriverException:
            pass
        if not _wait_reader(browser.driver, timeout=15):
            body_text = ""
            try:
                body_text = browser.driver.find_element(By.TAG_NAME, "body").text[:400]
            except Exception:  # noqa: BLE001
                pass
            low = body_text.lower()
            if "no preview" in low or "not available" in low or "无法预览" in body_text:
                raise GBDError(
                    "This book has no preview available, so it cannot be downloaded."
                )
            raise GBDError(
                "The book reader did not load in time. Google may be rate-limiting "
                "this session - wait a minute and try again."
            )

    collected: dict[int, Page] = {}
    idle = 0
    bottom_rounds = 0
    stop = stop or threading.Event()

    SCROLL_JS = """
      const el = document.querySelector('.overflow-scrolling');
      if (!el) return null;
      el.scrollTop += Math.max(600, el.clientHeight * 0.7);
      return [el.scrollTop, el.scrollHeight, el.clientHeight];
    """

    for rnd in range(1, max_rounds + 1):
        if stop.is_set():
            emit("Scan cancelled.")
            break

        try:
            pos = browser.driver.execute_script(SCROLL_JS)
        except WebDriverException:
            pos = None

        time.sleep(0.45)

        new = 0
        for u in browser.drain_content_urls():
            m = URL_RE.search(u)
            if not m:
                continue
            num = int(m.group(2))
            if num in collected:
                continue
            clean = re.sub(r"([&?])w=\d+", r"\1w=1280", m.group(0))
            collected[num] = Page(number=num, label=f"{m.group(1)}{m.group(2)}", url=clean)
            new += 1

        if new:
            idle = 0
            if rnd % 3 == 0 or rnd < 4:
                emit(f"Scanning ... {len(collected)} pages found")
        else:
            idle += 1
            if rnd % 5 == 0:
                emit(f"Scanning ... {len(collected)} pages found (waiting for more)")

        # Reached the bottom: keep going for a few more rounds, because lazy
        # page images often arrive *after* the scroll finishes. Bailing out on
        # the first empty round loses them (short previews hit this every time).
        at_bottom = bool(pos) and pos[0] + pos[2] >= pos[1] - 10
        if at_bottom:
            bottom_rounds += 1
        else:
            bottom_rounds = 0
        if (at_bottom and bottom_rounds >= idle_limit) or (not pos and idle >= idle_limit):
            break
        if rnd % 40 == 0:
            time.sleep(1.0)

    if not collected:
        raise GBDError(
            "No page images were captured. The book may have no preview, "
            "or Google blocked the request. Try a different book id."
        )

    # Metadata last: navigating away from the reader is safe now.
    emit("Reading title ...")
    title = get_book_meta(browser.driver, data_url) or f"book-{book_id}"
    if title.strip().lower() in ("google", "google books", "google 图书"):
        title = f"book-{book_id}"
    emit(f'Book resolved: "{title}"')

    return ScanResult(title=title, book_id=book_id, pages=dict(sorted(collected.items())))


def select_pages(
    selection: str, pages: dict[int, Page]
) -> dict[int, Page]:
    """Parse "all", "1,10-50,odd,603" against the discovered pages."""
    sel = (selection or "all").strip().lower()
    if not sel or sel == "all":
        return dict(pages)

    out: dict[int, Page] = {}
    tokens = [t.strip() for t in sel.replace(" ", "").split(",") if t.strip()]
    for tok in tokens:
        if tok == "odd":
            out.update({k: v for k, v in pages.items() if k % 2 == 1})
        elif tok == "even":
            out.update({k: v for k, v in pages.items() if k % 2 == 0})
        elif "-" in tok:
            a, b = tok.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise GBDError(f"Bad range: {tok}")
            out.update({k: v for k, v in pages.items() if lo <= k <= hi})
        else:
            try:
                n = int(tok)
            except ValueError:
                raise GBDError(f"Cannot understand: {tok}")
            if n in pages:
                out[n] = pages[n]
    if not out:
        raise GBDError(f"No available page matched: {selection}")
    return dict(sorted(out.items()))


FETCH_JS = """
  const url = arguments[0];
  const done = arguments[arguments.length - 1];
  fetch(url, {credentials: 'include'})
    .then(r => { if (!r.ok) return 'HTTP' + r.status; return r.blob(); })
    .then(b => {
      if (typeof b === 'string') { done(b); return; }
      const fr = new FileReader();
      fr.onload = () => done(fr.result);
      fr.onerror = () => done('READERR');
      fr.readAsDataURL(b);
    })
    .catch(e => done('ERR:' + e));
"""


def make_browser_fetcher(driver: webdriver.Edge) -> Callable[[str], bytes | None]:
    """Fetch images *inside* the browser.

    The browser already has a working route to Google (it just rendered the
    book), whereas Python's requests has to go through whatever HTTP proxy the
    machine exports - which intermittently answers "502 Bad Gateway" for
    books.google.com. So prefer this, and fall back to requests.
    """

    def _fetch(url: str) -> bytes | None:
        res = driver.execute_async_script(FETCH_JS, url)
        if isinstance(res, str) and res.startswith("data:"):
            _, b64 = res.split(",", 1)
            return base64.b64decode(b64)
        return None

    return _fetch


def download_pages(
    pages: dict[int, Page],
    outdir: str | Path,
    progress: Callable[[int, int, str], None] | None = None,
    stop: threading.Event | None = None,
    fetcher: Callable[[str], bytes | None] | None = None,
) -> list[Path]:
    """Download each page at max width. Returns written file paths."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    emit = progress or (lambda *_a: None)
    stop = stop or threading.Event()

    total = len(pages)
    written: list[Path] = []
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://books.google.com/"})

    def ext_for(data: bytes, ctype: str = "") -> str:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if "png" in ctype:
            return "png"
        return "jpg"

    for i, (num, page) in enumerate(sorted(pages.items()), 1):
        if stop.is_set():
            break
        data = None
        ctype = ""
        if fetcher is not None:
            try:
                data = fetcher(page.hires_url)
            except Exception:  # noqa: BLE001
                data = None
        if data is None:
            for attempt in range(2):
                try:
                    r = session.get(page.hires_url, timeout=25)
                    r.raise_for_status()
                    ctype = r.headers.get("content-type", "")
                    if "image" not in ctype:
                        raise ValueError(f"not an image ({ctype})")
                    data = r.content
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 1:
                        emit(i, total, f"page {num} failed: {str(exc)[:90]}")
                    else:
                        time.sleep(1.2)
        if data:
            path = outdir / f"page_{num:04d}_{page.label}.{ext_for(data, ctype)}"
            path.write_bytes(data)
            written.append(path)
        emit(i, total, f"page {num}")
    return written


def make_pdf(paths: list[Path], pdf_path: str | Path) -> Path | None:
    """Combine downloaded page images into a single PDF."""
    if not paths:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    pdf_path = Path(pdf_path)
    # Guard against MAX_PATH: fall back to a short name if the requested one is
    # too long for Windows to create (this used to raise FileNotFoundError).
    if len(str(pdf_path)) > PATH_BUDGET:
        pdf_path = _fit_path(pdf_path.parent, "book", ".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    imgs = []
    for p in sorted(paths):
        try:
            im = Image.open(p)
            if im.mode != "RGB":
                im = im.convert("RGB")
            imgs.append(im)
        except Exception:  # noqa: BLE001
            continue
    if not imgs:
        return None
    try:
        first, rest = imgs[0], imgs[1:]
        first.save(pdf_path, "PDF", resolution=150.0, save_all=bool(rest), append_images=rest)
    except Exception:  # noqa: BLE001 - never let PDF failure kill the download
        return None
    return pdf_path
