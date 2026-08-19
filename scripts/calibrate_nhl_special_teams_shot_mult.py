#!/usr/bin/env python3
"""Calibrate `pp_shot_cal_mult` / `pk_shot_cal_mult` against real boxscore-derived truth.

Sibling to `scripts/calibrate_nhl_special_teams_goal_mult.py` (same search method, same engine,
same real per-team `pp_pct`/`pk_pct`/`committed_per_game` inputs) but scores SHOT volume, not goal
conversion, against `historical_truth.boxscore_shot_strength`'s truth (`pp_shot_share`/
`sh_shot_share`) -- built from the `boxscore` endpoint's per-goalie strength-state splits, bulk-
fetched by `scripts/fetch_nhl_boxscore_cache.py` (1,312 games, previously only 11 cached).

`cal_pp_sh_mult` scales the ATTACKING team's shot volume while on the power play
(`pp_mult_shots = cfg.pp_shots_mult * cal_pp_sh_mult`, `engine.py:943`) -- target `pp_shot_share`.
`cal_pk_sh_mult` scales the DEFENDING (shorthanded) team's OWN shot volume while killing a penalty
(`pk_mult_shots`, same line) -- target `sh_shot_share`, the rare "shots taken while shorthanded"
event, exactly analogous to `sh_goal_share`'s role in the goal-multiplier calibration.

Usage:
  py -3 scripts/calibrate_nhl_special_teams_shot_mult.py
  py -3 scripts/calibrate_nhl_special_teams_shot_mult.py --pairings 50 --sims-per-pairing 40
"""
from __future__ import annotations

import argparse
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
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import (  # noqa: E402
    build_shot_strength_snapshot,
    parse_boxscore_shot_strength,
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


def _load_shot_strength_truth():
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
        if int(data.get("gameType") or 0) != 2:  # regular season only, matches the goal calibration's population
            continue
        rec = parse_boxscore_shot_strength(data)
        if rec is not None:
            recs.append(rec)
    return build_shot_strength_snapshot(recs)


def _round_robin_pairings(teams: List[str]) -> List[Tuple[str, str]]:
    """Every ORDERED team pair (each team home once against every other team, and away once
    against every other) -- eliminates the composition bias a random `rng.sample` draw can
    introduce (a persistent ~5% verification-vs-fit gap was observed with random sampling at
    n_pairings=80, even at a 260k-shot verification sample, far larger than sampling noise alone
    would explain -- see `docs/reports/hockeysim_special_teams_shot_cal_report.md`)."""
    return [(h, a) for h in teams for a in teams if h != a]


def _simulate_shot_shares(
    team_st: Dict[str, Dict[str, float]],
    league_goals_per_60: float,
    league_shots_per_60: float,
    *,
    pp_shot_cal_mult: float,
    pk_shot_cal_mult: float,
    n_pairings: int,
    sims_per_pairing: int,
    seed: int,
    full_round_robin: bool = False,
) -> Tuple[float, float, int]:
    rng = random.Random(seed)
    teams = sorted(team_st)
    rates = RateModels(
        home=TeamRates(shots_per_60=league_shots_per_60, goals_per_60=league_goals_per_60,
                       faceoff_win_pct=0.5),
        away=TeamRates(shots_per_60=league_shots_per_60, goals_per_60=league_goals_per_60,
                       faceoff_win_pct=0.5),
        player_rates={},
    )
    cfg = build_nhl_sim_config(overrides={
        "pp_shot_cal_mult": pp_shot_cal_mult, "pk_shot_cal_mult": pk_shot_cal_mult,
    })
    cal = {"pp_shot_multiplier": cfg.pp_shot_cal_mult, "pk_shot_multiplier": cfg.pk_shot_cal_mult,
           "pp_goal_multiplier": cfg.pp_goal_cal_mult, "pk_goal_multiplier": cfg.pk_goal_cal_mult,
           "blocks_ev_rate": cfg.block_rate_ev, "blocks_pk_rate": cfg.block_rate_pk,
           "blocks_pp_def_rate": cfg.block_rate_pp_def}

    pairings = _round_robin_pairings(teams) if full_round_robin else [tuple(rng.sample(teams, 2)) for _ in range(n_pairings)]

    total_shots = pp_shots = sh_shots = 0
    for home, away in pairings:
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
                if e.kind != "shot":
                    continue
                total_shots += 1
                strength = str((e.meta or {}).get("strength") or "").upper()
                if strength == "PP":
                    pp_shots += 1
                elif strength == "PK":
                    sh_shots += 1
    pp_share = pp_shots / total_shots if total_shots else 0.0
    sh_share = sh_shots / total_shots if total_shots else 0.0
    return pp_share, sh_share, total_shots


def _search_multiplier(label: str, target: float, get_share, *, lo: float = 0.1, hi: float = 5.0, iters: int = 5) -> float:
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
    ap.add_argument("--pairings", type=int, default=50, help="ignored when --full-round-robin is set")
    ap.add_argument("--sims-per-pairing", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--full-round-robin", action="store_true",
                     help="every ordered team pair once instead of a random draw -- eliminates "
                          "composition bias between the fitting and verification samples "
                          "(measured: random sampling left a ~5% verification-vs-fit gap even at "
                          "a 260k-shot sample, far larger than sampling noise alone explains)")
    args = ap.parse_args()

    team_st = _load_special_teams()
    print(f"loaded special_teams rates for {len(team_st)} teams")
    if args.full_round_robin:
        n_pairs = len(team_st) * (len(team_st) - 1)
        print(f"full round-robin: {n_pairs} ordered pairings x {args.sims_per_pairing} sims = {n_pairs * args.sims_per_pairing} games/batch")

    truth = _load_shot_strength_truth()
    print(f"shot-strength truth: {truth.n_games} games, pp_shot_share={truth.pp_shot_share:.4f}, "
          f"sh_shot_share={truth.sh_shot_share:.4f}, shots_per_game={truth.shots_per_game:.4f}")

    # Reuse the goal-calibration's league-average base rates for consistency (same substrate).
    league_goals_per_60 = 3.1269
    league_shots_per_60 = truth.shots_per_game / 2.0
    print(f"league-average per-team rates: goals_per_60={league_goals_per_60:.4f} shots_per_60={league_shots_per_60:.4f}")

    # JOINT fit, not a single pp-then-pk pass: `total_shots` (the shared denominator of BOTH
    # target ratios) shifts substantially between the two stages -- uncalibrated `pk_shot_cal_mult`
    # (1.0) inflates SH shots to ~3x their real share, so fitting `pp_shot_cal_mult` while `pk` is
    # still at that wrong placeholder absorbs a denominator bias that vanishes once `pk` is
    # corrected. Measured: a single pp-then-pk pass left a ~5% pp_shot_share verification gap even
    # at a 260k-shot, fully-balanced (round-robin) sample -- far larger than sampling noise. This
    # alternates both fits for `rounds` outer passes so each one converges against the OTHER's
    # current best estimate, not a stale 1.0.
    pp_mult, pk_mult = 1.0, 1.0
    ROUNDS = 3
    for outer in range(ROUNDS):
        print(f"\n=== joint round {outer + 1}/{ROUNDS} ===")
        print(f"--- pp_shot_cal_mult against pp_shot_share (pk held at {pk_mult:.4f}) ---")
        pp_mult = _search_multiplier(
            "pp_shot_cal_mult", truth.pp_shot_share,
            lambda mult: _simulate_shot_shares(
                team_st, league_goals_per_60, league_shots_per_60,
                pp_shot_cal_mult=mult, pk_shot_cal_mult=pk_mult,
                n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed + outer * 2,
                full_round_robin=args.full_round_robin,
            )[0],
            iters=args.iters,
        )
        print(f"--- pk_shot_cal_mult against sh_shot_share (pp held at {pp_mult:.4f}) ---")
        pk_mult = _search_multiplier(
            "pk_shot_cal_mult", truth.sh_shot_share,
            lambda mult: _simulate_shot_shares(
                team_st, league_goals_per_60, league_shots_per_60,
                pp_shot_cal_mult=pp_mult, pk_shot_cal_mult=mult,
                n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed + outer * 2 + 1,
                full_round_robin=args.full_round_robin,
            )[1],
            iters=args.iters,
        )
        print(f"=== round {outer + 1} result: pp={pp_mult:.4f} pk={pk_mult:.4f} ===")

    print("\n--- final verification run, both multipliers together, fresh seed ---")
    pp_share, sh_share, n = _simulate_shot_shares(
        team_st, league_goals_per_60, league_shots_per_60,
        pp_shot_cal_mult=pp_mult, pk_shot_cal_mult=pk_mult,
        n_pairings=args.pairings, sims_per_pairing=args.sims_per_pairing, seed=args.seed + 999,
        full_round_robin=args.full_round_robin,
    )
    print(f"  simulated pp_shot_share={pp_share:.4f} (target {truth.pp_shot_share:.4f})")
    print(f"  simulated sh_shot_share={sh_share:.4f} (target {truth.sh_shot_share:.4f})")
    print(f"  {n} total simulated shots observed")

    print(f"\nRESULT: pp_shot_cal_mult={pp_mult:.4f}  pk_shot_cal_mult={pk_mult:.4f}")
    print("Apply these to NHL_CALIBRATION_PROFILE_DEFAULT in calibration_profile.py with a")
    print("provenance comment, matching the goal-multiplier calibration's pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
