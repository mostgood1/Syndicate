#!/usr/bin/env python3
"""A/B the soccer MARKET PRIOR: `SYNDICATE_SOCCER_MARKET_PRIOR` off vs on.

WHAT IS BEING TESTED. `possession_priors._market_prior_index` reads
`market_features["total"]["line"]` and `["spread"]["home_line"]` and feeds the
result into `shot_generation_probability` at weight 0.02. Production has never
supplied `market_features`, so that index has returned a CONSTANT 0.5 for every
fixture ever simulated. This measures whether supplying it helps.

--------------------------------------------------------------------------
READ THIS BEFORE QUOTING THE NUMBER: IT IS A PROXY, AND HERE IS WHY
--------------------------------------------------------------------------
Production feeds REAL captured totals/spread lines. Those exist only for
2026-07-31..2026-09-20 (`odds_history`, 44 files). Match RESULTS exist only for
2023-07-28..2026-05-24 (`matches_*.csv`, 9,683 scored). The overlap is ZERO
matches, so the faithful backtest -- real lines graded against outcomes --
cannot be run today at all.

What the history DOES carry is closing `odds_home/draw/away` and
`odds_over_2_5/under_2_5` for every scored match. This script inverts those into
the two quantities the engine reads:

  total_line        <- de-vigged P(over 2.5), inverted through a Poisson to the
                       lambda that would price it. A totals line sits near the
                       market's expected goals, so lambda is the natural stand-in.
  spread_home_line  <- the home/away split of that same lambda which reproduces
                       the de-vigged 1X2 shape, expressed as the handicap that
                       levels the tie. Solved, not assumed.

So this measures the MECHANISM'S DIRECTION on a market-derived input of the
right shape. It does NOT measure the magnitude production would see: the proxy's
distribution is not the real lines' distribution (real lines put the index at
median 0.633, sd 0.201, measured 2026-09-07 over n=181).

PAIRED, and that is what makes it valid. Both arms use the SAME ratings, the
same fixtures and the same seeds; only `market_features` differs. Absolute Brier
here is not a statement about model quality -- ratings are computed per
(league, season) bucket and carry look-ahead -- but the DELTA isolates the
mechanism, because every other term is identical between the arms.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.soccer.features.loaders import (  # noqa: E402
    compute_team_ratings,
    team_rows_from_match_history,
)
from syndicate.features.soccer.sim_engine.soccersim.contracts import (  # noqa: E402
    SoccerSimSimulationInput,
)
from syndicate.features.soccer.sim_engine.soccersim.distribution import (  # noqa: E402
    simulate_match_distribution,
)
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import (  # noqa: E402
    get_league_profile,
)


def _data_root() -> Path:
    hosted = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(hosted) if hosted else (REPO / "data")


def _parse_date(text):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return dt.datetime.strptime((text or "").strip(), fmt).date()
        except Exception:
            pass
    return None


def _f(value):
    try:
        out = float(str(value).strip())
        return out if out > 0 else None
    except Exception:
        return None


def _devig(probabilities):
    total = sum(probabilities)
    return [p / total for p in probabilities] if total > 0 else probabilities


def _lambda_from_over25(p_over):
    """The Poisson mean that prices P(total > 2.5) at `p_over`.

    P(X >= 3) = 1 - e^-L (1 + L + L^2/2). Monotone in L, so bisect.
    """
    if not (0.02 < p_over < 0.98):
        return None
    lo, hi = 0.2, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        p = 1.0 - math.exp(-mid) * (1.0 + mid + mid * mid / 2.0)
        if p < p_over:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 4)


def _split_lambda(total_lambda, p_home, p_away):
    """Home/away split of `total_lambda` matching the 1X2 shape, as a handicap.

    Independent Poissons: solve for supremacy s = lh - la reproducing the
    de-vigged home-minus-away margin. Returned as the handicap that LEVELS the
    fixture (-s), which is the sign convention the odds feed uses -- a home
    favourite is quoted -0.5, not +0.5.
    """
    if total_lambda is None or p_home <= 0 or p_away <= 0:
        return None
    lo, hi = -3.0, 3.0
    for _ in range(40):
        s = (lo + hi) / 2.0
        lh = max(0.05, (total_lambda + s) / 2.0)
        la = max(0.05, (total_lambda - s) / 2.0)
        ph = pa = 0.0
        for h in range(0, 9):
            ph_term = math.exp(-lh) * lh ** h / math.factorial(h)
            for a in range(0, 9):
                pr = ph_term * (math.exp(-la) * la ** a / math.factorial(a))
                if h > a:
                    ph += pr
                elif a > h:
                    pa += pr
        if (ph - pa) < (p_home - p_away):
            lo = s
        else:
            hi = s
    return round(-((lo + hi) / 2.0), 4)


def load_matches(root):
    out = []
    pattern = str(root / "soccer_source" / "*" / "history" / "matches_*.csv")
    for path in sorted(glob.glob(pattern)):
        league = Path(path).parents[1].name
        for raw in csv.DictReader(open(path, encoding="utf-8-sig")):
            date = _parse_date(raw.get("date") or "")
            try:
                hg = int(float(raw.get("home_goals")))
                ag = int(float(raw.get("away_goals")))
            except Exception:
                continue
            oh, od, oa = _f(raw.get("odds_home")), _f(raw.get("odds_draw")), _f(raw.get("odds_away"))
            oo, ou = _f(raw.get("odds_over_2_5")), _f(raw.get("odds_under_2_5"))
            if not (date and oh and od and oa and oo and ou):
                continue
            row = dict(raw)
            row.update({"_league": league, "_date": date, "_hg": hg, "_ag": ag,
                        "_oh": oh, "_od": od, "_oa": oa, "_oo": oo, "_ou": ou})
            out.append(row)
    return out


def market_features_for(row):
    p_home, p_draw, p_away = _devig([1 / row["_oh"], 1 / row["_od"], 1 / row["_oa"]])
    p_over, _p_under = _devig([1 / row["_oo"], 1 / row["_ou"]])
    lam = _lambda_from_over25(p_over)
    if lam is None:
        return {}
    features = {"total": {"line": lam}}
    handicap = _split_lambda(lam, p_home, p_away)
    if handicap is not None:
        features["spread"] = {"home_line": handicap}
    return features


def _over_probability(dist):
    for name in ("over_2_5_probability", "over_2_5", "total_over_2_5_probability"):
        value = getattr(dist, name, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


_WORK = {}


def _init_worker(payload):
    """Ratings are large and identical for every task -- send them ONCE per
    process rather than pickling them with each match."""
    _WORK["ratings"] = payload


def _grade_one(task):
    """Simulate BOTH arms for one match. Runs in a worker process.

    The two arms share `seed`, and `simulate_match_distribution` derives its
    per-simulation seeds from it, so Monte-Carlo noise is COMMON MODE between
    the arms and largely cancels in the paired difference. That is what makes a
    modest simulation count usable here: the quantity being measured is the
    DIFFERENCE, not either arm's absolute probability.
    """
    key, home, away, date_s, league, hg, ag, mf, simulations = task
    ratings = _WORK["ratings"].get(key) or {}
    hr = ratings.get(home) or ratings.get(home.lower()) or {}
    ar = ratings.get(away) or ratings.get(away.lower()) or {}
    if not hr or not ar:
        return None
    try:
        profile = get_league_profile(league)
    except Exception:
        profile = get_league_profile("eredivisie")
    seed = abs(hash((home, away, date_s))) % 10_000_019
    arms = {}
    for arm, features in (("off", {}), ("on", mf)):
        sim_in = SoccerSimSimulationInput(
            home_team=home, away_team=away, seed=seed,
            home_attack_rating=float(hr.get("attack_rating") or 0.0),
            home_defense_rating=float(hr.get("defense_rating") or 0.0),
            away_attack_rating=float(ar.get("attack_rating") or 0.0),
            away_defense_rating=float(ar.get("defense_rating") or 0.0),
            feature_generation_payload={
                "team_metrics": {}, "defensive_metrics": {}, "set_piece_metrics": {},
                "possession_metrics": {}, "availability_metrics": {},
                "market_features": features,
            },
        )
        dist = simulate_match_distribution(sim_in, simulations=simulations, profile=profile)
        value = _over_probability(dist)
        if value is None:
            return None
        arms[arm] = value
    actual_over = 1 if (hg + ag) > 2.5 else 0
    return {
        "league": league, "date": date_s, "home": home, "away": away,
        "actual_goals": hg + ag, "actual_over": actual_over,
        "p_off": arms["off"], "p_on": arms["on"],
        "brier_off": (arms["off"] - actual_over) ** 2,
        "brier_on": (arms["on"] - actual_over) ** 2,
        "total_line": mf.get("total", {}).get("line"),
        "spread_home_line": mf.get("spread", {}).get("home_line"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="A/B the soccer market prior (off vs on).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sample", type=int, default=300, help="matches to grade (0 = all)")
    ap.add_argument("--simulations", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--json", default="")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2),
                    help="parallel processes; the sim is CPU-bound at ~8 matches/s/core")
    args = ap.parse_args()

    root = _data_root()
    matches = load_matches(root)
    if not matches:
        print("no scored matches with complete odds under %s -- cannot run" % root)
        return 2
    print("scored matches with complete closing odds: %d" % len(matches))
    print("date range: %s .. %s" % (min(m["_date"] for m in matches), max(m["_date"] for m in matches)))

    rng = random.Random(args.seed)
    sample = matches if args.sample <= 0 else rng.sample(matches, min(args.sample, len(matches)))
    print("grading %d matches at %d sims/arm" % (len(sample), args.simulations))

    buckets = defaultdict(list)
    for m in matches:
        buckets[(m["_league"], m.get("season") or "")].append(m)
    # `as_of` is REQUIRED by compute_team_ratings -- passing None raises. Use the
    # bucket's last match date, so a season's ratings are its end-of-season
    # ratings. That IS look-ahead, and it is why the absolute Brier below is not
    # a claim about model quality; both arms share the identical ratings object,
    # so the paired delta -- the thing being measured -- is unaffected.
    #
    # FAILURES ARE COUNTED, NOT SWALLOWED. An earlier version wrapped this in a
    # bare `except: {}` and every bucket silently became empty ratings; the run
    # reported "ZERO gradable matches" and looked like missing data rather than
    # a raised TypeError. A backtest that cannot tell "no data" from "I broke
    # it" is worse than no backtest.
    ratings_cache = {}
    ratings_errors = {}
    for key, rows in buckets.items():
        as_of = max((m["_date"] for m in rows), default=None)
        if as_of is None:
            ratings_errors[key] = "no dated rows"
            ratings_cache[key] = {}
            continue
        try:
            ratings_cache[key] = compute_team_ratings(
                team_rows_from_match_history(rows), as_of=as_of.isoformat(), allow_undated=True)
        except Exception as exc:
            ratings_errors[key] = "%s: %s" % (type(exc).__name__, exc)
            ratings_cache[key] = {}
    if ratings_errors:
        print("ratings FAILED for %d of %d bucket(s):" % (len(ratings_errors), len(buckets)))
        for key, err in list(ratings_errors.items())[:5]:
            print("   %s -> %s" % (key, err))
    rated = sum(1 for v in ratings_cache.values() if v)
    print("ratings built for %d of %d (league, season) buckets" % (rated, len(buckets)))
    if rated == 0:
        print("no ratings at all -- refusing to report a verdict built on nothing")
        return 5

    tasks = []
    no_features = 0
    for m in sample:
        mf = market_features_for(m)
        if not mf:
            no_features += 1
            continue
        tasks.append(((m["_league"], m.get("season") or ""), str(m.get("home_team") or ""),
                      str(m.get("away_team") or ""), str(m["_date"]), m["_league"],
                      m["_hg"], m["_ag"], mf, args.simulations))

    rows_out = []
    workers = max(1, int(args.workers))
    print("simulating %d matches x 2 arms x %d sims on %d worker(s)"
          % (len(tasks), args.simulations, workers), flush=True)
    if workers == 1:
        _init_worker(ratings_cache)
        results = (_grade_one(t) for t in tasks)
        for i, res in enumerate(results, 1):
            if res:
                rows_out.append(res)
            if i % 50 == 0:
                print("  ... %d/%d graded=%d" % (i, len(tasks), len(rows_out)), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(ratings_cache,)) as pool:
            for i, res in enumerate(pool.map(_grade_one, tasks, chunksize=4), 1):
                if res:
                    rows_out.append(res)
                if i % 50 == 0:
                    print("  ... %d/%d graded=%d" % (i, len(tasks), len(rows_out)), flush=True)
    no_ratings = len(tasks) - len(rows_out)

    if not rows_out:
        print("ZERO gradable matches (no_ratings=%d no_features=%d) -- no verdict"
              % (no_ratings, no_features))
        return 3

    b_off = [r["brier_off"] for r in rows_out]
    b_on = [r["brier_on"] for r in rows_out]
    diffs = [on - off for on, off in zip(b_on, b_off)]
    n = len(diffs)
    mean_d = statistics.mean(diffs)
    sd_d = statistics.pstdev(diffs) if n > 1 else 0.0
    t = (mean_d / (sd_d / math.sqrt(n))) if sd_d > 0 else 0.0
    moved = sum(1 for r in rows_out if abs(r["p_on"] - r["p_off"]) > 1e-9)

    print("")
    print("GRADED n=%d   dropped: no_ratings=%d no_features=%d" % (n, no_ratings, no_features))
    print("  arms differ on %d of %d  -- if this is 0 the mechanism is INERT and nothing below means anything" % (moved, n))
    print("  Brier OFF : %.5f" % statistics.mean(b_off))
    print("  Brier ON  : %.5f" % statistics.mean(b_on))
    print("  delta     : %+.5f   (NEGATIVE = ON is better)" % mean_d)
    print("  paired t  : %+.3f   sd=%.5f" % (t, sd_d))
    print("  mean |p_on - p_off| : %.5f" % statistics.mean(abs(r["p_on"] - r["p_off"]) for r in rows_out))
    print("")
    print("PROXY, not production's input -- see the module docstring. Results and real")
    print("captured lines have ZERO overlapping matches, so this measures the mechanism's")
    print("DIRECTION, never the magnitude production would see.")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "n": n, "brier_off": statistics.mean(b_off), "brier_on": statistics.mean(b_on),
            "delta": mean_d, "paired_t": t, "arms_differ": moved,
            "simulations": args.simulations, "sample": args.sample,
            "dropped": {"no_ratings": no_ratings, "no_features": no_features},
            "caveat": ("proxy market_features inverted from closing 1X2 + over/under 2.5; "
                       "ZERO overlap between match results and real captured lines"),
            "rows": rows_out,
        }, indent=2), encoding="utf-8")
        print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
