"""Mining resource finder data: where each mineable rock type spawns, how
likely it is, what it contains and at what quality.

Everything comes from the game files, built once per game build by
app.datahub (build), which caches it:

- **Locations.** Each planet/moon pivot entity, Lagrange-point gas cloud,
  belt and cluster carries a HarvestableProviderPreset by GUID inside its
  object container (.socpak). Stanton's clouds are named after their point
  (childcloud_s1_l1_01 → HUR L1); Pyro's generic warm/cool clouds are
  resolved through the Lagrange-point containers that include them.
- **Spawn chance.** A provider has groups (ship, ROC, hand mining), each a
  list of rock presets with relative weights; a rock's chance is its weight
  over the group total.
- **Contents.** Rock → entity → MineableComposition: parts of
  (resource, min–max %, probability, quality scale). The same resource can
  appear twice with different quality scales — a rich low-grade vein next
  to a thin high-grade one.
- **Quality.** Each resource type has a quality distribution (normal,
  clamped to a range), optionally overridden per star system, plus bands
  that quantize the rolled value into a few fixed qualities. Per vein we
  compute the probability of each displayed quality for (roll × the part's
  quality scale), assuming the roll is a normal truncated to its range. The game's exact rolling isn't
  documented, so it's labelled as an estimate in the UI.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from app import config, p4k, socpak
from app.datacore import DataCore

CACHE = config.CACHE_DIR / "mining"
FORMAT = 4  # bump when the extracted shape changes

SYSTEMS = ["stanton", "pyro", "nyx"]  # live systems; others in the files are unreleased
SYSTEM_ROOT = "data\\objectcontainers\\pu\\system\\"

METHODS = {
    "SpaceShip_Mineables": "ship",
    "GroundVehicle_Mineables": "roc",
    "FPS_Mineables": "hand",
}
METHOD_LABELS = {"ship": "Ship", "roc": "ROC", "hand": "Hand"}

# Containers without a matching global.ini name.
_SPECIAL_NAMES = {
    "keeger_gascloud_gen": ("Keeger Belt", "belt"),
    "glaciem_gascloud_gen": ("Glaciem Ring", "belt"),
    "akirocluster": ("Akiro Cluster", "cluster"),
    "aaronhalo": ("Aaron Halo", "belt"),
    "tsg_gascloud_001": ("Deep-space gas clouds", "cluster"),
}
_GUID_RE = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_CLOUD_RE = re.compile(r"childcloud_([a-z0-9_]+?)(?:_\d\d)?$")
_RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]


def guid_text(raw: bytes) -> str:
    """DataCore record GUID bytes → the text form used in level files."""
    h = raw[0:8][::-1].hex() + raw[8:16][::-1].hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _clean(name: str) -> str:
    """'Raw Ice' / 'Laranite (Raw)' / 'Hephaestanite (R)' → the bare name."""
    name = re.sub(r"\s*\((raw|ore|r)\)$", "", name.strip(), flags=re.I)
    return re.sub(r"^raw\s+", "", name, flags=re.I)


def _loc(table: dict[str, str], key: str | None, fallback: str = "") -> str:
    if key and key.startswith("@"):
        return table.get(key[1:].lower()) or fallback
    return fallback


# -- where each provider is used ---------------------------------------------------

def _scan_locations(p4k_path: Path, providers: dict[str, str]) -> list[tuple[str, str]]:
    """[(container path, provider name)] for every live-system container
    that references a harvestable provider.
    """
    def wanted(name: str) -> bool:
        low = name.lower()
        if not low.startswith(SYSTEM_ROOT) or not low.endswith(".socpak"):
            return False
        parts = low[len(SYSTEM_ROOT):].split("\\")
        if parts[0] not in SYSTEMS:
            return False
        stem = parts[-1].removesuffix(".socpak")
        if len(parts) == 2:
            return True                      # planet, moon, halo, cluster
        if "childcloud" in stem:
            return not re.search(r"l(i)?ghts?|entry", stem)
        return "gascloud" in stem or (parts[1] == "lagrangepoints" and len(parts) == 3)

    found: list[tuple[str, str]] = []
    cloud_parents: dict[str, set[str]] = {}   # generic child cloud → Lagrange points using it
    for name, data in p4k.iter_matching(p4k_path, wanted):
        path = name.lower()[len(SYSTEM_ROOT):]
        stem = path.rsplit("\\", 1)[-1].removesuffix(".socpak")
        is_point = "\\lagrangepoints\\" in "\\" + path and "childcloud" not in stem
        refs: set[str] = set()
        for _inner, blob in socpak.entries(data, lambda n: n.lower().endswith((".entxml", ".soc", ".xml"))):
            refs.update(g.decode() for g in _GUID_RE.findall(blob))
            if is_point:
                for cloud in re.findall(rb"childcloud_[a-z]+\d+_[a-z]\b", blob, re.I):
                    cloud_parents.setdefault(cloud.decode().lower(), set()).add(stem)
        found += [(path, providers[r]) for r in refs if r in providers]

    out = []
    for path, provider in found:
        folder, _, file = path.rpartition("\\")
        parents = cloud_parents.get(file.removesuffix(".socpak"))
        if parents:
            out += [(f"{folder}\\{p}.socpak", provider) for p in sorted(parents)]
        else:
            out.append((path, provider))
    return out


# -- naming ---------------------------------------------------------------------------

def _describe(path: str, provider: str, loc: dict[str, str]) -> dict | None:
    """Container path → {id, name, system, kind, parent} (None = skip)."""
    parts = path.split("\\")
    system = parts[0]
    stem = parts[-1].removesuffix(".socpak")

    cloud = _CLOUD_RE.match(stem)
    if cloud:
        body = cloud.group(1)
        m = re.fullmatch(r"s(\d)_(l\d)", body)
        key = f"stanton{m.group(1)}_{m.group(2)}" if m else body
        if key not in loc:
            return None
        return _entry(key, loc[key], system, "lagrange", loc)
    if re.fullmatch(rf"{system}\d_l\d", stem):
        return _entry(stem, loc.get(stem, stem.upper()), system, "lagrange", loc)
    if stem in _SPECIAL_NAMES:
        name, kind = _SPECIAL_NAMES[stem]
        return {"id": stem, "name": name, "system": system, "kind": kind, "parent": ""}
    if re.fullmatch(rf"{system}\d+[a-z]?", stem):
        name = loc.get(stem) or next(
            (v for k, v in loc.items() if re.fullmatch(rf"{stem}_[a-z]+", k) and v.lower() == k.split("_", 1)[1]),
            stem,
        )
        if provider.endswith("_Belt"):
            return {"id": stem + "_belt", "name": f"{name} Belt", "system": system,
                    "kind": "belt", "parent": ""}
        moon = stem[-1].isalpha()
        parent = loc.get(stem[:-1], "") if moon else ""
        return {"id": stem, "name": name, "system": system,
                "kind": "moon" if moon else "planet", "parent": parent}
    return None


def _entry(key: str, name: str, system: str, kind: str, loc: dict[str, str]) -> dict:
    planet = re.match(rf"{system}(\d)", key)
    parent = loc.get(f"{system}{planet.group(1)}", "") if planet else ""
    return {"id": key, "name": name, "system": system, "kind": kind, "parent": parent}


# -- quality ---------------------------------------------------------------------------

def _distribution(dc: DataCore, ref) -> dict | None:
    if isinstance(ref, dict):
        if ref.get("_type") == "CraftingQualityDistribution_RecordRef":
            rec = dc.record(ref["qualityDistributionRecord"][1:]) if ref.get("qualityDistributionRecord") else None
            return (rec or {}).get("qualityDistribution")
        if "mean" in ref:
            return ref
    return None


def _quality_model(dc: DataCore, resource: dict) -> dict | None:
    """{'base': dist, 'overrides': {system: dist}, 'bands': [(start, end, value)]}"""
    for prop in resource.get("properties") or []:
        if prop.get("_type") != "ResourceTypeCraftingData":
            continue
        base = _distribution(dc, prop.get("qualityDistribution"))
        if not base:
            return None
        overrides = {}
        lo = prop.get("qualityLocationOverride") or {}
        rec = dc.record(lo["locationOverrideRecord"][1:]) if lo.get("locationOverrideRecord") else None
        for entry in ((rec or {}).get("locationOverride") or {}).get("locationOverrideList") or []:
            where = str(entry.get("location") or "").lower()
            dist = _distribution(dc, entry.get("qualityDistribution"))
            for system in SYSTEMS:
                if system in where and dist:
                    overrides[system] = dist
        bands = []
        qq = prop.get("qualityQuantization") or {}
        rec = dc.record(qq["qualityQuantizationRecord"][1:]) if qq.get("qualityQuantizationRecord") else None
        for band in ((rec or {}).get("qualityQuantization") or {}).get("bands") or []:
            bands.append((band["start"], band["end"], band["mappedValue"]))
        return {"base": base, "overrides": overrides, "bands": bands}
    return None


def quality_distribution(dist: dict, scale: float, bands: list) -> list[tuple[int, float]]:
    """[(displayed quality, probability %)] for (roll × scale), roll ~
    Normal(mean, stddev) truncated to [min, max]. Values are the
    quantization bands' mapped values when the resource has bands,
    otherwise 100-wide buckets (labelled by their lower bound).
    """
    lo, hi = int(dist["min"]), int(dist["max"])
    mean, sd = float(dist["mean"]), max(float(dist["stddev"]), 1e-6)
    buckets: dict[int, float] = {}
    total = 0.0
    for q in range(lo, hi + 1):
        w = math.exp(-0.5 * ((q - mean) / sd) ** 2)
        eff = min(1000, max(0, round(q * scale)))
        value = next((v for start, end, v in bands if start <= eff <= end), None)
        if value is None:
            value = eff if bands else eff // 100 * 100
        buckets[value] = buckets.get(value, 0.0) + w
        total += w
    return [(v, 100 * w / total) for v, w in sorted(buckets.items())] if total else []


# -- extraction ---------------------------------------------------------------------------

def build(game, progress) -> dict:
    """The mining data from the game files (app.datahub.GameFiles); the hub
    caches it per patch."""
    p4k_path = game.p4k_path
    dc, loc = game.dc, game.loc

    providers = {guid_text(g): n.split(".", 1)[1]
                 for n, _si, _ii, g in dc.records() if n.startswith("HarvestableProviderPreset.")}

    progress("Finding mining locations…")
    locations: dict[str, dict] = {}
    for path, provider in _scan_locations(p4k_path, providers):
        info = _describe(path, provider, loc)
        if info is None:
            continue
        entry = locations.setdefault(info["id"], {**info, "providers": []})
        if provider not in entry["providers"]:
            entry["providers"].append(provider)

    progress("Reading rock compositions…")
    rocks: dict[str, dict] = {}
    resources: dict[str, dict] = {}
    quality_models: dict[str, dict | None] = {}

    def rock(preset_ref: str) -> dict | None:
        key = preset_ref.split(".", 1)[1]
        if key in rocks:
            return rocks[key]
        preset = dc.record(preset_ref[1:], max_depth=2) or {}
        entity = dc.record(str(preset.get("entityClass") or "")[1:]) if preset.get("entityClass") else None
        params = next((c for c in (entity or {}).get("Components") or []
                       if isinstance(c, dict) and c.get("_type") == "MineableParams"), None)
        comp = dc.record(params["composition"][1:]) if params and params.get("composition") else None
        if not comp:
            rocks[key] = None
            return None
        parts = []
        for part in comp.get("compositionArray") or []:
            element = dc.record(str(part.get("mineableElement") or "")[1:], max_depth=1) or {}
            res_ref = element.get("resourceType")
            if not res_ref:
                continue
            res_id = res_ref.split(".", 1)[1]
            if res_id not in resources:
                res = dc.record(res_ref[1:]) or {}
                name = _loc(loc, res.get("displayName"), res_id)
                resources[res_id] = {"name": _clean(name)}
                quality_models[res_id] = _quality_model(dc, res)
            lo, hi = float(part["minPercentage"]), float(part["maxPercentage"])
            exp = float(part.get("curveExponent") or 1.0)
            parts.append({
                "res": res_id,
                "min": round(lo, 1), "max": round(hi, 1),
                "avg": round(lo + (hi - lo) / (1 + exp), 1),
                "prob": round(float(part.get("probability") or 0), 3),
                "scale": round(float(part.get("qualityScale") or 1.0), 3),
            })
        signature = 0.0
        for c in (entity or {}).get("Components") or []:
            if isinstance(c, dict) and c.get("_type") == "SSCSignatureSystemParams":
                sigs = (((c.get("radarProperties") or {}).get("baseSignatureParams") or {})
                        .get("signatures") or [])
                signature = next((v for v in sigs if v), 0.0)
        rarity = next((r for r in reversed(_RARITIES) if r in key), "")
        deposit = _loc(loc, comp.get("depositName"), "")
        deposit = _clean(deposit)
        if not deposit and parts:
            deposit = resources[parts[0]["res"]]["name"]
        rocks[key] = {
            "name": deposit or key,
            "asteroid": "Asteroid" in key,
            "rarity": rarity,
            "signature": round(signature),
            "parts": parts,
        }
        return rocks[key]

    clusters: dict[str, dict] = {}

    def cluster(ref: str | None) -> dict:
        """{'chance': % that a spawn is a group, 'sizes': [[n, %], …]}"""
        if not ref:
            return {"chance": 0, "sizes": []}
        if ref not in clusters:
            rec = dc.record(ref[1:]) or {}
            sizes: dict[int, float] = {}
            params = rec.get("clusterParamsArray") or []
            weight = sum(float(c["relativeProbability"]) for c in params) or 1.0
            for c in params:
                span = range(int(c["minSize"]), int(c["maxSize"]) + 1)
                for n in span:
                    sizes[n] = sizes.get(n, 0) + 100 * float(c["relativeProbability"]) / weight / len(span)
            clusters[ref] = {
                "chance": round(float(rec.get("probabilityOfClustering") or 0), 1),
                "sizes": [[n, round(p, 1)] for n, p in sorted(sizes.items())],
            }
        return clusters[ref]

    out_locations = []
    for entry in locations.values():
        groups: dict[str, list] = {}
        for provider in entry["providers"]:
            rec = dc.record("HarvestableProviderPreset." + provider) or {}
            for group in rec.get("harvestableGroups") or []:
                method = METHODS.get(group.get("groupName"))
                if not method:
                    continue
                items = [(h["harvestable"], float(h["relativeProbability"]), h.get("clustering"))
                         for h in group.get("harvestables") or [] if h.get("harvestable")]
                total = sum(w for _, w, _ in items) or 1.0
                for ref, weight, clustering in items:
                    if rock(ref) is None:
                        continue
                    groups.setdefault(method, []).append({
                        "rock": ref.split(".", 1)[1],
                        "chance": round(100 * weight / total, 1),
                        "cluster": cluster(clustering),
                    })
        if groups:
            for items in groups.values():
                items.sort(key=lambda x: -x["chance"])
            out_locations.append({k: entry[k] for k in ("id", "name", "system", "kind", "parent")}
                                 | {"groups": groups})

    progress("Estimating qualities…")
    quality: dict[str, dict[str, dict[str, int]]] = {}
    for loc_entry in out_locations:
        system = loc_entry["system"]
        for items in loc_entry["groups"].values():
            for item in items:
                for part in rocks[item["rock"]]["parts"]:
                    model = quality_models.get(part["res"])
                    if not model:
                        continue
                    per = quality.setdefault(part["res"], {}).setdefault(system, {})
                    key = str(part["scale"])
                    if key not in per:
                        dist = model["overrides"].get(system, model["base"])
                        spread = quality_distribution(dist, part["scale"], model["bands"])
                        per[key] = {
                            "avg": round(sum(v * p for v, p in spread) / 100),
                            "dist": [[v, round(p, 4)] for v, p in spread if p >= 0.0001],
                            "banded": bool(model["bands"]),
                        }

    kind_order = {"planet": 0, "moon": 1, "lagrange": 2, "belt": 3, "cluster": 4}
    out_locations.sort(key=lambda l: (SYSTEMS.index(l["system"]), kind_order.get(l["kind"], 9), l["name"]))
    used = {p["res"] for r in rocks.values() if r for p in r["parts"]}
    return {
        "format": FORMAT,
        "systems": [{"id": s, "name": loc.get(s, s.title())} for s in SYSTEMS
                    if any(l["system"] == s for l in out_locations)],
        "locations": out_locations,
        "rocks": {k: v for k, v in rocks.items() if v},
        "resources": {k: v for k, v in resources.items() if k in used},
        "quality": quality,
    }
