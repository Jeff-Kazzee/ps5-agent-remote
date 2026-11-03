# 4. Using the remote

Start the server with `start.cmd` and open http://127.0.0.1:8765.

## The page

- **Top bar:** what the PS5 is running, its power state, and whether the
  remote is connected.
- **Screen:** tick **Live view** to see the PS5 screen, updated a few times
  a second. Untick it when you don't need it to save CPU.
- **Type box:** select a search box on the PS5 first (press ✕ on it so the
  PS5 keyboard opens), then type here and press Enter. Your text replaces
  the keyboard's contents and submits.
- **Home** jumps to the PS5 Home screen.
- **Activity:** everything the remote and agents did, newest first.
  Agent actions have a 🤖.
- **PlayStation Network:** type a game name, then **My library** or
  **Store**. Store results show the price, or **Owned**.
- **Controller:** every button. Hold a button to hold it on the console
  (for example hold **PS** to open Home). Drag inside the round pads to move
  the sticks.
- **Power on / Rest mode / Connect / Disconnect.**

The Remote Play connection opens on the first button press, screenshot or
Live view, and closes after 15 minutes without input.

## Keyboard shortcuts

Click on the page background first so the shortcuts reach the page.

| Key | Button |
|---|---|
| Arrow keys | D-pad |
| Enter | ✕ |
| Backspace | ○ |
| T | △ |
| S | □ |
| P | PS |
| O | Options |
| C | Create |
| Q / E | L1 / R1 |
| 1 / 3 | L2 / R2 |

## When the picture goes black

The PS5 hides protected content, such as video apps, from Remote Play. The
page shows a note when this happens. Buttons still work. Press **Home** to
get the picture back.

## Settings

Set these in `.env.local` (one `NAME=value` per line) or as environment
variables before `start.cmd`.

| Setting | Default | Meaning |
|---|---|---|
| `PS5_HOST` | found automatically | The PS5's IP address |
| `REMOTE_PORT` | `8765` | Port for the page and API |
| `PS5_RESOLUTION` | `720p` | `360p`, `540p`, `720p` or `1080p` |
| `PS5_FPS` | `60` | `30` or `60` |
| `IDLE_DISCONNECT_S` | `900` | Close Remote Play after this many idle seconds |
| `PS5_CHIAKI_LOG_MASK` | `7` | Native log detail. `31` logs everything |
| `PS5_REMOTE_URL` | `http://127.0.0.1:8765` | Where the MCP server finds the remote |
| `PS5_REMOTE_HOME` | `~\.ps5-remote` | Where link keys are stored |

Higher resolutions and 60 FPS use more CPU for decoding. 720p is enough for
agents to read menu and store text.
