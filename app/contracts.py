"""Mission database: every contract in the game data, summarised into one
structured, cached record per contract, to add details to the missions seen
in Game.log (and to browse).

Per contract (keys of each record):
- identity: id, debug, generator, handler (the sub-generator), template
- display: title, description, type (mobiGlas mission type), contractor,
  faction, illegal
- availability: systems, locations, rank (minimum standing, localized),
  max_rank, crimestat range, needs_completed (earlier contracts required),
  max_players, can_share, once_only
- rewards: rep, blueprints [{chance, items}], items [{name, amount}] (e.g.
  scrip), payout (fixed amounts only), calculated_payout, partial_payout
- work: stages [{name, kind, starts_active}] and flow (the template's
  mission steps), cargo [{resource, min_scu, max_scu}], salvage_percent,
  est_minutes, deadline_minutes, difficulty and difficulty_detail

Not in the game data: the aUEC reward of "calculated" contracts (nearly
all); the server works it out when the mission is offered.

The log's marker lines carry `contractDefinitionId` (a contract's `id`) and
the debug name. Instanced contracts log the debug name with a `_<n>` suffix
and an id that isn't in the data; they're matched by name instead.

Extracted once per game build (Game2.dcb, plus the installed localization)
and cached as JSON, like app.mining.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app import bindings, config, p4k
from app.datacore import DataCore

GAME2_ENTRY = "Data\\Game2.dcb"
CACHE = config.CACHE_DIR / "contracts"
FORMAT = 4  # bump when the extracted shape changes
# A localization installed next to the game (e.g. StarStrings) overrides the
# packed one, and the log shows its names ("Received Blueprint: …").
INSTALLED_INI = ("Data", "Localization", "english", "global.ini")

_MARKUP_RE = re.compile(r"<[^>]+>")


def _guid(hex32: str) -> str:
    """DataCore GUID value (hex of the stored bytes) → the text form the log uses."""
    b = bytes.fromhex(hex32)
    h = b[0:8][::-1].hex() + b[8:16][::-1].hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _loc(table: dict[str, str], key, fallback: str = "") -> str:
    if isinstance(key, str) and key.startswith("@"):
        text = table.get(key[1:].lower())
        if text:
            return text
    return fallback


def _clean(text: str) -> str:
    """Localized text → plain text (markup tags and ~mission(...) tokens out)."""
    text = _MARKUP_RE.sub("", text.replace("\\n", "\n"))
    text = re.sub(r"~mission\([^)]*\)", "…", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _title(text: str) -> str:
    """Without the reward markers StarStrings adds ("… [200 Rep] [BP]*"),
    which the overlay shows as chips anyway."""
    text = _clean(text)
    return re.sub(r"\s*\[(?:[\d,]+ Rep|BP)\]\*?", "", text).strip()


def _find_all(obj, type_name: str, out: list | None = None) -> list:
    out = [] if out is None else out
    if isinstance(obj, dict):
        if obj.get("_type") == type_name:
            out.append(obj)
        for v in obj.values():
            _find_all(v, type_name, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_all(v, type_name, out)
    return out


def _string_params(obj: dict) -> dict[str, str]:
    params = {}
    for p in _find_all(obj.get("paramOverrides") or {}, "ContractStringParam"):
        params.setdefault(p.get("param"), p.get("value"))
    return params


# Mission localities and star-map objects are named after their records;
# the planets' record names don't say which planet they are.
_PLACES = {
    "Stanton1": "Hurston", "Stanton2": "Crusader", "Stanton3": "ArcCorp", "Stanton4": "microTech",
    "StantonStar": "Stanton", "NyxStar": "Nyx", "PyroStar": "Pyro",
}


def _place(name: str) -> str:
    return _PLACES.get(name, re.sub(r"(?<=[a-z])(?=\d)", " ", name.replace("_", " ")))


def _words(name: str) -> str:
    """'ItemResourceGathering' / 'Easy_PvE_only_action' → 'Item Resource Gathering' / 'Easy PvE only action'."""
    name = name.replace("_", " ")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()


class _Extractor:
    def __init__(self, dc: DataCore, loc: dict[str, str]):
        self.dc, self.loc = dc, loc
        self._records: dict[str, dict | None] = {}
        self._items: dict[str, str] = {}
        self._templates: dict[str, dict] = {}

    def record(self, ref: str | None, depth: int = 3) -> dict | None:
        if not isinstance(ref, str) or not ref.startswith("@"):
            return None
        if ref not in self._records:
            self._records[ref] = self.dc.record(ref[1:], max_depth=depth)
        return self._records[ref]

    def item_name(self, entity_ref: str) -> str:
        """Localized display name of an entity class (what 'Received
        Blueprint: <name>' shows)."""
        if entity_ref in self._items:
            return self._items[entity_ref]
        cls = entity_ref.split(".", 1)[-1]
        name = cls
        rec = self.dc.record(entity_ref[1:], max_depth=4) if entity_ref.startswith("@") else None
        for attach in _find_all(rec, "SAttachableComponentParams") if rec else []:
            key = ((attach.get("AttachDef") or {}).get("Localization") or {}).get("Name")
            name = _loc(self.loc, key, cls)
            break
        self._items[entity_ref] = name
        return name

    def blueprint_pool(self, ref: str) -> list[str]:
        pool = self.record(ref, depth=2) or {}
        names = []
        for reward in pool.get("blueprintRewards") or []:
            bp = self.record(reward.get("blueprintRecord"), depth=4) or {}
            entity = ((bp.get("blueprint") or {}).get("processSpecificData") or {}).get("entityClass")
            if entity:
                names.append(self.item_name(entity))
        return sorted(set(names))

    def text(self, key, fallback: str = "") -> str:
        return _clean(_loc(self.loc, key, fallback))

    def template(self, ref: str | None) -> dict:
        """A ContractTemplate, summarised once: type, flags, stages, cargo."""
        if not isinstance(ref, str) or not ref.startswith("@"):
            return {}
        if ref in self._templates:
            return self._templates[ref]
        t = self.dc.record(ref[1:], max_depth=10) or {}
        display = t.get("contractDisplayInfo") or {}
        cls = t.get("contractClass") or {}
        deadline = ((cls.get("autoFinishSettings") or {}).get("contractDeadline") or {})
        stages = []
        for token in t.get("objectiveTokens") or []:
            if isinstance(token, dict) and token.get("debugName"):
                handler = (token.get("objectiveHandler") or {}).get("_type", "") if isinstance(
                    token.get("objectiveHandler"), dict) else ""
                stages.append({"name": _words(token["debugName"]),
                               "kind": _words(handler.removeprefix("ObjectiveHandler_")),
                               "starts_active": bool(token.get("startsActive"))})
        flow = [tr.get("description", "").replace("-&gt;", "→")
                for tr in (t.get("missionFlow") or {}).get("triggers") or []
                if isinstance(tr, dict) and tr.get("description")]
        summary = {
            "name": ref.split(".", 1)[-1],
            "type": self.mission_type(display.get("type")),
            "illegal": bool(display.get("illegal")),
            "can_share": bool(((cls.get("additionalParams") or {}).get("canBeShared"))),
            # In minutes: every hauling template has 300 (a 5 h limit).
            "deadline_minutes": deadline.get("missionCompletionTime")
            if (deadline.get("missionCompletionTime") or 0) > 0 else None,
            "partial_payout": bool(t.get("partialRewardPayout")),
            "stages": stages,
            "flow": flow,
            "cargo": self.cargo(t.get("contractProperties") or []),
        }
        self._templates[ref] = summary
        return summary

    def mission_type(self, ref) -> str:
        rec = self.record(ref, depth=0) or {}
        return self.text(rec.get("LocalisedTypeName"), ref.split(".", 1)[-1] if isinstance(ref, str) else "")

    def cargo(self, properties) -> list[dict]:
        out = []
        for order in _find_all(properties, "HaulingOrderContent_Resource"):
            res = self.record(order.get("resource"), depth=0) or {}
            name = self.text(res.get("displayName"), (order.get("resource") or "").split(".", 1)[-1])
            out.append({"resource": name, "min_scu": order.get("minSCU"), "max_scu": order.get("maxSCU")})
        return out

    def standing(self, ref) -> str:
        rec = self.record(ref, depth=0) or {}
        return self.text(rec.get("displayName"), (ref or "").rsplit("_", 1)[-1] if isinstance(ref, str) else "")

    def availability(self, prerequisites: list) -> dict:
        out: dict = {"systems": [], "locations": [], "rank": "", "crimestat": None, "needs_completed": 0}
        for p in prerequisites:
            if not isinstance(p, dict):
                continue
            t = p.get("_type", "")
            if t == "ContractPrerequisite_Locality" and p.get("localityAvailable"):
                out["systems"].append(_place(p["localityAvailable"].split(".", 1)[-1]))
            elif t == "ContractPrerequisite_Location" and p.get("locationAvailable"):
                out["locations"].append(_place(p["locationAvailable"].split(".", 1)[-1]))
            elif t == "ContractPrerequisite_Reputation" and not p.get("exclude"):
                out["rank"] = out["rank"] or self.standing(p.get("minStanding"))
            elif t == "ContractPrerequisite_CrimeStat":
                out["crimestat"] = [p.get("minCrimeStat"), p.get("maxCrimeStat")]
            elif t == "ContractPrerequisite_CompletedContractTags":
                out["needs_completed"] = max(out["needs_completed"], p.get("requiredCountValue") or 0)
        return out

    def contract(self, c: dict, generator: str, defaults: dict[str, str], handler: dict | None = None) -> dict:
        handler = handler or {}
        params = {**defaults, **_string_params(c)}
        template = self.template(c.get("template"))
        avail = handler.get("defaultAvailability") or {}
        prereqs = list(avail.get("prerequisites") or []) + list(c.get("additionalPrerequisites") or [])
        where = self.availability(prereqs)
        type_override = ((c.get("paramOverrides") or {}).get("missionTypeOverride")
                         or (handler.get("contractParams") or {}).get("missionTypeOverride"))
        results = c.get("contractResults") or {}
        info: dict = {
            "debug": c.get("debugName") or "",
            "generator": generator,
            "handler": handler.get("debugName") or "",
            "template": template.get("name", ""),
            "type": self.mission_type(type_override) if type_override else template.get("type", ""),
            "title": _title(_loc(self.loc, params.get("Title"))),
            "description": _clean(_loc(self.loc, params.get("Description"))),
            "contractor": "",
            "faction": self.text((self.record(handler.get("factionReputation"), depth=1) or {}).get("displayName")),
            "illegal": template.get("illegal", False),
            "can_share": template.get("can_share", False),
            "max_players": avail.get("maxPlayersPerInstance"),
            "once_only": bool(avail.get("onceOnly")),
            "systems": where["systems"],
            "locations": where["locations"],
            "rank": self.standing(c.get("minStanding")) if c.get("minStanding") else where["rank"],
            "max_rank": self.standing(c.get("maxStanding")) if c.get("maxStanding") else "",
            "crimestat": where["crimestat"],
            "needs_completed": where["needs_completed"],
            "est_minutes": results.get("timeToComplete") if (results.get("timeToComplete") or 0) > 0 else None,
            "deadline_minutes": template.get("deadline_minutes"),
            "stages": template.get("stages", []),
            "flow": template.get("flow", []),
            "cargo": self.cargo(c.get("paramOverrides") or {}) or template.get("cargo", []),
            "salvage_percent": None,
            "rep": None,
            "blueprints": [],        # [{chance, items: [names]}]
            "difficulty": "",
            "difficulty_detail": {},
            # Most contracts pay a "calculated" reward the server works out
            # (not in the game files, the description or the log). A few pay
            # a fixed amount, and some add items such as scrip.
            "payout": None,          # {amount, currency: "aUEC" | "merits"} when fixed
            "calculated_payout": False,
            "partial_payout": template.get("partial_payout", False),
            "items": [],             # [{name, amount}]
        }
        for prop in _find_all(c.get("paramOverrides") or {}, "MissionProperty"):
            if prop.get("missionVariableName") == "CompletionPercentage_BP":
                values = [o.get("value") for o in _find_all(prop, "MissionPropertyValueOption_Integer")]
                info["salvage_percent"] = values[0] if values else None
        contractor = params.get("Contractor")
        if contractor:
            info["contractor"] = _clean(_loc(self.loc, contractor))
        if not info["contractor"]:
            info["contractor"] = info["faction"]
        for rep in _find_all(c.get("contractResults") or {}, "SReputationAmountParams"):
            faction = self.record(rep.get("factionReputation"), depth=1) or {}
            if not info["contractor"]:
                info["contractor"] = _clean(_loc(self.loc, faction.get("displayName")))
            amount = (self.record(rep.get("reward"), depth=1) or {}).get("reputationAmount")
            if isinstance(amount, (int, float)) and amount > 0:
                info["rep"] = (info["rep"] or 0) + int(amount)
        for bp in _find_all(c.get("contractResults") or {}, "BlueprintRewards"):
            items = self.blueprint_pool(bp.get("blueprintPool"))
            if items:
                info["blueprints"].append({"chance": bp.get("chance"), "items": items})
        results = c.get("contractResults") or {}
        info["calculated_payout"] = bool(_find_all(results, "ContractResult_CalculatedReward"))
        for fixed in _find_all(results, "MissionReward"):
            amount = fixed.get("reward")
            if isinstance(amount, (int, float)) and amount > 0:
                currency = {"UEC": "aUEC", "MER": "merits"}.get(fixed.get("currencyType"), fixed.get("currencyType"))
                info["payout"] = {"amount": int(amount), "currency": currency}
        for item in _find_all(results, "ContractResult_Item"):
            entity, amount = item.get("entityClass"), item.get("amount") or 1
            if entity:
                info["items"].append({"name": self.item_name(entity), "amount": amount})
        profile = (_find_all(results, "ContractDifficulty") or [{}])[0]
        info["difficulty"] = (profile.get("difficultyProfile") or "").rsplit(".", 1)[-1]
        # "Easy_PvE_only_action_3" → level 3, "Easy PvE only action"
        for key, label in (("mechanicalSkill", "mechanical skill"), ("mentalLoad", "mental load"),
                           ("riskOfLoss", "risk of loss"), ("gameKnowledge", "game knowledge")):
            value = profile.get(key) or ""
            m = re.match(r"(.*?)_(\d+)$", value)
            if m:
                info["difficulty_detail"][label] = {"level": int(m.group(2)), "text": _words(m.group(1))}
        return info


def _installed_ini(channel_root: Path) -> Path:
    return channel_root.joinpath(*INSTALLED_INI)


def _localization(channel_root: Path) -> dict[str, str]:
    loc_raw = bindings._load_from_p4k_cached(channel_root, bindings.GLOBAL_INI_ENTRY, "global.ini")
    loc = bindings._parse_ini(loc_raw) if loc_raw else {}
    try:
        loc.update(bindings._parse_ini(_installed_ini(channel_root).read_bytes()))
    except OSError:
        pass
    return loc


def _extract(channel_root: Path, progress) -> dict:
    progress("Reading Star Citizen contract data (once per patch)…")
    raw = p4k.extract(channel_root / "Data.p4k", [GAME2_ENTRY]).get(GAME2_ENTRY)
    if raw is None:
        raise RuntimeError("Game2.dcb not found in Data.p4k")
    dc = DataCore(raw)
    del raw
    ex = _Extractor(dc, _localization(channel_root))

    contracts: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for rec_name in dc.record_names("ContractGenerator."):
        gen_rec = dc.record(rec_name) or {}
        generator = rec_name.split(".", 1)[1]
        for gen in gen_rec.get("generators") or []:
            defaults = _string_params(gen.get("contractParams") or {}) if isinstance(gen, dict) else {}
            stack = list(gen.get("contracts") or []) if isinstance(gen, dict) else []
            while stack:
                c = stack.pop()
                if not isinstance(c, dict):
                    continue
                stack.extend(c.get("subContracts") or [])
                cid, debug = c.get("id"), c.get("debugName")
                if not isinstance(cid, str) or len(cid) != 32 or not debug:
                    continue
                guid = _guid(cid)
                info = ex.contract(c, generator, defaults, gen)
                info["id"] = guid
                contracts[guid] = info
                by_name.setdefault(debug, guid)
    return {"format": FORMAT, "contracts": contracts, "by_name": by_name}


class Contracts:
    """Lookup over the extracted data."""

    def __init__(self, data: dict):
        self._contracts: dict[str, dict] = data.get("contracts") or {}
        self._by_name: dict[str, str] = data.get("by_name") or {}

    def __len__(self) -> int:
        return len(self._contracts)

    def all(self) -> list[dict]:
        return list(self._contracts.values())

    def search(self, text: str = "", **fields) -> list[dict]:
        """Contracts whose title, debug name, contractor or type contain
        `text` (any case), and whose fields equal the given values, e.g.
        search("salvage", contractor="Recco Battaglia")."""
        text = text.lower()
        out = []
        for c in self._contracts.values():
            if text and not any(text in (c.get(k) or "").lower()
                                for k in ("title", "debug", "contractor", "type")):
                continue
            if all(c.get(k) == v for k, v in fields.items()):
                out.append(c)
        return out

    def find(self, contract_id: str | None = None, debug_name: str | None = None) -> dict | None:
        """By the log's contractDefinitionId, else by its debug name (with or
        without the instance suffix)."""
        if contract_id and contract_id in self._contracts:
            return self._contracts[contract_id]
        if debug_name:
            for name in (debug_name, re.sub(r"_\d+$", "", debug_name)):
                if name in self._by_name:
                    return self._contracts[self._by_name[name]]
        return None


def load(channel_root: Path, progress=lambda _msg: None) -> Contracts:
    """Slow the first time after a game patch; cached afterwards. Call off
    the UI thread."""
    p4k_path = channel_root / "Data.p4k"
    if not p4k_path.is_file():
        raise RuntimeError(f"Data.p4k not found in {channel_root}")
    key = bindings._cache_key(p4k_path)
    try:
        key += f"-{int(_installed_ini(channel_root).stat().st_mtime)}"
    except OSError:
        pass
    cache_file = CACHE / f"contracts-{key}.json"
    try:
        cached = json.loads(cache_file.read_text())
        if cached.get("format") == FORMAT:
            return Contracts(cached)
    except (OSError, ValueError):
        pass
    data = _extract(channel_root, progress)
    CACHE.mkdir(parents=True, exist_ok=True)
    for stale in CACHE.glob("contracts-*.json"):
        stale.unlink(missing_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(cache_file)
    return Contracts(data)
