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
# Women's college basketball (lane wncaab-module, 2026-11-02): the same ESPN shape, its own list --
# 359 of 362 ids are shared with the men's; women's-only Queens/Lindenwood/Southern Indiana are IN
# ESPN's women's list, so the men's supplement below does not apply to it. The women's has its own (Mercyhurst).
WNCAAB_REGISTRY_PATH = Path(__file__).resolve().parent / "wncaab_team_registry.csv"

# DIVISION I PROGRAMMES ESPN'S TEAM LIST OMITS (2026-11-02). The CSV is ESPN's
# `/teams?limit=1000`, which returns 362 programmes and not these three -- yet
# ESPN's own per-team record files each under `groups.parent.id == "50"`
# (Division I), all three play full D1 schedules (ASUN / OVC), and OddsAPI
# prices them: Winthrop @ Queens and Southern Indiana @ Belmont were on the
# 11-02 board with no game to join to. Kept here rather than in the CSV so
# `build_ncaab_team_registry.py --check` still compares the CSV against ESPN's
# list alone. Same columns as the CSV.
_D1_MISSING_FROM_ESPN_TEAM_LIST: tuple[dict[str, str], ...] = (
    {"espn_id": "2511", "school": "Queens University", "display_name": "Queens University Royals",
     "short_display_name": "Queens", "abbreviation": "QUC", "mascot": "Royals", "slug": "queens-university-royals"},
    {"espn_id": "88", "school": "Southern Indiana", "display_name": "Southern Indiana Screaming Eagles",
     "short_display_name": "S Indiana", "abbreviation": "USI", "mascot": "Screaming Eagles",
     "slug": "southern-indiana-screaming-eagles"},
    {"espn_id": "2815", "school": "Lindenwood", "display_name": "Lindenwood Lions",
     "short_display_name": "Lindenwood", "abbreviation": "LIN", "mascot": "Lions", "slug": "lindenwood-lions"},
)
# THE WOMEN'S LIST OMITS ONE THE SAME WAY (2026-11-04, lane wncaab-module, user "Yes, fix it here"): Mercyhurst
# (NEC), whose women's team record files under `groups.parent.id == "50"` and is active. Out of the registry, its
# games never reached the women's slate, board, sims or grading. The women's VMI (no group) and The Citadel
# (inactive) are the other two men's-only ids, and neither is a women's D-I team.
_WNCAAB_D1_MISSING_FROM_ESPN_TEAM_LIST: tuple[dict[str, str], ...] = (
    {"espn_id": "2385", "school": "Mercyhurst", "display_name": "Mercyhurst Lakers", "short_display_name": "Mercyhurst",
     "abbreviation": "MERC", "mascot": "Lakers", "slug": "mercyhurst-lakers"},
)


def _registry_path(league: str) -> Path:
    return WNCAAB_REGISTRY_PATH if str(league).lower() == "wncaab" else REGISTRY_PATH


@lru_cache(maxsize=4)
def registry_rows(league: str = "ncaab") -> tuple[dict[str, str], ...]:
    """Every row of the committed registry, or an empty tuple if it is gone.

    An empty result here means THE FILE IS MISSING, which is a different fact
    from "this sport has no map" -- `team_aliases` logs nothing either way, so
    `tests/test_nhl_ncaab_club_maps.py` pins a non-empty registry so a deleted
    or truncated file fails a test instead of silently emptying the map.
    The supplement above is appended only to a registry that loaded.
    """
    path = _registry_path(league)
    if not path.exists():
        return ()
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = tuple(dict(row) for row in csv.DictReader(handle))
    except Exception:
        return ()
    if not rows:
        return ()
    missing = _WNCAAB_D1_MISSING_FROM_ESPN_TEAM_LIST if str(league).lower() == "wncaab" else _D1_MISSING_FROM_ESPN_TEAM_LIST
    present = {str(row.get("espn_id") or "") for row in rows}
    return rows + tuple(dict(row) for row in missing if row["espn_id"] not in present)


@lru_cache(maxsize=1)
def _mens_mascot_by_espn_id() -> dict[str, str]:
    """The men's registry mascot per ESPN id: a school's id is shared by its men's and women's teams."""
    return {str(row.get("espn_id") or ""): str(row.get("mascot") or "").strip() for row in registry_rows("ncaab")}


def iter_team_alias_offers(league: str = "ncaab") -> Iterator[Tuple[str, str]]:
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
    mens_mascots = _mens_mascot_by_espn_id() if str(league).lower() == "wncaab" else {}
    for row in registry_rows(league):
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
        mens = mens_mascots.get(str(row.get("espn_id") or ""), "")
        extra = (mens,) if mens and mens != str(row.get("mascot") or "").strip() else ()
        yield from _odds_feed_spellings(row, school, extra_mascots=extra)
    for token, school in _ODDS_FEED_ALIASES:
        yield token, school


# THE ODDS FEED SPELLS SCHOOLS ITS OWN WAY, and the registry is ESPN's. Measured
# 2026-11-02 over the 120 OddsAPI events commencing 11-02/11-03: 50 did not
# resolve to their ESPN game, almost all on a name the registry never offered --
# "Georgia St Panthers" (ESPN "Georgia State"), "GW Revolutionaries", "LIU
# Sharks", "Army Knights" (ESPN mascot "Black Knights"), "American Eagles"
# (ESPN school "American University"). An unresolved side has no canonical key,
# so the Games rail drew a chip-less card and Layer 1 left the game `unknown`.
# Each spelling below is derived from the row it names, so it can only point at
# that school; the collision pass in `team_aliases` still drops any token two
# schools both produce.
def _odds_feed_spellings(
    row: dict[str, str], school: str, extra_mascots: Tuple[str, ...] = ()
) -> Iterator[Tuple[str, str]]:
    mascot = str(row.get("mascot") or "").strip()
    short = str(row.get("short_display_name") or "").strip()
    abbreviation = str(row.get("abbreviation") or "").strip()
    # THE WOMEN'S "LADY" PREFIX (2026-11-07). ESPN's women's registry says "Morgan State Lady Bears" and
    # "Northwestern State Lady Demons"; the odds feed says "Morgan St Bears", "Northwestern St Demons". Both sides
    # failed to resolve on the 11-04..11-08 quote logs. Only COMPOSITE spellings take the bare mascot -- the lone
    # mascot token above stays "Lady Bears" -- so no bare "Bears" key is offered for the collision pass to fight over.
    mascots = [mascot] if mascot else []
    if mascot.startswith("Lady ") and len(mascot) > len("Lady "):
        mascots.append(mascot[len("Lady "):])
    # THE MEN'S MASCOT ON A WOMEN'S TEAM (2026-11-12, user "still have college teams not matching"). The odds feed
    # prices women's games under the school's men's mascot where ESPN's women's registry has its own: "Montana
    # Grizzlies" (ESPN "Lady Griz"), "Western Kentucky Hilltoppers" ("Lady Toppers"), and on 11-03 "Penn State Nittany
    # Lions" ("Lady Lions"). 29 of the women's schools carry a mascot that differs from the men's row with the same
    # ESPN id. The caller passes the men's mascot for those; like the "Lady" stem, it enters COMPOSITE spellings only.
    mascots.extend(name for name in extra_mascots if name and name not in mascots)
    stems = {school}
    if school.endswith(" State"):
        base = school[: -len(" State")]
        stems |= {f"{base} St", f"{base} St."}
    # "CSU X" FOR ESPN'S "Cal State X" (2026-11-12): the odds feed's "CSU Bakersfield Roadrunners" left both of
    # Bakersfield's 11-12 games (men's @ Western Illinois, women's @ Washington) chip-less on the Games rail; the 11-03
    # "CSU Fullerton Titans" was the same spelling, added then as a one-off entry. Bakersfield, Fullerton, Northridge.
    if school.startswith("Cal State "):
        stems.add("CSU " + school[len("Cal State "):])
    if school.endswith(" University"):
        stems.add(school[: -len(" University")])
    if school.startswith("Mount "):
        stems.add("Mt. " + school[len("Mount "):])
    for stem in stems:
        yield stem, school
        for name in mascots:
            yield f"{stem} {name}", school
    for name in mascots:
        for prefix in (short, abbreviation):
            if prefix:
                yield f"{prefix} {name}", school
        last = mascot.split()[-1]
        if last != mascot:
            yield f"{school} {last}", school


# Vendor spellings no rule above derives, each read off the 2026-11-02 odds feed.
_ODDS_FEED_ALIASES: tuple[tuple[str, str], ...] = (
    ("Arkansas-Little Rock Trojans", "Little Rock"),
    ("Boston Univ. Terriers", "Boston University"),
    ("Loyola (MD) Greyhounds", "Loyola Maryland"),
    ("St. Thomas (MN) Tommies", "St. Thomas"),
    ("Grambling St Tigers", "Grambling"),
    ("Central Connecticut St Blue Devils", "Central Connecticut"),
    ("Appalachian St Mountaineers", "App State"),
    ("SE Missouri St Redhawks", "Southeast Missouri State"),
    ("UMKC Kangaroos", "Kansas City"),
    ("Loyola (Chi) Ramblers", "Loyola Chicago"),
    ("Tenn-Martin Skyhawks", "UT Martin"),
    ("Grand Canyon Antelopes", "Grand Canyon"),
    ("Long Beach St 49ers", "Long Beach State"),
    ("Seattle Redhawks", "Seattle U"),
    # 2026-11-03: the 11-03/11-04 slates brought these (every unresolved name across the 11-01..11-05 quote logs,
    # both leagues). Unresolved, the Games rail drew a chip-less "N opportunities" card for each game, and the
    # live re-sim's margin anchor could not find the game's close.
    ("Cal Baptist Lancers", "California Baptist"),
    ("Fort Wayne Mastodons", "Purdue Fort Wayne"),
    ("New Orleans Privateers", "LSU New Orleans"),
    ("Sam Houston St Bearkats", "Sam Houston"),
    # 2026-11-07: every name in the 11-04..11-08 men's quote logs that still did not resolve (user: games on the
    # rail "not matched"). IUPUI renamed itself IU Indianapolis in 2024; the feed kept the old name.
    ("Albany Great Danes", "UAlbany"),
    ("Florida Int'l Golden Panthers", "Florida International"),
    ("IUPUI Jaguars", "IU Indianapolis"),
    ("Nicholls St Colonels", "Nicholls"),
)
