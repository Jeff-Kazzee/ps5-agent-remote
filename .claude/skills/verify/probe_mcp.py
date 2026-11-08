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
import re
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


def check_routes(checkout: Path) -> None:
    """Every path mcp_server.py calls must exist in server.py's routes.

    The unit tests fake the remote server with their own routes, so a path renamed in
    both mcp_server.py and the tests would pass them. This reads the real route table.
    """
    server = (checkout / "server.py").read_text(encoding="utf-8")
    client = (checkout / "mcp_server.py").read_text(encoding="utf-8")
    routes = [(m.upper(), re.compile("^" + re.sub(r"\\{[^/]+\\}", "[^/]+", re.escape(path)) + "$"))
              for m, path in re.findall(r'web\.(get|post)\("([^"]+)"', server)]
    calls = re.findall(r'_(?:req|json)\("(GET|POST)", f?"([^"]+)"', client)
    check(bool(routes) and bool(calls), "route table read", f"{len(routes)} routes, {len(calls)} calls")
    for method, path in calls:
        concrete = re.sub(r"\{[^}]*\}", "x", path)
        ok = any(m == method and rx.match(concrete) for m, rx in routes)
        check(ok, f"route {method} {path}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    checkout = Path(sys.argv[1]).resolve()
    check_routes(checkout)
    python = sys.argv[2] if len(sys.argv) > 2 else sys.executable
    # Port 1 is closed on any normal host, so every remote call fails to connect.
    env = dict(os.environ, PS5_REMOTE_URL="http://127.0.0.1:1")
    proc = subprocess.Popen([python, "mcp_server.py"], cwd=checkout, env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines: queue.Queue[str] = queue.Queue()
    errors: list[str] = []

    def pump() -> None:
        for line in proc.stdout:
            lines.put(line)

    def pump_errors() -> None:
        for line in proc.stderr:
            errors.append(line.rstrip())

    threading.Thread(target=pump, daemon=True).start()
    threading.Thread(target=pump_errors, daemon=True).start()

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
    except (queue.Empty, OSError, ValueError, KeyError) as err:
        check(False, "server answered", f"{type(err).__name__} {err}, exit code {proc.poll()}")
        for line in errors[-10:]:
            print(f"  server stderr: {line}")
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    print(f"RESULT {'PASS' if failures == 0 else 'FAIL'} ({failures} failed)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
