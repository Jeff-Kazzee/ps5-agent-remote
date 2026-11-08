---
name: verify
description: Proves a ps5-agent-remote head before merge. Runs the unit tests and a cold stdio probe of the MCP server on Linux, then hands Jeff the console checks that need his Windows PC and PS5. Use when you verify a PR or head SHA in this repo, or write its merge-gate receipt.
---

# Verify ps5-agent-remote

The Git law's merge gate runs this skill. Run it on the exact head SHA, from a
session that did not build the change. The app has two surfaces: the MCP server
(`mcp_server.py`, stdio) and the web remote (`server.py` on 127.0.0.1:8765 with
`web/index.html`). Only the MCP client layer runs without a PS5.

Requires `tests/` and the explicit tool hints from PR #7. On a head without
them (such as `dev` at 1e9650f) the headless part fails. CI runs the same unit
tests on Windows but is billing locked as of 2026-11-08, so this run is the
only automated gate.

Proved on linveo-16gb with Python 3.14.9, 2026-11-08: at 3fff202 the 24 tests
pass and the probe prints `RESULT PASS`. At 1e9650f the probe fails 10 checks.

## 1. Headless checks (any Linux host)

Run on Daytona or `ssh linveo-16gb`. `PY` is a Python 3.11 or newer with the
`venv` module. Daytona's `python3` works. linveo has no system pip, so there set
`PY=/home/jeff/.hermes/tools/python-3.14.9+20261021-linux-x64/bin/python3`.
If the head under test has no `.claude/skills/verify/probe_mcp.py`, copy this
folder's copy to `/tmp/probe_mcp.py` and set `PROBE=/tmp/probe_mcp.py`.

```sh
set -e
SHA=<head sha>; W=/tmp/ps5vs; PY="${PY:-python3}"; PROBE="${PROBE:-$W/repo/.claude/skills/verify/probe_mcp.py}"
rm -rf "$W"
git clone -q https://github.com/Jeff-Kazzee/ps5-agent-remote.git "$W/repo"
git -C "$W/repo" fetch -q origin "$SHA" && git -C "$W/repo" checkout -q "$SHA"
git -C "$W/repo" rev-parse HEAD            # must equal $SHA
"$PY" -m venv "$W/venv"
"$W/venv/bin/python" -m pip install -q -r "$W/repo/requirements.txt"
cd "$W/repo" && "$W/venv/bin/python" -m unittest discover -s tests -v
"$W/venv/bin/python" "$PROBE" "$W/repo" "$W/venv/bin/python"
```

Pass means:

- `git rev-parse HEAD` equals the SHA under test.
- `pip install` exits 0. If a package has no wheel for the interpreter, record
  the package and stop. Do not install a subset.
- unittest ends with `OK` and its `Ran N tests` line counts every test in
  `tests/`. At 403c396 that is 24.
- The probe prints `RESULT PASS`. It first checks that every path
  `mcp_server.py` calls exists in `server.py`'s route table, because the unit
  tests fake the server with their own routes. Then it starts `python mcp_server.py` with
  `PS5_REMOTE_URL=http://127.0.0.1:1`, sends `initialize`,
  `notifications/initialized` and `tools/list`, checks the 9 tool names and
  that each tool sends all four hints as booleans, then calls `ps5_look` and
  expects `isError: true` with text that names `start.cmd`.

Cleanup: `rm -rf /tmp/ps5vs`, then confirm it is gone. Save the output in the
receipt first. The probe stops the server it started. Kill nothing else.

## 2. Manual acceptance (Jeff's Windows PC and PS5)

The headless part never touches a console, Remote Play, PSN or the browser
page. A diff limited to `mcp_server.py`, `tests/`, `docs/`, `README.md`,
`.gitignore` or this skill's folder needs only part 1. Any other file, such as
`server.py`, `web/`, `native/`, `tools/`, `.github/` or `requirements.txt`, also
needs this list. Hand it to Jeff with the `manual-acceptance` skill.

1. Double-click `start.cmd`. The console prints
   `PS5 Agent Remote: http://127.0.0.1:8765` and the browser opens the page.
2. On the page: the live view shows the PS5 screen, a D-pad press moves focus,
   typing into a selected text field reaches the PS5 keyboard, and Home works.
3. With the server running: `.venv\Scripts\python.exe tools\check_mcp.py`
   lists 9 tools, `ps5_look` returns `['image', 'text']`, and `psn_library`
   returns games.
4. With the server stopped: `.venv\Scripts\python.exe tools\test_native.py`
   prints `connected: True` and writes `native\build\shot1.jpg` and
   `shot2.jpg`. A `luma_mean` above 0 means a real picture.
5. For `native/` changes, rebuild first with the steps in
   `docs/07-building.md`.
6. For sign-in or linking changes, repeat the NPSSO and PIN steps in
   `docs/02-ps5-setup.md`.
7. Through an agent, with the server running: `ps5_press` with one `RIGHT`,
   `ps5_type` into a selected search field, `ps5_home`, `ps5_power` rest then
   on, `psn_now_playing`, `psn_store_search`, and a one-second `ps5_play`. Then
   open `/api/debug` in the browser and call `/api/action/disconnect` and
   `/api/action/connect` as `docs/06-http-api.md` shows. Each answers without
   an error.

Jeff replies pass or fail per step. A step he skips stays unverified in the
receipt.

## 3. Feature map

`features/README.md` lists every MCP tool and server route and how each one is
proved: a unit test name, the probe, or a manual step. When a PR adds a tool
or route, the PR updates that table.

## 4. Receipt

Write one Markdown file in `C:\Users\jeffk\Development\company-os-evidence\`
named `ps5-agent-remote-pr<N>-verify-<yyyymmdd>.md`, or in
`Documents/Codex/<date>/task-N/`. It holds:

| Field | Value |
|---|---|
| Head SHA | full 40-character SHA, the one `git rev-parse HEAD` printed |
| Builder | runtime and session ID that wrote the change |
| Verifier | runtime and session ID of this run, which must differ |
| Result | PASS or FAIL for part 1, and pass, fail or pending for part 2 |
| Evidence | host, Python version, the unittest summary line, the probe output, and Jeff's manual replies |

Merge with `gh pr merge --match-head-commit <sha>` only after Jeff approves.
