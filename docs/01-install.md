# 1. Install

This takes about 10 minutes. Python and the project packages stay in the
project folder.

Last verified: 2026-11-14 against the Python 3.12.16 release and upgrade instructions. Windows execution remains unverified.

## 1.1 Download PS5 Agent Remote

Open **PowerShell** (press Start, type `powershell`, press Enter).

**With Git:**

```powershell
cd $HOME
git clone https://github.com/Jeff-Kazzee/ps5-agent-remote.git
if ($LASTEXITCODE -ne 0) { throw "Project clone failed. Inspect the existing folder before continuing." }
cd ps5-agent-remote
```

**Without Git:** on the GitHub page click **Code**, then **Download ZIP**.
Extract it to a folder you will keep, for example
`C:\Users\<you>\ps5-agent-remote`, and `cd` into that folder in PowerShell.

All commands below run from inside this folder.

## 1.2 Get patched Python

Use Python 3.12.16. The official Windows installers for 3.12 stop at
3.12.10, which lacks later security fixes. This project uses
[Astral's maintained Python 3.12.16 build](https://github.com/astral-sh/python-build-standalone/releases/tag/20261110)
for Windows x64. It keeps the existing Python 3.12 package compatibility.
See [Python's security release notes](https://www.python.org/downloads/release/python-31216/).

Paste this block into PowerShell. It checks the release's SHA-256 before
extracting Python into `.python`. It leaves your system Python alone.
If `.python` already exists, follow [Updating](#updating) first. A completed,
verified installation can be reused. An older or incomplete installation
must be moved aside before retrying this download.

```powershell
$ErrorActionPreference = "Stop"
if (Test-Path .python) { throw "The .python folder already exists. See Updating below." }
$archive = Join-Path $env:TEMP "ps5-cpython-3.12.16.tar.gz"
Invoke-WebRequest -Uri "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only.tar.gz" -OutFile $archive
$expected = "e23fe5b16926de1d81661b1a97352e89fb167549c55a6825796ccd0f32ec7f1b"
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw "Python archive SHA-256 mismatch"
}
New-Item -ItemType Directory -Path .python | Out-Null
tar -xzf $archive -C .python
if ($LASTEXITCODE -ne 0) { throw "Python archive extraction failed" }
.python\python\python.exe -c "import sys, struct; assert sys.version_info[:3] == (3, 12, 16); assert struct.calcsize('P') == 8; print(sys.executable, sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Python runtime verification failed" }
Remove-Item -LiteralPath $archive
```

## 1.3 Install the Python packages

Before recreating an existing `.venv`, stop the remote and stop or disable
the PS5 MCP server in each connected agent app. The MCP server is a separate
Python process and can keep files open after the remote stops. Keep those
connections disabled until this section completes, then restart them.

```powershell
.python\python\python.exe -m venv --clear .venv
if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Application dependency installation failed" }
.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency compatibility check failed" }
```

This recreates the private Python environment in `.venv` with the patched
interpreter and installs the packages into it. Updating pip alone does not
update the Python interpreter.

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

Stop the remote and stop or disable its PS5 MCP connection in every agent
app before updating. Closing `start.cmd` does not stop an agent's stdio MCP
process. If an app has no server-stop control, close that app for the update.
Pull the project changes, then check the existing environment:

```powershell
git pull
if ($LASTEXITCODE -ne 0) { throw "Project update failed. Resolve the Git error before continuing." }
.venv\Scripts\python.exe --version
```

For an older or incomplete `.venv`, first choose the matching runtime step:

- If `.python` is absent, complete section 1.2, then section 1.3.
- If section 1.2 previously completed successfully with its archive hash
  check, verify that runtime with the block below. When it passes, skip the
  download in section 1.2 and go directly to section 1.3. This also resumes
  an update interrupted after installing Python but before recreating `.venv`.
- If extraction was interrupted, a runtime check fails, or the runtime's
  origin is uncertain, preserve `.python` under an unused backup name,
  for example `Rename-Item .python .python-previous`. Repeat section 1.2
  into a new `.python` folder, then section 1.3. Do not extract over the
  existing folder or disable its hash check.

Only run this check for a runtime installed from the verified archive in
section 1.2:

```powershell
$ErrorActionPreference = "Stop"
.python\python\python.exe -c "import sys, struct, ssl, venv, ensurepip; print(sys.executable, sys.version); sys.exit(0 if sys.version_info[:3] == (3, 12, 16) and struct.calcsize('P') == 8 else 'Expected x64 Python 3.12.16')"
if ($LASTEXITCODE -ne 0) { throw "Runtime check failed. Preserve .python under an unused backup name and repeat section 1.2." }
```

Keep the backup until the new setup works. Do not copy the old virtual
environment into the new one. If `.venv` is missing or its version check
fails after an interrupted update, use the same runtime choices above and
rerun section 1.3.
Recreate an existing `.buildenv` with the [build steps](07-building.md) too.
Keep `.env.local` and the console credentials in `$HOME\.ps5-remote`.

If `.venv` already reports Python 3.12.16, still verify the trusted runtime
above first. If `.python` is absent, older, incomplete or unverified, use
the matching runtime step above and recreate `.venv` with section 1.3.
Otherwise confirm that `.venv` uses that exact x64 base interpreter before
updating its packages:

```powershell
$ErrorActionPreference = "Stop"
.venv\Scripts\python.exe -c "import os, sys, struct; valid = sys.version_info[:3] == (3, 12, 16) and struct.calcsize('P') == 8 and os.path.samefile(sys.base_prefix, os.path.abspath('.python/python')); print(sys.executable, sys.base_prefix); sys.exit(0 if valid else 'Expected the verified project-local x64 Python 3.12.16')"
if ($LASTEXITCODE -ne 0) { throw "Environment check failed. Recreate .venv with section 1.3 before continuing." }
.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Application dependency installation failed" }
.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency compatibility check failed" }
```

While the remote and MCP connections are still stopped, replace
`ps5bridge.dll` if the newest release notes say it changed. Verify its
SHA-256 as section 1.4 describes before starting anything that loads it.
Once the environment and native library updates succeed, restart the
remote and re-enable its PS5 MCP connections in your agent apps.
