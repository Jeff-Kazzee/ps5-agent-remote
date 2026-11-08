"""Cold stdio probe of mcp_server.py, with no remote server running.

Run: python probe_mcp.py <checkout> [python]
<checkout> holds mcp_server.py. [python] is the interpreter with the
requirements installed (default: this interpreter). Prints one line per check
and exits 1 if any check fails. Uses only the standard library.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

TOOLS = {"ps5_look", "ps5_play", "ps5_press", "ps5_type", "ps5_home", "ps5_power",
         "psn_now_playing", "psn_library", "psn_store_search"}
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
TIMEOUT_S = 30
failures = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""), flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    checkout = Path(sys.argv[1]).resolve()
    python = sys.argv[2] if len(sys.argv) > 2 else sys.executable
    # Port 1 is closed on any normal host, so every remote call fails to connect.
    env = dict(os.environ, PS5_REMOTE_URL="http://127.0.0.1:1")
    proc = subprocess.Popen([python, "mcp_server.py"], cwd=checkout, env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    lines: queue.Queue[str] = queue.Queue()
    def pump() -> None:
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def reply(msg_id: int) -> dict:
        while True:
            msg = json.loads(lines.get(timeout=TIMEOUT_S))
            if msg.get("id") == msg_id:
                return msg

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "verify-probe", "version": "1"}}})
        init = reply(1).get("result", {})
        check(init.get("serverInfo", {}).get("name") == "ps5", "initialize",
              f"server {init.get('serverInfo')}, protocol {init.get('protocolVersion')}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {t["name"]: t for t in reply(2).get("result", {}).get("tools", [])}
        check(set(tools) == TOOLS, "tools/list names", f"{len(tools)} tools")
        for name in sorted(tools):
            ann = tools[name].get("annotations") or {}
            vals = [ann.get(k) for k in HINTS]
            check(all(isinstance(v, bool) for v in vals), f"hints {name}", str(vals))

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "ps5_look", "arguments": {}}})
        res = reply(3).get("result", {})
        text = " ".join(c.get("text", "") for c in res.get("content", []))
        check(res.get("isError") is True and "start.cmd" in text, "ps5_look without server", text[:160])
    except queue.Empty:
        check(False, "server answered", f"no reply within {TIMEOUT_S} s, exit code {proc.poll()}")
    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=10)
    print(f"RESULT {'PASS' if failures == 0 else 'FAIL'} ({failures} failed)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
