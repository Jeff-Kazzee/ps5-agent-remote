# PS5 Agent Remote

Control your PlayStation 5 from your computer, and let AI agents control it too.

PS5 Agent Remote runs a small server on your PC. It connects to your PS5 over
Sony's Remote Play protocol on your home network and gives you:

- **A remote in your browser.** Every controller button, both sticks, a live
  view of the PS5 screen, and typing from your keyboard into the PS5 keyboard.
- **Agent tools (MCP).** Claude Code, Claude Desktop, Cursor, DeepSeek Harness
  and any other MCP client can see the screen, press buttons, type, go Home,
  and turn the console on or off.
- **Agents that play games.** `ps5_play` runs timed stick, button and
  trigger input on the server clock and returns frames captured during the
  move, so an agent can walk, jump, aim and fight, and see what happened.
- **PlayStation Network lookups.** Search your game library and the
  PlayStation Store (with prices and whether you already own a game), and see
  what your account is playing.

Ask your agent "put on some lo-fi on YouTube", "is Hades on sale?" or "start
downloading Astro Bot from my library" while you keep working.

> Not affiliated with or endorsed by Sony Interactive Entertainment.
> "PlayStation" and "PS5" are trademarks of Sony Interactive Entertainment Inc.

## Requirements

| | |
|---|---|
| Computer | Windows 10 or 11, 64-bit |
| Python | 3.11 or newer |
| Console | PS5 on the same home network as the computer |
| Account | A PlayStation Network account signed in on that PS5 |

macOS and Linux are not supported yet. The Python code is portable, but the
native library is only built for Windows today.

## Quick start

1. **Install** Python, download this project, and install its packages.
   [docs/01-install.md](docs/01-install.md)
2. **Prepare the PS5.** Turn on Remote Play and network wake.
   [docs/02-ps5-setup.md](docs/02-ps5-setup.md)
3. **Start it.** Double-click `start.cmd`. Your browser opens
   http://127.0.0.1:8765.
4. **Sign in and link.** Paste your PSN sign-in token, then type the 8-digit
   PIN from the PS5. [docs/02-ps5-setup.md](docs/02-ps5-setup.md#23-sign-in-and-link-this-computer)
5. **Connect your agent** (optional).
   [docs/03-agents.md](docs/03-agents.md)

## Documentation

| Guide | What it covers |
|---|---|
| [01 Install](docs/01-install.md) | Python, download, packages, the native library |
| [02 PS5 setup](docs/02-ps5-setup.md) | Console settings, sign-in, linking, purchase safety |
| [03 Agents](docs/03-agents.md) | Claude Code, Claude Desktop, Cursor, DeepSeek Harness, the tools |
| [04 Using the remote](docs/04-using-the-remote.md) | The web page, keyboard shortcuts, live view, typing |
| [05 Troubleshooting](docs/05-troubleshooting.md) | Black screen, can't find PS5, linking errors |
| [06 HTTP API](docs/06-http-api.md) | Endpoints for your own scripts |
| [07 Building the native library](docs/07-building.md) | Compile `ps5bridge.dll` yourself |

## How it works

```
 Browser page ─┐
               ├─ HTTP / WebSocket ─> server.py ─> ps5bridge.dll ─ Remote Play (LAN) ─> PS5
 Agent (MCP) ──┘   127.0.0.1:8765        │          (libchiaki)
  mcp_server.py                          ├─ ddp.py      find / wake the PS5 (UDP 9302)
                                         └─ psn.py      library, store, presence (psnawp)
```

- `server.py` owns the single Remote Play session. The page and the agent
  share it, so they never fight over the console.
- `native/ps5bridge.dll` is [chiaki-ng](https://github.com/streetpea/chiaki-ng)'s
  protocol library (libchiaki) plus a small C API (`native/bridge.c`).
  chiaki-ng tracks PS5 firmware changes, so this keeps working as Sony updates
  the console.
- `ps5native.py` drives the DLL from Python and decodes the H.264 video with
  PyAV, keeping only the newest frame for screenshots.
- `mcp_server.py` is the agent side. It is a thin client of the server.

Everything stays on your computer and your home network. The server listens
on 127.0.0.1 only. The only internet calls are PSN lookups to Sony.

## Safety

- **Agents can't buy things on their own.** The agent instructions forbid
  completing any purchase, pre-order or subscription without asking you. For
  a hard stop, turn on **Require password at checkout** on the PS5
  ([how](docs/02-ps5-setup.md#24-recommended-require-a-password-for-purchases)).
  The agent never has your password.
- Agents are also told not to change settings, delete games or saves, or
  accept new terms without asking.
- `~/.ps5-remote/consoles.json` and `.env.local` hold the keys that let this
  computer control your PS5 and read your PSN account. Treat them like
  passwords and don't share them.

## Known limits

- **Video apps hide the picture.** While YouTube, Netflix, Tubi and similar
  apps are on screen, the PS5 sends Remote Play a black picture on purpose
  (protected content). Buttons still work. The page and the agent tools tell
  you when this happens, and **Home** brings the picture back.
- **Download progress and system updates** have no network API. Agents read
  them from the console screen (Control Center, Downloads).
- **One Remote Play session at a time.** Opening the official PS Remote Play
  app or chiaki-ng disconnects this one.
- **No consoles with a login passcode yet.** If your PS5 user has a passcode,
  connecting fails for now.
- **Linking a new console** (the PIN step) with the native library has not
  been tested end to end on a second PS5 yet. Please open an issue if it
  fails for you.

## License and credits

AGPL-3.0, because the native library links
[chiaki-ng](https://github.com/streetpea/chiaki-ng) (AGPL-3.0). See
[LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).

Built on chiaki-ng's libchiaki, Mbed TLS, nanopb, Jerasure and gf-complete
(native), and on psnawp, PyAV, aiohttp and the MCP Python SDK.
