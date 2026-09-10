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


# APOSTROPHES AND THE OKINA ARE NOT PART OF A NAME. OddsAPI drops them and the
# registry keeps them, so "Hawaii Rainbow Warriors", "Louisiana Ragin Cajuns"
# and "Gardner-Webb Runnin Bulldogs" missed "Hawai'i", "Ragin'" and "Runnin'".
# Measured 2026-09-10 on production's board and plan: 3 of the 7 NCAAF names
# that failed the registry, out of 142. Stripped on BOTH sides (index keys and
# lookups), so it can only merge spellings of one name, and a merge that made
# two teams share a key would drop that key, not pick one.
_IGNORED_CHARACTERS = str.maketrans("", "", "'\u2018\u2019\u02bb`")



def _odds_name_supplement() -> list[tuple[str, str]]:
    """`(alias, canonical team name)` from the ODDS JOIN'S OWN supplement.

    The other 4 of those 7 names are forms the registry does not carry: OddsAPI
    sends the long form where the registry has the short one ("Appalachian
    State" / "App State", "Southern Mississippi", "Sam Houston State"), or the
    reverse ("UMass" / "Massachusetts"; ESPN's `shortDisplayName` "UMass" failed
    too). `oddsapi_lines._ODDSAPI_NAME_SUPPLEMENT` already answers every one of
    them, hand-verified against live OddsAPI reads, and it is how the board got
    these teams' lines in the first place. Settlement simply never read it.

    READ THROUGH `iter_team_alias_offers`, the one enumeration its docstring
    says every consumer must share ("reaches both consumers or neither"), so a
    name added there now reaches the grader too. A second hand-kept list here
    is the drift that function exists to prevent.

    [] if the module cannot be imported: the index then behaves exactly as it
    did before this existed, which refuses rather than guesses.
    """
    try:
        from syndicate.features.ncaaf.oddsapi_lines import iter_team_alias_offers

        return [(alias, canonical) for alias, canonical, is_supplement in iter_team_alias_offers() if is_supplement]
    except Exception:  # pragma: no cover - deploy-skew guard
        return []


def _norm(value: Any) -> str:
    return " ".join(str(value or "").translate(_IGNORED_CHARACTERS).strip().lower().split())


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
    by_canonical: dict[str, set[str]] = {}
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
        by_canonical.setdefault(_norm(row.get("canonical_team_name")), set()).add(team_id)
        for key in keys:
            if key:
                owners.setdefault(key, set()).add(team_id)

    # THE SUPPLEMENT ENTERS THE SAME AMBIGUITY PASS AS EVERY OTHER KEY. The odds
    # join lets it OVERRIDE a collision, since a board line is a display. Here a
    # wrong join is a confident wrong grade, so a supplement key two teams
    # would own refuses like any other. An entry whose canonical name this
    # registry does not hold, or holds twice, is skipped rather than guessed.
    for alias, canonical in _odds_name_supplement():
        ids = by_canonical.get(_norm(canonical)) or set()
        key = _norm(alias)
        if key and len(ids) == 1:
            owners.setdefault(key, set()).add(next(iter(ids)))

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
