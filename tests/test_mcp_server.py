"""Tests for the MCP tools in mcp_server.py.

Each tool is called by name through the MCP server, against a fake of the local
remote server, so no PS5, Remote Play session or PSN account is needed.

Run from the repo root: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mcp_server  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
STATE = {"power": "on", "app": "Terraria", "linked": True}

# Expected hints per tool: readOnly, destructive, idempotent, openWorld.
EXPECTED_HINTS = {
    "ps5_look": (True, False, True, True),
    "ps5_play": (False, True, False, True),
    "ps5_press": (False, True, False, True),
    "ps5_type": (False, True, False, True),
    "ps5_home": (False, False, True, False),
    "ps5_power": (False, True, True, False),
    "psn_now_playing": (True, False, True, True),
    "psn_library": (True, False, True, True),
    "psn_store_search": (True, False, True, True),
}
HINT_KEYS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


class FakeResponse:
    def __init__(self, status=200, body=None, content_type="application/json"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        if isinstance(body, bytes):
            self.content = body
            self.text = body.decode("latin-1")
        else:
            self.text = json.dumps(body)
            self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FakeRemote:
    """Stands in for requests.request. Records each call and answers by route."""

    def __init__(self, routes=None):
        self.calls = []
        self.routes = {
            ("GET", "/api/screen.jpg"): FakeResponse(200, JPEG, "image/jpeg"),
            ("GET", "/api/state"): FakeResponse(200, STATE),
        }
        self.routes.update(routes or {})

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        path = url[len(mcp_server.BASE):]
        self.calls.append({"method": method, "path": path, "headers": headers, **kw})
        if (method, path) not in self.routes:
            raise AssertionError(f"unexpected request {method} {path}")
        return self.routes[(method, path)]

    def sent(self, method, path):
        return [c for c in self.calls if c["method"] == method and c["path"] == path]


def call(name, args=None):
    return asyncio.run(mcp_server.mcp.call_tool(name, args or {}))


def kinds(result):
    return [c.type for c in result.content]


def texts(result):
    return [c.text for c in result.content if c.type == "text"]


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        sleep = mock.patch.object(mcp_server.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def remote(self, routes=None):
        fake = FakeRemote(routes)
        patcher = mock.patch.object(mcp_server.requests, "request", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class ToolListTest(unittest.TestCase):
    def tools(self):
        return {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}

    def test_server_lists_exactly_the_nine_tools(self):
        self.assertEqual(set(self.tools()), set(EXPECTED_HINTS))

    def test_every_tool_sets_all_four_hints_as_booleans(self):
        for name, tool in self.tools().items():
            with self.subTest(tool=name):
                hints = tool.model_dump(by_alias=True, exclude_none=True).get("annotations", {})
                for key in HINT_KEYS:
                    self.assertIn(key, hints)
                    self.assertIsInstance(hints[key], bool)

    def test_hints_match_what_each_handler_does(self):
        for name, tool in self.tools().items():
            with self.subTest(tool=name):
                hints = tool.model_dump(by_alias=True)["annotations"]
                self.assertEqual(tuple(hints[k] for k in HINT_KEYS), EXPECTED_HINTS[name])


class Ps5LookTest(ToolTestCase):
    def test_ps5_look_returns_screenshot_and_status(self):
        fake = self.remote()
        result = call("ps5_look", {"width": 100, "enhance": True, "zoom": [0.75, 0, 0.25, 0.2]})
        self.assertEqual(kinds(result), ["image", "text"])
        self.assertEqual(base64.b64decode(result.content[0].data), JPEG)
        self.assertIn("running: Terraria", texts(result)[0])
        params = fake.sent("GET", "/api/screen.jpg")[0]["params"]
        self.assertEqual(params, {"w": 480, "enhance": "1", "crop": "0.75,0.0,0.25,0.2"})
        self.assertEqual(fake.calls[0]["headers"], {"X-Client": "agent"})

    def test_ps5_look_reports_server_error_without_image(self):
        self.remote({("GET", "/api/screen.jpg"): FakeResponse(503, {"ok": False, "error": "PS5 is in rest mode."})})
        result = call("ps5_look")
        self.assertEqual(kinds(result), ["text"])
        self.assertIn("No screenshot: PS5 is in rest mode.", texts(result)[0])

    def test_ps5_look_tells_the_agent_when_remote_server_is_down(self):
        # The SDK hides the text of any exception that is not a ToolError, so the
        # agent would see only "Error executing tool ps5_look".
        with mock.patch.object(mcp_server.requests, "request", side_effect=requests.ConnectionError()):
            with self.assertRaises(ToolError) as ctx:
                call("ps5_look")
        self.assertNotIsInstance(ctx.exception, UnexpectedToolError)
        self.assertIn("is not running", str(ctx.exception))
        self.assertIn("start.cmd", str(ctx.exception))


    def test_ps5_look_tells_the_agent_when_remote_server_times_out(self):
        with mock.patch.object(mcp_server.requests, "request", side_effect=requests.ReadTimeout()):
            with self.assertRaises(ToolError) as ctx:
                call("ps5_look")
        self.assertNotIsInstance(ctx.exception, UnexpectedToolError)
        self.assertIn("did not answer within 45 seconds", str(ctx.exception))


    def test_ps5_look_reports_a_connect_timeout_as_a_timeout(self):
        # ConnectTimeout is both a ConnectionError and a Timeout. It means the server was
        # not reached in time, not that it is stopped.
        with mock.patch.object(mcp_server.requests, "request", side_effect=requests.ConnectTimeout()):
            with self.assertRaises(ToolError) as ctx:
                call("ps5_look")
        self.assertIn("did not answer within 45 seconds", str(ctx.exception))


class Ps5PlayTest(ToolTestCase):
    def test_ps5_play_sends_steps_and_returns_frames(self):
        frame = {"t": 0.5, "jpeg_b64": base64.b64encode(JPEG).decode()}
        fake = self.remote({("POST", "/api/play"): FakeResponse(200, {"ok": True, "frames": [frame, frame]})})
        steps = [{"left": [1, 0], "ms": 1000}, {"left": [1, 0], "hold": ["CROSS"], "ms": 500}]
        result = call("ps5_play", {"steps": steps, "frames": 4})
        self.assertEqual(kinds(result), ["text", "image", "text", "image", "text"])
        self.assertEqual(texts(result)[0], "t=0.5s")
        sent = fake.sent("POST", "/api/play")[0]["json"]
        self.assertEqual(sent["frame_every_ms"], 500)
        self.assertEqual(sent["steps"][1], {"hold": ["CROSS"], "left": [1.0, 0.0], "ms": 500})

    def test_ps5_play_reports_failure(self):
        self.remote({("POST", "/api/play"): FakeResponse(400, {"ok": False, "error": "too long"})})
        result = call("ps5_play", {"steps": [{"ms": 100}]})
        self.assertEqual(texts(result), ["Play failed: too long"])

    def test_ps5_play_rejects_unknown_button(self):
        fake = self.remote()
        with self.assertRaises(ToolError):
            call("ps5_play", {"steps": [{"hold": ["JUMP"], "ms": 100}]})
        self.assertEqual(fake.calls, [])


class Ps5PressTest(ToolTestCase):
    def test_ps5_press_sends_buttons_and_looks(self):
        fake = self.remote({("POST", "/api/press"): FakeResponse(200, {"ok": True})})
        result = call("ps5_press", {"buttons": ["DOWN", "CROSS"], "gap_ms": 800})
        self.assertEqual(kinds(result), ["image", "text"])
        self.assertEqual(fake.sent("POST", "/api/press")[0]["json"],
                         {"buttons": ["DOWN", "CROSS"], "hold_ms": 100, "gap_ms": 800})

    def test_ps5_press_without_look(self):
        fake = self.remote({("POST", "/api/press"): FakeResponse(200, {"ok": True})})
        result = call("ps5_press", {"buttons": ["CIRCLE"], "look": False})
        self.assertEqual(texts(result), ["Pressed CIRCLE"])
        self.assertEqual(fake.sent("GET", "/api/screen.jpg"), [])

    def test_ps5_press_reports_failure(self):
        self.remote({("POST", "/api/press"): FakeResponse(200, {"ok": False, "error": "not linked"})})
        self.assertEqual(texts(call("ps5_press", {"buttons": ["PS"]})), ["Press failed: not linked"])


class Ps5TypeTest(ToolTestCase):
    def test_ps5_type_sends_text_and_appends_hint(self):
        fake = self.remote({("POST", "/api/text"): FakeResponse(200, {"ok": True, "hint": "Keyboard closed."})})
        result = call("ps5_type", {"text": "Elden Ring", "submit": False})
        self.assertEqual(fake.sent("POST", "/api/text")[0]["json"], {"text": "Elden Ring", "submit": False})
        self.assertEqual(kinds(result), ["image", "text", "text"])
        self.assertEqual(texts(result)[-1], "Keyboard closed.")

    def test_ps5_type_reports_failure(self):
        self.remote({("POST", "/api/text"): FakeResponse(200, {"ok": False, "error": "no keyboard"})})
        self.assertEqual(texts(call("ps5_type", {"text": "x"})), ["Typing failed: no keyboard"])


class Ps5HomeTest(ToolTestCase):
    def test_ps5_home_goes_home_and_looks(self):
        fake = self.remote({("POST", "/api/action/home"): FakeResponse(200, {"ok": True})})
        result = call("ps5_home")
        self.assertEqual(len(fake.sent("POST", "/api/action/home")), 1)
        self.assertEqual(kinds(result), ["image", "text"])

    def test_ps5_home_reports_failure(self):
        self.remote({("POST", "/api/action/home"): FakeResponse(200, {"ok": False, "error": "asleep"})})
        self.assertEqual(texts(call("ps5_home")), ["Failed: asleep"])


class Ps5PowerTest(ToolTestCase):
    def test_ps5_power_on_wakes(self):
        fake = self.remote({("POST", "/api/action/wake"): FakeResponse(200, {"ok": True, "state": STATE})})
        self.assertTrue(texts(call("ps5_power", {"state": "on"}))[0].startswith("OK. PS5 on"))
        self.assertEqual(len(fake.sent("POST", "/api/action/wake")), 1)

    def test_ps5_power_rest_sends_rest(self):
        fake = self.remote({("POST", "/api/action/rest"): FakeResponse(200, {"ok": True, "state": STATE})})
        call("ps5_power", {"state": "rest"})
        self.assertEqual(len(fake.sent("POST", "/api/action/rest")), 1)

    def test_ps5_power_rejects_unknown_state(self):
        fake = self.remote()
        with self.assertRaises(ToolError):
            call("ps5_power", {"state": "off"})
        self.assertEqual(fake.calls, [])


class PsnTest(ToolTestCase):
    def test_psn_now_playing_returns_presence(self):
        presence = {"ok": True, "online": True, "game": "Terraria"}
        self.remote({("GET", "/api/psn/presence"): FakeResponse(200, presence)})
        self.assertEqual(json.loads(texts(call("psn_now_playing"))[0]), presence)

    def test_psn_library_passes_query_limit_and_refresh(self):
        fake = self.remote({("GET", "/api/psn/library"): FakeResponse(200, {"ok": True, "games": []})})
        call("psn_library", {"query": "elden", "limit": 5, "refresh": True})
        self.assertEqual(fake.sent("GET", "/api/psn/library")[0]["params"],
                         {"q": "elden", "limit": 5, "refresh": "1"})

    def test_psn_store_search_passes_query_and_limit(self):
        fake = self.remote({("GET", "/api/psn/store"): FakeResponse(200, {"ok": True, "results": []})})
        call("psn_store_search", {"query": "Astro Bot"})
        self.assertEqual(fake.sent("GET", "/api/psn/store")[0]["params"], {"q": "Astro Bot", "limit": 10})

    def test_psn_tools_turn_non_json_into_an_error(self):
        self.remote({("GET", "/api/psn/presence"): FakeResponse(502, b"Bad Gateway", "text/plain")})
        self.assertEqual(json.loads(texts(call("psn_now_playing"))[0]),
                         {"ok": False, "error": "HTTP 502: Bad Gateway"})


if __name__ == "__main__":
    unittest.main()
