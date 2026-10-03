"""Dump every request a book's embed page makes, to learn its image-URL shape."""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

url = sys.argv[1]
book_id, data_url, embed_url = core.normalize_book_url(url)
print("embed:", embed_url, flush=True)

b = core.Browser(headless=True)
b.start()
try:
    b.driver.get(embed_url)
    ok = core._wait_reader(b.driver, timeout=20)
    print("reader ready:", ok, flush=True)
    time.sleep(2)

    all_urls: list[str] = []
    for rnd in range(12):
        try:
            b.driver.execute_script(
                "const el=document.querySelector('.overflow-scrolling');"
                "if(el) el.scrollTop += Math.max(600, el.clientHeight*0.7);"
            )
        except Exception as e:  # noqa: BLE001
            print("scroll err", str(e)[:60], flush=True)
        time.sleep(0.8)
        for u in b.drain_all_urls():
            if u not in all_urls:
                all_urls.append(u)
        print(f"  round {rnd+1}: total unique urls={len(all_urls)}", flush=True)

    print("\n--- image-ish requests ---", flush=True)
    for u in all_urls:
        if any(k in u.lower() for k in ("content", "image", "jpg", "jpeg", "png", "page", "zoom")):
            print("  ", u[:170], flush=True)

    print("\n--- sample of everything (first 25) ---", flush=True)
    for u in all_urls[:25]:
        print("  ", u[:150], flush=True)
finally:
    b.close()
    print("closed", flush=True)
