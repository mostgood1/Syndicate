"""Solve for the home-field multiplier, and prove it does not move TOTALS.

THE TARGET, measured 2026-09-07 over 1,015 games / 78 dates against MLB
StatsAPI finals: the daily sim's mean predicted home margin is **-0.186 runs**
against an actual **+0.021**, so the engine owes the home team **+0.207 runs**
of margin. The whole bias sits in innings 1-5; innings 6+ are unbiased.

WHAT THIS SCRIPT IS FOR. `GameConfig.home_field_offense_mult` is a RATE
multiplier and the deficit is stated in RUNS, so the mapping between them has to
be measured rather than assumed. This runs the real `simulate_game` at several
multipliers and reports, for each:

  * the shift in mean HOME MARGIN      -- what we are trying to move
  * the shift in mean TOTAL RUNS       -- what must NOT move

The second is the whole reason the term is applied symmetrically (home x m,
away x 1/m). `model_engine_standard.md` requires that a mechanism added to a
calibrated engine be paid for by re-fitting whatever absorbed it; totals are a
separately priced market and are currently near-unbiased (-0.120 runs), so
"symmetric, and MEASURE that totals held" is the cheap version of that
requirement. If totals move here, the symmetry assumption is wrong and the term
must not ship.

SYNTHETIC ROSTERS, DELIBERATELY. Real roster artifacts are absent from both
production and the local mirror (`roster_objs` returns 0 files), and this is
measuring an ELASTICITY of the engine -- runs per unit of rate multiplier --
which is a property of the simulation, not of any particular roster. Both sides
are identical league-average teams, so at m=1.0 the expected margin is 0 by
construction and any departure is the effect being measured. What it CANNOT
establish is the value on real rosters; that needs a re-run against a real slate
before the default changes.

COMMON RANDOM NUMBERS. Every arm uses the same seed sequence, so the arms differ
only by the multiplier and the difference is not swamped by Monte-Carlo noise.

Run:  python scripts/calibrate_mlb_home_field.py --games 4000
"""

from __future__ import annotations

import argparse
import math
import pathlib
import random
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for p in (str(REPO), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sim_engine.models import (  # noqa: E402
    BatterProfile,
    GameConfig,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    PitchType,
    Player,
    Team,
    TeamRoster,
)
from sim_engine.simulate import simulate_game  # noqa: E402

TARGET_MARGIN_RUNS = 0.207


def _batter(pid: int) -> BatterProfile:
    return BatterProfile(
        player=Player(mlbam_id=pid, full_name=f"B{pid}", primary_position="1B",
                      bat_side=Handedness.R, throw_side=Handedness.R),
        k_rate=0.22, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035,
        inplay_hit_rate=0.275, xb_hit_share=0.28,
        sb_attempt_rate=0.02, sb_success_rate=0.72,
    )


def _pitcher(pid: int, stamina: int = 90) -> PitcherProfile:
    return PitcherProfile(
        player=Player(mlbam_id=pid, full_name=f"P{pid}", primary_position="P",
                      bat_side=Handedness.R, throw_side=Handedness.R),
        k_rate=0.24, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035,
        inplay_hit_rate=0.27,
        arsenal={PitchType.FF: 0.55, PitchType.SL: 0.25, PitchType.CH: 0.20},
        stamina_pitches=stamina,
    )


def _roster(team_id: int, abbr: str, base: int) -> TeamRoster:
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(batters=[_batter(base + i) for i in range(1, 10)],
                      pitcher=_pitcher(base + 100, stamina=95),
                      bench=[],
                      bullpen=[_pitcher(base + 200 + i, stamina=25) for i in range(8)]),
    )


def arm(mult: float, seeds: list[int]) -> dict:
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    margins, totals = [], []
    for s in seeds:
        cfg = GameConfig(rng_seed=s, home_field_offense_mult=mult)
        res = simulate_game(away, home, cfg)
        h, a = int(res.home_score or 0), int(res.away_score or 0)
        margins.append(h - a)
        totals.append(h + a)
    return {
        "mult": mult,
        "n": len(seeds),
        "margins": margins,
        "totals": totals,
        "margin": statistics.mean(margins),
        "margin_se": statistics.pstdev(margins) / math.sqrt(len(margins)),
        "total": statistics.mean(totals),
        "total_se": statistics.pstdev(totals) / math.sqrt(len(totals)),
    }


def paired(a: dict, b: dict, key: str) -> tuple[float, float]:
    """Mean and se of the PER-SEED difference b - a.

    THE PER-ARM STANDARD ERROR IS THE WRONG UNCERTAINTY HERE and the first cut
    of this script used it. Every arm replays the SAME seed sequence, so the two
    runs share almost all of their randomness and the difference is far better
    determined than either mean: on the 1,500-game run each arm's margin carried
    +/-0.17 while the effect being measured was 0.22, which made a real
    elasticity look like noise. Pairing removes the shared component.
    """
    d = [y - x for x, y in zip(a[key], b[key])]
    if not d:
        return float("nan"), float("nan")
    return statistics.mean(d), statistics.pstdev(d) / math.sqrt(len(d))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=4000)
    ap.add_argument("--mults", default="1.0,1.02,1.04,1.06")
    args = ap.parse_args()

    rng = random.Random(20260907)
    seeds = [rng.randint(1, 2**31 - 1) for _ in range(args.games)]
    mults = [float(x) for x in args.mults.split(",")]

    print(f"synthetic league-average rosters, identical both sides")
    print(f"{args.games} games per arm, COMMON RANDOM NUMBERS across arms\n")
    print(f"{'mult':>6s} {'margin':>9s} {'+/-':>6s} "
          f"{'d(marg)':>8s} {'+/-':>6s}  {'total':>7s} {'d(tot)':>8s} {'+/-':>6s}")
    print("       (d columns are PAIRED per-seed differences vs m=1.0 -- the "
          "arms share seeds)")

    base = None
    rows = []
    for m in mults:
        r = arm(m, seeds)
        if base is None:
            base = r
        dm, dm_se = paired(base, r, "margins")
        dt, dt_se = paired(base, r, "totals")
        rows.append((m, dm, dm_se, dt, dt_se, r))
        print(f"{m:6.3f} {r['margin']:+9.4f} {r['margin_se']:6.4f} "
              f"{dm:+8.4f} {dm_se:6.4f}  {r['total']:7.3f} {dt:+8.4f} {dt_se:6.4f}")

    z = abs(base["margin"]) / base["margin_se"] if base["margin_se"] else 0.0
    print(f"\nBASELINE AT m=1.0, IDENTICAL ROSTERS: margin {base['margin']:+.4f} "
          f"+/- {base['margin_se']:.4f}  ({z:.2f} sigma from zero)")
    if z > 2.0:
        print("  ** THE ENGINE CARRIES A STRUCTURAL SIDE TILT OF ITS OWN. **")
        print("  With identical teams the expected margin is the batting-order")
        print("  effect alone: the home side does not bat in the ninth when ahead,")
        print("  and a walk-off truncates the half-inning. Both are real baseball,")
        print("  so this is not automatically a defect.")
        print("  WHAT IT DOES NOT LICENSE is reading the distance from zero as the")
        print("  missing home advantage. The CALIBRATION TARGET is the real-roster")
        print("  gap (-0.186 predicted against +0.021 actual over 1,015 games), not")
        print("  this synthetic baseline. Conflating them would size the term")
        print("  against an artefact of equal rosters.")

    usable = [(m, dm, dse, dt, tse) for m, dm, dse, dt, tse, _r in rows if m != 1.0]
    if not usable or all(dm <= 0 for _m, dm, _s, _t, _ts in usable):
        print("\nUNMEASURED: no arm moved the margin.")
        return 1

    print(f"\nELASTICITY (paired), runs of margin per 1% of multiplier:")
    for m, dm, dse, _dt, _tse in usable:
        pct = (m - 1.0) * 100
        print(f"  m={m:.3f}  {dm / pct:+.4f} +/- {dse / pct:.4f} runs/%"
              f"   ({dm / dse:.1f} sigma)" if dse else "")

    pts = [(0.0, 0.0)] + [(m - 1.0, dm) for m, dm, _s, _t, _ts in usable]
    pts.sort()
    solved = float("nan")
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 <= TARGET_MARGIN_RUNS <= y1 and y1 > y0:
            solved = 1.0 + x0 + (x1 - x0) * (TARGET_MARGIN_RUNS - y0) / (y1 - y0)
            break
    else:
        x1, y1 = pts[-1]
        solved = 1.0 + x1 * TARGET_MARGIN_RUNS / y1 if y1 else float("nan")
        print("\n  (target outside the measured range -- extrapolated, weaker)")
    print(f"\nSOLVED for the measured +{TARGET_MARGIN_RUNS:.3f}-run deficit, by")
    print(f"interpolating between the BRACKETING arms rather than extrapolating a")
    print(f"far one (the elasticity is convex):  home_field_offense_mult ~= {solved:.4f}")

    # TOTALS: TEST THE TREND, NOT THE LARGEST ARM.
    #
    # The first cut of this check looked only at the biggest single |d(total)|
    # against a 3-sigma bar, and passed a drift of -0.053, -0.091, -0.155 across
    # rising multipliers as "held" at 2.20 sigma. Three readings moving the same
    # way with the parameter are not noise however small each one is -- the sign
    # pattern is the evidence, and a per-arm threshold is structurally blind to
    # it. Regress d(total) on (m - 1) and test the SLOPE.
    print(f"\nTOTALS CHECK -- the thing that must NOT move:")
    xs = [0.0] + [m - 1.0 for m, _dm, _s, _dt, _ts in usable]
    ys = [0.0] + [dt for _m, _dm, _s, dt, _ts in usable]
    n_pts = len(xs)
    mx = sum(xs) / n_pts
    my = sum(ys) / n_pts
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
    rse = (sum(r * r for r in resid) / max(n_pts - 2, 1)) ** 0.5
    slope_se = rse / (sxx ** 0.5) if sxx else float("inf")
    for m, _dm, _s, dt, tse in usable:
        print(f"  m={m:.3f}  d(total) {dt:+.4f} +/- {tse:.4f}")
    print(f"  TREND: d(total) per unit multiplier = {slope:+.3f} "
          f"+/- {slope_se:.3f}  ({abs(slope)/slope_se if slope_se else 0:.1f} sigma)")
    same_sign = all(dt < 0 for _m, _dm, _s, dt, _ts in usable) or \
                all(dt > 0 for _m, _dm, _s, dt, _ts in usable)
    projected = slope * (solved - 1.0) if solved == solved else float("nan")
    print(f"  PROJECTED totals shift at the solved m={solved:.4f}: "
          f"{projected:+.4f} runs")
    if same_sign and abs(slope) > 2 * slope_se:
        print("\n  ** TOTALS ARE COUPLED TO THIS TERM. The symmetric application")
        print("  REDUCES the coupling but does not remove it, and every arm moves")
        print("  the same way. A plausible mechanism: boosting the home side makes")
        print("  it lead more often, so the bottom of the ninth is skipped more")
        print("  often and total runs fall. That is real baseball, but it means")
        print("  adopting this term moves a SEPARATELY PRICED market.")
        print(f"  Today's full-game total bias is -0.120 runs; adding "
              f"{projected:+.3f}")
        print("  makes it worse, not better. Ship the default at 1.0 until the")
        print("  totals calibration is re-fitted to absorb it -- which is exactly")
        print("  what `model_engine_standard.md` means by paying for a mechanism. **")
    else:
        print("  no consistent trend -- symmetric application is doing its job.")
    print("\nSynthetic rosters measure the ENGINE's elasticity, not the value for")
    print("real teams. Re-run against a real slate before changing the default.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
