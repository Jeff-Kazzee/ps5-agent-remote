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

| Tool | What it does |
|---|---|
| `ps5_look` | Screenshot plus a status line (power, running app, keyboard, blocked picture) |
| `ps5_press` | Press buttons in order, then return a screenshot |
| `ps5_type` | Type into the PS5 keyboard (a text field must be selected first) |
| `ps5_home` | Go to the Home screen |
| `ps5_power` | Wake the PS5 or put it in rest mode |
| `psn_library` | Search your owned and played games |
| `psn_store_search` | Search the PlayStation Store with prices and ownership |
| `psn_now_playing` | What your account is playing now |

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

Each call takes about a second, so agents are good at menus, stores and
search, and too slow for fast action games.

## Several agents at once

They all share the one Remote Play session through the server, and every
action shows in the **Activity** feed on the page, marked with a robot.
