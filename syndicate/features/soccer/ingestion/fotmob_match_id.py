"""Resolve an ESPN-identified live match to its FotMob match id.

WHY THIS EXISTS. The 2026-08-22 deep dive found the goal-timing/direction
signal lives in FotMob's OWN momentum series, not in the ESPN-commentary
proxy `features/momentum.py` computes (that proxy was swept across every
half-life 30s-1800s against its production weighting scheme and showed no
measurable signal -- see `docs/ai_context/todo.md` #518). FotMob's shots and
momentum are keyed by FotMob's own numeric match id, which nothing in this
codebase has ever needed to resolve from an ESPN event before now.

JOIN STRATEGY: (league, date, home team name, away team name). No shared id
exists across the two providers, so this is a name-normalised match, not an
exact key lookup -- treated as best-effort and NEVER FATAL, matching this
module's neighbours' pattern of "no data" as a distinct, stated outcome from
"zero".

LEAGUE IDS ARE PINNED BY (NAME AND COUNTRY), not name alone, per the same
finding recorded in `scripts/soccer_fotmob_harvest_2y.py`: matching FotMob's
`Premier League` on name alone resolves to id 9986, which is CANADA's, and
`Serie A` alone resolves to id 268, which is BRAZIL's.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from typing import Any

from syndicate.features.soccer.ingestion.fotmob_shots import matches_for_date

# (fotmob league_id, expected ccode). Verified 2026-08-22 against FotMob's own
# response -- see the harvest script's docstring for the Canada/Brazil trap
# this guards against. Kept in sync manually; a league added to
# `LEAGUE_ESPN_SLUGS` needs an entry here before this module can resolve it.
_FOTMOB_LEAGUE_IDS: dict[str, tuple[int, str]] = {
    "epl": (47, "ENG"),
    "la_liga": (87, "ESP"),
    "bundesliga": (54, "GER"),
    "serie_a": (55, "ITA"),
    "ligue_1": (53, "FRA"),
    "mls": (913550, "USA"),
    "eredivisie": (900368, "NED"),
    "primeira_liga": (61, "POR"),
    "championship": (900638, "ENG"),
    "belgian_pro_league": (900433, "BEL"),
}

_JUNK_WORDS = (" fc", " cf", " sc", " afc", " club", " city", " united", " town")


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(name or "").lower())
    for junk in _JUNK_WORDS:
        s = s.replace(junk, " ")
    return " ".join(s.split())


def _names_match(a: str, b: str) -> bool:
    if a == b:
        return True
    # Substring rather than exact: FotMob's "Athletic Club" vs ESPN's
    # "Athletic Bilbao" would fail an exact match on either normalisation.
    return bool(a) and bool(b) and (a in b or b in a)


def resolve_fotmob_match_id(
    *, league: str, home_team: str, away_team: str, iso_date: str,
    _fetch: Any = None,
) -> int | None:
    """FotMob match id for this fixture, or None if it cannot be resolved.

    `_fetch` is an injection point for tests -- defaults to the real
    `matches_for_date` HTTP call.
    """
    fetch = _fetch or matches_for_date
    ids = _FOTMOB_LEAGUE_IDS.get(str(league).strip().lower())
    if ids is None:
        return None
    league_id, ccode = ids
    try:
        d = date_cls.fromisoformat(iso_date)
    except ValueError:
        return None
    compact = d.strftime("%Y%m%d")

    home_n, away_n = _norm(home_team), _norm(away_team)
    if not home_n or not away_n:
        return None

    try:
        # A fixture can be listed a day either side of the ESPN date, so both
        # neighbours are checked before giving up -- kickoffs near midnight UTC
        # otherwise resolve on one provider's date and not the other's.
        candidates: list[dict[str, Any]] = []
        for offset in (0, -1, 1):
            probe = (d.toordinal() + offset)
            probe_compact = date_cls.fromordinal(probe).strftime("%Y%m%d")
            candidates.extend(fetch(probe_compact))
    except Exception:
        return None

    for c in candidates:
        if c.get("league_id") != league_id:
            continue
        if str(c.get("ccode") or "").strip().upper() != ccode:
            continue
        c_home, c_away = _norm(c.get("home") or ""), _norm(c.get("away") or "")
        if _names_match(home_n, c_home) and _names_match(away_n, c_away):
            mid = c.get("match_id")
            return int(mid) if mid is not None else None
    return None


__all__ = ["resolve_fotmob_match_id"]
