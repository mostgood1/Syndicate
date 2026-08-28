"""Resolve an NCAAF team name to a team_id, or refuse.

`team_aliases` HAS NO NCAAF MAP, and that is the reason this file exists rather
than another entry there. `_alias_map("ncaaf")` returns `{}`, so
`teams_match("ncaaf", ...)` falls through to its heuristics -- the last of which
is `len(token) >= 3 and any(word.startswith(token))`. Across ~130 FBS teams
that rule matches:

    "Michigan"  -> "Michigan State"
    "Ohio"      -> "Ohio State"
    "Miami"     -> both Miamis

Those are fine-ish as a display nicety and catastrophic on a settlement path: a
bet graded against the wrong game gets a confident won/lost verdict and nothing
downstream can tell it was the wrong fixture.

--------------------------------------------------------------------------
THE REGISTRY IS AUTHORITATIVE, AND THE EXISTING INDEX OVER IT IS NOT SAFE
--------------------------------------------------------------------------

`ncaaf_team_registry.csv` carries 684 teams with `team_id`,
`canonical_team_name`, `abbreviation`, pipe-separated `aliases`, `display_name`,
`school_name` and `mascot_name`, and is already allowlisted in
`HOT_ARTIFACT_PATTERNS` as
`*_source/source_artifacts/data/processed/team_registry/*.csv`.

`ncaaf/cards.py::_team_registry_index` builds its index with `setdefault`, so
the FIRST row wins every collision. Measured 2026-08-28 over that same key
construction: **2,342 distinct keys, 128 of them owned by more than one
`team_id`** -- worst `tigers`, which names **25 teams**. `_resolve_team(
"Wildcats")` returns Abilene Christian, silently and confidently.

So this builds the same index and DROPS every ambiguous key instead of picking
a winner, which is the refusal `_nickname_alias_map` and
`unambiguous_club_tokens` already make for their own sports.

--------------------------------------------------------------------------
THE REFUSAL COSTS NOTHING ON REAL DATA, AND THAT WAS MEASURED FIRST
--------------------------------------------------------------------------

Against the live ESPN college-football scoreboard for 2026-08-29 (Week 1 opener
weekend, 8 games, 16 teams): **16/16 resolved unambiguously**. ESPN sends
specific forms -- `displayName` "TCU Horned Frogs", `location` "TCU",
`abbreviation` "TCU" -- and never a bare mascot, so nothing real is lost by
refusing bare mascots.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["resolve_ncaaf_team_id", "unambiguous_team_index", "registry_path"]


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def registry_path() -> Path | None:
    """The registry CSV, or None.

    `ncaaf_team_registry.csv` FIRST because it is the file `ncaaf/cards.py`
    actually reads today; the `_snapshot` variant is the fallback so a mirror
    that carries only one of the two still resolves. Routed through
    `sources.ncaaf_source_artifacts_data_path` rather than the hardcoded
    `parents[3]` walk in `cards.py`, so a `SYNDICATE_ARTIFACT_ROOT_NCAAF`
    override is honoured.
    """
    try:
        from syndicate.features.ncaaf.sources import ncaaf_source_artifacts_data_path
    except Exception:  # pragma: no cover - deploy-skew guard
        return None
    for name in ("ncaaf_team_registry.csv", "ncaaf_team_registry_snapshot.csv"):
        try:
            path = ncaaf_source_artifacts_data_path("processed", "team_registry", name)
            if path.is_file():
                return path
        except Exception:
            continue
    return None


@lru_cache(maxsize=1)
def unambiguous_team_index() -> dict[str, str]:
    """`{normalised name -> team_id}`, ambiguous names OMITTED.

    Empty when the registry cannot be read, and the caller must treat that as
    "cannot resolve" rather than "no teams" -- an empty index makes every join
    refuse, which is the safe direction and is visible in the counter.
    """
    path = registry_path()
    if path is None:
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return {}

    owners: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        team_id = _norm(row.get("team_id"))
        if not team_id:
            continue
        keys = {
            _norm(row.get(field))
            for field in ("canonical_team_name", "abbreviation", "display_name",
                          "school_name", "mascot_name")
        }
        keys |= {_norm(alias) for alias in str(row.get("aliases") or "").split("|")}
        # THE COMBINED FORM ESPN ACTUALLY SENDS. `displayName` is
        # "TCU Horned Frogs" -- school plus mascot -- and neither column carries
        # it on its own, so without this the scoreboard's primary name field
        # would miss the registry entirely.
        keys.add(_norm(f"{row.get('school_name')} {row.get('mascot_name')}"))
        for key in keys:
            if key:
                owners.setdefault(key, set()).add(team_id)

    return {key: next(iter(ids)) for key, ids in owners.items() if len(ids) == 1}


def resolve_ncaaf_team_id(name: Any) -> str | None:
    """The team's registry id, or None when the name is unknown OR AMBIGUOUS.

    One return value for both refusals ON PURPOSE. A caller must not be able to
    treat "ambiguous" as a weaker no than "unknown" and fall back to a guess --
    that fallback is the entire failure this module exists to prevent.
    """
    key = _norm(name)
    if not key:
        return None
    return unambiguous_team_index().get(key)
