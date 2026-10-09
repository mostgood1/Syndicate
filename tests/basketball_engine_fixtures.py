"""Synthetic inputs for the basketball possession engine (lane basketball-native-engine).

These shake out the PORT. They are not evidence about production. The parity
claim rests on the recorded production corpus
(scripts/record_basketball_engine_corpus.py), and these fixtures cannot
substitute for it (model engine standard §6).

The frames carry every column the engine reads, with plausible per-minute
rates, so every branch is exercised: lineup pools, targets, team adjustments,
quarter models, blowouts and overtime.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

_COLS_PM = {
    # col: (mean per minute, spread)
    "_prior_fga_pm": (0.36, 0.14),
    "_prior_threes_att_pm": (0.13, 0.08),
    "_prior_fta_pm": (0.10, 0.06),
    "_prior_tov_pm": (0.05, 0.02),
    "_prior_pf_pm": (0.07, 0.02),
    "_prior_reb_pm": (0.17, 0.08),
    "_prior_ast_pm": (0.10, 0.06),
    "_prior_stl_pm": (0.03, 0.012),
    "_prior_blk_pm": (0.02, 0.02),
}


def synthetic_players(rng: np.random.Generator, *, n: int, team_minutes: float, tag: str) -> pd.DataFrame:
    mins = np.sort(rng.gamma(3.0, 1.0, size=n))[::-1]
    mins = mins / mins.sum() * team_minutes
    rows: list[dict[str, Any]] = []
    for i in range(n):
        row: dict[str, Any] = {"player_name": f"{tag} Player {i:02d}", "_sim_min": float(mins[i])}
        for col, (mu, sd) in _COLS_PM.items():
            row[col] = float(max(0.0, rng.normal(mu, sd)))
        row["_prior_fgm_pm"] = row["_prior_fga_pm"] * float(rng.uniform(0.38, 0.58))
        row["_prior_threes_pm"] = row["_prior_threes_att_pm"] * float(rng.uniform(0.28, 0.42))
        row["_prior_ftm_pm"] = row["_prior_fta_pm"] * float(rng.uniform(0.62, 0.92))
        row["pred_pts"] = float(mins[i] * (2 * row["_prior_fgm_pm"] + row["_prior_threes_pm"] + row["_prior_ftm_pm"]))
        if rng.random() < 0.5:
            row["is_starter"] = bool(i < 5)
        else:
            row["starter_prob"] = float(np.clip(1.0 - i / 7.0, 0.0, 1.0))
        rows.append(row)
    df = pd.DataFrame(rows)
    if rng.random() < 0.15:  # a missing prior column: the engine's neutral defaults must agree too
        df = df.drop(columns=[str(rng.choice(list(_COLS_PM)))])
    return df


def synthetic_game_kwargs(rng: np.random.Generator, *, league: str, entrypoint: str) -> dict[str, Any]:
    team_minutes = 240.0 if league == "nba" else 200.0
    q_mu = 28.0 if league == "nba" else 20.5
    hp = synthetic_players(rng, n=int(rng.integers(9, 15)), team_minutes=team_minutes, tag="H")
    ap = synthetic_players(rng, n=int(rng.integers(9, 15)), team_minutes=team_minutes, tag="A")
    kwargs: dict[str, Any] = {"home_players": hp, "away_players": ap}
    if rng.random() < 0.75:
        # Production passes Syndicate's EventSimConfigLocal, re-paced per game by the vendored smart_sim.
        from dataclasses import replace

        from syndicate.features.shared.basketball_props_smart_sim import EventSimConfigLocal

        pace = float(rng.normal(99.0 if league == "nba" else 80.0, 3.0))
        kwargs["cfg"] = replace(EventSimConfigLocal(), possessions_per_game=pace)

    def pool(df: pd.DataFrame):
        if rng.random() < 0.4:
            return None, None
        n = len(df)
        lus = [sorted(rng.choice(n, size=5, replace=False).tolist()) for _ in range(int(rng.integers(3, 12)))]
        if rng.random() < 0.2:
            lus.append([0, 1, 2, 3])  # an invalid unit the pool must skip
        return lus, rng.uniform(0.1, 3.0, size=len(lus))

    kwargs["home_lineups"], kwargs["home_lineup_weights"] = pool(hp)
    kwargs["away_lineups"], kwargs["away_lineup_weights"] = pool(ap)
    if rng.random() < 0.8:
        kwargs["home_team_adj"] = {"eff_mult": float(rng.uniform(0.9, 1.1)), "tov_mult": float(rng.uniform(0.9, 1.1)), "foul_mult": float(rng.uniform(0.9, 1.1)), "oreb_mult": float(rng.uniform(0.85, 1.2))}
        kwargs["away_team_adj"] = {"eff_mult": float(rng.uniform(0.9, 1.1))}
    if entrypoint == "simulate_event_level_boxscore":
        kwargs["home_q_pts"] = [int(rng.normal(q_mu, 5)) for _ in range(4)]
        kwargs["away_q_pts"] = [int(rng.normal(q_mu, 5)) for _ in range(4)]
        return kwargs
    if rng.random() < 0.85:
        kwargs["target_home_points"] = float(rng.normal(4 * q_mu, 8))
        kwargs["target_away_points"] = float(rng.normal(4 * q_mu, 8))
    if rng.random() < 0.85:
        kwargs["quarters"] = [
            SimpleNamespace(q=k + 1, home_pts_mu=float(rng.normal(q_mu, 2)), home_pts_sigma=float(rng.uniform(5, 8)),
                            away_pts_mu=float(rng.normal(q_mu, 2)), away_pts_sigma=float(rng.uniform(5, 8)), corr=float(rng.uniform(-0.1, 0.3)))
            for k in range(4)
        ]
    if rng.random() < 0.3:
        # Tilt the game hard so blowout / garbage-time branches run.
        kwargs["target_home_points"] = float(4 * q_mu + 30)
        kwargs["target_away_points"] = float(4 * q_mu - 20)
    return kwargs
