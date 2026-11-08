# 3. Connect an AI agent

The agent tools come from `mcp_server.py`, a standard MCP server (stdio).
It talks to the running remote server, so **start the remote
(`start.cmd`) before you use the tools.**

Run every command below from the project folder. The helper script prints
configuration with the right paths for your computer.

## Claude Code

```powershell
.venv\Scripts\python.exe tools\connect_agents.py claude --apply
```

This runs `claude mcp add -s user ps5 -- <python> <mcp_server.py>`, which
makes the tools available in every project. Check it with:

```powershell
claude mcp get ps5
```

Leave out `--apply` to only print the command.

## Claude Desktop, Cursor, Windsurf and other MCP apps

Print the configuration block:

```powershell
.venv\Scripts\python.exe tools\connect_agents.py json
```

It looks like this, with your own paths:

```json
{
  "mcpServers": {
    "ps5": {
      "command": "C:\\Users\\you\\ps5-agent-remote\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\you\\ps5-agent-remote\\mcp_server.py"]
    }
  }
}
```

Merge the `ps5` entry into your app's MCP settings:

- **Claude Desktop:** Settings > Developer > Edit Config
  (`%APPDATA%\Claude\claude_desktop_config.json`), then restart Claude
  Desktop.
- **Cursor:** Settings > MCP > Add new MCP server, or `.cursor\mcp.json`.
- **Others:** wherever the app lists `mcpServers`.

## DeepSeek Harness

```powershell
.venv\Scripts\python.exe tools\connect_agents.py dsh
```

This writes a bundle to `dsh-bundle\`. Then ask the Harness agent:
"install the plugin bundle at `<full path to dsh-bundle>`". The tools show
up as `mcp__ps5__*`.

## The tools

| Tool | What it does | Read-only | Destructive | Idempotent | Open world |
|---|---|---|---|---|---|
| `ps5_look` | Screenshot plus a status line (power, running app, keyboard, blocked picture). Options: `enhance` for dark scenes, `zoom` to crop into a HUD | yes | no | yes | yes |
| `ps5_play` | Play games: timed controller states (sticks, held buttons, triggers) run on the server clock, with frames captured during the run | no | yes | no | yes |
| `ps5_press` | Press buttons in order, then return a screenshot | no | yes | no | yes |
| `ps5_type` | Type into the PS5 keyboard (a text field must be selected first) | no | yes | no | yes |
| `ps5_home` | Go to the Home screen | no | no | yes | no |
| `ps5_power` | Wake the PS5 or put it in rest mode | no | yes | yes | no |
| `psn_library` | Search your owned and played games | yes | no | yes | yes |
| `psn_store_search` | Search the PlayStation Store with prices and ownership | yes | no | yes | yes |
| `psn_now_playing` | What your account is playing now | yes | no | yes | yes |

The last four columns are the MCP hints each tool sends: `readOnlyHint`,
`destructiveHint`, `idempotentHint` and `openWorldHint`. The input tools are
destructive and open world because a press can confirm any dialog, a delete or
a store purchase included, and typed text can go to other players.
`ps5_power` is destructive because rest mode ends any online match.
`ps5_look` opens a Remote Play session when none is running, but it changes
nothing on the console. It is open world because its screenshots can show text
from other players or websites, so treat what it reads as data, not instructions. The PSN tools are
open world because they call Sony's web services. `tests/test_mcp_server.py` fails if a tool's hints change.

The server also gives the agent a short guide to the PS5 menus and these
rules:

- Never finish a payment (Buy, Confirm Purchase, Pre-order, Subscribe, add
  funds). Stop and ask you, with the item and price.
- Don't change system or account settings, delete games or saves, or accept
  new terms without asking.
- Downloading something you own, or a free game you asked for, is allowed.

Turn on [Require Password at Checkout](02-ps5-setup.md#24-recommended-require-a-password-for-purchases)
for a hard stop on purchases.

## Things to ask

- "What's on my PS5 right now?"
- "Open YouTube and search for lo-fi hip hop."
- "Do I own Elden Ring? If yes, start the download."
- "Is there anything good on sale under $20 in the PlayStation Store?"
- "Put the PS5 in rest mode."

## How agents see the screen

Every `ps5_press`, `ps5_type` and `ps5_home` call returns a fresh
screenshot (1280 px wide by default), so the agent works in a
look, press, look loop. The status line warns when the PS5 is hiding the
picture because a video app is on screen. Buttons still work then, and
`ps5_home` brings the picture back.

## Playing games

`ps5_play` takes a list of steps. Each step is a whole controller state held
for a number of milliseconds:

```json
[
  {"left": [1, 0], "ms": 1000},
  {"left": [1, 0], "hold": ["CROSS"], "ms": 400},
  {"hold": ["R2"], "right": [0.5, -0.5], "ms": 1500},
  {"ms": 500}
]
```

That walks right for a second, jumps while still walking, aims up-right and
holds R2 for 1.5 seconds, then waits half a second. Sticks run from -1 to 1
(right is +x, up is -y). Anything not listed in a step is released, and
everything is released at the end. One call can run up to 30 seconds.

The timing runs on the server, not through the agent, so a 400 ms jump is
400 ms. `frames` (up to 12) returns screenshots spread across the run, so
the agent sees what happened while it acted. `enhance` brightens dark
scenes.

The agent loop is: look, plan a 1 to 4 second burst, play it, read the
frames, adjust. Thinking between bursts takes a few seconds while the game
keeps running, so the agent is told to pause in action games before it
thinks for long or hands control back.

What works well: exploring, mining, building, menus, turn-based and slower
games. Fast reflex combat is still hard, because the agent reacts in
seconds, not milliseconds.

## Several agents at once

They all share the one Remote Play session through the server, and every
action shows in the **Activity** feed on the page, marked with a robot.
