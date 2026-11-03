# 5. Troubleshooting

Start with the console window that `start.cmd` opened. Errors show up there.
For more detail, set `PS5_CHIAKI_LOG_MASK=31` in `.env.local` and restart.

## "No PS5 found on this network"

- The PS5 must be on or in rest mode, not fully off.
- The computer and PS5 must be on the same network. Guest Wi-Fi and some
  mesh "isolation" settings block devices from seeing each other.
- VPNs on the computer can hide the local network. Pause them.
- Set the address yourself: `PS5_HOST=192.168.x.x` in `.env.local`. Find it
  on the PS5 under **Settings > Network > Connection Status > View
  Connection Status**.
- Run `.venv\Scripts\python.exe ddp.py`. It lists every PS5 that answers.

## The picture is black but buttons work

The PS5 hides protected content from Remote Play. This happens in video
apps (YouTube, Netflix, Tubi, Disney+ and others) and sometimes right after
leaving one. Press **Home** on the page (or the agent uses `ps5_home`). The
page and the agent status line say "picture blocked" when this is the cause.

## The picture is black and buttons don't work

The Remote Play connection isn't up.

- Look at the top bar. **Not linked** means setup isn't finished.
- **PS5 resting** means it's in rest mode. Press **Power on** and wait about
  20 seconds.
- Allow Python through **Windows Firewall** on private networks. Search
  Start for "Allow an app through Windows Firewall" and tick **Private** for
  the `python.exe` inside `.venv`.

## "Another Remote Play session is connected"

Only one Remote Play session can run. Close the official PS Remote Play app,
chiaki-ng, or a second copy of this server. After a crash the PS5 keeps the
old session for a few seconds. Wait 10 to 20 seconds and try again.

## Linking fails

- The PIN expires after a few minutes. Open **Link Device** again for a new
  one.
- The PS5 must be on, not in rest mode.
- Sign in (step 1) must be done first, with the same account that is
  signed in on the PS5.
- If your PS5 user has a **login passcode**, linking and connecting don't
  work yet.

## "Sony rejected the token" or PSN lookups fail

The `npsso` token expired, or it was replaced by a newer one. Repeat
[step 1 of the sign-in](02-ps5-setup.md#step-1-sign-in-to-playstation-network).

## "native\ps5bridge.dll is missing" or a DLL load error

Download `ps5bridge.dll` from the newest release into the `native` folder
([install step 1.4](01-install.md#14-get-the-native-library)). Antivirus
tools sometimes quarantine new DLLs. Check its quarantine list.

## The agent says the server is not running

Start `start.cmd` first. The agent tools are a client of that server. If
you changed `REMOTE_PORT`, set `PS5_REMOTE_URL` for the MCP server too.

## Typing does nothing

Select a text field on the PS5 first so its on-screen keyboard is open. The
status line shows `keyboard open` when the PS5 is ready for text.

## Power on doesn't wake the PS5

Turn on **Stay Connected to the Internet** and **Enable Turning On PS5 from
Network** ([PS5 setup 2.2](02-ps5-setup.md#22-let-the-computer-wake-the-ps5-optional-recommended)).

## Still stuck

Open an issue with the console window output (remove your PSN name and
token first) and your PS5 system software version from **Settings >
System > System Software**.
