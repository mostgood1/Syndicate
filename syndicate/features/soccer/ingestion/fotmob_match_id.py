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


def _fold(name: str) -> str:
    return unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")


def _norm(name: str) -> str:
    # Fold accents BEFORE dropping non-letters. Dropping them outright turned
    # FotMob's "Standard Liège" into "standard lige", which never matched ESPN's
    # "Standard Liege" (measured 2026-09-12).
    s = re.sub(r"[^a-z ]", "", _fold(name).lower())
    for junk in _JUNK_WORDS:
        s = s.replace(junk, " ")
    return " ".join(s.split())


def _names_match(a: str, b: str) -> bool:
    if a == b:
        return True
    # Substring rather than exact: FotMob's "Athletic Club" vs ESPN's
    # "Athletic Bilbao" would fail an exact match on either normalisation.
    return bool(a) and bool(b) and (a in b or b in a)


# Words that name a KIND of club, a squad, or nothing in particular. Two names
# sharing only these are not evidence of one club ("Royal Antwerp" is not
# "Royal Charleroi", "Real Madrid" is not "Real Sociedad").
_GENERIC_TOKENS = frozenset({
    "ac", "afc", "as", "bk", "cd", "cf", "cp", "fc", "fk", "if", "kaa", "krc", "ksv", "kv", "kvc",
    "nk", "rc", "rfc", "rsc", "sad", "sc", "sd", "sk", "ss", "sv", "ud", "us", "vfb", "vfl",
    "athletic", "atletico", "club", "city", "county", "de", "del", "deportivo", "inter", "la",
    "le", "north", "olympique", "racing", "real", "royal", "saint", "sint", "south", "sporting",
    "st", "stade", "the", "town", "union", "united", "wanderers", "rovers", "albion",
    "ii", "reserves", "futures", "u19", "u21", "u23", "w", "women",
})

# Club-type codes an acronym keeps WHOLE: "LAFC" is "LA" + "FC", not "L-A-F".
_CLUB_CODES = frozenset({"ac", "afc", "as", "cf", "fc", "sc", "sk", "sv"})

# ESPN `displayName` -> FotMob's name, for clubs NO name rule can bridge: a
# translation, or a nickname against a town. Every entry is a measured miss
# (2026-09-15, 230 ESPN fixtures across all 10 leagues, 7 dates): keep it that
# way -- an entry nobody measured is a guess about someone else's spelling.
_ESPN_NAME_ALIASES: dict[str, str] = {
    "stade rennais": "Rennes",          # ligue_1 2026-08-23, 2026-08-30
    "fc cologne": "1. FC Köln",         # bundesliga 2026-08-29, 2026-09-12
}


def _tokens(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(name).lower())


def _espn_alias(name: str) -> str:
    return _ESPN_NAME_ALIASES.get(" ".join(_tokens(name)), name)


def _is_acronym(short: list[str], long: list[str]) -> bool:
    """`LAFC` for `Los Angeles FC`, `PSG` for `Paris Saint-Germain`: one 2-5
    letter token spelling the other name's initials, club codes kept whole or not.
    """
    if len(short) != 1 or len(long) < 2 or not 2 <= len(short[0]) <= 5 or short[0].isdigit():
        return False
    words = [t for t in long if not t.isdigit()]
    initials = "".join(t[0] for t in words)
    with_codes = "".join(t if t in _CLUB_CODES else t[0] for t in words)
    return short[0] in (initials, with_codes)


def _loose_side_match(espn_name: str, fotmob_name: str) -> bool:
    """One team, by a DISTINCTIVE word: equal, a 5+ letter prefix, a 6+ letter
    substring, or an acronym. Only used after the strict match has found nothing.
    """
    ta, tb = _tokens(espn_name), _tokens(fotmob_name)
    da = [t for t in ta if len(t) >= 3 and not t.isdigit() and t not in _GENERIC_TOKENS]
    db = [t for t in tb if len(t) >= 3 and not t.isdigit() and t not in _GENERIC_TOKENS]
    for s in da:
        for t in db:
            short, long_ = sorted((s, t), key=len)
            if s == t:
                return True
            if len(short) >= 5 and long_.startswith(short):
                return True
            if len(short) >= 6 and short in long_:
                return True
    return _is_acronym(ta, tb) or _is_acronym(tb, ta)


def _side_match(espn_name: str, fotmob_name: str) -> bool:
    # A side the STRICT rule already matches counts in the loose pass: "D.C.
    # United" has no 3+ letter word to match loosely, and its fixture v "LAFC"
    # needed the other side's acronym to resolve (measured 2026-08-29).
    a, b = _norm(espn_name), _norm(fotmob_name)
    return (bool(a) and bool(b) and _names_match(a, b)) or _loose_side_match(espn_name, fotmob_name)


def _strict_match_id(rows: list[dict[str, Any]], home_team: str, away_team: str) -> int | None:
    home_n, away_n = _norm(home_team), _norm(away_team)
    if not home_n or not away_n:
        return None
    for c in rows:
        c_home, c_away = _norm(c.get("home") or ""), _norm(c.get("away") or "")
        if _names_match(home_n, c_home) and _names_match(away_n, c_away):
            mid = c.get("match_id")
            return int(mid) if mid is not None else None
    return None


def _loose_match_ids(rows: list[dict[str, Any]], home_team: str, away_team: str) -> set[int]:
    return {
        int(c["match_id"]) for c in rows
        if c.get("match_id") is not None
        and _side_match(home_team, c.get("home") or "")
        and _side_match(away_team, c.get("away") or "")
    }


def resolve_fotmob_match_id(
    *, league: str, home_team: str, away_team: str, iso_date: str,
    _fetch: Any = None,
) -> int | None:
    """FotMob match id for this fixture, or None if it cannot be resolved.

    ESPN names listed in `_ESPN_NAME_ALIASES` are swapped for FotMob's first.
    Then two passes run over the league's fixtures in the date window:

    1. STRICT, the original: normalised names, equal or substring, both sides.
    2. LOOSE, only when (1) finds nothing. Each side must match strictly or by a
       DISTINCTIVE word (`_loose_side_match`), and exactly ONE fixture may
       qualify; two or more is refused rather than guessed. It exists for name
       shapes (1) cannot bridge, measured on production's own inputs
       2026-09-15: ESPN "Waasland-Beveren" / FotMob "SK Beveren",
       "Sint-Truidense" / "St.Truiden", "LAFC" / "Los Angeles FC",
       "Bayern Munich" / "Bayern München". Over 230 fixtures it added 13
       resolves and disagreed with (1) on none of the 212 (1) resolved.
       Because it runs only after (1) fails, it cannot change an id (1) returns.

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

    home_team, away_team = _espn_alias(home_team), _espn_alias(away_team)
    if not _norm(home_team) or not _norm(away_team):
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

    rows = [c for c in candidates if fotmob_league_slug(c) == league_key]
    strict = _strict_match_id(rows, home_team, away_team)
    if strict is not None:
        return strict
    loose = _loose_match_ids(rows, home_team, away_team)
    return next(iter(loose)) if len(loose) == 1 else None


__all__ = ["FOTMOB_LEAGUES", "fotmob_league_slug", "fotmob_leagues_record", "resolve_fotmob_match_id"]
