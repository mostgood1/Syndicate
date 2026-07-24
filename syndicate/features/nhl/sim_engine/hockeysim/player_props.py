"""Player-prop projections from repeated boxscore-engine simulations.

Mirrors ``soccersim.player_props`` / the vendor ``props-simulate-boxscores`` +
``props-recommendations`` path. Runs the detailed boxscore engine ``n_sims`` times for one game,
aggregates each run's events into per-player boxscores (``props_boxscore``), and turns the
resulting per-player stat sample distributions into ``HockeyPropProjection`` rows
(``proj_lambda`` = mean intensity, ``p_over``/``p_under`` empirical vs the book line).

Markets: SOG / GOALS / ASSISTS / POINTS / BLOCKS / SAVES — the canonical NHL prop set the
existing ``props_recommendations_{date}.csv`` covers.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .adapters import game_seed
from .contracts import HockeyGameFeatures, HockeyPlayerFeatures, HockeyPropProjection
from .engine import SimConfig
from .models import RateModels, TeamRates
from .props_boxscore import aggregate_events_to_boxscores_fast
from .runtime import run_hockeysim_game

# Market -> index into the fast boxscore row tuple:
# (shots, goals, assists, points, blocks, saves, toi_sec)
_MARKET_STAT_INDEX: Dict[str, int] = {
    "SOG": 0,
    "GOALS": 1,
    "ASSISTS": 2,
    "POINTS": 3,
    "BLOCKS": 4,
    "SAVES": 5,
}

# Which markets apply to which position group.
_SKATER_MARKETS = ("SOG", "GOALS", "ASSISTS", "POINTS", "BLOCKS")
_GOALIE_MARKETS = ("SAVES",)

_DEFAULT_PROP_SIMS = 1000


def _team_rates(team) -> TeamRates:
    return TeamRates(
        shots_per_60=float(team.shots_per_60),
        goals_per_60=float(team.goals_per_60),
        blocks_per_60=float(team.blocks_per_60),
        penalties_per_60=float(team.penalties_per_60),
        faceoff_win_pct=float(team.faceoff_win_pct),
    )


def _starter_goalie_id(players: Tuple[HockeyPlayerFeatures, ...]) -> Optional[int]:
    goalies = [p for p in players if str(p.position).strip().upper() == "G"]
    if not goalies:
        return None
    flagged = [p for p in goalies if p.is_starting_goalie]
    pick = flagged[0] if flagged else max(goalies, key=lambda p: float(p.proj_toi or 0.0))
    return int(pick.player_id)


def build_prop_projections(
    game: HockeyGameFeatures,
    *,
    lines: Optional[Dict[Tuple[int, str], float]] = None,
    n_sims: int = _DEFAULT_PROP_SIMS,
    profile: Optional[SimConfig] = None,
    base_seed: Optional[int] = None,
) -> List[HockeyPropProjection]:
    """Return one projection per (player, applicable market) for a single game.

    ``lines`` optionally maps ``(player_id, market)`` -> book line; when a line is present the
    empirical over/under probabilities are attached. Deterministic given ``base_seed`` (defaults
    to the per-game crc32 seed); each sim uses ``base_seed + i``.
    """
    lines = lines or {}
    rates = RateModels(home=_team_rates(game.home), away=_team_rates(game.away), player_rates={})

    roster_home = [p.roster_row() for p in game.home_players]
    roster_away = [p.roster_row() for p in game.away_players]
    lineup_home = [p.lineup_row() for p in game.home_players]
    lineup_away = [p.lineup_row() for p in game.away_players]
    starter_goalies = {}
    gh = _starter_goalie_id(game.home_players)
    ga = _starter_goalie_id(game.away_players)
    if gh is not None:
        starter_goalies[game.home.name] = gh
    if ga is not None:
        starter_goalies[game.away.name] = ga

    st_home = dict(game.home.special_teams) or None
    st_away = dict(game.away.special_teams) or None

    # player metadata lookup keyed by (team_name, player_id)
    meta: Dict[Tuple[str, int], HockeyPlayerFeatures] = {}
    for p in game.home_players:
        meta[(game.home.name, int(p.player_id))] = p
    for p in game.away_players:
        meta[(game.away.name, int(p.player_id))] = p

    # samples[(team, pid)][market] -> list of per-game totals
    samples: Dict[Tuple[str, int], Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))

    seed0 = int(base_seed) if base_seed is not None else game_seed(game.date, game.game_pk)
    for i in range(int(n_sims)):
        gs, events = run_hockeysim_game(
            game.home.name, game.away.name, roster_home, roster_away, rates,
            lineup_home=lineup_home, lineup_away=lineup_away,
            st_home=st_home, st_away=st_away, profile=profile, seed=seed0 + i,
        )
        box = aggregate_events_to_boxscores_fast(gs, events, starter_goalies)
        for (team, pid, period), row in box.items():
            if int(period) != 0:  # game totals only
                continue
            bucket = samples[(str(team), int(pid))]
            for market, idx in _MARKET_STAT_INDEX.items():
                bucket[market].append(int(row[idx]))

    projections: List[HockeyPropProjection] = []
    for (team, pid), by_market in samples.items():
        pf = meta.get((team, int(pid)))
        if pf is None:
            continue
        pos = str(pf.position).strip().upper()
        applicable = _GOALIE_MARKETS if pos == "G" else _SKATER_MARKETS
        opp = game.away.name if team == game.home.name else game.home.name
        for market in applicable:
            vals = by_market.get(market) or []
            if not vals:
                continue
            proj = sum(vals) / len(vals)
            line = lines.get((int(pid), market))
            p_over = p_under = None
            if line is not None:
                ln = float(line)
                n = len(vals)
                p_over = sum(1 for v in vals if v > ln) / n
                p_under = sum(1 for v in vals if v < ln) / n
            projections.append(
                HockeyPropProjection(
                    date=game.date,
                    player_id=int(pid),
                    player=pf.full_name,
                    team=team,
                    opp=opp,
                    market=market,
                    proj_lambda=round(float(proj), 4),
                    proj=round(float(proj), 4),
                    line=(float(line) if line is not None else None),
                    p_over=(round(p_over, 4) if p_over is not None else None),
                    p_under=(round(p_under, 4) if p_under is not None else None),
                )
            )
    return projections
