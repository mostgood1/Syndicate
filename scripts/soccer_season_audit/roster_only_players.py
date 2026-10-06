"""MEASUREMENT ONLY -- NOT SHIPPED. H-ROSTER FAILED its pre-registered test 2026-10-06
(`.syndicate/findings_2026-10-06_soccer_roster_only_players_result.md`); kept here so the
replay is reproducible. Do not import it from production code.

Roster-only players: ESPN-roster players with NO stats row, added to the sim squad.

THE GAP THIS CLOSES (`.syndicate/findings_2026-10-06_soccer_roster_only_players_prereg.md`).
A player reaches `player_props` only if he has a row in the league's `players_*.csv`.
The ESPN roster is a RESCUE inside the departed-player filter and never ADDS anyone,
so a new signing, an academy debutant or a player the stats source has not reached
yet is in no sim squad at all: the board cannot project him, and his real share of
the team's shots and goals is handed to the listed teammates instead.

THE MECHANISM, exactly as pre-registered (lane `soccer-roster-only-players`, choices
fixed in `lanes.md` before any measurement):

  * who: a row of the league's ESPN roster whose normalised name matches NO row of
    ANY `players_*.csv` of that league (any season, any club). A name that is merely
    CLOSE to a stats name (two shared tokens, or same surname + same first three
    letters of the first name) is treated as having a stats row: a duplicate would
    steal share from the real player, so doubt refuses to add.
  * rate: the league's median per-90 rates for the player's position bucket
    (G/D/M/F), over the league's sim rows with >= 450 minutes; a bucket with fewer
    than 5 such rows takes the league outfield median.
  * minutes: `expected_minutes_share` 0.10. A confirmed lineup acts through the
    EXISTING starter path in `build_usage_profiles`, unchanged.
  * team totals unchanged: the rows are APPENDED to the squad, and
    `build_usage_profiles` normalises shares across the squad, so their mass comes
    out of the listed teammates rather than being added.

OFF unless `SYNDICATE_SOCCER_ROSTER_ONLY_PLAYERS` is set. Absent = off, so a host
that never set it builds byte-identical artifacts.
"""

from __future__ import annotations

import os
import re
from statistics import median
from typing import Any, Iterable

from syndicate.features.soccer.features.lineups import _norm_player_name

ENV_FLAG = "SYNDICATE_SOCCER_ROSTER_ONLY_PLAYERS"
#: Every added player's expected minutes share (pre-registered).
ROSTER_ONLY_MINUTES_SHARE = 0.10
#: Rows below this many minutes do not define a positional median (five full matches).
PRIOR_MIN_MINUTES = 450.0
#: A position bucket with fewer qualifying rows falls back to the league outfield median.
PRIOR_MIN_ROWS = 5
#: The rate fields the engine reads (`build_usage_profiles`), carried on every added row.
PRIOR_FIELDS = ("shots_per90", "xg_per90", "xa_per90", "goals_per90", "assists_per90")
#: The `source` tag on an added row, so an artifact and the squad audit can count them.
SOURCE_TAG = "espn_roster_positional_prior"
SEASON_EVIDENCE = "roster_only"


def enabled() -> bool:
    return str(os.environ.get(ENV_FLAG) or "").strip().lower() in {"1", "true", "on", "yes"}


_ASA_CODES = {"GK": "G", "CB": "D", "FB": "D", "DM": "M", "CM": "M", "AM": "M", "W": "F", "ST": "F"}
_UNDERSTAT_CODES = {"GK": "G", "D": "D", "M": "M", "F": "F"}


def position_bucket(position: Any) -> str:
    """G / D / M / F, or "?" when the source says nothing usable.

    Three spellings reach here: Understat codes ("F M S", "GK"), ASA codes ("CB",
    "W") and ESPN prose ("Center Left Defender", "Substitute", "Forward")."""
    text = str(position or "").strip()
    if not text:
        return "?"
    upper = text.upper()
    if upper in _ASA_CODES:
        return _ASA_CODES[upper]
    first = upper.split()[0]
    if first in _UNDERSTAT_CODES and all(token in {"GK", "D", "M", "F", "S"} for token in upper.split()):
        return _UNDERSTAT_CODES[first]
    lower = text.lower()
    if "goalkeeper" in lower or lower in {"g", "gk"}:
        return "G"
    if "defender" in lower or "back" in lower or "sweeper" in lower or lower == "d":
        return "D"
    if "midfielder" in lower or lower == "m":
        return "M"
    if "forward" in lower or "striker" in lower or "wing" in lower or lower == "f":
        return "F"
    return "?"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _minutes(row: dict[str, Any]) -> float:
    for key in ("minutes", "minutes_played"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return 0.0


def positional_priors(player_rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Per bucket, the unweighted median of each rate over rows with >= 450 minutes.

    Always returns all four buckets plus "outfield". A bucket with fewer than
    PRIOR_MIN_ROWS qualifying rows is the outfield median. "G" falls back to zeros
    rather than an outfield rate: a keeper's attacking rates are ~0, and borrowing
    an outfield median would hand a backup keeper a striker's share."""
    by_bucket: dict[str, list[dict[str, Any]]] = {}
    for row in player_rows:
        if _minutes(row) < PRIOR_MIN_MINUTES:
            continue
        by_bucket.setdefault(position_bucket(row.get("position")), []).append(row)

    def medians(rows: list[dict[str, Any]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for field in PRIOR_FIELDS:
            values = [v for v in (_number(r.get(field)) for r in rows) if v is not None]
            out[field] = float(median(values)) if values else 0.0
        return out

    outfield_rows = [row for bucket, rows in by_bucket.items() if bucket != "G" for row in rows]
    outfield = medians(outfield_rows)
    priors = {"outfield": outfield}
    for bucket in ("D", "M", "F"):
        rows = by_bucket.get(bucket, [])
        priors[bucket] = medians(rows) if len(rows) >= PRIOR_MIN_ROWS else dict(outfield)
    keepers = by_bucket.get("G", [])
    priors["G"] = medians(keepers) if len(keepers) >= PRIOR_MIN_ROWS else {field: 0.0 for field in PRIOR_FIELDS}
    priors["?"] = dict(outfield)
    return priors


def _tokens(name: str) -> list[str]:
    return [token for token in re.split(r"[^a-z']+", name) if token]


def _close_match(key: str, stats_keys: set[str], by_surname: dict[str, list[str]]) -> bool:
    """True when the roster name is plausibly a stats name spelled differently."""
    tokens = _tokens(key)
    if not tokens:
        return False
    token_set = set(tokens)
    for candidate in by_surname.get(tokens[-1], []):
        other = _tokens(candidate)
        if other and other[0][:3] == tokens[0][:3]:
            return True
    for candidate in stats_keys:
        other = set(_tokens(candidate))
        if len(token_set & other) >= 2:
            return True
        # One-word stats names ("Gabriel", "Rodri") match a roster name that contains them.
        if len(other) == 1 and other <= token_set and len(next(iter(other))) >= 4:
            return True
    return False


def roster_only_rows(
    roster_rows: Iterable[dict[str, Any]],
    stats_names: Iterable[str],
    sim_player_rows: list[dict[str, Any]],
    *,
    league: str = "",
    teams: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The rows to APPEND to the squad, and an audit of what was decided.

    `roster_rows`: the league's ESPN roster rows (`team`, `player_id`, `player_name`,
    `position`). `stats_names`: every player name in every `players_*.csv` of the
    league, before any dedupe or departed filter. `sim_player_rows`: the rows the sim
    already uses, which define the positional prior. `teams`, when given, restricts
    the additions to those clubs' roster rows (exact roster team string)."""
    stats_keys = {_norm_player_name(name) for name in stats_names if str(name or "").strip()}
    stats_keys.discard("")
    by_surname: dict[str, list[str]] = {}
    for key in stats_keys:
        tokens = _tokens(key)
        if tokens and len(tokens[-1]) >= 3:
            by_surname.setdefault(tokens[-1], []).append(key)
    priors = positional_priors(sim_player_rows)
    wanted = None if teams is None else {str(team) for team in teams}

    added: list[dict[str, Any]] = []
    audit = {"roster_rows": 0, "with_stats_row": 0, "close_name_refused": 0, "added": 0, "by_bucket": {}}
    seen: set[tuple[str, str]] = set()
    for row in roster_rows:
        team = str(row.get("team") or "").strip()
        name = str(row.get("player_name") or "").strip()
        if not team or not name or (wanted is not None and team not in wanted):
            continue
        key = _norm_player_name(name)
        if (team, key) in seen:
            continue
        seen.add((team, key))
        audit["roster_rows"] += 1
        if key in stats_keys:
            audit["with_stats_row"] += 1
            continue
        if _close_match(key, stats_keys, by_surname):
            audit["close_name_refused"] += 1
            continue
        bucket = position_bucket(row.get("position") or row.get("position_abbreviation"))
        rates = priors.get(bucket) or priors["outfield"]
        added.append(
            {
                "league": league,
                "player_id": f"espn_roster_{row.get('player_id') or key.replace(' ', '_')}",
                "player_name": name,
                "team": team,
                "position": str(row.get("position") or ""),
                "is_goalkeeper": bucket == "G",
                "expected_minutes_share": ROSTER_ONLY_MINUTES_SHARE,
                **{field: round(rates[field], 4) for field in PRIOR_FIELDS},
                "source": SOURCE_TAG,
                "season_evidence": SEASON_EVIDENCE,
            }
        )
        audit["added"] += 1
        audit["by_bucket"][bucket] = audit["by_bucket"].get(bucket, 0) + 1
    audit["priors"] = {bucket: {k: round(v, 4) for k, v in rates.items()} for bucket, rates in priors.items()}
    return added, audit


__all__ = [
    "ENV_FLAG",
    "ROSTER_ONLY_MINUTES_SHARE",
    "SEASON_EVIDENCE",
    "SOURCE_TAG",
    "enabled",
    "position_bucket",
    "positional_priors",
    "roster_only_rows",
]
