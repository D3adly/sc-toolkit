"""Ship part prices and the shops that sell them, from UEX (api.uexcorp.space,
reported by players), for the loadout shopping list. Fetched by app.datahub
every 6 hours at most and cached; when UEX can't be reached the last good copy
stays (the UI says "prices from cache" with its age).

Parts are matched by the game entity's uuid (app.loadoutdata.entity_uuid),
which UEX keys its items by. Each price keeps when it was last reported, for
the FRESH / AGEING / STALE label. Shops carry their place in the star map
(system → planet or moon → station, city or outpost) for grouping a buy run
into stops.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app import config

API = "https://api.uexcorp.space/2.0/"
TIMEOUT = 30
CACHE = config.CACHE_DIR / "uexparts.json"
DAY = 24 * 3600
FRESH_DAYS = 14          # ≤ 14 days: FRESH; ≤ 45: AGEING; older: STALE
AGEING_DAYS = 45


class UexError(Exception):
    pass


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _get(endpoint: str) -> list[dict]:
    try:
        payload = json.loads(_http_get(API + endpoint))
    except (OSError, json.JSONDecodeError) as exc:
        raise UexError(f"Could not fetch UEX {endpoint}: {exc}") from exc
    if payload.get("status") != "ok":
        raise UexError(f"UEX {endpoint} returned {payload.get('status')}")
    return [r for r in payload.get("data") or [] if isinstance(r, dict)]


def _terminal(t: dict) -> dict:
    name = str(t.get("name") or "")
    place = (t.get("space_station_name") or t.get("city_name") or t.get("outpost_name") or t.get("poi_name")
             or t.get("orbit_name") or "")
    return {
        "name": name,
        # "Platinum Bay - HUR-L5" → the shop is "Platinum Bay" at that place.
        "shop": name.split(" - ", 1)[0].strip() if " - " in name else str(t.get("company_name") or name),
        "place": str(place),
        "system": str(t.get("star_system_name") or ""),
        "planet": str(t.get("planet_name") or ""),
        "moon": str(t.get("moon_name") or ""),
    }


def refresh() -> None:
    """Downloads part buy prices and item shops; raises UexError (the old cache stays)."""
    terminals = {str(t["id"]): _terminal(t) for t in _get("terminals") if t.get("id") and t.get("type") == "item"}
    prices: dict[str, list] = {}
    for row in _get("items_prices_all"):
        buy, item, term = row.get("price_buy") or 0, row.get("item_uuid"), str(row.get("id_terminal") or "")
        if buy > 0 and item and term in terminals:
            prices.setdefault(item, []).append([term, round(float(buy), 2), int(row.get("date_modified") or 0)])
    for rows in prices.values():
        rows.sort(key=lambda r: r[1])
    if not prices:
        raise UexError("UEX returned no part prices")
    data = {"fetched": time.time(), "terminals": terminals, "prices": prices}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(CACHE)


def fetched() -> float:
    return load().fetched if load() else 0.0


@dataclass
class Offer:
    terminal: str              # UEX terminal id
    shop: str                  # "Platinum Bay"
    place: str                 # "HUR-L5 High Course Station"
    system: str
    planet: str
    moon: str
    price: float
    reported: int              # unix time the price was last reported

    def age_days(self, now: float | None = None) -> int:
        return max(0, int(((now or time.time()) - self.reported) // DAY))

    def freshness(self, now: float | None = None) -> str:
        days = self.age_days(now)
        return "fresh" if days <= FRESH_DAYS else "ageing" if days <= AGEING_DAYS else "stale"


class Prices:
    def __init__(self, data: dict):
        self.fetched: float = float(data.get("fetched") or 0)
        self.terminals: dict[str, dict] = data.get("terminals") or {}
        self._prices: dict[str, list] = data.get("prices") or {}

    def offers(self, part_uuid: str) -> list[Offer]:
        """Where a part is sold, cheapest first ([] if no player reported a shop)."""
        out = []
        for term, price, at in self._prices.get(part_uuid, []):
            t = self.terminals.get(term)
            if t:
                out.append(Offer(term, t["shop"], t["place"], t["system"], t["planet"], t["moon"], price, at))
        return out

    def cheapest(self, part_uuid: str) -> Offer | None:
        offers = self.offers(part_uuid)
        return offers[0] if offers else None


_loaded: tuple[float, Prices | None] = (-1.0, None)


def load(path: Path = CACHE) -> Prices | None:
    """The cached prices (re-read when the file changed), or None before the first fetch."""
    global _loaded
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if path == CACHE and _loaded[0] == mtime:
        return _loaded[1]
    try:
        prices = Prices(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if path == CACHE:
        _loaded = (mtime, prices)
    return prices
