"""PlayStation Device Discovery Protocol (DDP): find, query and wake a PS5.

Plain UDP text messages on port 9302 (PS5). A SRCH gets back an HTTP-like
status: "200 Ok" when on, "620 Server Standby" in rest mode, plus fields
such as host-id (MAC), host-name, system-version and running-app-name.
"""
from __future__ import annotations

import socket
import time

PS5_PORT = 9302
VERSION = "00030010"


def _message(kind: str, fields: dict | None = None) -> bytes:
    msg = f"{kind} * HTTP/1.1\n"
    for key, value in (fields or {}).items():
        msg += f"{key}:{value}\n"
    msg += f"device-discovery-protocol-version:{VERSION}\n"
    return msg.encode()


def _parse(data: bytes, ip: str) -> dict:
    lines = data.decode("utf-8", errors="replace").splitlines()
    info: dict = {"ip": ip}
    if lines and lines[0].startswith("HTTP/1.1"):
        parts = lines[0].split(" ", 2)
        info["status_code"] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()
    info["on"] = info.get("status_code") == 200
    return info


def search(host: str | None = None, timeout: float = 2.0) -> list[dict]:
    """Return PS5 consoles that answer. host=None broadcasts to the LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.settimeout(0.3)
    targets = [host] if host else ["255.255.255.255"]
    found: dict[str, dict] = {}
    try:
        deadline = time.monotonic() + timeout
        for target in targets:
            sock.sendto(_message("SRCH"), (target, PS5_PORT))
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = sock.recvfrom(4096)
            except socket.timeout:
                if host and found:
                    break
                continue
            info = _parse(data, ip)
            if info.get("host-type", "").upper() == "PS5":
                found[ip] = info
                if host:
                    break
    finally:
        sock.close()
    return list(found.values())


def status(host: str, timeout: float = 1.5) -> dict | None:
    """Status of one console, or None if it did not answer."""
    res = search(host, timeout)
    return res[0] if res else None


def wake(host: str, regist_key: bytes) -> None:
    """Wake a PS5 from rest mode. regist_key is the 16-byte key from linking.

    The credential is the registration key read as a hex number, the same
    value chiaki-ng and the official app send.
    """
    credential = int(regist_key.rstrip(b"\x00").decode("ascii"), 16)
    msg = _message("WAKEUP", {
        "user-credential": credential,
        "client-type": "vr",
        "auth-type": "R",
        "model": "w",
        "app-type": "r",
    })
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(msg, (host, PS5_PORT))
    finally:
        sock.close()


if __name__ == "__main__":
    for console in search(timeout=3.0):
        print(console)
