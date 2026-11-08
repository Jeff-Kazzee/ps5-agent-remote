# 7. Building the native library

You only need this if you don't want the prebuilt `ps5bridge.dll` from the
release, or you're changing `native/bridge.c`.

The build uses [zig](https://ziglang.org) as the C compiler, installed as a
Python package, so you don't need Visual Studio, MSYS2 or CMake. Nothing is
installed system-wide.

## Steps

From the project folder in PowerShell:

```powershell
git clone --depth 1 --branch v1.10.0 --recurse-submodules --shallow-submodules https://github.com/streetpea/chiaki-ng.git vendor\chiaki-ng-src
py -3.12 -m venv .buildenv
.buildenv\Scripts\python.exe -m pip install ziglang "protobuf>=4,<6" grpcio-tools requests
.buildenv\Scripts\python.exe tools\build_native.py
```

The last step:

1. Downloads Mbed TLS 2.28.10 into `vendor\` and checks its SHA-256 against
   the value published in the Mbed TLS release notes.
2. Generates the protobuf code for chiaki-ng's `takion.proto` with nanopb.
3. Compiles libchiaki, Mbed TLS, nanopb, Jerasure, gf-complete and
   `native\bridge.c` into `native\ps5bridge.dll` (about 1.2 MB).

The `vendor\`, `.buildenv\` and `native\build\` folders are ignored by git.

## What the build changes

The vendored chiaki-ng source stays untouched. The build script:

- **Patches a copy of `lib/src/rpcrypt.c`.** In its Mbed TLS code path,
  `chiaki_rpcrypt_generate_iv` lets HMAC-SHA256 write 32 bytes into a
  16-byte stack buffer. That overflow crashes the session. The copy uses a
  32-byte buffer. Official chiaki-ng builds use OpenSSL, so they don't hit
  this.
- **Leaves out internet play.** chiaki-ng's holepunch code needs curl,
  json-c, miniupnpc and libevent. This project only connects on your home
  network, so `native\holepunch_stub.c` replaces those functions.
- **Turns off Mbed TLS AES-NI and Padlock** (`native\ps5_mbedtls_user.h`)
  to keep the inline assembly out of the zig build.
- Uses Mbed TLS 2.28 because libchiaki's crypto code uses the 2.x API.

## Checking the build

With the remote server stopped (only one Remote Play session can run):

```powershell
.venv\Scripts\python.exe tools\test_native.py
```

It connects, saves two screenshots to `native\build\`, presses Right in
between, and prints frame stats. `luma_mean` above 0 means a real picture.

## Running the unit tests

The tests in `tests\` call each MCP tool by name against a fake remote server.
They need no PS5 and no native library:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

CI runs them after the native build on every pull request, on pushes to `prod`,
and on `v*` release tags.

## The C API

`native\bridge.c` exports a small API that `ps5native.py` calls with
ctypes:

| Function | Purpose |
|---|---|
| `ps5_lib_init` | Initialize libchiaki once |
| `ps5_register` | Link with an 8-digit PIN, return the keys |
| `ps5_start` | Open a session, with video, event and log callbacks |
| `ps5_set_controller` | Buttons, triggers and sticks |
| `ps5_keyboard_set_text`, `ps5_keyboard_accept` | PS5 on-screen keyboard |
| `ps5_go_home`, `ps5_goto_bed` | Home screen, rest mode |
| `ps5_stop` | Close the session and free it |
