"""Scan an arbitrary Google Books URL from the command line.

    .venv/Scripts/python.exe tests/scan_url.py "<url>" [rounds]
"""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

url = sys.argv[1]
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 30

bid, data_url, embed_url = core.normalize_book_url(url)
print("book_id  :", bid, flush=True)
print("embed    :", embed_url, flush=True)

b = core.Browser(headless=True)
b.start()
try:
    t0 = time.time()
    res = core.scan_book(
        url, b,
        progress=lambda m: print("  " + m, flush=True),
        max_rounds=rounds,
    )
    print("title    :", res.title, flush=True)
    print("pages    :", res.count, flush=True)
    for n, p in sorted(res.pages.items())[:5]:
        print(f"   {n:>4} {p.label}", flush=True)
    print(f"elapsed  : {time.time()-t0:.0f}s", flush=True)
except core.GBDError as e:
    print("GBDError :", e, flush=True)
finally:
    b.close()
    print("closed", flush=True)
