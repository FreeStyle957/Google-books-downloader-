"""Diagnose one book id across several Google Books hosts / URL shapes."""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

BOOK = sys.argv[1] if len(sys.argv) > 1 else "PqFUCwAAQBAJ"

CASES = {
    "legacy_embed_com": f"https://books.google.com/books?id={BOOK}&pg=1&hl=zh-CN&f=false&output=embed&source=gbs_embed",
    "embed_sg": f"https://www.google.com.sg/books?id={BOOK}&pg=1&hl=zh-CN&f=false&output=embed&source=gbs_embed",
    "new_reader_sg": f"https://www.google.com.sg/books/edition/_/{BOOK}?hl=zh-CN&gbpv=1",
    "new_reader_com": f"https://books.google.com/books/edition/_/{BOOK}?hl=zh-CN&gbpv=1",
    "plain_com": f"https://books.google.com/books?id={BOOK}&pg=1&hl=zh-CN",
}

b = core.Browser(headless=True)
b.start()
try:
    for name, url in CASES.items():
        print(f"\n=== {name} ===", flush=True)
        print("  url:", url, flush=True)
        try:
            b.driver.get(url)
            time.sleep(4)
        except Exception as e:  # noqa: BLE001
            print("  nav error:", str(e)[:90], flush=True)
            continue
        print("  landed:", b.driver.current_url[:120], flush=True)
        print("  title :", repr(b.driver.title)[:80], flush=True)
        try:
            n_pid = len(b.driver.find_elements(By.CLASS_NAME, "pageImageDisplay"))
        except Exception:  # noqa: BLE001
            n_pid = -1
        try:
            txt = b.driver.find_element(By.TAG_NAME, "body").text[:260]
        except Exception:  # noqa: BLE001
            txt = ""
        print("  pageImageDisplay count:", n_pid, flush=True)
        print("  body:", repr(txt)[:300], flush=True)
finally:
    b.close()
    print("\nclosed", flush=True)
