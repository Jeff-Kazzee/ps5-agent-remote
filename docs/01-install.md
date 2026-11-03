# 1. Install

This takes about 10 minutes. Everything goes into one folder. Nothing is
installed system-wide except Python.

## 1.1 Install Python

You need Python 3.11 or newer.

1. Open **PowerShell** (press Start, type `powershell`, press Enter).
2. Check whether Python is already there:

   ```powershell
   py --version
   ```

   If it prints `Python 3.11` or higher, skip to 1.2.
3. Otherwise install it with winget:

   ```powershell
   winget install Python.Python.3.12
   ```

   Or download it from https://www.python.org/downloads/windows/. In the
   installer, tick **Add python.exe to PATH**.
4. Close and reopen PowerShell, then run `py --version` again.

## 1.2 Download PS5 Agent Remote

**With Git:**

```powershell
cd $HOME
git clone https://github.com/Jeff-Kazzee/ps5-agent-remote.git
cd ps5-agent-remote
```

**Without Git:** on the GitHub page click **Code**, then **Download ZIP**.
Extract it to a folder you will keep, for example
`C:\Users\<you>\ps5-agent-remote`, and `cd` into that folder in PowerShell.

All commands below run from inside this folder.

## 1.3 Install the Python packages

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This creates a private Python environment in `.venv` and installs the
packages into it. If `py -3.12` says the version isn't installed, use the
version you have, for example `py -3.11`.

## 1.4 Get the native library

The Remote Play connection lives in `native\ps5bridge.dll`. Download the
prebuilt file, or [build it yourself](07-building.md).

1. Open the project's **Releases** page on GitHub and download
   `ps5bridge.dll` from the newest release.
2. Put it in the `native` folder, so the path is `native\ps5bridge.dll`.
3. Check that the file matches the release:

   ```powershell
   Get-FileHash native\ps5bridge.dll -Algorithm SHA256
   ```

   The hash must equal the `SHA-256` listed in the release notes. If it
   doesn't, delete the file and download it again.

The release DLL is built by GitHub Actions from this repository's source,
using [`tools/build_native.py`](../tools/build_native.py). The workflow is in
[`.github/workflows/build-native.yml`](../.github/workflows/build-native.yml).

## 1.5 Start it

Double-click **`start.cmd`**, or run:

```powershell
.\start.cmd
```

A console window opens and your browser goes to http://127.0.0.1:8765.
Keep the window open while you use the remote. Close it to stop.

The first time, **Windows Firewall** may ask whether Python can use the
network. Allow it on **Private networks**. The PS5 sends video back to your
computer, and the firewall would otherwise block it.

Next: [2. PS5 setup](02-ps5-setup.md)

## Updating

```powershell
git pull
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then download the `ps5bridge.dll` from the newest release again if the
release notes say it changed.
