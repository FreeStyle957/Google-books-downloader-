"""Scan a URL then download pages, to validate the end-to-end path."""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

url = sys.argv[1]
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 60

b = core.Browser(headless=True)
b.start()
try:
    res = core.scan_book(url, b, progress=lambda m: print("  " + m, flush=True),
                         max_rounds=rounds)
    print("title:", res.title, flush=True)
    print("pages:", res.count, flush=True)

    outdir = core.Path("downloads") / core._safe(res.title)
    files = core.download_pages(
        res.pages, outdir,
        progress=lambda i, t, l: print(f"  [{i}/{t}] {l}", flush=True),
        fetcher=core.make_browser_fetcher(b.driver),
    )
    print("wrote:", len(files), "->", outdir, flush=True)
    for f in files[:6]:
        print(f"   {f.name}  {f.stat().st_size/1024:.0f} KB", flush=True)

    if files:
        pdf = core.make_pdf(files, core._fit_path(outdir, core._safe(res.title), ".pdf"))
        print("pdf:", pdf, (f"{pdf.stat().st_size/1048576:.2f} MB" if pdf else "FAILED"), flush=True)
finally:
    b.close()
    print("closed", flush=True)
