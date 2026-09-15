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

LEAGUES ARE MATCHED BY (COUNTRY AND FOTMOB'S STABLE `primaryId`).

- NOT BY NAME ALONE. Per the finding recorded in
  `scripts/soccer_fotmob_harvest_2y.py`, FotMob's `Premier League` on name alone
  resolves to id 9986, which is CANADA's. `Serie A` alone resolves to id 268,
  which is BRAZIL's.
- NOT BY THE LEAGUE `id`. It is SEASON-SCOPED for four of the ten leagues. This
  module pinned the 2025-26 ids until 2026-09-15: Eredivisie 900368, Championship
  900638, Belgian Pro League 900433, and MLS 913550 for the 2026 season. The
  2026-27 listings carry 937276, 938218 and 937988, so every fixture in those
  three leagues returned None and the live momentum panel was hidden.
  `primaryId` (57/48/40/130) was the same in every season read, from 2024-25 to
  2026-27. The other six leagues have `id == primaryId`, which is why only these
  four ever broke.
- The exact-name allowlist is a FALLBACK, for a row that carries no
  `primaryId`. It is never a substring match. Same-day lookalikes include
  `Eredivisie Vrouwen` and `Eerste Divisie` (NED), `Premier League 2` (ENG),
  `USL Championship` (USA) and `First Division B` (BEL). Names also change:
  Belgium's top flight was `First Division A` in 2024-25.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date as date_cls
from typing import Any

from syndicate.features.soccer.ingestion.fotmob_shots import matches_for_date


@dataclass(frozen=True)
class FotmobLeague:
    primary_id: int          # FotMob's `primaryId`: the competition, not one season of it
    ccode: str
    names: tuple[str, ...]   # exact names; consulted only when a row has no `primaryId`


# Verified 2026-09-15 against FotMob's own listings for 2024-10-19, 2025-03-01,
# 2025-10-18, 2026-09-13 and 2026-09-15. A league added to `LEAGUE_ESPN_SLUGS`
# needs an entry here before this module can resolve it, and in
# `reports/soccer_backtest/fotmob_league_ids.json` (a test holds the two equal).
FOTMOB_LEAGUES: dict[str, FotmobLeague] = {
    "epl": FotmobLeague(47, "ENG", ("Premier League",)),
    "la_liga": FotmobLeague(87, "ESP", ("LaLiga",)),
    "bundesliga": FotmobLeague(54, "GER", ("Bundesliga",)),
    "serie_a": FotmobLeague(55, "ITA", ("Serie A",)),
    "ligue_1": FotmobLeague(53, "FRA", ("Ligue 1",)),
    "mls": FotmobLeague(130, "USA", ("Major League Soccer",)),
    "eredivisie": FotmobLeague(57, "NED", ("Eredivisie",)),
    "primeira_liga": FotmobLeague(61, "POR", ("Liga Portugal",)),
    "championship": FotmobLeague(48, "ENG", ("Championship",)),
    "belgian_pro_league": FotmobLeague(40, "BEL", ("Belgian Pro League", "First Division A")),
}

_JUNK_WORDS = (" fc", " cf", " sc", " afc", " club", " city", " united", " town")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fotmob_league_slug(candidate: dict[str, Any]) -> str | None:
    """Which tracked league a `matches_for_date` row belongs to, or None.

    Country must match. Then, if the row carries `league_primary_id`, that alone
    decides: a present-but-different primary id is a different competition, even
    under an allowlisted name. Only a row without one falls back to
    `league_id == primary_id` or an exact allowlisted name.
    """
    ccode = str(candidate.get("ccode") or "").strip().upper()
    primary = _as_int(candidate.get("league_primary_id"))
    league_id = _as_int(candidate.get("league_id"))
    name = str(candidate.get("league") or "").strip()
    for slug, spec in FOTMOB_LEAGUES.items():
        if ccode != spec.ccode:
            continue
        if primary is not None:
            if primary == spec.primary_id:
                return slug
            continue
        if league_id == spec.primary_id or name in spec.names:
            return slug
    return None


def fotmob_leagues_record() -> dict[str, dict[str, Any]]:
    """`FOTMOB_LEAGUES` in the JSON shape of `fotmob_league_ids.json`."""
    return {
        slug: {"primary_id": spec.primary_id, "ccode": spec.ccode, "names": list(spec.names)}
        for slug, spec in FOTMOB_LEAGUES.items()
    }


def _norm(name: str) -> str:
    # Fold accents BEFORE dropping non-letters. Dropping them outright turned
    # FotMob's "Standard Liège" into "standard lige", which never matched ESPN's
    # "Standard Liege" (measured 2026-09-12).
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z ]", "", folded.lower())
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
    league_key = str(league).strip().lower()
    if league_key not in FOTMOB_LEAGUES:
        return None
    try:
        d = date_cls.fromisoformat(iso_date)
    except ValueError:
        return None

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
        if fotmob_league_slug(c) != league_key:
            continue
        c_home, c_away = _norm(c.get("home") or ""), _norm(c.get("away") or "")
        if _names_match(home_n, c_home) and _names_match(away_n, c_away):
            mid = c.get("match_id")
            return int(mid) if mid is not None else None
    return None


__all__ = ["FOTMOB_LEAGUES", "fotmob_league_slug", "fotmob_leagues_record", "resolve_fotmob_match_id"]
