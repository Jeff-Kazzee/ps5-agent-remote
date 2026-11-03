"""Local credential store: ~/.ps5-remote/consoles.json.

Holds the PSN account ID (from sign-in) and, per linked console, the
Remote Play registration key and RP key. Treat the file as a password: it
lets this computer control the console. It never leaves this machine.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

HOME = Path(os.environ.get("PS5_REMOTE_HOME", Path.home() / ".ps5-remote"))
FILE = HOME / "consoles.json"
LEGACY = Path.home() / ".pyremoteplay" / ".profile.json"


def load() -> dict:
    if FILE.exists():
        return json.loads(FILE.read_text(encoding="utf-8"))
    data = {"account": None, "consoles": {}}
    migrated = _from_pyremoteplay()
    if migrated:
        data = migrated
        save(data)
    return data


def save(data: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(FILE)


def set_account(online_id: str, account_id: int) -> None:
    data = load()
    data["account"] = {
        "online_id": online_id,
        "account_id_b64": base64.b64encode(int(account_id).to_bytes(8, "little")).decode(),
    }
    save(data)


def account_id_bytes(data: dict) -> bytes | None:
    acc = data.get("account")
    return base64.b64decode(acc["account_id_b64"]) if acc else None


def add_console(mac: str, nickname: str, host: str, regist_key: bytes, rp_key: bytes) -> None:
    data = load()
    data["consoles"][mac.upper()] = {
        "nickname": nickname,
        "host": host,
        "regist_key": regist_key.hex(),
        "rp_key": rp_key.hex(),
    }
    save(data)


def console(data: dict, mac: str | None) -> dict | None:
    if not mac:
        return None
    return data["consoles"].get(mac.upper())


def keys(entry: dict) -> tuple[bytes, bytes]:
    return bytes.fromhex(entry["regist_key"]), bytes.fromhex(entry["rp_key"])


def _from_pyremoteplay() -> dict | None:
    """One-time import of a link made by earlier versions (pyremoteplay format)."""
    if not LEGACY.exists():
        return None
    try:
        profiles = json.loads(LEGACY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for name, prof in profiles.items():
        hosts = prof.get("hosts") or {}
        if not hosts or not prof.get("id"):
            continue
        out = {"account": {"online_id": name, "account_id_b64": prof["id"]}, "consoles": {}}
        for mac, entry in hosts.items():
            d = entry.get("data", {})
            if "RegistKey" in d and "RP-Key" in d:
                out["consoles"][mac.upper()] = {
                    "nickname": d.get("Nickname", ""),
                    "host": "",
                    "regist_key": bytes.fromhex(d["RegistKey"]).ljust(16, b"\x00")[:16].hex(),
                    "rp_key": d["RP-Key"],
                }
        if out["consoles"]:
            return out
    return None
