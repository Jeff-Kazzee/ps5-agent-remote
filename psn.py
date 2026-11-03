"""PlayStation Network queries through psnawp 3.1.0.

Auth is the account's NPSSO cookie in PSN_NPSSO (see .env.schema). Calls
are blocking, so the server runs them in a thread. psnawp rate limits to
about one request every 3 seconds, so the library list is cached.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from psnawp_api import PSNAWP
from psnawp_api.models.search.games_search_datatypes import SearchDomain

ENV_LOCAL = Path(__file__).parent / ".env.local"
LIBRARY_TTL_S = 1800


class PSNError(RuntimeError):
    pass


class PSN:
    def __init__(self):
        self._client: PSNAWP | None = None
        self._lock = threading.Lock()
        self._library: list[dict] = []
        self._library_time = 0.0
        self._owned_titles: set[str] = set()
        self._owned_concepts: set[str] = set()

    @property
    def configured(self) -> bool:
        return bool(os.environ.get("PSN_NPSSO"))

    def client(self) -> PSNAWP:
        if self._client is None:
            npsso = os.environ.get("PSN_NPSSO", "").strip()
            if not npsso:
                raise PSNError("PlayStation Network is not connected. Add the NPSSO token on the remote page.")
            try:
                self._client = PSNAWP(npsso)
            except Exception as err:  # noqa: BLE001
                raise PSNError(f"PSN sign-in failed: {err}. The NPSSO token may be expired.") from err
        return self._client

    def set_npsso(self, npsso: str) -> dict:
        npsso = npsso.strip().strip('"')
        if npsso.startswith("{"):
            import json
            npsso = json.loads(npsso).get("npsso", "")
        if len(npsso) != 64:
            return {"ok": False, "error": "The NPSSO is 64 characters. Paste the npsso value, or the whole {\"npsso\": ...} text."}
        os.environ["PSN_NPSSO"] = npsso
        self._client = None
        try:
            me = self.client().me()
            name = me.online_id
        except Exception as err:  # noqa: BLE001
            os.environ.pop("PSN_NPSSO", None)
            self._client = None
            return {"ok": False, "error": f"Sony rejected the token: {err}"}
        lines = []
        if ENV_LOCAL.exists():
            lines = [l for l in ENV_LOCAL.read_text(encoding="utf-8").splitlines() if not l.startswith("PSN_NPSSO=")]
        lines.append(f"PSN_NPSSO={npsso}")
        ENV_LOCAL.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": True, "online_id": name}

    # ---------- queries ----------
    def presence(self) -> dict:
        with self._lock:
            c = self.client()
            data = c.user(account_id=c.me().account_id).get_presence()
        bp = data.get("basicPresence", {})
        games = bp.get("gameTitleInfoList") or []
        g = games[0] if games else {}
        return {
            "online_status": bp.get("primaryPlatformInfo", {}).get("onlineStatus"),
            "platform": bp.get("primaryPlatformInfo", {}).get("platform"),
            "title": g.get("titleName"),
            "title_id": g.get("npTitleId"),
            "image": g.get("conceptIconUrl") or g.get("npTitleIconUrl"),
        }

    def _load_library(self, force: bool = False) -> list[dict]:
        if self._library and not force and time.time() - self._library_time < LIBRARY_TTL_S:
            return self._library
        with self._lock:
            me = self.client().me()
            items: dict[str, dict] = {}
            for e in me.game_entitlements():
                tm, cm, gm = e.get("titleMeta") or {}, e.get("conceptMeta") or {}, e.get("gameMeta") or {}
                name = gm.get("name") or tm.get("name") or cm.get("name")
                if not name or e.get("isSubscription") and not e.get("activeFlag"):
                    continue
                key = cm.get("conceptId") or tm.get("titleId") or e.get("productId")
                platforms = sorted({a.get("platformId") for a in e.get("entitlementAttributes") or [] if a.get("platformId")})
                items.setdefault(key, {
                    "name": name,
                    "title_id": tm.get("titleId"),
                    "concept_id": cm.get("conceptId"),
                    "product_id": e.get("productId"),
                    "platforms": platforms,
                    "active": e.get("activeFlag"),
                    "preorder": e.get("preorderFlag"),
                    "source": "owned",
                })
            played = {}
            for t in me.title_stats():
                played[t.title_id] = t
            for it in items.values():
                t = played.get(it["title_id"])
                if t:
                    it["last_played"] = str(t.last_played_date_time)
                    it["play_hours"] = round(t.play_duration.total_seconds() / 3600, 1) if t.play_duration else 0
            for tid, t in played.items():
                if not any(i["title_id"] == tid for i in items.values()):
                    items[tid] = {
                        "name": t.name, "title_id": tid, "concept_id": None, "product_id": None,
                        "platforms": [str(t.category)], "source": "played (may be PS Plus or disc)",
                        "last_played": str(t.last_played_date_time),
                        "play_hours": round(t.play_duration.total_seconds() / 3600, 1) if t.play_duration else 0,
                    }
        self._library = sorted(items.values(), key=lambda i: i.get("last_played") or "", reverse=True)
        self._library_time = time.time()
        self._owned_titles = {i["title_id"] for i in self._library if i.get("title_id")}
        self._owned_concepts = {i["concept_id"] for i in self._library if i.get("concept_id")}
        return self._library

    def library(self, query: str = "", limit: int = 25, refresh: bool = False) -> dict:
        lib = self._load_library(refresh)
        q = query.lower().strip()
        hits = [i for i in lib if q in i["name"].lower()] if q else lib
        return {"total": len(lib), "matches": len(hits), "games": hits[:limit]}

    def store_search(self, query: str, limit: int = 10) -> dict:
        try:
            self._load_library()
        except Exception:  # noqa: BLE001
            pass
        out = []
        with self._lock:
            for item in self.client().search(query, SearchDomain.FULL_GAMES, limit=limit):
                r = item.get("result") or {}
                prod = r.get("defaultProduct") or r
                price = r.get("price") or prod.get("price") or {}
                concept_id = r.get("id") if r.get("__typename") == "Concept" else None
                out.append({
                    "name": r.get("name"),
                    "concept_id": concept_id,
                    "product_id": prod.get("id"),
                    "platforms": r.get("platforms"),
                    "type": r.get("localizedStoreDisplayClassification") or r.get("storeDisplayClassification"),
                    "price": price.get("discountedPrice") or price.get("basePrice"),
                    "base_price": price.get("basePrice"),
                    "is_free": price.get("isFree"),
                    "deal": price.get("discountText") or price.get("upsellText"),
                    "owned": bool(concept_id and concept_id in self._owned_concepts),
                })
        return {"query": query, "results": out}
