"""Does the home-field elasticity measured on TOY rosters hold on REAL ones?

WHAT IS BEING CHECKED, and why it is the last open question on this term.
`scripts/calibrate_mlb_home_field.py` solved `home_field_offense_mult ~= 1.0096`
by measuring how many runs of margin a 1% multiplier buys -- **on synthetic
rosters where both sides are identical league-average teams**. The TARGET it was
solving for (+0.207 runs) came from 1,015 REAL games. Mixing them assumes the
engine responds to the multiplier the same way on real teams as on toy ones, and
that assumption has a concrete way to fail:

    toy roster   every batter hr_rate 0.035, inplay 0.275
    real roster  hr_rate 0.0037 .. 0.0694 (19x), inplay spread to match

The rates are multiplied and then CLAMPED (`_clamp_rate(hr, 0.002, 0.12)`,
`inplay` to 0.10-0.45). A clamp that never binds on a uniform toy lineup can
bind on a real one's extremes, and a multiplier whose effect is partly clipped
delivers less margin per percent than the toy measurement promises. The
direction of that error is knowable in advance -- real elasticity <= toy
elasticity -- but the SIZE is not, and the size is what decides whether 1.0096
is the right number.

DESIGN.
  * Real slate, real probable pitchers, rosters as of that date.
  * The SAME arms and the SAME paired common-random-numbers scheme as the toy
    calibrator, so the two elasticities are directly comparable and any
    difference is the rosters rather than the method.
  * Rosters are cached to disk: building one takes ~27s of API calls, and the
    point is to spend that once and then vary only the multiplier.

WHAT IT CANNOT SETTLE. A real slate has real home/away teams of differing
quality, so the BASELINE margin is not zero and carries no information about the
term. Only the DIFFERENCE between arms is read here.

Run:
    python scripts/validate_home_field_real_slate.py --date 2026-07-15 \
        --games 10 --sims 300
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import pickle
import random
import statistics
import sys
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for _p in (str(REPO), str(VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sim_engine.data.build_roster import build_team, build_team_roster  # noqa: E402
from sim_engine.data.statsapi import StatsApiClient  # noqa: E402
from sim_engine.models import GameConfig  # noqa: E402
from sim_engine.simulate import simulate_game  # noqa: E402

CACHE = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "mlb_real_rosters"

# From `calibrate_mlb_home_field.py` at 6,000 games/arm on synthetic rosters.
TOY_ELASTICITY = {1.01: 0.2158, 1.02: 0.1878, 1.04: 0.1725}   # runs of margin per 1%
TARGET_MARGIN_RUNS = 0.207


def schedule(date: str) -> list[dict]:
    url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
           f"&hydrate=probablePitcher,team")
    with urllib.request.urlopen(url, timeout=60) as resp:
        doc = json.load(resp)
    out = []
    for day in doc.get("dates") or []:
        for g in day.get("games") or []:
            teams = g.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            ht, at = home.get("team") or {}, away.get("team") or {}
            if not ht.get("id") or not at.get("id"):
                continue
            out.append({
                "gamePk": g.get("gamePk"),
                "home_id": int(ht["id"]), "home_name": ht.get("name"),
                "home_abbr": ht.get("abbreviation") or "HOM",
                "away_id": int(at["id"]), "away_name": at.get("name"),
                "away_abbr": at.get("abbreviation") or "AWY",
                "home_pp": ((home.get("probablePitcher") or {}).get("id")),
                "away_pp": ((away.get("probablePitcher") or {}).get("id")),
            })
    return out


def roster_for(client, team_id, name, abbr, season, date, probable):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / f"{season}_{date}_{team_id}_{probable or 0}.pkl"
    if key.is_file():
        try:
            with key.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass
    roster = build_team_roster(
        client, build_team(int(team_id), str(name), str(abbr)), int(season),
        as_of_date=date,
        probable_pitcher_id=int(probable) if probable else None,
        fast_mode=True,
    )
    try:
        with key.open("wb") as fh:
            pickle.dump(roster, fh)
    except Exception:
        pass
    return roster


def measure_slate(date, n_games, n_sims, mults, client):
    """One slate's paired elasticity. Returns None when the slate is unusable."""
    season = int(date[:4])
    games = schedule(date)[:n_games]
    if not games:
        print(f"  {date}: NO GAMES (All-Star break or off day) -- UNMEASURED")
        return None
    built = []
    t0 = time.time()
    for g in games:
        try:
            home = roster_for(client, g["home_id"], g["home_name"], g["home_abbr"],
                              season, date, g["home_pp"])
            away = roster_for(client, g["away_id"], g["away_name"], g["away_abbr"],
                              season, date, g["away_pp"])
        except Exception as exc:
            print(f"    skip {g['away_abbr']}@{g['home_abbr']}: "
                  f"{type(exc).__name__}: {str(exc)[:60]}")
            continue
        built.append((g, away, home))
    if not built:
        print(f"  {date}: no rosters built -- UNMEASURED")
        return None
    print(f"  {date}: {len(built)} games, rosters ready ({time.time()-t0:.0f}s)",
          flush=True)

    rng = random.Random(20260908)
    seeds = [rng.randint(1, 2**31 - 1) for _ in range(n_sims)]
    margins = {m: [] for m in mults}
    totals = {m: [] for m in mults}
    for g, away, home in built:
        for m in mults:
            for s in seeds:
                res = simulate_game(away, home,
                                    GameConfig(rng_seed=s, home_field_offense_mult=m))
                h, a = int(res.home_score or 0), int(res.away_score or 0)
                margins[m].append(h - a)
                totals[m].append(h + a)
    print(f"  {date}: simulated ({time.time()-t0:.0f}s)", flush=True)

    base = mults[0]
    out = {"date": date, "games": len(built), "sims": n_sims, "arms": {}}
    hrs = [b.hr_rate for _g, a, h in built for r in (a, h) for b in r.lineup.batters]
    out["hr_rate_sd"] = statistics.pstdev(hrs)
    for m in mults:
        if m == base:
            continue
        dm_pairs = [y - x for x, y in zip(margins[base], margins[m])]
        dt_pairs = [y - x for x, y in zip(totals[base], totals[m])]
        pct = (m - base) * 100
        dm = statistics.mean(dm_pairs)
        dm_se = statistics.pstdev(dm_pairs) / math.sqrt(len(dm_pairs))
        out["arms"][m] = {
            "elasticity": dm / pct, "elasticity_se": dm_se / pct,
            "d_total": statistics.mean(dt_pairs),
            "d_total_se": statistics.pstdev(dt_pairs) / math.sqrt(len(dt_pairs)),
            "n_pairs": len(dm_pairs),
        }
    return out


def pool(values, errs):
    """Inverse-variance pooled mean, its se, and a heterogeneity chi-square.

    POOLING SLATES THAT DISAGREE WOULD BE ITS OWN ERROR -- it would report a
    tight interval around a number no single slate supports. So Q is computed
    alongside: under the null that every slate measures the SAME elasticity, Q
    is chi-square with (k-1) degrees of freedom, and Q >> k-1 means the slates
    are measuring different things and the pooled value is not meaningful.
    """
    w = [1.0 / (e * e) for e in errs if e > 0]
    v = [x for x, e in zip(values, errs) if e > 0]
    if not w:
        return float("nan"), float("nan"), float("nan"), 0
    mean = sum(wi * xi for wi, xi in zip(w, v)) / sum(w)
    se = math.sqrt(1.0 / sum(w))
    q = sum(wi * (xi - mean) ** 2 for wi, xi in zip(w, v))
    return mean, se, q, len(v) - 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None, help="single slate (back-compat)")
    ap.add_argument("--dates", default=None, help="comma-separated slates to pool")
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--sims", type=int, default=400)
    ap.add_argument("--mults", default="1.0,1.01,1.02")
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

    dates = [d.strip() for d in (args.dates or args.date or "2026-07-20").split(",")
             if d.strip()]
    mults = [float(x) for x in args.mults.split(",")]
    client = StatsApiClient()

    print(f"slates: {dates}   {args.games} games each, {args.sims} sims/arm/game\n")
    results = []
    for d in dates:
        r = measure_slate(d, args.games, args.sims, mults, client)
        if r:
            results.append(r)
    if not results:
        print("\nUNMEASURED: no slate produced a reading.")
        return 1

    print(f"\n{'slate':>12s} {'games':>6s} {'hr sd':>7s}", end="")
    for m in mults[1:]:
        print(f"   {('m=%.3f' % m):>18s}", end="")
    print()
    for r in results:
        print(f"{r['date']:>12s} {r['games']:6d} {r['hr_rate_sd']:7.4f}", end="")
        for m in mults[1:]:
            a = r["arms"][m]
            print(f"   {a['elasticity']:+8.4f} +/-{a['elasticity_se']:.4f}", end="")
        print()

    print(f"\nPOOLED ELASTICITY (inverse-variance), runs of margin per 1%:")
    verdict = {}
    for m in mults[1:]:
        vals = [r["arms"][m]["elasticity"] for r in results]
        errs = [r["arms"][m]["elasticity_se"] for r in results]
        mean, se, q, df = pool(vals, errs)
        toy = TOY_ELASTICITY.get(m)
        line = (f"  m={m:.3f}   pooled {mean:+.4f} +/- {se:.4f}   "
                f"(Q={q:.1f}, df={df}")
        if df > 0:
            line += f" -> {'HETEROGENEOUS, do not pool' if q > 2 * df + 2 else 'slates agree'}"
        line += ")"
        if toy is not None:
            line += f"   toy {toy:+.4f}  ({(mean - toy)/se:+.1f} sigma)"
        print(line)
        verdict[m] = (mean, se, q, df)

    m0 = mults[1]
    mean, se, q, df = verdict[m0]
    if mean and mean > 0:
        solved = 1.0 + (TARGET_MARGIN_RUNS / mean) / 100
        lo = 1.0 + (TARGET_MARGIN_RUNS / (mean + se)) / 100
        hi = 1.0 + (TARGET_MARGIN_RUNS / (mean - se)) / 100 if mean > se else float("nan")
        print(f"\nSOLVED MULTIPLIER for the +{TARGET_MARGIN_RUNS:.3f}-run deficit,")
        print(f"from the POOLED real elasticity at m={m0:.3f}:  {solved:.4f}"
              f"   (1 se: {lo:.4f} .. {hi:.4f})")
        print(f"  toy said 1.0096; the single 2026-07-20 slate said 1.0170")
        if df > 0 and q > 2 * df + 2:
            print(f"\n  ** THE SLATES DISAGREE (Q={q:.1f} on df={df}). The pooled")
            print(f"  number is not meaningful -- something varies BETWEEN slates")
            print(f"  that this design treats as fixed. Do not adopt it. **")

    print(f"\nTOTALS, pooled across slates:")
    for m in mults[1:]:
        vals = [r["arms"][m]["d_total"] for r in results]
        errs = [r["arms"][m]["d_total_se"] for r in results]
        mean, se, q, df = pool(vals, errs)
        print(f"  m={m:.3f}   {mean:+.4f} +/- {se:.4f}   ({abs(mean)/se:.1f} sigma "
              f"from zero)" if se else "")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    print(f"\nBASELINE NOTE: a real slate has teams of differing quality, so raw "
          f"margins\nare not centred on zero. Only the paired DIFFERENCES are read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
