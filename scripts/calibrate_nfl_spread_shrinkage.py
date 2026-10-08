"""Tune a shrinkage constant for the NFL prop model's SPREAD, out of sample.

WHY THIS EXISTS. `player_stats.player_rate` returns
`statistics.pstdev(values)` over as few as TWO games and nothing shrinks it.
Measured 2026-09-28 by back-deriving the model's own implied sd from its served
rows (`sigma = (projected - line) / z(model_prob_over)`):

    Rushing Attempts 0.97   Receptions 0.70   Passing Yards 23.86

An implied sd of 0.97 on rushing ATTEMPTS says a back's carry count is known to
within one carry. The consequence reaches the board: 86% of NFL model edges
exceed `layer2_board._MODEL_EDGE_MAX_POINTS` (15 probability points) and are
dropped, so the model reaches 3% of served rows against NCAAF's 55%.

`#471` ESTABLISHED THIS EXACT DEFECT FOR THE MEAN AND FIXED IT. The raw
per-player MLE underestimates `anytime_td` at small n, fixed with Gamma-Poisson
shrinkage whose `ANYTIME_TD_SHRINKAGE_K = 12.0` was swept and selected by
`calibrate_nfl_anytime_td_shrinkage.py`. **The identical argument for the SPREAD
of every other market was never made.** This script makes it, in the same shape.

TWO ARMS, because two things are wrong with that one line and they must be
separable or a win cannot be attributed:

  * `pstdev` -> `stdev`. Population sd (/n) where a SAMPLE sd (/n-1) is wanted.
    Understates 29.3% at n=2 and 18.4% at n=3, and `player_rate` filters
    `week < week`, so n IS 3 at week 4.
  * shrinkage toward a league prior: `(n*raw + k*prior) / (n+k)`, the same
    formula `shrink_count_mean` already uses for the mean.

METHOD, mirroring `backtest_nfl_props.py`'s discipline.

  * **No lookahead anywhere.** A row's estimate uses only games with
    `week < w`, and the league prior for `(season, week, stat)` pools ONLY
    prior seasons plus this season's pre-week games.
  * **NOT gated on real odds.** Real quoted props exist for ~13 sparse weeks
    (2025 wk10-22) with no historical backfill, so an odds-gated sweep would
    select a constant on a tiny recency-biased slice. Every row is graded
    against the REAL SETTLED OUTCOME from nflverse play-by-play.
  * **Scored through the PRODUCTION function.** `_nfl_prop_model_probability`
    is called directly rather than a Normal re-implemented here, so the sweep
    measures the consumer that actually ships -- including its
    `_COVER_PROBABILITY_BLEND_WEIGHT` log-normal blend.
  * **Lines are a LADDER, not one point.** Half-integer thresholds spanning the
    plausible quoting range, so the constant is not fitted to whatever single
    line a market happened to post.
  * **SELECT on the fit seasons, REPORT on the held-out ones.** A number chosen
    and reported on the same seasons is not a measurement.

WHAT THIS SCRIPT DOES NOT DO: it does not change production, and it does not
re-fit `_COVER_PROBABILITY_BLEND_WEIGHT`. That table was calibrated ON TOP OF
the current too-narrow sd, so shipping a wider sd without re-fitting it is
exactly the interaction `docs/ai_context/model_engine_standard.md` warns about
(two mechanisms together produced a NEGATIVE interaction in 4 of 4 markets).
The blend re-fit is a REQUIRED follow-on, not an optional polish.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats as ps  # noqa: E402
from syndicate.features.nfl.props import _nfl_prop_model_probability  # noqa: E402

# `anytime_td` is excluded: it has no line and no distribution -- its own rate IS
# the probability, and `#471` already shrank it. Shrinking a spread it never uses
# would be a no-op reported as a win.
SWEPT_STATS = (
    "passing_yards", "passing_attempts", "passing_tds",
    "rushing_yards", "rushing_attempts",
    "receiving_yards", "receptions", "interceptions",
)

# Where markets actually quote, in units of the league prior sd. A ladder rather
# than one line, so k is not fitted to a single threshold.
LADDER_SPAN_SDS = 1.5
LADDER_STEPS = 7

MIN_PRIOR_GAMES_FOR_POOL = 4

# The STATIC league CV table a production build would actually carry, derived
# from the FIT seasons only (2022-2023). The sweep's own `stdev_cv` arm uses a
# prior recomputed per (season, week) from the no-lookahead pool; production
# cannot do that, so this arm exists to prove the constant survives the switch to
# a frozen table rather than assuming it does.
STATIC_LEAGUE_CV: dict[str, float] = {
    "passing_yards": 0.4256,
    "passing_attempts": 0.4281,  # re-derived 2026-10-08 on OFFICIAL attempts (sacks excluded); was 0.5444
    "passing_tds": 0.9354,
    "rushing_yards": 1.2271,
    "rushing_attempts": 0.9129,
    "receiving_yards": 0.9424,
    "receptions": 0.7092,
    "interceptions": 1.2766,
}

# z for a two-sided 80% interval. Named rather than inlined because the whole
# point of reporting coverage is that the number means something exact.
Z80 = 1.2815515655446004


def _sd_prior_pool(values_by_player: dict[str, list[float]]) -> float | None:
    """Median per-player SAMPLE sd -- the league's typical game-to-game spread.

    Median, not mean: a handful of players with one enormous game would drag a
    mean prior upward and quietly widen every other player's distribution.
    """
    sds = [statistics.stdev(v) for v in values_by_player.values()
           if len(v) >= MIN_PRIOR_GAMES_FOR_POOL]
    sds = [s for s in sds if s == s and s > 0]
    return statistics.median(sds) if sds else None


def season_logs(season: int) -> dict[str, dict[int, dict[str, float]]]:
    """`{player_id: {week: {stat: total}}}` in ONE pass over the season's plays.

    `player_game_log` re-scans every play for each player, which is O(players x
    plays) and unusable across four seasons. This aggregates every player at
    once and is otherwise the same computation -- the same `_STAT_EXTRACTORS`,
    and the same rule that a row exists only for a game the player has a
    qualifying play in.
    """
    out: dict[str, dict[int, dict[str, float]]] = defaultdict(dict)
    for play in ps.load_player_plays(season):
        week = play["week"]
        for pid in {play.get("passer_player_id"), play.get("rusher_player_id"),
                    play.get("receiver_player_id")}:
            if not pid:
                continue
            weeks = out[pid]
            row = weeks.get(week)
            if row is None:
                row = {stat: 0.0 for stat in SWEPT_STATS}
                weeks[week] = row
            for stat in SWEPT_STATS:
                row[stat] += ps._STAT_EXTRACTORS[stat](play, pid)  # noqa: SLF001
    return dict(out)


def collect(seasons: list[int], stats: list[str], min_week: int) -> list[dict[str, Any]]:
    """One observation per (season, week, player, stat). NO LOOKAHEAD.

    An observation carries the raw estimates a production row would have had at
    that moment, the league prior available at that moment, and the outcome that
    actually happened. Candidate constants are applied afterwards, so the
    expensive pass over play-by-play runs exactly once.
    """
    logs = {s: season_logs(s) for s in seasons}
    for s in seasons:
        print(f"  season {s}: {len(logs[s])} players", flush=True)

    obs: list[dict[str, Any]] = []
    for season in seasons:
        by_player = logs[season]
        weeks = sorted({w for wk in by_player.values() for w in wk})
        # Prior seasons contribute ENTIRELY -- they are wholly in the past. The
        # current season contributes only weeks strictly before w.
        prior_seasons = [s for s in seasons if s < season]
        prior_values: dict[str, dict[str, list[float]]] = {}
        for stat in stats:
            acc: dict[str, list[float]] = {}
            for ps_season in prior_seasons:
                for pid, wk in logs[ps_season].items():
                    acc[f"{ps_season}:{pid}"] = [r[stat] for r in wk.values()]
            prior_values[stat] = acc

        for w in weeks:
            if w < min_week:
                continue
            for stat in stats:
                pool = dict(prior_values[stat])
                for pid, wk in by_player.items():
                    vals = [r[stat] for week, r in wk.items() if week < w]
                    if vals:
                        pool[f"{season}:{pid}"] = vals
                prior_sd = _sd_prior_pool(pool)
                if prior_sd is None:
                    continue
                # The league's typical COEFFICIENT OF VARIATION for this stat,
                # from the same no-lookahead pool. Multiplied by a row's own mean
                # it gives a usage-scaled prior.
                cvs = []
                for vals_p in pool.values():
                    if len(vals_p) >= MIN_PRIOR_GAMES_FOR_POOL:
                        m = statistics.fmean(vals_p)
                        sd_p = statistics.stdev(vals_p)
                        if m > 0 and sd_p > 0:
                            cvs.append(sd_p / m)
                prior_cv = statistics.median(cvs) if cvs else None
                if prior_cv is None:
                    continue
                for pid, wk in by_player.items():
                    if w not in wk:
                        continue
                    vals = [r[stat] for week, r in wk.items() if week < w]
                    if len(vals) < 2:
                        continue
                    obs.append({
                        "season": season, "week": w, "player_id": pid, "stat": stat,
                        "n": len(vals),
                        "mean": statistics.fmean(vals),
                        "raw_pstdev": statistics.pstdev(vals),
                        "raw_stdev": statistics.stdev(vals),
                        "prior_sd": prior_sd,
                        "prior_cv": prior_cv,
                        "actual": wk[w][stat],
                    })
    return obs


def ladder(mean: float, prior_sd: float) -> list[float]:
    """Half-integer thresholds where a market would plausibly quote."""
    lo = mean - LADDER_SPAN_SDS * prior_sd
    hi = mean + LADDER_SPAN_SDS * prior_sd
    if not (hi > lo):
        return []
    step = (hi - lo) / max(1, LADDER_STEPS - 1)
    out: list[float] = []
    for i in range(LADDER_STEPS):
        line = math.floor(lo + i * step) + 0.5
        if line > 0 and line not in out:
            out.append(line)
    return out


def _prior_for(o: dict[str, Any], estimator: str) -> float:
    """The prior this arm shrinks toward.

    `stdev_cv` EXISTS BECAUSE A FLAT PER-STAT PRIOR IS THE WRONG SHAPE, and that
    was measured rather than argued. The league-median per-player sd for
    `rushing_yards` over 2022-23 is 10.2, computed across 564 "rushers" who are
    mostly marginal; a workhorse back's own sd is ~25. Shrinking him toward 10.2
    makes him NARROWER, which is the opposite of the intent -- and on the
    high-usage population the board actually quotes, flat-prior shrinkage was
    monotonically harmful in both Brier and coverage (cov80 0.7356 at k=0 down to
    0.5557 at k=20).

    A prior proportional to the player's OWN mean carries the usage level with
    it, so a starter is shrunk toward a starter-sized spread.
    """
    if estimator == "stdev_cv":
        return o["prior_cv"] * o["mean"]
    if estimator == "stdev_cv_static":
        return STATIC_LEAGUE_CV.get(o["stat"], 0.0) * o["mean"]
    return o["prior_sd"]


def scorable(o: dict[str, Any], *, k: float, estimator: str) -> bool:
    """Would production attach a probability to this row under these settings?

    `_nfl_prop_model_probability` returns None when `stdev <= 0`, so a player
    whose prior games are all identical gets NO probability at all today.
    """
    raw = o["raw_pstdev"] if estimator == "pstdev" else o["raw_stdev"]
    n = o["n"]
    prior = _prior_for(o, estimator)
    sd = (n * raw + k * prior) / (n + k) if (n + k) > 0 else raw
    return sd > 0


def score(obs: list[dict[str, Any]], *, k: float, estimator: str,
          only: set[int] | None = None) -> dict[str, Any]:
    """Brier through the PRODUCTION probability function, plus 80% coverage.

    Coverage is reported alongside because it is the interpretable one: "too
    narrow" means the realised value falls outside the model's own 80% interval
    far more often than 20% of the time, and that says so in a single number a
    reader can check against 0.80 without knowing what a good Brier looks like.

    `only` PINS THE POPULATION, and without it this comparison is invalid.
    Measured on the first pilot: the k=0 arm scored 11,038 cells and the k=4 arm
    15,659, because shrinkage gives a positive sd to players whose prior games
    were all identical -- rows production drops entirely. Comparing those two
    Briers compares two different populations, and the extra rows are exactly
    the degenerate ones, so the difference could be wholly composition. Rescuing
    them is a real benefit, but it is reported as a COUNT (`rows_rescued`), never
    folded into the score.
    """
    sq = 0.0
    cells = 0
    inside = 0
    counted = 0
    # CALIBRATION BY PREDICTED-PROBABILITY BUCKET -- the platform's own bar
    # (`#499`: worst POWERED bucket gap vs 0.150). Brier and 80% coverage can
    # disagree (they did: Brier bottoms at k=8 while coverage passes 0.80 at
    # k~1.5), and a single aggregate cannot say WHERE a model is wrong. This can.
    buckets = [[0.0, 0] for _ in range(10)]
    for i, o in enumerate(obs):
        if only is not None and i not in only:
            continue
        raw = o["raw_pstdev"] if estimator == "pstdev" else o["raw_stdev"]
        n = o["n"]
        prior = _prior_for(o, estimator)
        sd = (n * raw + k * prior) / (n + k) if (n + k) > 0 else raw
        if sd <= 0:
            continue
        counted += 1
        if abs(o["actual"] - o["mean"]) <= Z80 * sd:
            inside += 1
        for line in ladder(o["mean"], o["prior_sd"]):
            p = _nfl_prop_model_probability(stat=o["stat"], mean=o["mean"],
                                            stdev=sd, n=n, line=line)
            if p is None:
                continue
            hit = 1.0 if o["actual"] > line else 0.0
            sq += (p - hit) ** 2
            cells += 1
            b = buckets[min(9, int(p * 10))]
            b[0] += hit
            b[1] += 1
    MIN_BUCKET_N = 30
    calib = []
    worst_gap = None
    for idx, (hits, n_b) in enumerate(buckets):
        if n_b <= 0:
            continue
        predicted = (idx + 0.5) / 10.0
        realised = hits / n_b
        powered = n_b >= MIN_BUCKET_N
        gap = abs(predicted - realised)
        calib.append({"bucket": f"{idx/10:.1f}-{(idx+1)/10:.1f}", "n": n_b,
                      "predicted": round(predicted, 3), "realised": round(realised, 4),
                      "gap": round(gap, 4), "powered": powered})
        if powered and (worst_gap is None or gap > worst_gap):
            worst_gap = gap
    return {
        "k": k, "estimator": estimator,
        "brier": round(sq / cells, 6) if cells else None,
        "cells": cells, "rows": counted,
        "coverage_80": round(inside / counted, 4) if counted else None,
        "worst_powered_bucket_gap": round(worst_gap, 4) if worst_gap is not None else None,
        "calibration": calib,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--fit-seasons", default="2022,2023")
    parser.add_argument("--candidates", default="0,1,2,3,4,6,8,10,12,15,20,25,30")
    parser.add_argument("--min-week", type=int, default=3)
    parser.add_argument("--stats", default=",".join(SWEPT_STATS))
    parser.add_argument("--out", default="")
    parser.add_argument("--cache", default="",
                        help="JSON path: reuse a previous collection instead of "
                             "re-reading four seasons of play-by-play.")
    parser.add_argument(
        "--min-mean-pct", type=float, default=0.0,
        help=(
            "Keep only rows whose rolling mean is at or above this percentile of "
            "that stat's POSITIVE means. THE POPULATION THIS CONSTANT IS FITTED ON "
            "MUST MATCH THE ONE IT IS APPLIED TO: the raw observation set is "
            "dominated by marginal players (564 'rushers' in 2022-23, median "
            "per-player sd 10.2 against a workhorse back's ~25), while the BOARD "
            "only ever quotes props for high-usage players. A constant fitted on "
            "the first population and shipped to the second can shrink a starter's "
            "distribution NARROWER, which is the opposite of the intent."
        ))
    args = parser.parse_args()

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
    fit = {int(s) for s in args.fit_seasons.split(",") if s.strip()}
    stats = [s.strip() for s in args.stats.split(",") if s.strip()]
    cands = [float(c) for c in args.candidates.split(",") if c.strip()]
    held = [s for s in seasons if s not in fit]

    print(f"collecting {seasons} stats={len(stats)} min_week={args.min_week} ...", flush=True)
    cache = Path(args.cache) if args.cache else None
    if cache and cache.is_file():
        obs = json.loads(cache.read_text(encoding="utf-8"))
        print(f"reused cached collection: {len(obs)} rows from {cache}", flush=True)
    else:
        obs = collect(seasons, stats, args.min_week)
        if cache:
            cache.write_text(json.dumps(obs), encoding="utf-8")
            print(f"cached collection -> {cache}", flush=True)
    if args.min_mean_pct > 0:
        before = len(obs)
        cuts: dict[str, float] = {}
        for stat in stats:
            means = sorted(o["mean"] for o in obs if o["stat"] == stat and o["mean"] > 0)
            if means:
                i = min(len(means) - 1, int(len(means) * args.min_mean_pct / 100.0))
                cuts[stat] = means[i]
        obs = [o for o in obs if o["mean"] >= cuts.get(o["stat"], 0.0)]
        print(f"usage filter p{args.min_mean_pct:g}: {before} -> {len(obs)} rows; "
              f"cuts={ {k: round(v, 2) for k, v in cuts.items()} }", flush=True)
    fit_obs = [o for o in obs if o["season"] in fit]
    held_obs = [o for o in obs if o["season"] not in fit]
    print(f"observations: {len(obs)}  fit={len(fit_obs)} ({sorted(fit)})  "
          f"held-out={len(held_obs)} ({held})", flush=True)
    if not fit_obs or not held_obs:
        print("REFUSED: need both a fit and a held-out population.", flush=True)
        return 2

    # THE COMMON POPULATION, pinned before any arm is scored. Every arm is
    # graded on exactly the rows that ALL arms can price, so a Brier difference
    # cannot be composition. The rows only some arms can price are counted
    # separately as `rows_rescued`.
    def common(pop: list[dict[str, Any]]) -> set[int]:
        idx = {i for i in range(len(pop))}
        for estimator in ("pstdev", "stdev", "stdev_cv", "stdev_cv_static"):
            for k in cands + [0.0]:
                idx &= {i for i in idx if scorable(pop[i], k=k, estimator=estimator)}
        return idx

    fit_common = common(fit_obs)
    held_common = common(held_obs)
    print(f"common population: fit {len(fit_common)}/{len(fit_obs)}  "
          f"held-out {len(held_common)}/{len(held_obs)}", flush=True)

    rows = []
    for estimator in ("pstdev", "stdev", "stdev_cv", "stdev_cv_static"):
        for k in cands:
            r = score(fit_obs, k=k, estimator=estimator, only=fit_common)
            r["arm"] = "fit"
            rows.append(r)
            print(f"  fit  {estimator:8s} k={k:5.1f}  brier={r['brier']}  "
                  f"cov80={r['coverage_80']}  worstBucket={r['worst_powered_bucket_gap']}  "
                  f"cells={r['cells']}", flush=True)

    scored = [r for r in rows if r["brier"] is not None]
    if not scored:
        print("REFUSED: no candidate produced a score.", flush=True)
        return 2
    best = min(scored, key=lambda r: r["brier"])
    print(f"\nSELECTED on {sorted(fit)}: estimator={best['estimator']} k={best['k']} "
          f"brier={best['brier']} cov80={best['coverage_80']}", flush=True)

    # Production TODAY is pstdev with no shrinkage. That is the only honest
    # baseline: comparing against a k=0 *stdev* arm would credit this sweep with
    # the estimator fix as well as the shrinkage.
    baseline = score(held_obs, k=0.0, estimator="pstdev", only=held_common)
    chosen = score(held_obs, k=best["k"], estimator=best["estimator"], only=held_common)
    estimator_only = score(held_obs, k=0.0, estimator="stdev", only=held_common)
    # ARM-INDEPENDENT, because this is the benefit shrinkage has that the Brier
    # deliberately cannot show: any k>0 gives a positive sd to a player whose
    # prior games were identical, and production drops those rows entirely.
    # Reported whether or not the sweep selects a shrinking arm.
    unpriceable_today = sum(
        1 for o in held_obs if not scorable(o, k=0.0, estimator="pstdev"))
    rescued = sum(
        1 for o in held_obs
        if scorable(o, k=best["k"], estimator=best["estimator"])
        and not scorable(o, k=0.0, estimator="pstdev")
    )
    any_shrink = max([c for c in cands if c > 0], default=0.0)
    rescued_by_any_shrink = sum(
        1 for o in held_obs
        if any_shrink > 0 and scorable(o, k=any_shrink, estimator="stdev")
        and not scorable(o, k=0.0, estimator="pstdev")
    )
    baseline["rows_rescued"] = 0
    chosen["rows_rescued"] = rescued
    print(f"\nHELD OUT {held}:  (all three scored on the SAME {len(held_common)} rows)")
    print(f"  production (pstdev, k=0)  brier={baseline['brier']} "
          f"cov80={baseline['coverage_80']} cells={baseline['cells']}")
    print(f"  estimator only (stdev, k=0) brier={estimator_only['brier']} "
          f"cov80={estimator_only['coverage_80']}")
    print(f"  selected ({best['estimator']}, k={best['k']}) brier={chosen['brier']} "
          f"cov80={chosen['coverage_80']}")
    if baseline["brier"] is not None and chosen["brier"] is not None:
        delta = chosen["brier"] - baseline["brier"]
        print(f"  delta brier vs production: {delta:+.6f} "
              f"({'BETTER' if delta < 0 else 'WORSE'})")
    print(f"  rows production cannot price at all (raw sd == 0): {unpriceable_today} "
          f"of {len(held_obs)}")
    print(f"  of those, rescued by the SELECTED arm: {rescued}; "
          f"by any shrinkage (k={any_shrink}): {rescued_by_any_shrink}")
    print("  (counted, NEVER folded into the Brier above -- those rows are exactly "
          "the degenerate ones, so including them would make the comparison "
          "composition rather than accuracy)")

    payload = {"seasons": seasons, "fit_seasons": sorted(fit), "held_out": held,
               "stats": stats, "min_week": args.min_week,
               "observations": len(obs), "fit_rows": rows,
               "selected": best, "held_out_baseline": baseline,
               "held_out_estimator_only": estimator_only,
               "held_out_selected": chosen,
               "held_out_unpriceable_today": unpriceable_today,
               "held_out_rescued_by_selected": rescued,
               "held_out_rescued_by_any_shrink": rescued_by_any_shrink}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
