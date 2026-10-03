"""End-to-end check of core.py: launch Edge, scan a real book, download pages, build PDF."""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core

URL = "https://books.google.com/books?id=buc0AAAAMAAJ"
MAX_ROUNDS = int(os.environ.get("GBD_ROUNDS", "20"))
DL_PAGES = int(os.environ.get("GBD_DL", "4"))

t0 = time.time()
print("[1] starting browser ...", flush=True)
b = core.Browser(headless=True)
b.start()
print(f"    ok ({time.time()-t0:.1f}s)", flush=True)

try:
    print(f"[2] scanning (max {MAX_ROUNDS} rounds) ...", flush=True)
    res = core.scan_book(URL, b, progress=lambda m: print("      " + m, flush=True),
                         max_rounds=MAX_ROUNDS, idle_limit=6)
    print(f"    title : {res.title!r}", flush=True)
    print(f"    pages : {res.count}", flush=True)
    sample = sorted(res.pages.items())[:6]
    for n, p in sample:
        print(f"      {n:>4} {p.label:<6} {p.hires_url[:110]}", flush=True)

    print(f"[3] downloading first {DL_PAGES} page(s) ...", flush=True)
    chosen = core.select_pages(f"1-{DL_PAGES}", res.pages)
    print("    selected:", sorted(chosen), flush=True)
    outdir = core.Path("downloads") / core._safe(res.title)
    files = core.download_pages(
        chosen, outdir,
        progress=lambda i, t, l: print(f"      [{i}/{t}] {l}", flush=True),
    )
    print(f"    wrote {len(files)} file(s) -> {outdir}", flush=True)
    for f in files:
        print(f"      {f.name}  {f.stat().st_size/1024:.0f} KB", flush=True)

    print("[4] building pdf ...", flush=True)
    pdf = core.make_pdf(files, outdir / f"{core._safe(res.title)}.pdf")
    if pdf:
        print(f"    pdf: {pdf}  {pdf.stat().st_size/1024:.0f} KB", flush=True)
    else:
        print("    pdf: FAILED", flush=True)

    print(f"[5] total {time.time()-t0:.1f}s", flush=True)
finally:
    b.close()
    print("[6] browser closed.", flush=True)
