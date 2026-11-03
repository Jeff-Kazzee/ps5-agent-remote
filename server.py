"""PS5 Agent Remote: local web server on 127.0.0.1.

Owns the single Remote Play session. The browser page and the agent MCP
server are both clients of this HTTP API, so they never fight over the PS5.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import deque
from pathlib import Path

from aiohttp import WSMsgType, web

import ddp
import store
from ps5native import NativeSession, register
from psn import PSN, PSNError

ROOT = Path(__file__).parent


def _load_env_local() -> None:
    """Read KEY=value lines from .env.local unless already in the environment."""
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env_local()

PS5_HOST = os.environ.get("PS5_HOST", "").strip()
PORT = int(os.environ.get("REMOTE_PORT", "8765"))
IDLE_DISCONNECT_S = int(os.environ.get("IDLE_DISCONNECT_S", "900"))
RESOLUTION = os.environ.get("PS5_RESOLUTION", "720p")
FPS = int(os.environ.get("PS5_FPS", "60"))
MAX_PLAY_FRAMES = 12
MAX_PLAY_MS = 30000
VALID_BUTTONS = {
    "UP", "DOWN", "LEFT", "RIGHT", "L1", "R1", "L2", "R2", "CROSS", "CIRCLE",
    "SQUARE", "TRIANGLE", "OPTIONS", "SHARE", "PS", "L3", "R3", "TOUCHPAD",
}

log = logging.getLogger("ps5remote")
psn = PSN()


class Remote:
    def __init__(self, host: str):
        self.host = host
        self.status: dict = {}
        self.lock = asyncio.Lock()
        self.last_input = 0.0
        self.retry_after = 0.0
        self.message = ""
        self.native: NativeSession | None = None
        self.activity: deque[dict] = deque(maxlen=60)

    def note(self, source: str, text: str) -> None:
        self.activity.appendleft({"t": time.time(), "source": source, "text": text})
        log.info("[%s] %s", source, text)

    # ---------- console state ----------
    def mac(self) -> str | None:
        return self.status.get("host-id")

    def linked_console(self) -> dict | None:
        return store.console(store.load(), self.mac())

    def connected(self) -> bool:
        s = self.native
        return bool(s and s.connected and not s.stopped)

    def snapshot(self) -> dict:
        st = self.status
        data = store.load()
        s = self.native
        on = st.get("status_code") == 200
        return {
            "reachable": bool(st),
            "host": self.host,
            "name": st.get("host-name"),
            "firmware": st.get("system-version"),
            "power": "on" if on else ("standby" if st else "unknown"),
            "app": st.get("running-app-name") or "",
            "title_id": st.get("running-app-titleid") or "",
            "signed_in": (data.get("account") or {}).get("online_id"),
            "linked": bool(store.console(data, self.mac())),
            "connected": self.connected(),
            "connecting": self.lock.locked(),
            "keyboard_open": bool(s and s.keyboard_open),
            "keyboard_text": s.keyboard_text if s else "",
            "frame_age_s": round(time.time() - s.frame_time, 1) if s and s.frame_time else None,
            "protected_content": bool(s and s.cant_display),
            "message": self.message,
        }

    async def refresh_status(self) -> None:
        if not self.host:
            consoles = await asyncio.to_thread(ddp.search, None, 2.0)
            if not consoles:
                self.status = {}
                self.message = "No PS5 found on this network. Turn it on, or set PS5_HOST."
                return
            linked = store.load()["consoles"]
            pick = next((c for c in consoles if c.get("host-id", "").upper() in linked), consoles[0])
            self.host = pick["ip"]
            self.status = pick
            log.info("Found %s at %s", pick.get("host-name"), self.host)
            if self.message.startswith("No PS5 found"):
                self.message = ""
            return
        st = await asyncio.to_thread(ddp.status, self.host)
        self.status = st or {}

    async def poll(self) -> None:
        while True:
            try:
                await self.refresh_status()
            except OSError as err:
                log.debug("status poll failed: %s", err)
            idle = time.monotonic() - self.last_input
            if self.connected() and idle > IDLE_DISCONNECT_S:
                self.disconnect()
                self.note("server", f"Closed Remote Play after {int(idle)}s idle")
                self.message = "Disconnected after being idle."
            await asyncio.sleep(3)

    # ---------- session ----------
    async def ensure_session(self) -> bool:
        if self.connected():
            return True
        if time.monotonic() < self.retry_after:
            return False
        ok = await self._connect()
        if not ok:
            # The PS5 keeps a dropped session for a few seconds. Do not hammer it.
            self.retry_after = time.monotonic() + 8
        return ok

    async def _connect(self) -> bool:
        async with self.lock:
            if self.connected():
                return True
            await self.refresh_status()
            if not self.status:
                self.message = self.message or "PS5 not reachable."
                return False
            data = store.load()
            account_id = store.account_id_bytes(data)
            entry = store.console(data, self.mac())
            if not account_id or not entry:
                self.message = "This computer is not linked to the PS5 yet. Finish setup on the remote page."
                return False
            if self.status.get("status_code") != 200:
                self.message = "PS5 is in rest mode. Power it on first."
                return False
            self.disconnect()
            regist_key, rp_key = store.keys(entry)
            self.message = "Connecting to PS5..."
            try:
                session = await asyncio.to_thread(
                    NativeSession, self.host, regist_key, rp_key, account_id,
                    resolution=RESOLUTION, fps=FPS)
            except (OSError, RuntimeError) as err:
                self.message = f"Connect failed: {err}"
                self.note("server", self.message)
                return False
            self.native = session
            if not await asyncio.to_thread(session.wait_connected, 20):
                self.message = f"Connect failed: {session.quit_reason or 'timed out'}"
                self.note("server", self.message)
                self.disconnect()
                return False
            self.message = "Connected."
            self.note("server", "Remote Play session connected")
            return True

    def disconnect(self) -> None:
        s, self.native = self.native, None
        if s:
            s.stop()

    def touch(self) -> None:
        self.last_input = time.monotonic()

    async def button(self, name: str, action: str = "tap", hold_ms: int = 100) -> bool:
        self.touch()
        if not await self.ensure_session():
            return False
        s = self.native
        if action == "press":
            s.button(name, True)
        elif action == "release":
            s.button(name, False)
        else:
            s.button(name, True)
            await asyncio.sleep(hold_ms / 1000)
            s.button(name, False)
        return True

    async def press_sequence(self, buttons: list[str], hold_ms: int, gap_ms: int, source: str) -> dict:
        bad = [b for b in buttons if b.upper() not in VALID_BUTTONS]
        if bad:
            return {"ok": False, "error": f"Unknown buttons: {bad}. Valid: {sorted(VALID_BUTTONS)}"}
        if not await self.ensure_session():
            return {"ok": False, "error": self.message}
        self.note(source, "press " + " ".join(b.upper() for b in buttons))
        for b in buttons:
            await self.button(b.upper(), "tap", hold_ms)
            await asyncio.sleep(gap_ms / 1000)
        return {"ok": True}

    async def stick(self, which: str, x: float, y: float) -> None:
        self.touch()
        if not await self.ensure_session():
            return
        self.native.stick(which, x, y)

    async def screenshot(self, width: int, wait_s: float = 6.0, enhance: bool = False,
                         crop: tuple | None = None) -> bytes | None:
        self.touch()
        if not await self.ensure_session():
            return None
        start = time.time()
        while time.time() - start < wait_s:
            s = self.native
            if s and s.frame_time:
                return await asyncio.to_thread(s.jpeg, width, 80, enhance, crop)
            await asyncio.sleep(0.2)
        return None

    async def play(self, steps: list[dict], frame_every_ms: int, width: int, enhance: bool,
                   source: str) -> dict:
        """Run timed controller steps on the server clock, grabbing frames as it goes.

        Each step sets the whole controller for `ms` milliseconds: `hold` lists
        the buttons down, `left` and `right` are stick positions [x, y] from -1
        to 1 (up is negative y). Everything is released at the end.
        """
        self.touch()
        if not await self.ensure_session():
            return {"ok": False, "error": self.message}
        s = self.native
        frames: list[tuple[float, bytes]] = []
        t0 = time.monotonic()
        next_shot = 0.0 if frame_every_ms else float("inf")

        async def maybe_shot() -> None:
            nonlocal next_shot
            now = time.monotonic() - t0
            if now >= next_shot and len(frames) < MAX_PLAY_FRAMES:
                jpg = await asyncio.to_thread(s.jpeg, width, 75, enhance, None)
                if jpg:
                    frames.append((round(now, 2), jpg))
                next_shot = now + frame_every_ms / 1000

        summary = []
        try:
            for step in steps:
                held = {b.upper() for b in step.get("hold", [])}
                left = tuple(step.get("left") or (0, 0))[:2]
                right = tuple(step.get("right") or (0, 0))[:2]
                ms = max(0, min(10000, int(step.get("ms", 100))))
                s.set_state(held, left, right)
                summary.append("+".join(sorted(held)) + (f" L{list(left)}" if any(left) else "")
                               + (f" R{list(right)}" if any(right) else "") + f" {ms}ms")
                end = time.monotonic() + ms / 1000
                while True:
                    await maybe_shot()
                    left_s = end - time.monotonic()
                    if left_s <= 0:
                        break
                    await asyncio.sleep(min(0.03, left_s))
        finally:
            s.set_state(set())
        await asyncio.sleep(0.15)
        if frame_every_ms or not frames:
            jpg = await asyncio.to_thread(s.jpeg, width, 80, enhance, None)
            if jpg:
                frames.append((round(time.monotonic() - t0, 2), jpg))
        self.note(source, "play " + " | ".join(summary)[:180])
        return {"ok": True, "frames": frames}

    async def type_text(self, text: str, submit: bool, source: str) -> dict:
        self.touch()
        if not await self.ensure_session():
            return {"ok": False, "error": self.message}
        s = self.native
        was_open = s.keyboard_open
        s.keyboard_set_text(text)
        await asyncio.sleep(0.4)
        if submit:
            s.keyboard_accept()
        self.note(source, f"type {text!r}" + (" and submit" if submit else ""))
        return {
            "ok": True,
            "keyboard_was_open": was_open,
            "keyboard_text": s.keyboard_text,
            "hint": "" if was_open else "The PS5 had not reported an open keyboard. Select a text field first, then check a screenshot.",
        }

    async def go_home(self, source: str) -> dict:
        self.touch()
        if not await self.ensure_session():
            return {"ok": False, "error": self.message}
        self.native.go_home()
        self.note(source, "go to Home screen")
        return {"ok": True}

    # ---------- power ----------
    async def wake(self, source: str) -> dict:
        await self.refresh_status()
        entry = self.linked_console()
        if not self.host or not entry:
            return {"ok": False, "error": "Link this computer to the PS5 first."}
        regist_key, _ = store.keys(entry)
        await asyncio.to_thread(ddp.wake, self.host, regist_key)
        self.note(source, "power on")
        self.message = "Wake signal sent. The PS5 takes about 20 seconds."
        return {"ok": True}

    async def rest(self, source: str) -> dict:
        if not await self.ensure_session():
            return {"ok": False, "error": self.message}
        self.native.goto_bed()
        await asyncio.sleep(1.0)
        self.disconnect()
        self.note(source, "rest mode")
        self.message = "Rest mode signal sent."
        return {"ok": True}

    # ---------- setup ----------
    async def sign_in(self, npsso: str) -> dict:
        res = await asyncio.to_thread(psn.set_npsso, npsso)
        if not res.get("ok"):
            return res
        account_id = await asyncio.to_thread(lambda: psn.client().me().account_id)
        store.set_account(res["online_id"], account_id)
        self.note("setup", f"signed in as {res['online_id']}")
        return {"ok": True, "user": res["online_id"]}

    async def link(self, pin: str) -> dict:
        data = store.load()
        account_id = store.account_id_bytes(data)
        if not account_id:
            return {"ok": False, "error": "Sign in first (step 1)."}
        await self.refresh_status()
        if self.status.get("status_code") != 200:
            return {"ok": False, "error": "The PS5 must be on (not in rest mode) to link."}
        try:
            res = await asyncio.to_thread(register, self.host, account_id, pin)
        except (ValueError, RuntimeError) as err:
            return {"ok": False, "error": str(err)}
        mac = res["mac"] if res["mac"] != "000000000000" else self.mac()
        store.add_console(mac, res["nickname"], self.host, res["regist_key"], res["rp_key"])
        self.note("setup", f"linked to {res['nickname'] or mac}")
        return {"ok": True, "nickname": res["nickname"]}


remote: Remote


def source_of(req: web.Request) -> str:
    return req.headers.get("X-Client", "ui")[:20]


async def body_of(req: web.Request) -> dict:
    try:
        return await req.json()
    except (json.JSONDecodeError, ValueError):
        return {}


async def index(_req):
    return web.FileResponse(ROOT / "web" / "index.html")


async def state(_req):
    return web.json_response(remote.snapshot())


async def debug(_req):
    s = remote.native
    return web.json_response({
        "session": await asyncio.to_thread(s.stats) if s else None,
        "resolution": RESOLUTION, "fps": FPS, "status": remote.status,
    })


async def activity(_req):
    return web.json_response(list(remote.activity))


async def sign_in(req):
    b = await body_of(req)
    return web.json_response(await remote.sign_in(str(b.get("npsso") or b.get("redirect_url") or "")))


async def link(req):
    return web.json_response(await remote.link(str((await body_of(req)).get("pin", ""))))


def _crop_of(value: str | None) -> tuple | None:
    if not value:
        return None
    try:
        parts = tuple(float(v) for v in value.split(","))
    except ValueError:
        return None
    return parts if len(parts) == 4 else None


async def screen(req):
    width = max(320, min(1920, int(req.query.get("w", "1280"))))
    jpg = await remote.screenshot(width, enhance=req.query.get("enhance") == "1",
                                  crop=_crop_of(req.query.get("crop")))
    if jpg is None:
        return web.json_response({"ok": False, "error": remote.message or "No video frame yet."}, status=503)
    return web.Response(body=jpg, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def press(req):
    b = await body_of(req)
    buttons = b.get("buttons") or []
    if isinstance(buttons, str):
        buttons = buttons.replace(",", " ").split()
    hold = max(30, min(3000, int(b.get("hold_ms", 100))))
    gap = max(0, min(5000, int(b.get("gap_ms", 250))))
    return web.json_response(await remote.press_sequence(buttons, hold, gap, source_of(req)))


async def play(req):
    """POST {"steps": [...], "frame_every_ms": 500, "width": 960, "enhance": false}.

    Returns {"ok", "frames": [{"t": seconds, "jpeg_b64": ...}]}.
    """
    b = await body_of(req)
    steps = b.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return web.json_response({"ok": False, "error": "steps must be a non-empty list"}, status=400)
    bad = sorted({h.upper() for st in steps for h in st.get("hold", [])} - VALID_BUTTONS)
    if bad:
        return web.json_response({"ok": False, "error": f"Unknown buttons {bad}. Valid: {sorted(VALID_BUTTONS)}"}, status=400)
    total = sum(int(st.get("ms", 100)) for st in steps)
    if total > MAX_PLAY_MS:
        return web.json_response({"ok": False, "error": f"Sequence is {total} ms; the limit is {MAX_PLAY_MS}."}, status=400)
    every = max(0, int(b.get("frame_every_ms", 0)))
    if every:
        every = max(150, every)
    width = max(320, min(1920, int(b.get("width", 960))))
    res = await remote.play(steps, every, width, bool(b.get("enhance")), source_of(req))
    if not res.get("ok"):
        return web.json_response(res, status=503)
    return web.json_response({"ok": True, "frames": [
        {"t": t, "jpeg_b64": base64.b64encode(j).decode()} for t, j in res["frames"]]})


async def text(req):
    b = await body_of(req)
    t = str(b.get("text", ""))[:500]
    return web.json_response(await remote.type_text(t, bool(b.get("submit", True)), source_of(req)))


async def action(req):
    name = req.match_info["name"]
    src = source_of(req)
    if name == "wake":
        result = await remote.wake(src)
    elif name == "rest":
        result = await remote.rest(src)
    elif name == "home":
        result = await remote.go_home(src)
    elif name == "connect":
        remote.touch()
        result = {"ok": await remote.ensure_session(), "error": remote.message}
    elif name == "disconnect":
        remote.disconnect()
        remote.message = "Disconnected."
        result = {"ok": True}
    else:
        raise web.HTTPNotFound()
    return web.json_response({**result, "state": remote.snapshot()})


async def psn_call(fn, *args):
    try:
        return web.json_response({"ok": True, **(await asyncio.to_thread(fn, *args))})
    except PSNError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=400)
    except Exception as err:  # noqa: BLE001
        log.exception("PSN call failed")
        return web.json_response({"ok": False, "error": f"PSN request failed: {err}"}, status=502)


async def psn_status(_req):
    return web.json_response({"configured": psn.configured})


async def psn_npsso(req):
    return web.json_response(await remote.sign_in(str((await body_of(req)).get("npsso", ""))))


async def psn_presence(_req):
    return await psn_call(psn.presence)


async def psn_library(req):
    q = req.query.get("q", "")
    limit = max(1, min(200, int(req.query.get("limit", "25"))))
    remote.note(source_of(req), f"library lookup {q!r}" if q else "library list")
    return await psn_call(psn.library, q, limit, req.query.get("refresh") == "1")


async def psn_store(req):
    q = req.query.get("q", "").strip()
    if not q:
        return web.json_response({"ok": False, "error": "q is required"}, status=400)
    limit = max(1, min(30, int(req.query.get("limit", "10"))))
    remote.note(source_of(req), f"store search {q!r}")
    return await psn_call(psn.store_search, q, limit)


async def ws(req):
    sock = web.WebSocketResponse(heartbeat=20)
    await sock.prepare(req)
    async for msg in sock:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            data = json.loads(msg.data)
            if data.get("type") == "button":
                btn = str(data["button"]).upper()
                act = data.get("action", "tap")
                if btn in VALID_BUTTONS and act in ("tap", "press", "release"):
                    asyncio.create_task(remote.button(btn, act))
            elif data.get("type") == "stick":
                which = data.get("stick")
                if which in ("left", "right"):
                    asyncio.create_task(remote.stick(which, float(data["x"]), float(data["y"])))
        except (ValueError, KeyError, TypeError) as err:
            log.warning("bad ws message: %s", err)
    return sock


async def on_startup(app):
    app["poller"] = asyncio.create_task(remote.poll())


async def on_cleanup(app):
    app["poller"].cancel()
    remote.disconnect()


def main() -> None:
    global remote
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    remote = Remote(PS5_HOST)
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/api/state", state),
        web.get("/api/activity", activity),
        web.get("/api/debug", debug),
        web.post("/api/sign-in", sign_in),
        web.post("/api/link", link),
        web.get("/api/screen.jpg", screen),
        web.post("/api/press", press),
        web.post("/api/text", text),
        web.post("/api/play", play),
        web.post("/api/action/{name}", action),
        web.get("/api/psn/status", psn_status),
        web.post("/api/psn/npsso", psn_npsso),
        web.get("/api/psn/presence", psn_presence),
        web.get("/api/psn/library", psn_library),
        web.get("/api/psn/store", psn_store),
        web.get("/ws", ws),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    where = PS5_HOST or "auto-discovery"
    print(f"PS5 Agent Remote: http://127.0.0.1:{PORT}  (PS5: {where})", flush=True)
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
