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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default="2026-07-15")
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--mults", default="1.0,1.01,1.02")
    args = ap.parse_args()

    season = int(args.date[:4])
    games = schedule(args.date)[: args.games]
    if not games:
        print(f"UNMEASURED: no games on {args.date}")
        return 1
    print(f"slate {args.date}: {len(games)} games, {args.sims} sims/arm/game")

    client = StatsApiClient()
    built = []
    t0 = time.time()
    for g in games:
        try:
            home = roster_for(client, g["home_id"], g["home_name"], g["home_abbr"],
                              season, args.date, g["home_pp"])
            away = roster_for(client, g["away_id"], g["away_name"], g["away_abbr"],
                              season, args.date, g["away_pp"])
        except Exception as exc:
            print(f"  skip {g['away_abbr']}@{g['home_abbr']}: "
                  f"{type(exc).__name__}: {str(exc)[:70]}")
            continue
        built.append((g, away, home))
        print(f"  {g['away_abbr']}@{g['home_abbr']}  rosters ready "
              f"({time.time() - t0:.0f}s)", flush=True)
    if not built:
        print("UNMEASURED: no rosters built")
        return 1

    # How much do these real rosters actually differ from the toy uniform one?
    hrs = [b.hr_rate for _g, a, h in built for r in (a, h) for b in r.lineup.batters]
    print(f"\nreal batter hr_rate across the slate: {min(hrs):.4f}..{max(hrs):.4f} "
          f"(sd {statistics.pstdev(hrs):.4f})   toy roster was a constant 0.0350")

    mults = [float(x) for x in args.mults.split(",")]
    rng = random.Random(20260908)
    seeds = [rng.randint(1, 2**31 - 1) for _ in range(args.sims)]

    # margins[m] is one entry per (game, seed) -- the pairing key
    margins: dict[float, list[float]] = {m: [] for m in mults}
    totals: dict[float, list[float]] = {m: [] for m in mults}
    for g, away, home in built:
        for m in mults:
            for s in seeds:
                res = simulate_game(away, home,
                                    GameConfig(rng_seed=s, home_field_offense_mult=m))
                h, a = int(res.home_score or 0), int(res.away_score or 0)
                margins[m].append(h - a)
                totals[m].append(h + a)
        print(f"  simulated {g['away_abbr']}@{g['home_abbr']} "
              f"({time.time() - t0:.0f}s)", flush=True)

    base = mults[0]
    print(f"\n{'mult':>6s} {'margin':>9s} {'d(marg)':>9s} {'+/-':>6s} "
          f"{'runs/%':>9s} {'+/-':>7s}   {'d(total)':>9s} {'+/-':>6s}")
    real_elastic = {}
    for m in mults:
        dm_pairs = [y - x for x, y in zip(margins[base], margins[m])]
        dt_pairs = [y - x for x, y in zip(totals[base], totals[m])]
        dm = statistics.mean(dm_pairs)
        dm_se = statistics.pstdev(dm_pairs) / math.sqrt(len(dm_pairs)) if dm_pairs else float("nan")
        dt = statistics.mean(dt_pairs)
        dt_se = statistics.pstdev(dt_pairs) / math.sqrt(len(dt_pairs)) if dt_pairs else float("nan")
        pct = (m - base) * 100
        e = dm / pct if pct else float("nan")
        e_se = dm_se / pct if pct else float("nan")
        if pct:
            real_elastic[m] = (e, e_se)
        print(f"{m:6.3f} {statistics.mean(margins[m]):+9.4f} {dm:+9.4f} {dm_se:6.4f} "
              f"{e:+9.4f} {e_se:7.4f}   {dt:+9.4f} {dt_se:6.4f}")

    print(f"\nREAL vs TOY elasticity (runs of margin per 1% of multiplier):")
    verdict_lines = []
    for m, (e, e_se) in real_elastic.items():
        toy = TOY_ELASTICITY.get(m)
        if toy is None:
            continue
        z = (e - toy) / e_se if e_se else float("nan")
        verdict_lines.append((m, e, e_se, toy, z))
        print(f"  m={m:.3f}   real {e:+.4f} +/- {e_se:.4f}   toy {toy:+.4f}   "
              f"difference {e - toy:+.4f}  ({z:+.2f} sigma)")

    if verdict_lines:
        m, e, e_se, toy, z = verdict_lines[0]
        solved_real = 1.0 + (TARGET_MARGIN_RUNS / e) / 100 if e else float("nan")
        solved_toy = 1.0 + (TARGET_MARGIN_RUNS / toy) / 100 if toy else float("nan")
        print(f"\nSOLVED MULTIPLIER for the +{TARGET_MARGIN_RUNS:.3f}-run deficit")
        print(f"  from the REAL elasticity at m={m:.3f}:  {solved_real:.4f}")
        print(f"  from the TOY  elasticity at m={m:.3f}:  {solved_toy:.4f}")
        if abs(z) < 2.0:
            print(f"\n  The two agree within {abs(z):.1f} sigma. The toy calibration "
                  f"TRANSFERS, and\n  1.0096 stands as the value to adopt.")
        else:
            print(f"\n  ** THEY DISAGREE at {abs(z):.1f} sigma. The toy calibration "
                  f"does NOT transfer;\n  use the real-roster number. **")
    print(f"\nBASELINE NOTE: a real slate has teams of differing quality, so the "
          f"margin\ncolumn is not centred on zero and carries no information about "
          f"the term.\nOnly the paired DIFFERENCES above are read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
