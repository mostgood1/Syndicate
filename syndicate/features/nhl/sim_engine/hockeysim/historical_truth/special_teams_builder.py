"""Team special-teams rates (`pp_pct`, `pk_pct`, `committed_per_game`) from real settled games.

`HockeyTeamFeatures.special_teams` — the ACTUAL dict `engine.py` consumes for these three keys via
`st_home`/`st_away` (`engine.py:677-678,973-980`) — was CONSUMED and had no producer, always `{}`,
so every team ran through the boxscore/props engine's PP/PK goal-rate adjustment at the same
league-average fallback (`{"pp_pct": 0.2, "pk_pct": 0.8, "drawn_per_game": 3.0, "committed_per_game": 3.0}`,
`engine.py:667-668`).

NOTE on a DIFFERENT, separate dead parameter: `engine.py` ALSO reads a `special_teams_cal` dict for
seven OTHER keys (`pp_shot_multiplier`, `pk_shot_multiplier`, `pp_goal_multiplier`,
`pk_goal_multiplier`, `blocks_ev_rate`, `blocks_pk_rate`, `blocks_pp_def_rate`). That parameter is
plumbed end-to-end (`runtime.py` -> `engine.py`, twice) but **no caller anywhere passes it a
value** — it is not fed by `HockeyTeamFeatures.special_teams` or anything else. This module does
NOT address that gap (see `docs/ai_context/hockeysim_engine_reference.md` for the correction and
why the two were conflated in an earlier pass); it addresses only the three keys the `special_teams`
dict genuinely reaches.

Pure function, no I/O — mirrors `elo_builder.py`'s shape. The producer script
(`scripts/build_nhl_special_teams_artifact.py`) does the file I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from .contracts import HistoricalGameRecord

DEFAULT_PP_PCT = 0.2
DEFAULT_PK_PCT = 0.8
DEFAULT_COMMITTED_PER_GAME = 3.0
# A team with very few power-play opportunities in the sample produces a noisy pp_pct estimate
# (e.g. 1-for-2 reads as a 50% power play, which is not a real signal). Below this many
# opportunities, fall back to the league-average default rather than publish a noisy rate.
MIN_OPPORTUNITIES_FOR_RATE = 15
# Recency-weighted committed rate `[2026-10-08, lane nhl-pp-time, "C20"]`: the team's own games weighted with a
# half-life of RECENT_HALF_LIFE_GAMES, times the league's trailing-RECENT_LEAGUE_DAYS-day committed level over its
# season level. Offline on 2025-26 (official PP time, 1,362 held-out team-games): sim/real PP-time ratio 1.061
# (season-to-date) -> 1.012. Read by the engine only under pp_time_model="per_minor" + pp_rate_source="recent".
RECENT_HALF_LIFE_GAMES = 20.0
RECENT_LEAGUE_DAYS = 20
RECENT_MIN_GAMES = 5


@dataclass(frozen=True)
class TeamSpecialTeamsRates:
    team: str
    pp_pct: float
    pk_pct: float
    committed_per_game: float
    games: int
    pp_opportunities: int
    pp_goals: int
    pk_opportunities: int
    pp_goals_against: int
    committed_per_game_recent: Optional[float] = None
    recent_asof: Optional[str] = None


def compute_special_teams_rates(
    games: Sequence[HistoricalGameRecord],
) -> Dict[str, TeamSpecialTeamsRates]:
    """Aggregate settled games into one rate row per team.

    ``pp_pct`` = team's own power-play goals / the opponent's committed minor penalties (the
    team's PP opportunities). ``pk_pct`` = 1 - (opponent's PP goals scored against this team /
    this team's own committed minor penalties, i.e. its PK opportunities) -- the standard
    "penalty-kill percentage" definition. ``committed_per_game`` = this team's own committed
    minors per game played, used by the engine to estimate how much PP time the OPPONENT gets.
    """
    acc: Dict[str, Dict[str, int]] = {}

    def _touch(team: str) -> Dict[str, int]:
        return acc.setdefault(team, {
            "games": 0, "pp_opp": 0, "pp_goals": 0, "pk_opp": 0, "pp_ga": 0, "committed": 0,
        })

    for g in games:
        h = _touch(g.home_abbr)
        a = _touch(g.away_abbr)
        h["games"] += 1
        a["games"] += 1
        # Home's PP opportunities come from AWAY's committed penalties, and vice versa.
        h["pp_opp"] += g.penalties_committed_away
        a["pp_opp"] += g.penalties_committed_home
        h["pp_goals"] += g.pp_goals_home
        a["pp_goals"] += g.pp_goals_away
        # Home's PK opportunities come from HOME's own committed penalties (home goes shorthanded).
        h["pk_opp"] += g.penalties_committed_home
        a["pk_opp"] += g.penalties_committed_away
        # Goals scored AGAINST a team while it is killing = the opponent's PP goals in that game.
        h["pp_ga"] += g.pp_goals_away
        a["pp_ga"] += g.pp_goals_home
        h["committed"] += g.penalties_committed_home
        a["committed"] += g.penalties_committed_away

    recent, asof = _recent_committed(games)
    out: Dict[str, TeamSpecialTeamsRates] = {}
    for team, row in acc.items():
        games_n = row["games"]
        pp_pct = (row["pp_goals"] / row["pp_opp"]) if row["pp_opp"] >= MIN_OPPORTUNITIES_FOR_RATE else DEFAULT_PP_PCT
        pk_pct = (
            1.0 - (row["pp_ga"] / row["pk_opp"])
        ) if row["pk_opp"] >= MIN_OPPORTUNITIES_FOR_RATE else DEFAULT_PK_PCT
        committed_per_game = (row["committed"] / games_n) if games_n else DEFAULT_COMMITTED_PER_GAME
        out[team] = TeamSpecialTeamsRates(
            team=team,
            pp_pct=round(pp_pct, 4),
            pk_pct=round(pk_pct, 4),
            committed_per_game=round(committed_per_game, 4),
            games=games_n,
            pp_opportunities=row["pp_opp"],
            pp_goals=row["pp_goals"],
            pk_opportunities=row["pk_opp"],
            pp_goals_against=row["pp_ga"],
            committed_per_game_recent=recent.get(team),
            recent_asof=asof,
        )
    return out


def _recent_committed(games: Sequence[HistoricalGameRecord]) -> Tuple[Dict[str, float], Optional[str]]:
    """``({team: recency-weighted committed minors per game}, last game date)``; see RECENT_HALF_LIFE_GAMES."""
    per_team: Dict[str, List[Tuple[str, int]]] = {}
    league: List[Tuple[str, int]] = []
    for g in games:
        d = str(g.date or "")[:10]
        if not d:
            continue
        for team, c in ((g.home_abbr, g.penalties_committed_home), (g.away_abbr, g.penalties_committed_away)):
            per_team.setdefault(team, []).append((d, int(c)))
            league.append((d, int(c)))
    if not league:
        return {}, None
    asof = max(d for d, _ in league)
    cutoff = (_date.fromisoformat(asof) - timedelta(days=RECENT_LEAGUE_DAYS)).isoformat()
    recent_l = [c for d, c in league if d >= cutoff]
    season_mean = sum(c for _, c in league) / len(league)
    ratio = (sum(recent_l) / len(recent_l)) / season_mean if recent_l and season_mean > 0 else 1.0
    out: Dict[str, float] = {}
    for team, rows in per_team.items():
        rows.sort()
        if len(rows) < RECENT_MIN_GAMES:
            continue
        n = len(rows)
        w = [0.5 ** ((n - 1 - i) / RECENT_HALF_LIFE_GAMES) for i in range(n)]
        ewm = sum(wi * c for wi, (_, c) in zip(w, rows)) / sum(w)
        out[team] = round(ewm * ratio, 4)
    return out, asof
