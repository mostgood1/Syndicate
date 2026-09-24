"""Public entry point for the ``hockeysim`` engine.

Analogous to ``smartsim2.runtime.run_smartsim2_simulation`` and ``soccersim.runtime``: a thin,
stable façade over the internal ``GameSimulator`` so callers (the Phase-2 adapter, artifact
producers, live-lens resume, tests) never reach into engine internals directly.

``run_hockeysim_game`` runs ONE deterministic game given a seed and returns the terminal
``GameState`` (final score + per-player ``stats``) plus the full event stream. Aggregating many
seeded runs into win/total/period distributions and player-prop projections is the adapter's
job (Phase 2), not the engine's.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .calibration_profile import build_nhl_sim_config
from .engine import GameSimulator, SimConfig
from .models import RateModels
from .state import Event, GameState


def run_hockeysim_game(
    home_name: str,
    away_name: str,
    roster_home: List[Dict],
    roster_away: List[Dict],
    rates: RateModels,
    *,
    lineup_home: Optional[List[Dict]] = None,
    lineup_away: Optional[List[Dict]] = None,
    st_home: Optional[Dict[str, float]] = None,
    st_away: Optional[Dict[str, float]] = None,
    special_teams_cal: Optional[Dict[str, float]] = None,
    profile: Optional[SimConfig] = None,
    seed: Optional[int] = None,
) -> Tuple[GameState, List[Event]]:
    """Simulate a single hockey game.

    - With ``lineup_home``/``lineup_away`` (line-slot / PP-unit / PK-unit rows) the richer
      line-rotation path (``simulate_with_lineups``) runs — this is the production path used by
      the boxscore/props pipeline. Without lineups, the simpler roster-only path is used.
    - ``rates`` supplies per-60 team shot/goal/block/faceoff rates (see ``models.RateModels``).
    - ``profile`` defaults to ``NHL_CALIBRATION_PROFILE``; ``seed`` makes the run reproducible.
    """
    cfg = build_nhl_sim_config(seed=seed, profile=profile)
    simulator = GameSimulator(cfg, rates)
    if lineup_home is not None or lineup_away is not None:
        return simulator.simulate_with_lineups(
            home_name,
            away_name,
            roster_home,
            roster_away,
            lineup_home or [],
            lineup_away or [],
            st_home=st_home,
            st_away=st_away,
            special_teams_cal=special_teams_cal,
        )
    return simulator.simulate(home_name, away_name, roster_home, roster_away)


def run_hockeysim_game_from_state(
    home_name: str,
    away_name: str,
    roster_home: List[Dict],
    roster_away: List[Dict],
    rates: RateModels,
    *,
    period_idx: int,
    seconds_remaining: int,
    home_score: int,
    away_score: int,
    lineup_home: Optional[List[Dict]] = None,
    lineup_away: Optional[List[Dict]] = None,
    st_home: Optional[Dict[str, float]] = None,
    st_away: Optional[Dict[str, float]] = None,
    special_teams_cal: Optional[Dict[str, float]] = None,
    profile: Optional[SimConfig] = None,
    seed: Optional[int] = None,
) -> Tuple[GameState, List[Event]]:
    """Simulate the REMAINDER of a game already in progress.

    The live-lens resume this module's header reserves a place for. It runs the
    same production path as `run_hockeysim_game` -- `simulate_with_lineups` --
    and differs only in that the period loop starts at `period_idx` with
    `seconds_remaining` left on the clock and the score already on the board.

    `period_idx` IS ZERO-BASED, matching the engine's own loop
    (`for pd in range(self.cfg.periods)`), NOT the 1-based period a scoreboard
    shows. First period is 0. The caller converts; getting this wrong resumes a
    whole period early and the answer stays plausible, which is why it is said
    here rather than left to be inferred.

    THE RETURNED SCORE IS FINAL (banked + rest-of-game). Per-player `stats` are
    REST-OF-GAME ONLY -- the banked boxscore is not replayed -- so this must not
    feed a full-game player prop. `live_resim` publishes the moneyline alone.

    LINEUPS ARE REQUIRED IN PRACTICE. Without them the caller falls to the
    roster-only path, which has no line rotation and no score effects, and the
    score effects are precisely what makes a resumed state produce a different
    answer. This signature accepts `None` to match its sibling, and
    `live_resim` refuses rather than silently taking that path.
    """
    cfg = build_nhl_sim_config(seed=seed, profile=profile)
    simulator = GameSimulator(cfg, rates)
    return simulator.simulate_with_lineups(
        home_name,
        away_name,
        roster_home,
        roster_away,
        lineup_home or [],
        lineup_away or [],
        st_home=st_home,
        st_away=st_away,
        special_teams_cal=special_teams_cal,
        resume_period_idx=int(period_idx),
        resume_seconds_remaining=int(seconds_remaining),
        resume_home_score=int(home_score),
        resume_away_score=int(away_score),
    )
