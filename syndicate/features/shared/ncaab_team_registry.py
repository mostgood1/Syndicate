"""The NCAAB Division I team registry, and the alias offers derived from it.

The registry itself is `ncaab_team_registry.csv`, committed BESIDE this module
rather than under `data/` -- see `scripts/build_ncaab_team_registry.py` for why
(a map derived from `data/` builds empty in a session worktree, in silence,
which is how the soccer alias map once returned None for every club).

This module only READS and offers. It deliberately does no collision
resolution: `team_aliases._ncaab_alias_to_name` owns that, because dropping an
ambiguous key is a decision about the MAP's semantics, not about the registry.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Tuple

REGISTRY_PATH = Path(__file__).resolve().parent / "ncaab_team_registry.csv"


@lru_cache(maxsize=1)
def registry_rows() -> tuple[dict[str, str], ...]:
    """Every row of the committed registry, or an empty tuple if it is gone.

    An empty result here means THE FILE IS MISSING, which is a different fact
    from "this sport has no map" -- `team_aliases` logs nothing either way, so
    `tests/test_nhl_ncaab_club_maps.py` pins a non-empty registry so a deleted
    or truncated file fails a test instead of silently emptying the map.
    """
    if not REGISTRY_PATH.exists():
        return ()
    try:
        with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except Exception:
        return ()


def iter_team_alias_offers() -> Iterator[Tuple[str, str]]:
    """Yield ``(alias_token, canonical_school)`` for every name a feed may emit.

    CANONICAL IS THE SCHOOL, NOT THE DISPLAY NAME -- the same choice
    `_ncaaf_alias_to_name` makes. "Abilene Christian" is what a board row, an
    odds feed and a schedule all agree on; "Abilene Christian Wildcats" is one
    vendor's rendering of it.

    THE BARE MASCOT IS OFFERED, NOT WITHHELD. It is the single largest source
    of collisions in college sport -- NCAAF measured 95 dropped keys, `tigers`
    claimed by 25 schools -- but withholding it here would also hide the
    handful that ARE unique, and it would put the collision policy in two
    places. Offer everything; let one collision pass decide.
    """
    for row in registry_rows():
        school = str(row.get("school") or "").strip()
        if not school:
            continue
        for column in ("school", "display_name", "short_display_name", "abbreviation", "mascot"):
            token = str(row.get(column) or "").strip()
            if token:
                yield token, school
        slug = str(row.get("slug") or "").strip()
        if slug:
            yield slug.replace("-", " "), school
