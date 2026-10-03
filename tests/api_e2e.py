"""API-level e2e: start server, act like the UI (heartbeat + scan + download),
then stop the heartbeat and verify the service shuts itself down."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
PY = os.path.join(BASE, ".venv", "Scripts", "python.exe")
PORT = 8733
URL = f"http://127.0.0.1:{PORT}"
ENV = dict(os.environ, GBD_SCAN_ROUNDS="20", GBD_IDLE_TIMEOUT="15")

logf = open(os.path.join(BASE, "server_test.log"), "w", encoding="utf-8")
proc = subprocess.Popen(
    [PY, os.path.join(BASE, "server.py")],
    cwd=BASE, env=ENV, stdout=logf, stderr=subprocess.STDOUT,
)

def req(path, payload=None, timeout=600):
    data = json.dumps(payload or {}).encode()
    r = urllib.request.Request(
        f"{URL}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"    HTTP {e.code} from {path}: {body[:300]}", flush=True)
        raise

stop_beat = threading.Event()
def heartbeat():
    while not stop_beat.is_set():
        try:
            req("/api/ping", timeout=4)
        except Exception:
            pass
        stop_beat.wait(4)

time.sleep(4)
threading.Thread(target=heartbeat, daemon=True).start()
print("[1] server up, heartbeat on", flush=True)

print("[2] scan:", flush=True)
t0 = time.time()
res = req("/api/scan", {"url": "https://books.google.com/books?id=buc0AAAAMAAJ"})
print(f"    ok={res['ok']} title={res['title']!r} pages={res['count']} ({time.time()-t0:.0f}s)", flush=True)

print("[3] download pages 1-3 + pdf:", flush=True)
t0 = time.time()
res = req("/api/download", {"selection": "1-3", "make_pdf": True})
print(f"    ok={res['ok']} files={res['files']} dir={res['dir']}", flush=True)
print(f"    pdf={res['pdf']} ({time.time()-t0:.0f}s)", flush=True)

print("[4] stopping heartbeat -> service should self-exit", flush=True)
stop_beat.set()
t_stop = time.time()
deadline = t_stop + 90
while time.time() < deadline:
    if proc.poll() is not None:
        print(f"    exited rc={proc.returncode} {time.time()-t_stop:.0f}s after last beat", flush=True)
        break
    time.sleep(1)
else:
    print("    STILL RUNNING after 90s - FAIL", flush=True)

logf.close()
print("[5] done", flush=True)
