"""Live check of the native session: connect, screenshot, press RIGHT, screenshot.

Run with the server stopped (one Remote Play session at a time):
    .venv\\Scripts\\python.exe tools\\test_native.py [PS5_IP]
Needs a completed link (setup on the remote page). Writes
native/build/shot1.jpg and shot2.jpg and prints stats.
"""
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ddp  # noqa: E402
import store  # noqa: E402
from ps5native import NativeSession  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

found = ddp.search(sys.argv[1] if len(sys.argv) > 1 else None, timeout=3.0)
if not found:
    sys.exit("No PS5 answered. Is it on and on this network?")
console = found[0]
data = store.load()
entry = store.console(data, console.get("host-id"))
if not entry or not data.get("account"):
    sys.exit("This computer is not linked to that PS5. Run setup on the remote page first.")
regist_key, rp_key = store.keys(entry)
print("PS5:", console.get("host-name"), console["ip"], "on" if console["on"] else "rest mode")

s = NativeSession(console["ip"], regist_key, rp_key, store.account_id_bytes(data), resolution="720p", fps=60)
out = ROOT / "native" / "build"
out.mkdir(parents=True, exist_ok=True)
try:
    print("connected:", s.wait_connected(25), s.quit_reason)
    time.sleep(4)
    if s.cant_display:
        print("PS5 reports protected content. Sending Go Home.")
        s.go_home()
        time.sleep(4)
    shot = s.jpeg()
    print("stats 1:", s.stats())
    if shot:
        (out / "shot1.jpg").write_bytes(shot)
    s.button("RIGHT", True)
    time.sleep(0.12)
    s.button("RIGHT", False)
    time.sleep(1.5)
    shot = s.jpeg()
    print("stats 2:", s.stats())
    if shot:
        (out / "shot2.jpg").write_bytes(shot)
finally:
    s.stop()
    print("stopped")
