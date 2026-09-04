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
import os
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

# `SYNDICATE_MLB_DATA_ROOT` overrides where the artifacts are read from. A
# worktree carries only the families it was created with -- this one has 13 of
# them and NOT `processed/`, where the ACTUAL game log lives -- so without an
# override the harness can only run in whichever tree happens to be complete.
# The mirror is still a MIRROR: nothing read through here is evidence about
# production, whichever tree it comes from.
DATA = Path(os.environ.get("SYNDICATE_MLB_DATA_ROOT")
            or (REPO_ROOT / "data/mlb_source/source_artifacts/data"))
SNAPSHOTS = DATA / "daily_pitcher_props/snapshots"
PK_RE = re.compile(r"_pk(\d+)_")

# rate parameter -> (simulated numerator, simulated denominator, log columns)
STATS = {
    "hr_rate": ("HR", "PA", "hr", "pa"),
    "inplay_hit_rate": ("H", "AB", "h", "ab"),
    "k_rate": ("SO", "PA", "so", "pa"),
    "bb_rate": ("BB", "PA", "bb", "pa"),
}



# rate name -> the `PitchModelConfig` knob that ships it, and that knob's CURRENT
# default. The correction multiplies the BASELINE rather than replacing it: hr
# and inplay already carry a fitted 1.03, so a correction of 1.80 must ship as
# 1.03 * 1.80, not as 1.80. k and bb start neutral at 1.0.
_RATE_TO_KNOB = {
    "hr_rate": "hr_rate_mult",
    "inplay_hit_rate": "inplay_hit_rate_mult",
    "k_rate": "k_rate_mult",
    "bb_rate": "bb_rate_mult",
}
_KNOB_BASELINE = {
    "hr_rate_mult": 1.03,
    "inplay_hit_rate_mult": 1.03,
    "k_rate_mult": 1.0,
    "bb_rate_mult": 1.0,
}

def load_actual_rates(dates: "set[str] | None" = None) -> tuple:
    """League aggregate counting stats, OPTIONALLY restricted to `dates`.

    **THE DATE FILTER IS THE POINT, and its absence was a real defect.** This
    function used to read the WHOLE game log while `sim_aggregates` ran over
    whichever `roster_objs` happened to exist, so `correction = actual /
    simulated` compared two different POPULATIONS. Measured on this checkout,
    2026-09-04:

        simulated side   roster_objs/           13 dates, 186 games   06-15..06-27
        actual side      mlb_batter_game_log    47 dates, 12,185 rows 05-28..07-14

    and the documented `--games 30` takes the FIRST 30 jobs in sort order, which
    is about THREE dates. A correction fitted that way absorbs the difference
    between three June days and seven weeks of baseball as if it were mechanism
    bias -- and it would look like it had 12,185 rows behind it.

    This is `CLAUDE.md`'s named trap: an analysis joining across artifact
    families silently collapses to their intersection. So the caller passes the
    dates it actually simulated, and the row count backing the answer is
    returned rather than assumed.
    """
    tot = defaultdict(float)
    matched = skipped = 0
    seen: set[str] = set()
    with (DATA / "processed/mlb_batter_game_log.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            day = str(r.get("date") or "")[:10]
            if dates is not None and day not in dates:
                skipped += 1
                continue
            matched += 1
            if day:
                seen.add(day)

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
    return tot, matched, skipped, seen


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
            # BATTERS, at ROSTER scope -- deliberately NOT inside the pitcher
            # loop above. A patch of mine re-indented this by four spaces on
            # 2026-09-04 and it ran once per PITCHER instead of once per roster,
            # applying the batted-ball, arsenal and quality blends repeatedly.
            # It moved the UNCORRECTED baseline hr_rate 0.01873 -> 0.02732, a 46%
            # shift in a pass that is supposed to be identical between runs, and
            # every correction derived from it was wrong. Caught only because the
            # two runs' PASS 1 disagreed and PASS 1 takes no corrections at all.
            for b in list(r.lineup.batters) + list(r.lineup.bench or []):
                apply_batted_ball_to_batter(b, season=season, weight=weight)
                apply_arsenal_to_batter(b, season=season)
                apply_quality(b, season=season, side="batters")
        # CORRECTIONS APPLIED THROUGH THE SHIPPING KNOB, not the batter profile.
        #
        # They used to be `setattr(b, rate, ...)` on every batter, which is a
        # different transformation from the one that would ship:
        # `PitchModelConfig`'s multipliers act on the COMBINED target, after the
        # batter and pitcher rates are blended and after `clamp01`. A correction
        # fitted by scaling the batter and then applied at the combined target is
        # not the correction that was measured -- so the harness now measures the
        # configuration that would actually be deployed.
        #
        # `pitch_model_overrides` is the existing seam: `simulate_game` filters it
        # against `PitchModelConfig.__dataclass_fields__` and builds the config
        # from it (simulate.py:2255-2263).
        overrides = dict(cfg_kwargs.pop("pitch_model_overrides", {}) or {})
        for rate, mult in (corrections or {}).items():
            knob = _RATE_TO_KNOB.get(rate)
            if not knob:
                continue
            overrides[knob] = float(_KNOB_BASELINE[knob]) * float(mult)
        cfg = GameConfig(
            rng_seed=seed, manager_pitching="v2",
            pitch_model_overrides=overrides, **cfg_kwargs,
        )
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
    ap.add_argument("--match-dates", dest="match_dates", action="store_true", default=True,
                    help="restrict ACTUAL rates to the dates actually simulated (default)")
    ap.add_argument("--no-match-dates", dest="match_dates", action="store_false",
                    help="the old behaviour: compare against the whole game log")
    ap.add_argument("--spread", action="store_true", default=True,
                    help="sample --games evenly across the window (default), not the first N")
    ap.add_argument("--no-spread", dest="spread", action="store_false")
    ap.add_argument("--holdout-dates", type=int, default=0,
                    help="fit on all but the LAST N dates, then validate on "
                         "those N. learnings.md 2026-08-31 FORBIDS shipping a "
                         "calibration validated only in-sample.")
    args = ap.parse_args()

    jobs = []
    for snap in sorted(SNAPSHOTS.iterdir()):
        for path in sorted((snap / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                jobs.append((snap.name, path))
    all_dates = sorted({d for d, _ in jobs})
    if args.spread and args.games and args.games < len(jobs):
        # SPREAD ACROSS THE WINDOW rather than taking the first N. `jobs` is
        # sorted by date, so `jobs[:30]` is the three EARLIEST dates -- a
        # correction fitted on one long weekend, presented as a league rate.
        step = len(jobs) / float(args.games)
        jobs = [jobs[int(i * step)] for i in range(args.games)]
    else:
        jobs = jobs[:args.games]
    sim_dates = {d for d, _ in jobs}

    if args.match_dates:
        actual, matched, skipped, act_dates = load_actual_rates(sim_dates)
        scope = "MATCHED to the %d simulated date(s)" % len(sim_dates)
    else:
        actual, matched, skipped, act_dates = load_actual_rates(None)
        scope = "UNMATCHED -- the whole game log"
    missing = sorted(sim_dates - act_dates)
    if not actual.get("pa"):
        print("  no actual rows matched the simulated dates -- refusing to divide by zero")
        return 1
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
    # COVERAGE FIRST. `CLAUDE.md`: report the number of dates a result actually
    # rests on, because a cross-family join silently collapses to the
    # intersection and still looks like it ran on everything.
    print(f"  ACTUAL scope    {scope}")
    print(f"  actual rows     {matched} matched, {skipped} skipped, "
          f"{len(act_dates)} date(s) {min(act_dates) if act_dates else 'n/a'}"
          f" .. {max(act_dates) if act_dates else 'n/a'}")
    print(f"  simulated       {len(jobs)} game(s) over {len(sim_dates)} date(s) "
          f"{min(sim_dates)} .. {max(sim_dates)}   (of {len(all_dates)} available)")
    if missing:
        print(f"  !! {len(missing)} simulated date(s) have NO actual rows: {missing[:6]}")
    if not args.match_dates:
        print("  !! UNMATCHED: the correction absorbs the difference between two")
        print("     populations as if it were mechanism bias.")

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

    # ------------------------------------------------------------------
    # OUT-OF-SAMPLE VALIDATION.
    #
    # `learnings.md` 2026-08-31 marks shipping a calibration validated ONLY
    # in-sample as FORBIDDEN: a WNBA sigma refit was tuned to 18.25 on a pooled
    # residual, looked good in-sample, and was worse out of it. PASS 2 below is
    # in-sample BY CONSTRUCTION -- same games, same seeds, corrections fitted on
    # exactly the rows they are then scored against.
    #
    # So this re-fits on the TRAIN dates alone and scores on dates the fit never
    # saw. A correction that shrinks the residual here has earned something PASS
    # 2 cannot demonstrate at any sample size.
    # ------------------------------------------------------------------
    if args.holdout_dates > 0:
        held = sorted(sim_dates)[-args.holdout_dates:]
        held_set = set(held)
        train = [j for j in jobs if j[0] not in held_set]
        test = [j for j in jobs if j[0] in held_set]
        print(f"HELD-OUT VALIDATION  train {len(train)} game(s) / "
              f"{len(sim_dates) - len(held)} date(s)   "
              f"test {len(test)} game(s) / {len(held)} date(s) "
              f"{held[0]}..{held[-1]}")
        if not train or not test:
            print("  the split leaves one side empty -- refusing to report a number")
            return 1
        tr_actual, _, _, _ = load_actual_rates({d for d, _ in train})
        te_actual, _, _, _ = load_actual_rates({d for d, _ in test})
        if not tr_actual.get("pa") or not te_actual.get("pa"):
            print("  no actual rows on one side of the split -- refusing")
            return 1

        def _rates(agg, pa_key="PA", ab_key="AB"):
            return {"hr_rate": agg["HR"] / agg[pa_key],
                    "inplay_hit_rate": agg["H"] / agg[ab_key],
                    "k_rate": agg["SO"] / agg[pa_key],
                    "bb_rate": agg["BB"] / agg[pa_key]}

        def _act(tot):
            return {"hr_rate": tot["hr"] / tot["pa"],
                    "inplay_hit_rate": tot["h"] / tot["ab"],
                    "k_rate": tot["so"] / tot["pa"],
                    "bb_rate": tot["bb"] / tot["pa"]}

        tr_act, te_act = _act(tr_actual), _act(te_actual)
        tr_sim = _rates(sim_aggregates(train, on, args.sims, args.seed, None,
                                       args.season, args.bb_weight))
        oos_corr = {k: (tr_act[k] / tr_sim[k]) if tr_sim[k] > 0 else 1.0 for k in STATS}
        before = _rates(sim_aggregates(test, on, args.sims, args.seed, None,
                                       args.season, args.bb_weight))
        after = _rates(sim_aggregates(test, on, args.sims, args.seed, oos_corr,
                                      args.season, args.bb_weight))
        print()
        print(f"  {'rate':18} {'fitted':>9} {'oos before':>11} {'oos after':>10} "
              f"{'oos actual':>11}   residual")
        print("  " + "-" * 82)
        oos_improved = 0
        for k in STATS:
            r1 = abs(before[k] - te_act[k]) / te_act[k]
            r2 = abs(after[k] - te_act[k]) / te_act[k]
            if r2 < r1:
                oos_improved += 1
            print(f"  {k:18} {oos_corr[k]:9.4f} {before[k]:11.5f} {after[k]:10.5f} "
                  f"{te_act[k]:11.5f}   {r1:+7.1%} -> {r2:+7.1%}")
        print()
        print(f"  OUT-OF-SAMPLE: residual shrank on {oos_improved} of {len(STATS)} rates")
        if oos_improved < len(STATS):
            print("  DO NOT SHIP -- `learnings.md` 2026-08-31 forbids shipping a refit")
            print("  validated only in-sample, and THIS is the out-of-sample answer.")
        print()

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
           "improved": improved, "of": len(STATS),
           # PROVENANCE travels with the numbers. A corrections blob whose
           # population cannot be reconstructed is one nobody can re-fit or
           # refute later.
           "match_dates": bool(args.match_dates),
           "spread": bool(args.spread),
           "sim_dates": sorted(sim_dates),
           "actual_dates": sorted(act_dates),
           "actual_rows_matched": matched,
           "actual_rows_skipped": skipped}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
