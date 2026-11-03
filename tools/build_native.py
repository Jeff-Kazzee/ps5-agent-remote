"""Build native/ps5bridge.dll: chiaki-ng's libchiaki (LAN only) + bridge.c.

Run with the build venv:  .buildenv\\Scripts\\python.exe tools\\build_native.py
Needs vendor/chiaki-ng-src (git clone --branch v1.10.0 --recurse-submodules).
Downloads Mbed TLS 3.6.6 once and checks the SHA-256 published in its
release notes. Compiler is zig cc (pip package ziglang), target
x86_64-windows-gnu. Nothing is installed system-wide.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tarfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
CHIAKI = VENDOR / "chiaki-ng-src"
BUILD = ROOT / "native" / "build"
GEN = BUILD / "gen"
OUT = ROOT / "native" / "ps5bridge.dll"

# libchiaki's ecdh.c and gkcrypt.c use the Mbed TLS 2.x API (ctx.d, 6-arg
# mbedtls_gcm_starts). 3.6 fails to compile them (checked 2026-11-02).
MBEDTLS_VER = "2.28.10"
MBEDTLS_URL = f"https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-{MBEDTLS_VER}/mbedtls-{MBEDTLS_VER}.tar.bz2"
MBEDTLS_SHA256 = "19e5b81fdac0fe22009b9e2bdcd52d7dcafbf62bc67fc59cf0a76b5b5540d149"
MBEDTLS = VENDOR / f"mbedtls-{MBEDTLS_VER}"

PY = sys.executable


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "", flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode:
        sys.exit(f"command failed with exit code {r.returncode}")


def fetch_mbedtls() -> None:
    if (MBEDTLS / "include" / "mbedtls" / "aes.h").exists():
        return
    archive = VENDOR / f"mbedtls-{MBEDTLS_VER}.tar.bz2"
    h = hashlib.sha256()
    with requests.get(MBEDTLS_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(archive, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                h.update(chunk)
    if h.hexdigest() != MBEDTLS_SHA256:
        archive.unlink()
        sys.exit(f"Mbed TLS SHA-256 mismatch: {h.hexdigest()}")
    with tarfile.open(archive) as t:
        t.extractall(VENDOR, filter="data")
    archive.unlink()
    print("mbedtls ok")


def gen_protobuf() -> None:
    GEN.mkdir(parents=True, exist_ok=True)
    proto_dir = CHIAKI / "lib" / "protobuf"
    pb = GEN / "takion.pb"
    run([PY, "-m", "grpc_tools.protoc", f"-o{pb}", f"-I{proto_dir}", str(proto_dir / "takion.proto")])
    run([PY, str(CHIAKI / "third-party" / "nanopb" / "generator" / "nanopb_generator.py"), str(pb)], cwd=GEN)
    cfg = GEN / "chiaki" / "config.h"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(
        "#ifndef CHIAKI_CONFIG_H\n#define CHIAKI_CONFIG_H\n"
        "#define CHIAKI_LIB_ENABLE_OPUS 0\n#define CHIAKI_LIB_ENABLE_PI_DECODER 0\n"
        "#define CHIAKI_LIB_ENABLE_FFMPEG_DECODER 0\n#endif\n"
    )


def patched_rpcrypt() -> Path:
    """Copy rpcrypt.c with a stack overflow fix.

    In the Mbed TLS branch, chiaki_rpcrypt_generate_iv declares
    uint8_t hmac[CHIAKI_RPCRYPT_KEY_SIZE] (16 bytes) and lets
    mbedtls_md_hmac_finish write a 32-byte SHA-256 into it. Official
    chiaki-ng builds use OpenSSL, so they never run this path.
    """
    src = (CHIAKI / "lib" / "src" / "rpcrypt.c").read_text(encoding="utf-8")
    marker = "#ifdef CHIAKI_LIB_ENABLE_MBEDTLS\nCHIAKI_EXPORT ChiakiErrorCode chiaki_rpcrypt_generate_iv"
    head, sep, tail = src.partition(marker)
    old = "\tuint8_t hmac[CHIAKI_RPCRYPT_KEY_SIZE];"
    if not sep or old not in tail:
        sys.exit("rpcrypt.c layout changed; re-check the HMAC buffer fix")
    tail = tail.replace(old, "\tuint8_t hmac[32]; // SHA-256 output (ps5-remote fix)", 1)
    out = BUILD / "patched" / "rpcrypt.c"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + sep + tail, encoding="utf-8")
    return out


def sources() -> list[Path]:
    lib = CHIAKI / "lib" / "src"
    chiaki = [
        "common.c", "sock.c", "session.c", "thread.c", "base64.c", "http.c", "log.c", "ctrl.c",
        "takion.c", "senkusha.c", "streamconnection.c", "ecdh.c", "launchspec.c",
        "random.c", "gkcrypt.c", "audio.c", "audioreceiver.c", "audiosender.c", "videoreceiver.c",
        "frameprocessor.c", "packetstats.c", "discovery.c", "congestioncontrol.c", "stoppipe.c",
        "reorderqueue.c", "discoveryservice.c", "feedback.c", "feedbacksender.c", "controller.c",
        "takionsendbuffer.c", "time.c", "fec.c", "regist.c", "orientation.c", "bitstream.c",
        "remote/rudp.c", "remote/rudpsendbuffer.c",
    ]
    tp = CHIAKI / "third-party"
    gf = ["gf.c", "gf_wgen.c", "gf_w4.c", "gf_w8.c", "gf_w16.c", "gf_w32.c", "gf_w64.c",
          "gf_w128.c", "gf_rand.c", "gf_general.c", "gf_cpu.c"]
    jer = ["galois.c", "jerasure.c", "reed_sol.c", "cauchy.c", "liberation.c"]
    nano = ["pb_common.c", "pb_encode.c", "pb_decode.c"]
    out = [lib / s for s in chiaki] + [patched_rpcrypt()]
    out += [tp / "gf-complete" / "src" / s for s in gf]
    out += [tp / "jerasure" / "src" / s for s in jer]
    out += [tp / "nanopb" / s for s in nano]
    out += sorted((MBEDTLS / "library").glob("*.c"))
    out += [GEN / "takion.pb.c", ROOT / "native" / "holepunch_stub.c", ROOT / "native" / "bridge.c"]
    return out


def build() -> None:
    incs = [
        CHIAKI / "lib" / "include", CHIAKI / "lib" / "src", GEN, CHIAKI / "third-party" / "nanopb",
        CHIAKI / "third-party" / "jerasure" / "include", CHIAKI / "third-party" / "gf-complete" / "include",
        MBEDTLS / "include", MBEDTLS / "library", ROOT / "native",
    ]
    defs = [
        "CHIAKI_LIB_ENABLE_MBEDTLS", "PB_C99_STATIC_ASSERT", "CHIAKI_VERSION_MAJOR=1",
        "CHIAKI_VERSION_MINOR=10", "CHIAKI_VERSION_PATCH=0", 'CHIAKI_VERSION="1.10.0"',
        "_WIN32_WINNT=0x0A00", "WINVER=0x0A00", "NDEBUG",
        'MBEDTLS_USER_CONFIG_FILE="ps5_mbedtls_user.h"',
    ]
    cmd = [PY, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2",
           "-std=gnu11", "-w", "-o", OUT]
    cmd += [f"-I{i}" for i in incs] + [f"-D{d}" for d in defs] + sources()
    cmd += ["-lws2_32", "-lwsock32", "-lbcrypt", "-liphlpapi", "-ladvapi32"]
    run(cmd)
    print("built", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    fetch_mbedtls()
    gen_protobuf()
    build()
