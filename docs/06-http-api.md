# 6. HTTP API

The server listens on `http://127.0.0.1:8765` (local only). The page and
the MCP server use this API, and your own scripts can too. Send the header
`X-Client: <name>` to label your actions in the Activity feed.

Any call that needs the console opens the Remote Play session first if it
isn't open.

## Status

| Method | Path | Returns |
|---|---|---|
| GET | `/api/state` | Power, running app, linked, connected, keyboard state, `protected_content`, message |
| GET | `/api/activity` | Last 60 actions |
| GET | `/api/debug` | Video stats and the raw discovery reply |

## Screen and input

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/screen.jpg?w=1280` | | JPEG of the newest frame. `w` from 320 to 1920 |
| POST | `/api/press` | `{"buttons": ["DOWN","CROSS"], "hold_ms": 100, "gap_ms": 250}` | Taps in order |
| POST | `/api/text` | `{"text": "lofi", "submit": true}` | PS5 keyboard must be open |
| POST | `/api/action/home` | | Home screen |
| POST | `/api/action/wake` | | Power on from rest mode |
| POST | `/api/action/rest` | | Rest mode |
| POST | `/api/action/connect` | | Open the session now |
| POST | `/api/action/disconnect` | | Close the session |

Buttons: `UP DOWN LEFT RIGHT CROSS CIRCLE SQUARE TRIANGLE L1 R1 L2 R2 L3 R3
OPTIONS SHARE PS TOUCHPAD` (`SHARE` is the Create button).

### WebSocket `/ws`

For held buttons and sticks with low delay:

```json
{"type": "button", "button": "CROSS", "action": "press"}
{"type": "button", "button": "CROSS", "action": "release"}
{"type": "stick", "stick": "left", "x": 0.0, "y": -1.0}
```

Stick values run from -1.0 to 1.0. Up is negative `y`.

## Setup

| Method | Path | Body |
|---|---|---|
| POST | `/api/sign-in` | `{"npsso": "<token or the whole {\"npsso\":...} line>"}` |
| POST | `/api/link` | `{"pin": "12345678"}` |

## PlayStation Network

| Method | Path | Notes |
|---|---|---|
| GET | `/api/psn/status` | `{"configured": true}` once signed in |
| GET | `/api/psn/presence` | Online status and current game |
| GET | `/api/psn/library?q=elden&limit=25&refresh=0` | Owned and played games |
| GET | `/api/psn/store?q=hades&limit=10` | Store search with price and `owned` |

PSN calls are rate limited by the psnawp library to about one request every
3 seconds. The library list is cached for 30 minutes.

## Example (PowerShell)

```powershell
$h = @{ "X-Client" = "my-script" }
Invoke-RestMethod http://127.0.0.1:8765/api/press -Method Post -Headers $h `
  -ContentType application/json -Body '{"buttons":["PS"]}'
Invoke-WebRequest http://127.0.0.1:8765/api/screen.jpg -OutFile screen.jpg
```
