"""Blueprints you have, as the launcher counts them: received in your own
LIVE / HOTFIX logs, plus — with Sync online — the online collection (which
also holds blueprints received before a reinstall and ones marked owned on
sc-toolbox.com). Matched by app.contracts.blueprint_key."""

from __future__ import annotations

import json

from app import config, contracts, portal, settings


def online_owned() -> set[str]:
    """The signed-in account's online collection, as last fetched by app.sync
    (empty without a sign-in or with Sync online off)."""
    if not settings.load().sync_enabled:
        return set()
    profile = portal.load_profile()
    if profile is None or not profile.account_id:
        return set()
    try:
        data = json.loads((config.DATA_DIR / f"blueprints-owned-{profile.account_id}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    return {contracts.blueprint_key(n) for n in data.get("names", []) if n}
