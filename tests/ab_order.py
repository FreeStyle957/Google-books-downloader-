"""A/B: does visiting the plain page first break the embed reader?"""
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402

URL = sys.argv[1]
bid, data_url, embed_url = core.normalize_book_url(URL)
print("embed:", embed_url, flush=True)


def trial(label, visit_plain_first):
    b = core.Browser(headless=True)
    b.start()
    try:
        if visit_plain_first:
            b.driver.get(data_url)
            time.sleep(2.5)
        b.driver.get(embed_url)
        ok = core._wait_reader(b.driver, timeout=20)
        landed = b.driver.current_url[:110]
        n = 0
        try:
            n = len(b.driver.find_elements(core.By.CLASS_NAME, "pageImageDisplay"))
        except Exception:
            pass
        print(f"[{label}] reader={ok} containers={n}", flush=True)
        print(f"        landed: {landed}", flush=True)
        return ok
    finally:
        b.close()
        time.sleep(3)


trial("B: embed only       ", False)
trial("A: plain then embed ", True)
trial("B2: embed only again", False)
