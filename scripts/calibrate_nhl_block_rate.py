#!/usr/bin/env python3
"""Calibrate the ABSOLUTE `block_rate_ev`/`block_rate_pk`/`block_rate_pp_def` base constants
against real truth -- the gap `docs/reports/hockeysim_per_team_block_rate_report.md` explicitly
left open: that pass built PER-TEAM relative differentiation (`block_rate_index`) but left the
vendor's original, never-measured base constants (0.45/0.55/0.35) untouched.

WHY A SINGLE SHARED SCALE, NOT THREE INDEPENDENT FITS. The truth source
(`historical_truth.boxscore_block_rate`) carries exactly ONE league-wide target -- real average
blocks/team/game -- because blocked shots have no strength-state breakdown in the `boxscore`
payload at all (see that module's docstring). Fitting 3 independent constants against 1 target is
underdetermined (infinite solutions); this script instead fits ONE proportional scale factor `k`
applied uniformly to all three (`block_rate_ev *= k`, `block_rate_pk *= k`, `block_rate_pp_def *=
k`), preserving their existing STRUCTURAL ratio (higher on the PK, lower on the PP) -- the only
degree of freedom the data actually supports, per `model_engine_standard.md` §4.4 (don't invent
unconstrained degrees of freedom).

WHY `block_rate_index` IS HELD NEUTRAL DURING THE FIT. `block_rate_index` (§2g) is a SEPARATE,
already-verified per-team layer that averages to ~1.0 by construction. Fitting the base level with
it OFF isolates "what absolute scale matches the league-wide truth" from "how do teams differ from
each other" -- the same mechanism-vs-estimator split `model_engine_standard.md` §4.4 requires.
After fitting, this script re-verifies (does not re-fit) that turning the real per-team index back
on does not disturb the newly-calibrated league average, mirroring the per-team shot-rate report's
own verification step.

Usage:
  py -3 scripts/calibrate_nhl_block_rate.py
  py -3 scripts/calibrate_nhl_block_rate.py --sims-per-pairing 20
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import (  # noqa: E402
    build_league_block_rate_snapshot,
    parse_boxscore_block_rate,
)
from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels, TeamRates  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.runtime import run_hockeysim_game  # noqa: E402


def _roster(team: str, base_pid: int) -> List[Dict]:
    rows: List[Dict] = []
    pid = base_pid
    for i in range(12):
        rows.append({"player_id": pid, "full_name": f"{team} F{i+1}", "position": "F", "proj_toi": 20.0 - i * 0.9})
        pid += 1
    for i in range(6):
        rows.append({"player_id": pid, "full_name": f"{team} D{i+1}", "position": "D", "proj_toi": 22.0 - i * 2.0})
        pid += 1
    rows.append({"player_id": pid, "full_name": f"{team} G1", "position": "G", "proj_toi": 60.0})
    return rows


def _load_special_teams() -> Dict[str, Dict[str, float]]:
    """Full real per-team row (all 6 columns) -- unlike the earlier calibration scripts, this
    one also needs `block_rate_index` (for the post-fit verification pass) and the shot indices
    (so the FIT sees the same shot-volume substrate production actually runs on)."""
    path = REPO / "data" / "nhl_source" / "data" / "processed" / "team_special_teams_latest.csv"
    if not path.exists():
        print(f"REFUSED: {path} does not exist -- run scripts/build_nhl_special_teams_artifact.py first", file=sys.stderr)
        sys.exit(1)
    out: Dict[str, Dict[str, float]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["abbr"]] = {
                "pp_pct": float(row["pp_pct"]), "pk_pct": float(row["pk_pct"]),
                "committed_per_game": float(row["committed_per_game"]),
                "pp_shot_index": float(row.get("pp_shot_index", 1.0) or 1.0),
                "pk_shot_index_allowed": float(row.get("pk_shot_index_allowed", 1.0) or 1.0),
                "block_rate_index": float(row.get("block_rate_index", 1.0) or 1.0),
            }
    return out


def _load_block_rate_truth():
    cache_dir = REPO / "data" / "nhl_source" / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "boxscore_*.json")))
    if not files:
        print(f"REFUSED: no boxscore cache under {cache_dir} -- run scripts/fetch_nhl_boxscore_cache.py first", file=sys.stderr)
        sys.exit(1)
    recs = []
    for p in files:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if int(data.get("gameType") or 0) != 2:  # regular season only, matches the other calibrations' population
            continue
        rec = parse_boxscore_block_rate(data)
        if rec is not None:
            recs.append(rec)
    return build_league_block_rate_snapshot(recs)


def _round_robin_pairings(teams: List[str]) -> List[Tuple[str, str]]:
    """Every ORDERED team pair -- same discipline as the shot-multiplier calibration: random
    sampling left a real, non-noise verification gap there (see
    `hockeysim_special_teams_shot_cal_report.md`)."""
    return [(h, a) for h in teams for a in teams if h != a]


def _simulate_blocks_per_game(
    team_st: Dict[str, Dict[str, float]],
    *,
    block_scale: float,
    use_real_block_index: bool,
    n_pairings: int,
    sims_per_pairing: int,
    seed: int,
    full_round_robin: bool = False,
) -> Tuple[float, int]:
    """Average blocks/TEAM/game across the simulated slate -- same definition
    `build_league_block_rate_snapshot` uses (`total_blocks / (2 * n_games)`)."""
    rng = random.Random(seed)
    teams = sorted(team_st)
    rates = RateModels(
        home=TeamRates(shots_per_60=30.0, goals_per_60=3.1269, blocks_per_60=12.0,
                       penalties_per_60=3.0, faceoff_win_pct=0.5),
        away=TeamRates(shots_per_60=30.0, goals_per_60=3.1269, blocks_per_60=12.0,
                       penalties_per_60=3.0, faceoff_win_pct=0.5),
        player_rates={},
    )
    cfg = build_nhl_sim_config(overrides={
        "pp_shot_cal_mult": 0.9108, "pk_shot_cal_mult": 0.3369,
        "pp_goal_cal_mult": 1.0, "pk_goal_cal_mult": 0.4645,
        "block_rate_ev": 0.45 * block_scale, "block_rate_pk": 0.55 * block_scale,
        "block_rate_pp_def": 0.35 * block_scale,
    })
    cal = {"pp_shot_multiplier": cfg.pp_shot_cal_mult, "pk_shot_multiplier": cfg.pk_shot_cal_mult,
           "pp_goal_multiplier": cfg.pp_goal_cal_mult, "pk_goal_multiplier": cfg.pk_goal_cal_mult,
           "blocks_ev_rate": cfg.block_rate_ev, "blocks_pk_rate": cfg.block_rate_pk,
           "blocks_pp_def_rate": cfg.block_rate_pp_def}

    pairings = _round_robin_pairings(teams) if full_round_robin else [tuple(rng.sample(teams, 2)) for _ in range(n_pairings)]

    total_blocks = 0
    n_games = 0
    for home, away in pairings:
        base_home = team_st[home]
        base_away = team_st[away]
        st_home = dict(base_home)
        st_away = dict(base_away)
        if not use_real_block_index:
            st_home["block_rate_index"] = 1.0
            st_away["block_rate_index"] = 1.0
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
            total_blocks += sum(1 for e in events if e.kind == "block")
            n_games += 1
    blocks_per_game = total_blocks / (2 * n_games) if n_games else 0.0
    return blocks_per_game, n_games


def _search_scale(label: str, target: float, get_value, *, lo: float = 0.1, hi: float = 5.0, iters: int = 5) -> float:
    scale = 1.0
    for i in range(iters):
        measured = get_value(scale)
        if measured <= 0:
            print(f"  {label} iter {i}: measured=0 at scale={scale:.4f} -- cannot correct proportionally, stopping")
            break
        new_scale = max(lo, min(hi, scale * (target / measured)))
        print(f"  {label} iter {i}: scale={scale:.4f} -> measured={measured:.4f} (target {target:.4f}) -> next={new_scale:.4f}")
        if abs(new_scale - scale) < 1e-4:
            scale = new_scale
            break
        scale = new_scale
    return scale


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit-pairings", type=int, default=60,
                     help="random pairings used for the (cheap, iterative) fit search -- a single "
                          "proportional-scale fit against one plain mean has no shared-denominator "
                          "or cross-parameter bias to worry about, unlike the shot-multiplier "
                          "calibration's joint fit, so random sampling is fine here and much "
                          "cheaper than a full round-robin per iteration")
    ap.add_argument("--fit-sims-per-pairing", type=int, default=20)
    ap.add_argument("--verify-sims-per-pairing", type=int, default=20,
                     help="verification runs always use the FULL round-robin (992 ordered pairs) "
                          "for a high-confidence final number")
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--iters", type=int, default=5)
    args = ap.parse_args()

    team_st = _load_special_teams()
    print(f"loaded special_teams rates for {len(team_st)} teams")
    n_full = len(team_st) * (len(team_st) - 1)
    print(f"fit: {args.fit_pairings} random pairings x {args.fit_sims_per_pairing} sims/iter")
    print(f"verify: full round-robin, {n_full} pairings x {args.verify_sims_per_pairing} sims = "
          f"{n_full * args.verify_sims_per_pairing} games")

    truth = _load_block_rate_truth()
    print(f"block-rate truth: {truth.n_games} games, league_block_rate={truth.league_block_rate:.4f}, "
          f"blocks_per_game(team)={truth.blocks_per_game:.4f}")

    print("\n--- fitting block_scale against blocks_per_game (block_rate_index held NEUTRAL) ---")
    scale = _search_scale(
        "block_scale", truth.blocks_per_game,
        lambda s: _simulate_blocks_per_game(
            team_st, block_scale=s, use_real_block_index=False,
            n_pairings=args.fit_pairings, sims_per_pairing=args.fit_sims_per_pairing, seed=args.seed,
            full_round_robin=False,
        )[0],
        iters=args.iters,
    )

    print("\n--- verification run #1: full round-robin, fresh seed, block_rate_index still NEUTRAL ---")
    bpg_neutral, n1 = _simulate_blocks_per_game(
        team_st, block_scale=scale, use_real_block_index=False,
        n_pairings=0, sims_per_pairing=args.verify_sims_per_pairing, seed=args.seed + 999,
        full_round_robin=True,
    )
    print(f"  simulated blocks_per_game={bpg_neutral:.4f} (target {truth.blocks_per_game:.4f}), {n1} games")

    print("\n--- verification run #2: full round-robin, REAL per-team block_rate_index active ---")
    bpg_real, n2 = _simulate_blocks_per_game(
        team_st, block_scale=scale, use_real_block_index=True,
        n_pairings=0, sims_per_pairing=args.verify_sims_per_pairing, seed=args.seed + 1998,
        full_round_robin=True,
    )
    print(f"  simulated blocks_per_game={bpg_real:.4f} (target {truth.blocks_per_game:.4f}), {n2} games")

    print(f"\nRESULT: block_scale={scale:.4f}")
    print(f"  block_rate_ev={0.45 * scale:.4f}  block_rate_pk={0.55 * scale:.4f}  block_rate_pp_def={0.35 * scale:.4f}")
    print("Apply these to NHL_CALIBRATION_PROFILE_DEFAULT in calibration_profile.py with a")
    print("provenance comment, matching the goal/shot-multiplier calibrations' pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
