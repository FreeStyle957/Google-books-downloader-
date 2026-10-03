"""Replicate scan_book step by step, printing every request, to find where
publisher/content URLs get lost."""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

url = sys.argv[1]
bid, data_url, embed_url = core.normalize_book_url(url)

b = core.Browser(headless=True)
b.start()
try:
    # --- step 1: metadata page (same as scan_book) ---
    print("[1] data_url (metadata)", flush=True)
    b.driver.get(data_url)
    time.sleep(2.5)
    print("    title:", repr(b.driver.title)[:70], flush=True)

    # --- step 2: embed reader ---
    print("[2] embed_url", flush=True)
    b.driver.get(embed_url)
    ok = core._wait_reader(b.driver, timeout=20)
    print("    reader ready:", ok, flush=True)
    print("    landed:", b.driver.current_url[:110], flush=True)

    seen: list[str] = []
    content: list[str] = []
    for rnd in range(10):
        pos = b.driver.execute_script(
            "const el=document.querySelector('.overflow-scrolling');"
            "if(!el) return null;"
            "el.scrollTop += Math.max(600, el.clientHeight*0.7);"
            "return [el.scrollTop, el.scrollHeight, el.clientHeight];"
        )
        time.sleep(0.45)
        for u in b.drain_all_urls():
            if u not in seen:
                seen.append(u)
                if core.CONTENT_MARK_RE.search(u):
                    content.append(u)
        print(f"    round {rnd+1}: pos={pos} all={len(seen)} content={len(content)}", flush=True)

    print("\n[3] content URLs matched:", len(content), flush=True)
    for u in content[:8]:
        m = core.URL_RE.search(u)
        print("    ", "MATCH" if m else "NO-MATCH", u[:150], flush=True)
finally:
    b.close()
    print("closed", flush=True)
