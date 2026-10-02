"""Refreshes assets/ships.json, the ship catalogue bundled with the app (used
until the first download, e.g. offline). Run before a release:

    .venv/bin/python -m tools.update_ship_snapshot
"""

from collections import Counter

from app import ships


def main() -> None:
    catalogue = ships.build(print)
    ships.save(catalogue, ships.SNAPSHOT_FILE)
    status = Counter(s.status for s in catalogue.ships)
    print(f"{len(catalogue)} ships ({status[ships.FLIGHT_READY]} flight-ready, {status[ships.IN_CONCEPT]} in concept, "
          f"{sum(1 for s in catalogue.ships if not s.store)} game-only) -> {ships.SNAPSHOT_FILE}")
    unlinked = [s.name for s in catalogue.ships if s.store and not s.concept and not s.class_id]
    if unlinked:
        print("Flight-ready store ships without a game class (add to ships._CLASS_ALIASES):", ", ".join(unlinked))


if __name__ == "__main__":
    main()
