#!/usr/bin/env python3
"""Second half of the "one faceoff per segment" impact measurement (see
`scripts/measure_nhl_faceoff_segment_approximation.py` for the first half -- the real vs assumed
faceoff-COUNT mismatch itself). That script found the engine assumes exactly 1 real faceoff drives
every ~44.4s segment when only 51.36% of real segment-windows have ANY real faceoff at all
(48.64% have zero). Since every discrete-event curve is mean-1.0 preserving by construction, this
cannot bias the AVERAGE simulated shot total (already verified via round-robin every time this
session touched a faceoff mechanism) -- what it COULD do is inject extra VARIANCE: applying a real,
non-trivial win/loss-driven shot-share tilt to segments where reality had no such event at all.

METHODOLOGY. A controlled A/B, same team rosters/rates/seeds structure, same real per-team
`special_teams` data (`team_special_teams_latest.csv`) both sides of the comparison -- the ONLY
difference is every `faceoff_*` mechanism flag in `SimConfig`: ON (shipped defaults) vs OFF (every
flag disabled, verified by reading `engine.py` for the complete flag list rather than guessing it).
Compares the STANDARD DEVIATION of total (home+away) shots-per-game between the two conditions, and
against the REAL observed std from 1,312 actual boxscores -- the target this whole exercise is
implicitly calibrated to match.

Usage:
  py -3 scripts/measure_nhl_faceoff_segment_variance_impact.py
  py -3 scripts/measure_nhl_faceoff_segment_variance_impact.py --pairings 200 --sims-per-pairing 2
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import (  # noqa: E402
    build_nhl_sim_config,
)
from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels, TeamRates  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.runtime import run_hockeysim_game  # noqa: E402

# The COMPLETE set of faceoff-related boolean flags on SimConfig -- read directly from engine.py
# (`grep -n "faceoff_.*: bool" engine.py`), not assumed or guessed. Disabling all ten is the only
# way to fully silence every mechanism (legacy diff-based, discrete-event EV/OZ/DZ/NZ,
# strength-state, joint role-zone, and both lineup-aware layers) -- `faceoff_enabled=False` alone
# only kills the LEGACY `_faceoff_multipliers` path; it does not gate the discrete-event branches
# at all (confirmed: `faceoff_enabled` appears in engine.py exactly once, inside
# `_faceoff_multipliers` itself).
_ALL_FACEOFF_FLAGS_OFF = {
    "faceoff_enabled": False,
    "faceoff_discrete_event_model": False,
    "faceoff_dz_discrete_event_model": False,
    "faceoff_oz_specific_curve": False,
    "faceoff_nz_discrete_event_model": False,
    "faceoff_strength_state_model": False,
    "faceoff_strength_state_zone_model": False,
    "faceoff_lineup_model": False,
    "faceoff_lineup_model_strength_state": False,
}


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _load_team_special_teams(root: Path) -> Dict[str, Dict[str, float]]:
    import csv
    path = root / "data" / "processed" / "team_special_teams_latest.csv"
    out: Dict[str, Dict[str, float]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            abbr = row.get("abbr")
            if not abbr:
                continue
            entry = {}
            for k, v in row.items():
                if k == "abbr":
                    continue
                try:
                    entry[k] = float(v)
                except (TypeError, ValueError):
                    continue
            out[abbr] = entry
    return out


def _roster(prefix: str, base_id: int) -> List[Dict[str, str]]:
    positions = (["C"] * 4 + ["L"] * 4 + ["R"] * 4 + ["D"] * 6 + ["G"] * 2)
    return [{"player_id": str(base_id + i), "full_name": f"{prefix}{i}", "position": p,
             "proj_toi": "15.0"} for i, p in enumerate(positions)]


def _round_robin_pairings(teams: List[str]) -> List[Tuple[str, str]]:
    return [(h, a) for h in teams for a in teams if h != a]


def _real_shot_totals(root: Path) -> List[int]:
    """Real (home_sog + away_sog) per game, from the boxscore cache -- the target distribution."""
    cache_dir = root / "data" / "ingestion_cache"
    files = sorted(glob.glob(str(cache_dir / "boxscore_*.json")))
    totals: List[int] = []
    for p in files:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if int(data.get("gameType") or 0) != 2:
            continue
        pbg = data.get("playerByGameStats") or {}

        def _team_sog(side: str) -> int:
            total = 0
            for group in ("forwards", "defense"):
                for pl in (pbg.get(side) or {}).get(group) or []:
                    try:
                        total += int(pl.get("sog") or 0)
                    except (TypeError, ValueError):
                        continue
            return total

        home_sog, away_sog = _team_sog("homeTeam"), _team_sog("awayTeam")
        if home_sog + away_sog > 0:
            totals.append(home_sog + away_sog)
    return totals


def _simulate_total_shots_per_game(
    team_st: Dict[str, Dict[str, float]], *, flags_override: Dict[str, bool],
    n_pairings: int, sims_per_pairing: int, seed: int,
) -> List[int]:
    rng = random.Random(seed)
    teams = sorted(team_st)
    league_shots = 30.0  # league-average shots/60, matches this session's other synthetic checks
    league_goals = 3.0
    rates = RateModels(
        home=TeamRates(shots_per_60=league_shots, goals_per_60=league_goals, faceoff_win_pct=0.5),
        away=TeamRates(shots_per_60=league_shots, goals_per_60=league_goals, faceoff_win_pct=0.5),
        player_rates={},
    )
    cfg = build_nhl_sim_config(overrides=dict(flags_override))
    all_pairings = _round_robin_pairings(teams)
    pairings = rng.sample(all_pairings, min(n_pairings, len(all_pairings))) if n_pairings < len(all_pairings) else all_pairings

    totals: List[int] = []
    for home, away in pairings:
        st_home = team_st[home]
        st_away = team_st[away]
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None, "proj_toi": r["proj_toi"]} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None, "proj_toi": r["proj_toi"]} for r in ra]
        for _ in range(sims_per_pairing):
            gs, events = run_hockeysim_game(
                "HOME", "AWAY", rh, ra, rates,
                lineup_home=lineup_h, lineup_away=lineup_a,
                st_home=st_home, st_away=st_away, special_teams_cal=None,
                profile=cfg, seed=rng.randint(0, 2**31 - 1),
            )
            n_shots = sum(1 for e in events if e.kind == "shot")
            totals.append(n_shots)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--pairings", type=int, default=200)
    ap.add_argument("--sims-per-pairing", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    team_st = _load_team_special_teams(root)
    if not team_st:
        print("REFUSED: no team_special_teams_latest.csv -- run "
              "scripts/build_nhl_special_teams_artifact.py first", file=sys.stderr)
        return 1
    print(f"loaded special_teams rates for {len(team_st)} teams")

    real_totals = _real_shot_totals(root)
    print(f"real games with a usable SOG total: {len(real_totals)}")

    on_totals = _simulate_total_shots_per_game(
        team_st, flags_override={}, n_pairings=args.pairings,
        sims_per_pairing=args.sims_per_pairing, seed=args.seed,
    )
    off_totals = _simulate_total_shots_per_game(
        team_st, flags_override=_ALL_FACEOFF_FLAGS_OFF, n_pairings=args.pairings,
        sims_per_pairing=args.sims_per_pairing, seed=args.seed,  # SAME seed -- paired comparison
    )

    def _stats(xs: List[int]) -> Tuple[float, float, int]:
        return (statistics.mean(xs), statistics.pstdev(xs), len(xs))

    real_mean, real_std, real_n = _stats(real_totals)
    on_mean, on_std, on_n = _stats(on_totals)
    off_mean, off_std, off_n = _stats(off_totals)

    print(f"\nREAL   (boxscore):        n={real_n:5d}  mean={real_mean:.3f}  std={real_std:.3f}")
    print(f"SIM ON  (shipped default): n={on_n:5d}  mean={on_mean:.3f}  std={on_std:.3f}")
    print(f"SIM OFF (all faceoff off): n={off_n:5d}  mean={off_mean:.3f}  std={off_std:.3f}")
    print(f"\nmean delta ON vs OFF: {on_mean - off_mean:+.3f} ({100.0 * (on_mean - off_mean) / off_mean:+.3f}%)")
    print(f"std  delta ON vs OFF: {on_std - off_std:+.3f} ({100.0 * (on_std - off_std) / off_std:+.3f}%)")
    print(f"\nON std vs REAL std:  {on_std:.3f} vs {real_std:.3f}  (ratio {on_std / real_std:.4f})")
    print(f"OFF std vs REAL std: {off_std:.3f} vs {real_std:.3f}  (ratio {off_std / real_std:.4f})")

    result = {
        "real": {"n": real_n, "mean": round(real_mean, 4), "std": round(real_std, 4)},
        "sim_on": {"n": on_n, "mean": round(on_mean, 4), "std": round(on_std, 4)},
        "sim_off": {"n": off_n, "mean": round(off_mean, 4), "std": round(off_std, 4)},
        "mean_delta_on_vs_off_pct": round(100.0 * (on_mean - off_mean) / off_mean, 4),
        "std_delta_on_vs_off_pct": round(100.0 * (on_std - off_std) / off_std, 4),
        "on_std_over_real_std": round(on_std / real_std, 4),
        "off_std_over_real_std": round(off_std / real_std, 4),
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
