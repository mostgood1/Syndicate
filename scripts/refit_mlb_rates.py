"""RE-FIT the sim's rate parameters with all mechanisms ON. `#440`.

WHY THIS EXISTS. The 2x2 factorial measured a NEGATIVE interaction (mean
−0.00331, 4 of 4 markets) when substitution and pitch-type splits were both
enabled: each helped alone, together they cancelled. The mechanism is that
`k_rate` / `hr_rate` / `inplay_hit_rate` / `bb_rate` were fitted so the sim's
OUTPUT matched observed outcomes — using a sim that had NEITHER feature. Those
rates therefore already absorb the average effect of the missing mechanisms, and
re-adding a mechanism double-counts it.

**So a mechanism is a two-part change: the mechanism AND a re-fit of the
parameters that were absorbing it.** This is the second part.

METHOD — a global multiplicative recalibration, deliberately the simplest thing
that can work:

  1. simulate the window with ALL mechanisms on, uncorrected;
  2. compare SIMULATED aggregate rates to ACTUAL (HR/PA, H/AB, SO/PA, BB/PA);
  3. correction = actual / simulated, per stat, league-wide;
  4. re-simulate with corrections applied and confirm the residual shrank.

**Global, not per-player, on purpose.** The rates absorbed the mechanisms'
AVERAGE effect, so an average-sized correction is what removes it. Per-player
corrections would refit noise and would silently undo the batted-ball blend,
which is a deliberate per-player signal.

Step 4 is not optional: a correction that does not reduce the residual is a
correction that was computed against the wrong quantity.

Usage:
  py -3 scripts/refit_mlb_rates.py --games 30 --sims 80
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for p in (str(REPO_ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
SNAPSHOTS = DATA / "daily_pitcher_props/snapshots"
PK_RE = re.compile(r"_pk(\d+)_")

# rate parameter -> (simulated numerator, simulated denominator, log columns)
STATS = {
    "hr_rate": ("HR", "PA", "hr", "pa"),
    "inplay_hit_rate": ("H", "AB", "h", "ab"),
    "k_rate": ("SO", "PA", "so", "pa"),
    "bb_rate": ("BB", "PA", "bb", "pa"),
}


def load_actual_rates() -> dict:
    tot = defaultdict(float)
    with (DATA / "processed/mlb_batter_game_log.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            def f(k):
                try:
                    return float(r.get(k) or 0)
                except (TypeError, ValueError):
                    return 0.0
            ab, bb = f("ab"), f("bb")
            tot["ab"] += ab
            tot["bb"] += bb
            tot["pa"] += ab + bb
            tot["h"] += f("h")
            tot["hr"] += f("hr")
            tot["so"] += f("so")
    return tot


def sim_aggregates(jobs, cfg_kwargs, sims, seed, corrections, season, weight):
    from datetime import date as _dt_date
    from sim_engine.data.arsenal import (apply_arsenal_to_batter,
                                         apply_arsenal_to_pitcher)
    from sim_engine.data.batted_ball import (apply_batted_ball_to_batter,
                                             apply_batted_ball_to_pitcher)
    from sim_engine.data.quality import apply_quality
    from sim_engine.data.statcast_bvp import (apply_starter_bvp_hr_multipliers,
                                              default_bvp_cache)
    from sim_engine.data.build_roster import _apply_cached_statcast_pitch_splits
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.data.statcast_pitch_splits import default_statcast_cache
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    cache = default_statcast_cache()
    bvp_cache = default_bvp_cache()
    tot = defaultdict(float)
    for _date, path in jobs:
        try:
            raw = read_game_roster_artifact(path)
        except Exception:
            continue
        away, home = raw["away"], raw["home"]
        # BVP once per GAME (each side vs the opposing starter), before the
        # per-roster loop -- it is applied by daily_update.py, not build_roster.
        for _bat_side, _pit_side in (("away", "home"), ("home", "away")):
            try:
                apply_starter_bvp_hr_multipliers(
                    batting_roster=raw[_bat_side],
                    pitcher_id=int(raw[_pit_side].lineup.pitcher.player.mlbam_id),
                    season=season, start_date=_dt_date(season, 3, 1),
                    end_date=_dt_date(season, 7, 30), cache=bvp_cache)
            except Exception:
                pass
        for r in (away, home):
            for p in [r.lineup.pitcher] + list(r.lineup.bullpen or []):
                _apply_cached_statcast_pitch_splits(
                    p, season=season, statcast_cache=cache, statcast_ttl_seconds=None)
                # PITCHER batted-ball rates. Added 2026-08-18 -- without this the
                # refit fits against a HALF-FED engine (pitchers keeping the
                # league-default 0.44 GB rate) and every correction it derives
                # would be absorbing the absence of a field that is about to be
                # populated. A refit is only valid for the input set it was run
                # against.
                apply_batted_ball_to_pitcher(p, season=season)
                # `#440`: the FULL input set. A refit against a half-fed engine
                # derives corrections that absorb the absence of fields which are
                # about to be populated -- measured 2026-08-18, when the earlier
                # run lacked arsenal, quality and BVP and its corrections are
                # therefore stale by construction.
                apply_arsenal_to_pitcher(p, season=season)
                apply_quality(p, season=season, side="pitchers")
            for b in list(r.lineup.batters) + list(r.lineup.bench or []):
                apply_batted_ball_to_batter(b, season=season, weight=weight)
                apply_arsenal_to_batter(b, season=season)
                apply_quality(b, season=season, side="batters")
                # apply the refit corrections on top of every other source
                for rate, mult in (corrections or {}).items():
                    try:
                        setattr(b, rate, float(getattr(b, rate)) * float(mult))
                    except Exception:
                        pass
        cfg = GameConfig(rng_seed=seed, manager_pitching="v2", **cfg_kwargs)
        for i in range(sims):
            try:
                res = simulate_game(away, home, replace(cfg, rng_seed=seed + i))
            except Exception:
                continue
            for _pid, st in res.batter_stats.items():
                for k in ("PA", "AB", "H", "HR", "SO", "BB"):
                    v = st.get(k)
                    if v is not None:
                        tot[k] += float(v)
    return tot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--sims", type=int, default=80)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--bb-weight", type=float, default=0.35)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    jobs = []
    for snap in sorted(SNAPSHOTS.iterdir()):
        for path in sorted((snap / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                jobs.append((snap.name, path))
    jobs = jobs[:args.games]

    actual = load_actual_rates()
    act = {
        "hr_rate": actual["hr"] / actual["pa"],
        "inplay_hit_rate": actual["h"] / actual["ab"],
        "k_rate": actual["so"] / actual["pa"],
        "bb_rate": actual["bb"] / actual["pa"],
    }

    print("=" * 88)
    print("RE-FIT — global rate recalibration with ALL mechanisms ON")
    print("=" * 88)
    print(f"\n  games {len(jobs)}   sims/game {args.sims}   batted-ball weight {args.bb_weight}")
    print("  mechanisms: position substitutions ON, pitch splits ON, batted-ball blend ON\n")

    on = {"position_substitutions": True}

    print("PASS 1 — uncorrected, mechanisms on")
    s1 = sim_aggregates(jobs, on, args.sims, args.seed, None, args.season, args.bb_weight)
    if not s1.get("PA"):
        print("  nothing simulated")
        return 1
    sim1 = {"hr_rate": s1["HR"] / s1["PA"], "inplay_hit_rate": s1["H"] / s1["AB"],
            "k_rate": s1["SO"] / s1["PA"], "bb_rate": s1["BB"] / s1["PA"]}

    corr = {}
    print(f"\n  {'rate':18s} {'simulated':>10s} {'actual':>10s} {'residual':>10s} {'correction':>11s}")
    print("  " + "-" * 64)
    for k in STATS:
        s, a = sim1[k], act[k]
        c = (a / s) if s > 0 else 1.0
        corr[k] = c
        print(f"  {k:18s} {s:10.5f} {a:10.5f} {(s - a) / a:+9.1%} {c:11.4f}")

    print("\nPASS 2 — corrections applied, same seeds")
    s2 = sim_aggregates(jobs, on, args.sims, args.seed, corr, args.season, args.bb_weight)
    sim2 = {"hr_rate": s2["HR"] / s2["PA"], "inplay_hit_rate": s2["H"] / s2["AB"],
            "k_rate": s2["SO"] / s2["PA"], "bb_rate": s2["BB"] / s2["PA"]}

    print(f"\n  {'rate':18s} {'before':>10s} {'after':>10s} {'actual':>10s} {'residual':>11s}")
    print("  " + "-" * 66)
    improved = 0
    for k in STATS:
        r1 = abs(sim1[k] - act[k]) / act[k]
        r2 = abs(sim2[k] - act[k]) / act[k]
        if r2 < r1:
            improved += 1
        print(f"  {k:18s} {sim1[k]:10.5f} {sim2[k]:10.5f} {act[k]:10.5f} "
              f"{r1:+6.1%} -> {r2:+6.1%}")

    print(f"\n  residual shrank on {improved} of {len(STATS)} rates")
    if improved < len(STATS):
        print("  WARNING: a correction that does not reduce its residual was computed")
        print("  against the wrong quantity. Do not ship those.")

    out = {"season": args.season, "games": len(jobs), "sims": args.sims,
           "bb_weight": args.bb_weight, "corrections": corr,
           "actual": act, "sim_before": sim1, "sim_after": sim2,
           "improved": improved, "of": len(STATS)}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
