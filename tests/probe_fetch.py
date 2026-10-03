"""Can we download a page image from inside the browser (no Python proxy)?"""
import base64
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

BOOK = "PqFUCwAAQBAJ"
EMBED = f"https://books.google.com/books?id={BOOK}&pg=1&hl=zh-CN&f=false&output=embed&source=gbs_embed"
IMG = (
    "https://books.google.com/books/publisher/content?id=PqFUCwAAQBAJ&hl=zh-CN"
    "&pg=PA14&img=1&zoom=3&sig=ACfU3U3P66maj1BG6MDhLJNxLO2XgVkWjQ&w=69420"
)

JS = """
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

b = core.Browser(headless=True)
b.start()
try:
    b.driver.get(EMBED)
    core._wait_reader(b.driver, timeout=20)
    print("reader loaded, fetching image via JS ...", flush=True)
    t0 = time.time()
    res = b.driver.execute_async_script(JS, IMG)
    print(f"  elapsed {time.time()-t0:.1f}s", flush=True)
    if isinstance(res, str) and res.startswith("data:"):
        head, b64 = res.split(",", 1)
        raw = base64.b64decode(b64)
        print("  ok:", head, flush=True)
        print("  bytes:", len(raw), f"({len(raw)/1024:.0f} KB)", flush=True)
        open("tests/_fetch_test.jpg", "wb").write(raw)
        print("  saved tests/_fetch_test.jpg", flush=True)
    else:
        print("  FAILED:", str(res)[:160], flush=True)
finally:
    b.close()
    print("closed", flush=True)
