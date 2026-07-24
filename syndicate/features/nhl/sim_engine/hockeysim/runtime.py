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
