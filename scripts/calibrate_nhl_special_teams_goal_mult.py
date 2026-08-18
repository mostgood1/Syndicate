#!/usr/bin/env python3
"""Calibrate `pp_goal_cal_mult` / `pk_goal_cal_mult` against real settled-game truth.

`docs/ai_context/hockeysim_engine_reference.md` §2c wired `special_teams_cal` reachable but
deliberately left its values at the old neutral defaults (1.0) -- a wiring fix, not a calibration.
This script does the calibration: run the REAL engine (not a formula approximation) over many
simulated games using REAL per-team `pp_pct`/`pk_pct` (from `team_special_teams_latest.csv`) and
REAL league-average base rates (from the truth snapshot), measure the simulated `pp_goal_share`/
`sh_goal_share`, and search for the multiplier that makes them match the real truth values.

WHY NOT ANALYTICAL. The PP/PK goal-conversion multiplier interacts with the PP/PK SHOT-volume
multiplier (`SimConfig.pp_shots_mult=1.4`/`pk_shots_mult=0.7`, already real and non-neutral) and a
clamp (`p_goal_home = min(0.45, ...)`), inside a possession/segment Monte Carlo loop -- not a closed
form. Simulating with the real engine is the only faithful measurement.

WHY `pk_goal_cal_mult` GETS ITS OWN TARGET (`sh_goal_share`), NOT `pp_goal_share` REUSED.
`cal_pp_gl_mult` scales the ATTACKING team's goal rate while on the power play (the primary PP-goal
event); `cal_pk_gl_mult` scales the DEFENDING (shorthanded) team's goal rate during that SAME
segment -- i.e. shorthanded goals, a distinct and much rarer event. Calibrating both against
`pp_goal_share` would leave the shorthanded-goal rate unmeasured. `sh_goal_share` (this session's
truth-parser extension, `historical_truth/contracts.py` `sh_goals_home/away`) is what closes that.

Usage:
  py -3 scripts/calibrate_nhl_special_teams_goal_mult.py
  py -3 scripts/calibrate_nhl_special_teams_goal_mult.py --pairings 60 --sims-per-pairing 40
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.snapshot_builder import (  # noqa: E402
    build_truth_snapshot,
)
from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels, TeamRates  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.runtime import run_hockeysim_game  # noqa: E402


def _roster(team: str, base_pid: int) -> List[Dict]:
    """Same synthetic-roster shape `tests/test_hockeysim_engine.py` uses -- only AGGREGATE
    team-level shot/goal counts matter for this calibration, not per-player attribution, so a
    synthetic roster is a faithful substrate (no per-game lineup data exists for most of the
    1,312-game truth cache -- see the reference doc §7)."""
    rows: List[Dict] = []
    pid = base_pid
    for i in range(12):
        rows.append({"player_id": pid, "full_name": f"{team} F{i+1}", "position": "F",
                     "proj_toi": 20.0 - i * 0.9})
        pid += 1
    for i in range(6):
        rows.append({"player_id": pid, "full_name": f"{team} D{i+1}", "position": "D",
                     "proj_toi": 22.0 - i * 2.0})
        pid += 1
    rows.append({"player_id": pid, "full_name": f"{team} G1", "position": "G", "proj_toi": 60.0})
    return rows


def _load_special_teams() -> Dict[str, Dict[str, float]]:
    path = REPO / "data" / "nhl_source" / "data" / "processed" / "team_special_teams_latest.csv"
    if not path.exists():
        print(f"REFUSED: {path} does not exist -- run scripts/build_nhl_special_teams_artifact.py first", file=sys.stderr)
        sys.exit(1)
    import csv
    out: Dict[str, Dict[str, float]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["abbr"]] = {"pp_pct": float(row["pp_pct"]), "pk_pct": float(row["pk_pct"]),
                                 "committed_per_game": float(row["committed_per_game"])}
    return out


def _simulate_goal_shares(
    team_st: Dict[str, Dict[str, float]],
    league_goals_per_60: float,
    league_shots_per_60: float,
    *,
    pp_goal_cal_mult: float,
    pk_goal_cal_mult: float,
    n_pairings: int,
    sims_per_pairing: int,
    seed: int,
) -> Tuple[float, float, int]:
    """Run the real engine over `n_pairings` team matchups, `sims_per_pairing` seeds each.

    Every team uses the SAME league-average `shots_per_60`/`goals_per_60` (team-specific rates
    aren't populated yet -- `hockeysim_engine_reference.md` §5) so this isolates exactly the
    special-teams goal-rate effect, not a confound from unrelated team-strength variation.
    Returns (simulated pp_goal_share, simulated sh_goal_share, total goals observed).
    """
    rng = random.Random(seed)
    teams = sorted(team_st)
    rates = RateModels(
        home=TeamRates(shots_per_60=league_shots_per_60, goals_per_60=league_goals_per_60,
                       blocks_per_60=12.0, penalties_per_60=3.0, faceoff_win_pct=0.5),
        away=TeamRates(shots_per_60=league_shots_per_60, goals_per_60=league_goals_per_60,
                       blocks_per_60=12.0, penalties_per_60=3.0, faceoff_win_pct=0.5),
        player_rates={},
    )
    cfg = build_nhl_sim_config(overrides={
        "pp_goal_cal_mult": pp_goal_cal_mult, "pk_goal_cal_mult": pk_goal_cal_mult,
    })
    cal = {"pp_shot_multiplier": cfg.pp_shot_cal_mult, "pk_shot_multiplier": cfg.pk_shot_cal_mult,
           "pp_goal_multiplier": cfg.pp_goal_cal_mult, "pk_goal_multiplier": cfg.pk_goal_cal_mult,
           "blocks_ev_rate": cfg.block_rate_ev, "blocks_pk_rate": cfg.block_rate_pk,
           "blocks_pp_def_rate": cfg.block_rate_pp_def}

    total_goals = pp_goals = sh_goals = 0
    for _ in range(n_pairings):
        home, away = rng.sample(teams, 2)
        st_home = team_st[home]
        st_away = team_st[away]
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        for s in range(sims_per_pairing):
            gs, events = run_hockeysim_game(
                "HOME", "AWAY", rh, ra, rates,
                lineup_home=lineup_h, lineup_away=lineup_a,
                st_home=st_home, st_away=st_away, special_teams_cal=cal,
                profile=cfg, seed=rng.randint(0, 2**31 - 1),
            )
            for e in events:
                if e.kind != "goal":
                    continue
                total_goals += 1
                # The SIMULATED event stream's own strength vocabulary (engine.py:1043-1044) is
                # "PP"/"PK"/"EV" (uppercase) -- NOT the real landing feed's "pp"/"sh"/"ev". Here
                # "PK" labels a goal scored BY the team that was shorthanded in that segment, i.e.
                # a shorthanded goal -- the engine's own naming, matched exactly, not re-derived.
                strength = str((e.meta or {}).get("strength") or "").upper()
                if strength == "PP":
                    pp_goals += 1
                elif strength == "PK":
                    sh_goals += 1
    pp_share = pp_goals / total_goals if total_goals else 0.0
    sh_share = sh_goals / total_goals if total_goals else 0.0
    return pp_share, sh_share, total_goals


def _search_multiplier(
    label: str, target: float, get_share, *, lo: float = 0.3, hi: float = 3.0, iters: int = 5,
) -> float:
    """Proportional-correction search: the goal-rate multiplier enters ~linearly (pre-clamp), so
    `mult *= target / measured` converges in a few steps. Clamped to [lo, hi] to avoid the engine's
    own p_goal clamps (0.01..0.45) making the search meaningless."""
    mult = 1.0
    for i in range(iters):
        measured = get_share(mult)
        if measured <= 0:
            print(f"  {label} iter {i}: measured=0 at mult={mult:.4f} -- cannot correct proportionally, stopping")
            break
        new_mult = max(lo, min(hi, mult * (target / measured)))
        print(f"  {label} iter {i}: mult={mult:.4f} -> measured={measured:.4f} (target {target:.4f}) -> next={new_mult:.4f}")
        if abs(new_mult - mult) < 1e-4:
            mult = new_mult
            break
        mult = new_mult
    return mult


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairings", type=int, default=40)
    ap.add_argument("--sims-per-pairing", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--iters", type=int, default=5)
    args = ap.parse_args()

    team_st = _load_special_teams()
    print(f"loaded special_teams rates for {len(team_st)} teams")

    loader = NhlStatsWebTruthLoader(offline=True)
    games = [g for g in loader.load_from_cache() if int(g.game_type) == 2]
    if not games:
        print("REFUSED: no cached truth games", file=sys.stderr)
        return 1
    snap = build_truth_snapshot(games)
    m = snap.metrics
    print(f"truth: {snap.n_games} games, pp_goal_share={m.pp_goal_share:.4f}, sh_goal_share={m.sh_goal_share:.4f}")
    league_goals_per_60 = m.goals_per_game / 2.0
    league_shots_per_60 = m.shots_per_game / 2.0
    print(f"league-average per-team rates: goals_per_60={league_goals_per_60:.4f} shots_per_60={league_shots_per_60:.4f}")

    print("\n--- calibrating pp_goal_cal_mult against pp_goal_share ---")
    pp_mult = _search_multiplier(
        "pp_goal_cal_mult", m.pp_goal_share,
        lambda mult: _simulate_goal_shares(
            team_st, league_goals_per_60, league_shots_per_60,
            pp_goal_cal_mult=mult, pk_goal_cal_mult=1.0,
            n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed,
        )[0],
        iters=args.iters,
    )

    print("\n--- calibrating pk_goal_cal_mult against sh_goal_share (using the fitted pp_goal_cal_mult) ---")
    pk_mult = _search_multiplier(
        "pk_goal_cal_mult", m.sh_goal_share,
        lambda mult: _simulate_goal_shares(
            team_st, league_goals_per_60, league_shots_per_60,
            pp_goal_cal_mult=pp_mult, pk_goal_cal_mult=mult,
            n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed + 1,
        )[1],
        iters=args.iters,
    )

    print("\n--- final verification run, both multipliers together, fresh seed ---")
    pp_share, sh_share, n = _simulate_goal_shares(
        team_st, league_goals_per_60, league_shots_per_60,
        pp_goal_cal_mult=pp_mult, pk_goal_cal_mult=pk_mult,
        n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed + 999,
    )
    print(f"  simulated pp_goal_share={pp_share:.4f} (target {m.pp_goal_share:.4f})")
    print(f"  simulated sh_goal_share={sh_share:.4f} (target {m.sh_goal_share:.4f})")
    print(f"  {n} total simulated goals observed")

    print(f"\nRESULT: pp_goal_cal_mult={pp_mult:.4f}  pk_goal_cal_mult={pk_mult:.4f}")
    print("Apply these to NHL_CALIBRATION_PROFILE_DEFAULT in calibration_profile.py with a")
    print("provenance comment, matching the Phase 3b pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
