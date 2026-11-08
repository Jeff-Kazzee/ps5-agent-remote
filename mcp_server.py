"""MCP server that lets an agent see and drive the user's PS5.

Stdio transport. It is a thin client of the local remote server
(server.py, default http://127.0.0.1:8765), which owns the Remote Play
session, so the agent and the browser remote share one connection.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Literal

import requests
from pydantic import BaseModel, Field
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

BASE = os.environ.get("PS5_REMOTE_URL", "http://127.0.0.1:8765")
HEADERS = {"X-Client": "agent"}
SETTLE_S = 0.9

INSTRUCTIONS = """\
These tools see and drive the user's PS5 over Remote Play, and query their PlayStation Network account.

Work in small steps: look, act with one to four presses, look at the returned screenshot, repeat. The \
screen is the only ground truth for what is selected. Report what you see rather than assuming a press worked.

PS5 controls: D-pad moves focus. CROSS selects. CIRCLE goes back. OPTIONS opens the item menu. \
L1/R1 switch tabs. A short PS press opens the Control Center, which also shows the Downloads card. \
ps5_home jumps to the Home screen. On Home, the top row holds games and apps (Game Library is the last \
tile of the Games row, and apps such as YouTube and Spotify are in the Media tab). The magnifier at the \
top right is system search. Text entry: select a text field with CROSS so the PS5 keyboard opens, then \
use ps5_type.

If the status line says the picture is blocked, a video app is on screen: the PS5 hides protected \
content from Remote Play. Input still works.

Playing games: use ps5_play. It runs a timed list of controller states on the server clock (sticks, \
held buttons and triggers together, with exact durations) and returns frames captured during the run, \
so you see what happened while you acted, not only the end. Work in bursts of 1 to 4 seconds: look, \
plan a burst, play it, read the frames, adjust. Learn each game's controls from its on-screen hints or \
its Controls menu, then test one control at a time with a short ps5_play and frames. Use enhance=true \
for dark scenes and ps5_look zoom to read small HUD text such as health or ammo. Real time keeps \
running between your calls, so in action games pause (usually OPTIONS) before long thinking, and \
pause before handing back to the user.

Use psn_library to check whether the user owns a game and psn_store_search for prices before navigating \
the console store.

Hard rules. Never complete a payment: stop before any Confirm Purchase, Buy, Pre-order, Subscribe, or \
add-funds step and ask the user, stating the item and price. Do not change system or account settings, \
delete games or saves, or accept new terms without asking. Starting a download of something the user \
owns, or of a free game they asked for, is allowed.\
"""

mcp = MCPServer("ps5", instructions=INSTRUCTIONS)


def _hints(*, read_only: bool, destructive: bool, idempotent: bool, open_world: bool) -> ToolAnnotations:
    """All four MCP tool hints, always explicit, so clients never fall back to the spec defaults."""
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


# Watching the screen changes nothing, but it can show other players' chat and web pages,
# so ps5_look is open world. Controller input can confirm any dialog on the console,
# a delete or a store purchase included, and can send text to other players, so the input tools
# are destructive and open world. Rest mode ends any online match, so power is destructive.
# PSN tools read Sony's web services.
LOOK = _hints(read_only=True, destructive=False, idempotent=True, open_world=True)
INPUT = _hints(read_only=False, destructive=True, idempotent=False, open_world=True)
NAVIGATE = _hints(read_only=False, destructive=False, idempotent=True, open_world=False)
POWER = _hints(read_only=False, destructive=True, idempotent=True, open_world=False)
PSN_READ = _hints(read_only=True, destructive=False, idempotent=True, open_world=True)


class RemoteDown(ToolError):
    """The local remote server is down or stuck. A ToolError, so the SDK shows the agent this text."""


def _req(method: str, path: str, **kw) -> requests.Response:
    timeout = kw.pop("timeout", 45)
    try:
        return requests.request(method, BASE + path, headers=HEADERS, timeout=timeout, **kw)
    except requests.ConnectionError as err:
        raise RemoteDown(
            f"The PS5 Agent Remote server is not running at {BASE}. Ask the user to start it "
            "(start.cmd in the ps5-agent-remote folder)."
        ) from err
    except requests.Timeout as err:
        raise RemoteDown(
            f"The PS5 Agent Remote server at {BASE} did not answer within {timeout:g} seconds. "
            "Call ps5_look to see the console, or ask the user to restart start.cmd."
        ) from err


def _json(method: str, path: str, **kw) -> dict:
    r = _req(method, path, **kw)
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _status_line(s: dict) -> str:
    parts = [f"PS5 {s.get('power')}"]
    parts.append(f"running: {s.get('app') or 'Home/system UI'}")
    if s.get("protected_content"):
        parts.append("PICTURE BLOCKED: protected video content is on screen, so the screenshot is black. "
                     "Input still works. ps5_home brings the picture back")
    if s.get("keyboard_open"):
        parts.append(f"keyboard open, text={s.get('keyboard_text')!r}")
    if not s.get("linked"):
        parts.append("this computer is NOT linked to the PS5 (the user must finish setup on the remote page)")
    if s.get("message"):
        parts.append(f"server: {s['message']}")
    return " | ".join(parts)


def _look(width: int = 1280, enhance: bool = False, zoom: list[float] | None = None) -> list:
    params = {"w": width}
    if enhance:
        params["enhance"] = "1"
    if zoom and len(zoom) == 4:
        params["crop"] = ",".join(str(v) for v in zoom)
    r = _req("GET", "/api/screen.jpg", params=params)
    state = _json("GET", "/api/state")
    if r.status_code != 200 or r.headers.get("content-type") != "image/jpeg":
        err = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return [f"No screenshot: {err}\n{_status_line(state)}"]
    return [Image(data=r.content, format="jpeg"), _status_line(state)]


Button = Literal[
    "UP", "DOWN", "LEFT", "RIGHT", "CROSS", "CIRCLE", "SQUARE", "TRIANGLE",
    "L1", "R1", "L2", "R2", "L3", "R3", "OPTIONS", "SHARE", "PS", "TOUCHPAD",
]


class Step(BaseModel):
    """One controller state, held for ms. Anything not listed is released."""

    hold: list[Button] = Field(default_factory=list, description="Buttons and triggers held down during this step.")
    left: list[float] | None = Field(None, description="Left stick [x, y], each -1 to 1. Right is +x, up is -y.")
    right: list[float] | None = Field(None, description="Right stick [x, y], each -1 to 1.")
    ms: int = Field(200, description="Duration, 0 to 10000.")


@mcp.tool(annotations=LOOK)
def ps5_look(width: int = 1280, enhance: bool = False, zoom: list[float] | None = None) -> list:
    """Screenshot the PS5 screen with a one-line status (power, running app, keyboard state).

    Args:
        width: Image width in pixels, 480 to 1920. Use 1280 to read store and menu text.
        enhance: Stretch contrast and lift shadows. Use for dark game scenes.
        zoom: Crop to [x, y, w, h] as fractions of the screen, scaled up to width. Example: [0.75, 0, 0.25, 0.2] for the top-right HUD.
    """
    return _look(max(480, min(1920, width)), enhance, zoom)


@mcp.tool(annotations=INPUT)
def ps5_play(steps: list[Step], frames: int = 4, enhance: bool = False, width: int = 960) -> list:
    """Run timed controller input for games, and return frames captured while it runs.

    Steps run back to back on the server clock, up to 30 seconds in total; everything is released at the
    end. Example, walk right 1 s then jump while still walking: [{"left": [1, 0], "ms": 1000},
    {"left": [1, 0], "hold": ["CROSS"], "ms": 400}]. Waiting with no input is a step with only ms.

    Args:
        steps: Controller states in order.
        frames: Frames to capture, spread evenly across the run (0 to 12). The last image is after release.
        enhance: Brighten dark scenes in the returned frames.
        width: Frame width in pixels, 320 to 1920.
    """
    total = sum(max(0, s.ms) for s in steps)
    every = int(total / max(1, frames - 1)) if frames > 1 else 0
    res = _json("POST", "/api/play", json={
        "steps": [s.model_dump(exclude_none=True) for s in steps],
        "frame_every_ms": every if frames > 1 else 0,
        "width": width, "enhance": enhance,
    }, timeout=total / 1000 + 60)
    if not res.get("ok"):
        return [f"Play failed: {res.get('error')}"]
    out: list = []
    for f in res["frames"]:
        out.append(f"t={f['t']}s")
        out.append(Image(data=base64.b64decode(f["jpeg_b64"]), format="jpeg"))
    out.append(_status_line(_json("GET", "/api/state")))
    return out


@mcp.tool(annotations=INPUT)
def ps5_press(
    buttons: list[Button],
    hold_ms: int = 100,
    gap_ms: int = 300,
    look: bool = True,
) -> list:
    """Press controller buttons in order, then return a screenshot of the result.

    Args:
        buttons: Buttons to tap in sequence. SHARE is the Create button.
        hold_ms: How long each button is held. Hold PS for 1200 to open Home.
        gap_ms: Pause between presses. Raise it to 800 or more when each press loads a new page.
        look: Return a screenshot after the presses settle.
    """
    res = _json("POST", "/api/press", json={"buttons": buttons, "hold_ms": hold_ms, "gap_ms": gap_ms}, timeout=120)
    if not res.get("ok"):
        return [f"Press failed: {res.get('error')}"]
    if not look:
        return [f"Pressed {' '.join(buttons)}"]
    time.sleep(SETTLE_S)
    return _look()


@mcp.tool(annotations=INPUT)
def ps5_type(text: str, submit: bool = True) -> list:
    """Type into the PS5 on-screen keyboard and return a screenshot. A text field must already be selected.

    Args:
        text: Text that replaces the keyboard's contents.
        submit: Close the keyboard with Done, which runs the search in most apps.
    """
    res = _json("POST", "/api/text", json={"text": text, "submit": submit})
    if not res.get("ok"):
        return [f"Typing failed: {res.get('error')}"]
    time.sleep(1.2)
    out = _look()
    if res.get("hint"):
        out.append(res["hint"])
    return out


@mcp.tool(annotations=NAVIGATE)
def ps5_home() -> list:
    """Go to the PS5 Home screen and return a screenshot."""
    res = _json("POST", "/api/action/home")
    if not res.get("ok"):
        return [f"Failed: {res.get('error')}"]
    time.sleep(1.5)
    return _look()


@mcp.tool(annotations=POWER)
def ps5_power(state: Literal["on", "rest"]) -> str:
    """Wake the PS5 from rest mode, or put it into rest mode. Waking takes about 20 seconds."""
    res = _json("POST", f"/api/action/{'wake' if state == 'on' else 'rest'}")
    return "OK. " + _status_line(res.get("state", {})) if res.get("ok") else f"Failed: {res.get('error')}"


@mcp.tool(annotations=PSN_READ)
def psn_now_playing() -> dict:
    """What the user's PlayStation Network account is doing now: online status, platform, and current game."""
    return _json("GET", "/api/psn/presence")


@mcp.tool(annotations=PSN_READ)
def psn_library(query: str = "", limit: int = 25, refresh: bool = False) -> dict:
    """Search the user's game library: games they own plus titles they have played, newest played first.

    Args:
        query: Case-insensitive name filter. Empty lists everything.
        limit: Maximum games returned, 1 to 200.
        refresh: Reload from PSN instead of the 30-minute cache, for example right after a purchase.
    """
    return _json("GET", "/api/psn/library", params={"q": query, "limit": limit, "refresh": "1" if refresh else "0"}, timeout=120)


@mcp.tool(annotations=PSN_READ)
def psn_store_search(query: str, limit: int = 10) -> dict:
    """Search the PlayStation Store for full games. Returns name, platforms, price, deals, and whether the user owns it.

    Args:
        query: Search text.
        limit: Maximum results, 1 to 30.
    """
    return _json("GET", "/api/psn/store", params={"q": query, "limit": limit}, timeout=60)


if __name__ == "__main__":
    mcp.run("stdio")
