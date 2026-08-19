"""Per-team EVEN-STRENGTH faceoff win-rate index from the `playbyplay` endpoint.

WHY THIS EXISTS. `engine.py`'s faceoff-driven shot-share adjustment
(`_faceoff_multipliers`) is gated `faceoff_ev_only=True` -- it is ONLY applied
during even-strength segments. But the input feeding it, `TeamRates.faceoff_win_pct`
(`historical_truth/team_game_rates.py`), is an ALL-SITUATIONS blend (every faceoff
the team took, PP/PK/EV together) -- a real mismatch between what the mechanism
claims to model and what the data it reads actually measures. This module closes
that gap: a genuinely EV-SPECIFIC per-team signal, parsed from the SAME
`playbyplay` cache the block/shot-index work already bulk-fetched (no new fetch).

WHY AN INDEX (ratio to league average), NOT A RAW PERCENTAGE. Consistent with
every other per-team signal this session built (`block_rate_index`,
`pp_shot_index`/`pk_shot_index_allowed`) -- a ratio centered at 1.0 is easy to
sanity-check (mean should land near 1.0) and easy to reason about when layering a
new signal on top of an existing mechanism. `engine.py` converts the index back to
an effective win percentage (`0.5 * index`, clamped) at the point of use, since
`_faceoff_multipliers` itself operates on percentages, not indices.

STRENGTH STATE FROM `situationCode`, NOT GUESSED. Each `playbyplay` faceoff event
carries a 4-digit `situationCode`: `[awayGoalieInNet][awaySkaters][homeSkaters]
[homeGoalieInNet]` (e.g. `"1551"` = 5v5 EV, `"1451"` = home team on the power play,
`"1541"` = away team on the power play -- confirmed against a real cached game,
not assumed from documentation). EVEN STRENGTH is defined as `away_skaters ==
home_skaters` (covers 5v5/4v4/3v3 alike, the standard hockey definition), matching
the same "not a power play for either side" condition `engine.py`'s own
`seg_is_home_pp`/`seg_is_away_pp` flags represent -- this module's ground truth and
the engine's own segment classification are conceptually the same split, just
computed from real historical data here instead of simulated on the fly there.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence


def _skaters_from_situation_code(code: object) -> Optional[tuple]:
    """`(away_skaters, home_skaters)` from a 4-digit `situationCode` string, or
    `None` if the code is missing/malformed (never raises)."""
    text = str(code or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    return int(text[1]), int(text[2])


@dataclass(frozen=True)
class GameFaceoffEvRecord:
    """One finished game's EVEN-STRENGTH faceoff counts, parsed from a
    `playbyplay` payload."""

    game_id: str
    home_abbr: str
    away_abbr: str
    home_ev_wins: int
    away_ev_wins: int

    @property
    def ev_total(self) -> int:
        return self.home_ev_wins + self.away_ev_wins


def parse_playbyplay_faceoffs_ev(payload: Dict) -> Optional[GameFaceoffEvRecord]:
    """Parse one `playbyplay` payload into a :class:`GameFaceoffEvRecord`, EVEN-
    STRENGTH faceoffs only. Returns `None` if the payload is missing team info or
    carries no `plays` list -- never raises. A game with zero EV faceoffs (should
    not happen in practice, but data is data) returns a record with `ev_total==0`
    rather than `None`, so the caller's own floor decides whether to trust it."""
    if not isinstance(payload, dict):
        return None
    home_team = payload.get("homeTeam") or {}
    away_team = payload.get("awayTeam") or {}
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_abbr = str(home_team.get("abbrev") or "").upper()
    away_abbr = str(away_team.get("abbrev") or "").upper()
    if home_id is None or away_id is None or not home_abbr or not away_abbr:
        return None
    plays = payload.get("plays")
    if not isinstance(plays, list):
        return None

    home_wins = away_wins = 0
    for play in plays:
        if not isinstance(play, dict) or play.get("typeDescKey") != "faceoff":
            continue
        skaters = _skaters_from_situation_code(play.get("situationCode"))
        if skaters is None or skaters[0] != skaters[1]:
            continue  # not even strength (or malformed code) -- skip, don't guess
        details = play.get("details") or {}
        owner = details.get("eventOwnerTeamId")
        if owner == home_id:
            home_wins += 1
        elif owner == away_id:
            away_wins += 1
        # else: owner unresolved -- skip rather than misattribute

    return GameFaceoffEvRecord(
        game_id=str(payload.get("id") or ""),
        home_abbr=home_abbr, away_abbr=away_abbr,
        home_ev_wins=home_wins, away_ev_wins=away_wins,
    )


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


# Same small-sample discipline as `boxscore_block_rate`/`boxscore_shot_strength`.
MIN_GAMES_FOR_FACEOFF_INDEX = 10
DEFAULT_FACEOFF_EV_INDEX = 1.0


@dataclass(frozen=True)
class TeamFaceoffEvIndex:
    """Per-team EVEN-STRENGTH faceoff win-rate tendency, normalized against the
    league-wide EV win rate -- 1.0 = league average; >1.0 = wins EV draws more
    than average; <1.0 = less. `engine.py` converts this back to an effective win
    percentage (`0.5 * index`) at the point of use."""

    team: str
    index: float
    games: int
    ev_wins: int
    ev_total: int


def compute_team_faceoff_ev_index(records: Sequence[GameFaceoffEvRecord]) -> Dict[str, TeamFaceoffEvIndex]:
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {"games": 0, "ev_wins": 0, "ev_total": 0})

    for r in records:
        h = _touch(r.home_abbr)
        a = _touch(r.away_abbr)
        h["games"] += 1
        a["games"] += 1
        h["ev_wins"] += r.home_ev_wins
        a["ev_wins"] += r.away_ev_wins
        h["ev_total"] += r.ev_total
        a["ev_total"] += r.ev_total

    league_wins = sum(v["ev_wins"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_INDEX)
    league_total = sum(v["ev_total"] for v in acc.values() if v["games"] >= MIN_GAMES_FOR_FACEOFF_INDEX)
    league_rate = _safe_div(league_wins, league_total)

    out: Dict[str, TeamFaceoffEvIndex] = {}
    for team, row in acc.items():
        games = row["games"]
        index = DEFAULT_FACEOFF_EV_INDEX
        if games >= MIN_GAMES_FOR_FACEOFF_INDEX and league_rate > 0:
            team_rate = _safe_div(row["ev_wins"], row["ev_total"])
            index = round(team_rate / league_rate, 4)
        out[team] = TeamFaceoffEvIndex(
            team=team, index=index, games=games,
            ev_wins=row["ev_wins"], ev_total=row["ev_total"],
        )
    return out
