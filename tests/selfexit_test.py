"""Measure exactly how long the service takes to self-exit after heartbeats stop."""
import json
import os
import subprocess
import threading
import time
import urllib.request

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
PY = os.path.join(BASE, ".venv", "Scripts", "python.exe")
URL = "http://127.0.0.1:8733"

logf = open(os.path.join(BASE, "selfexit.log"), "w", encoding="utf-8")
proc = subprocess.Popen(
    [PY, os.path.join(BASE, "server.py")],
    cwd=BASE, env=dict(os.environ, GBD_IDLE_TIMEOUT="10"),
    stdout=logf, stderr=subprocess.STDOUT,
)

def ping():
    r = urllib.request.Request(f"{URL}/api/ping", data=b"{}",
                               headers={"Content-Type": "application/json"})
    urllib.request.urlopen(r, timeout=4).read()

time.sleep(4)
print("t=0      server up", flush=True)
beat = threading.Event()
def hb():
    while not beat.is_set():
        try: ping()
        except Exception: pass
        beat.wait(3)
threading.Thread(target=hb, daemon=True).start()
time.sleep(6)

t_stop = time.time()
beat.set()
print(f"t={time.time()-t_stop:5.1f}  heartbeats stopped", flush=True)

while time.time() - t_stop < 120:
    if proc.poll() is not None:
        print(f"t={time.time()-t_stop:5.1f}  SERVER EXITED rc={proc.returncode}", flush=True)
        break
    time.sleep(0.5)
else:
    print("STILL ALIVE after 120s", flush=True)
logf.close()
