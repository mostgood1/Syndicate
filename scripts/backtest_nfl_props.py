"""Backtest: does NFL's real player-prop model predict anything, across
ALL players/weeks/markets? (`nfl-player-props-backtest` lane, 2026-08-19.)

`syndicate.features.nfl.player_stats.player_rate` is a rolling pre-week
(mean, stdev, n) computed directly from real nflverse play-by-play, no
lookahead. `syndicate.features.nfl.props._nfl_prop_model_probability`
turns that into a Normal-CDF cover probability (or the raw rate itself for
the one-sided `anytime_td` market). Together they ARE the model behind the
board's NFL player props today -- and neither has ever been backtested.
`props.py`'s own module docstring says as much: "no NBA/WNBA-style trained
per-player model exists ... (real rate model instead)".

WHY THIS MATTERS MORE THAN IT LOOKS: real quoted odds
(`oddsapi_player_props_<season>_wk<week>.csv`) only exist for ~13 sparse
weeks (2025 wk10-22) -- the-odds-api's live-only fetch has no historical
backfill. A backtest gated on real odds would therefore measure the model
on a tiny, recency-biased slice. This script does NOT gate on odds
availability for its main measurement -- it grades every real NFL game
2022-2025 (complete seasons, real nflverse play-by-play already on disk),
using the model's OWN predicted mean against the real settled outcome. The
odds-gated section is a SEPARATE, smaller check at the end, scoring the
model's actual over/under call against a real quoted line wherever one
exists.

WHAT "ULTIMATE OUTCOME" RIGOR LOOKS LIKE, per MLB, and why NFL is not
there yet: MLB's pitcher ladder (`syndicate/features/mlb/pitcher_ladders.py`
-> `k_ladder_targets.py`) prices an entire ladder of thresholds (Over 4.5
K, 5.5 K, 6.5 K, ...) off a real 1000-draw simulated PMF per pitcher per
game. NFL's player_rate model has NO distribution at all -- confirmed
absent by the `convergence-phase7-crps` lane (165 files / 160 dates
checked, zero spread columns in any NFL projection artifact) -- just a
single Normal(mean, stdev) fitted from the player's own rolling history.
Section 2 below (LADDER CALIBRATION) tests that Normal approximation the
way a real ladder would be tested: at several synthetic thresholds around
each player's own mean, not just the one line a market happens to quote.

WHAT IT MEASURES
  1. POINT ACCURACY, per stat market, across every real NFL game 2022-2025:
     player_rate's rolling pre-week mean vs the real settled value, against
     a constant per-market baseline (the sample's own mean) -- same
     discipline as scripts/backtest_mlb_props.py (per-market denominators,
     in-sample AND out-of-sample: fit bias on the earlier half of weeks,
     score it on the later half).
  2. LADDER CALIBRATION: at 5 synthetic thresholds per player-week
     (mean - 1sd, -0.5sd, mean, +0.5sd, +1sd), bucket the model's
     Normal-CDF cover probability into deciles and compare each bucket's
     average predicted probability to its actual hit rate -- a reliability
     check across the WHOLE population, not just the weeks with a real
     line. Reports Brier score too.
  3. REAL MARKET HIT RATE: wherever a real quoted line exists for this
     exact (player, market, week), score the model's actual over/under
     CALL (not just its probability) against the real settled outcome.

TWO HONESTY RULES, ported from backtest_mlb_props.py:
  1. PER-MARKET DENOMINATORS. Reported separately per stat; a market with
     too few qualifying rows says so rather than printing a number.
  2. EXCLUDE PLAYERS WITH NO REAL ENGAGEMENT IN THAT STAT. player_game_log
     rows already exclude weeks a player did not play at all (no DNP
     fabrication possible -- a row only exists for a game with >=1
     qualifying play). But most non-QBs have a structural ZERO passing
     history; scoring them on "passing_yards" would pool a real market
     with thousands of trivial 0-vs-0 rows and make the number unreadable
     (learnings.md 2026-08-13: "a pooled denominator can make a
     measurement unreadable"). So section 1's per-market rows additionally
     require the player's OWN rolling mean to be > 0 for every stat except
     `anytime_td` -- real historical engagement in that specific stat,
     mirroring the fact that `_nfl_prop_model_probability` already returns
     None for a zero-stdev (structurally uninvolved) player whenever a
     real line is priced. `anytime_td` has no such gate: "will this player
     score" is graded for every game-log row with a resolvable rate
     (n>=2), because a genuine zero rate is part of the prediction being
     tested, not a sign the player is off-market. Sections 2 and 3 read
     the UNGATED substrate (`collect_raw`) instead, because
     `_nfl_prop_model_probability`'s own stdev>0 gate already does this
     filtering for them, and gating twice would just double-count.

Data: entirely LOCAL and entirely historical (complete, already-played
real nflverse play-by-play -- no network calls). If this checkout has no
data/nfl_source, set SYNDICATE_NFL_SOURCE_ROOT to one that does before
running (this repo's worktree convention excludes data/ by default).

Usage:
  py -3 scripts/backtest_nfl_props.py --seasons 2022,2023,2024,2025
  py -3 scripts/backtest_nfl_props.py --seasons 2025 --min-games 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props as nfl_props

STAT_KEYS = player_stats.STAT_KEYS


def _cached_game_log(cache: dict[tuple[int, str], list[dict[str, Any]]], season: int, player_id: str) -> list[dict[str, Any]]:
    """`player_stats.player_game_log` is not itself cached, and rescans
    the ENTIRE season's play list on every call. `player_rate()` calls it
    once per (season, week, player_id, stat), so calling that directly in
    a loop over every player x week x stat is O(players x weeks x stats x
    plays) -- minutes to hours, not seconds. Fixed by caching the log
    ourselves and re-deriving the rate locally (`_rate_from_log`) instead
    of monkeypatching the shared module function: `player_game_log` is a
    plain module-level symbol other test files import and call directly,
    and reassigning it process-wide would leak a stale cache across every
    OTHER test file in the same pytest run (they use overlapping
    (season, player_id) fixture keys with different temp-dir data)."""
    key = (season, player_id)
    if key not in cache:
        cache[key] = player_stats.player_game_log(season, player_id)
    return cache[key]


def _rate_from_log(log: list[dict[str, Any]], week: int, stat: str) -> tuple[float | None, float | None, int]:
    """Identical math to player_stats.player_rate, operating on an
    already-fetched log instead of re-fetching it -- see
    `_cached_game_log`'s docstring for why this is a local re-derivation
    rather than a call to the production function."""
    values = [row[stat] for row in log if row["week"] < week]
    if len(values) < 2:
        return None, None, len(values)
    return statistics.fmean(values), statistics.pstdev(values), len(values)


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = fmean(xs), fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


def mae(pred: list[float], actual: list[float]) -> float:
    return round(fmean(abs(p - a) for p, a in zip(pred, actual)), 4)


def brier(probs: list[float], outcomes: list[int]) -> float:
    return round(fmean((p - o) ** 2 for p, o in zip(probs, outcomes)), 4)


def _all_player_ids(season: int) -> list[str]:
    """Every real id that ever appears as a passer/rusher/receiver this
    season -- the population of players a prop market could plausibly
    exist for."""
    ids: set[str] = set()
    for play in player_stats.load_player_plays(season):
        for key in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
            pid = play.get(key)
            if pid:
                ids.add(pid)
    return sorted(ids)


def collect_raw(seasons: list[int]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One row per (season, player_id, week, stat) with a resolvable
    pre-week rate (n>=2) -- UNGATED for engagement, the substrate both the
    ladder-calibration and real-market sections read. Rows for weeks a
    player did not play do not exist at all, because player_game_log only
    has entries for games with >=1 qualifying play -- no DNP fabrication
    is possible here, unlike a roster-driven sport."""
    rows: list[dict[str, Any]] = []
    counts = {"player_ids": 0, "player_game_weeks": 0, "player_stat_weeks_no_rate": 0}
    log_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for season in seasons:
        player_ids = _all_player_ids(season)
        counts["player_ids"] += len(player_ids)
        for pid in player_ids:
            log = _cached_game_log(log_cache, season, pid)
            counts["player_game_weeks"] += len(log)
            for entry in log:
                week = entry["week"]
                for stat in STAT_KEYS:
                    mean, stdev, n = _rate_from_log(log, week, stat)
                    if mean is None:
                        counts["player_stat_weeks_no_rate"] += 1
                        continue
                    if stat == "anytime_td":
                        # `#471` fix: match production's
                        # anytime_td_rate -- shrink the raw rate toward
                        # the pre-week league prior before this row is
                        # used anywhere downstream. _anytime_td_league_prior
                        # is cheap (lru_cached per season, sums ~18 weeks),
                        # so calling it per row here is fine.
                        prior_mean, prior_n = player_stats._anytime_td_league_prior(season, week)
                        if prior_n:
                            mean = player_stats.shrink_count_mean(mean, n, prior_mean, player_stats.ANYTIME_TD_SHRINKAGE_K)
                    rows.append({
                        "season": season, "player_id": pid, "week": week,
                        "game_id": entry["game_id"], "stat": stat,
                        "pred_mean": mean, "pred_stdev": stdev, "n": n,
                        "actual": entry[stat],
                    })
    return rows, counts


def _market_rows(raw_rows: list[dict[str, Any]], stat: str) -> tuple[list[dict[str, Any]], int]:
    """Gate 2 applied for ONE market: real historical engagement required
    (own rolling mean > 0) for every stat except anytime_td. Returns the
    surviving rows and how many were excluded for zero engagement."""
    excluded = 0
    kept: list[dict[str, Any]] = []
    for row in raw_rows:
        if row["stat"] != stat:
            continue
        if stat != "anytime_td" and row["pred_mean"] <= 0.0:
            excluded += 1
            continue
        kept.append(row)
    return kept, excluded


def point_accuracy_report(raw_rows: list[dict[str, Any]], min_games: int, min_split_games: int) -> dict[str, Any]:
    print("\n" + "=" * 78)
    print("SECTION 1 -- POINT ACCURACY (every real game, 2022-2025, per market)")
    print("=" * 78)
    header = (f"  {'market':16s} {'n':>6s} {'excl0':>6s} {'corr':>8s} {'MAE model':>10s} "
              f"{'MAE base':>9s} {'MAE debias':>10s} {'bias':>8s} {'verdict'}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    out: dict[str, Any] = {}
    for stat in STAT_KEYS:
        market_rows, excluded = _market_rows(raw_rows, stat)
        pred = [r["pred_mean"] for r in market_rows]
        act = [float(r["actual"]) for r in market_rows]
        weeks = [(r["season"], r["week"]) for r in market_rows]

        if len(pred) < min_games:
            print(f"  {stat:16s} {len(pred):6d} {excluded:6d} below --min-games {min_games}, no number emitted")
            out[stat] = {"n": len(pred), "excluded_zero_engagement": excluded, "verdict": "not measurable (sample too small)"}
            continue
        if len(set(pred)) == 1:
            print(f"  {stat:16s} {len(pred):6d} {excluded:6d} CONSTANT {pred[0]} -- degenerate")
            out[stat] = {"n": len(pred), "excluded_zero_engagement": excluded, "constant_value": pred[0], "verdict": "degenerate constant"}
            continue

        baseline = fmean(act)
        m_model = mae(pred, act)
        m_base = mae([baseline] * len(act), act)
        c = corr(pred, act)
        bias = fmean(p - a for p, a in zip(pred, act))
        m_debiased = mae([p - bias for p in pred], act)
        beats = m_model < m_base
        debiased_beats = m_debiased < m_base

        # Out-of-sample: fit the bias/baseline on the EARLIER half of
        # distinct (season, week) pairs, score on the LATER half. Same
        # discipline as backtest_mlb_props.py's D4 -- an in-sample number
        # leaks (baseline and bias are fit on the same rows they score),
        # so it is reported but never treated as the finding on its own.
        ordered = sorted(set(weeks))
        oos: dict[str, Any] = {"available": False, "reason": None}
        if len(ordered) < 2 * min_split_games:
            oos["reason"] = f"needs >= {2 * min_split_games} distinct (season,week) pairs, have {len(ordered)}"
        else:
            cut = len(ordered) // 2
            fit_set, score_set = set(ordered[:cut]), set(ordered[cut:])
            fit_idx = [i for i, w in enumerate(weeks) if w in fit_set]
            score_idx = [i for i, w in enumerate(weeks) if w in score_set]
            if len(fit_idx) < min_games or len(score_idx) < min_games:
                oos["reason"] = f"split leaves {len(fit_idx)}/{len(score_idx)} rows, below --min-games {min_games}"
            else:
                fit_bias = fmean(pred[i] - act[i] for i in fit_idx)
                fit_baseline = fmean(act[i] for i in fit_idx)
                s_pred = [pred[i] for i in score_idx]
                s_act = [act[i] for i in score_idx]
                oos_model = mae(s_pred, s_act)
                oos_base = mae([fit_baseline] * len(s_act), s_act)
                oos_debiased = mae([p - fit_bias for p in s_pred], s_act)
                oos = {
                    "available": True, "reason": None,
                    "fit_range": f"{ordered[0]}..{ordered[cut - 1]}", "score_range": f"{ordered[cut]}..{ordered[-1]}",
                    "n_fit": len(fit_idx), "n_score": len(score_idx),
                    "mae_model": oos_model, "mae_constant_baseline": oos_base, "mae_debiased": oos_debiased,
                    "debiased_beats_baseline": oos_debiased < oos_base, "correlation": corr(s_pred, s_act),
                }

        verdict = (f"beats baseline by {round(m_base - m_model, 4)}" if beats else
                   f"BIASED, NOT BLIND -- de-biased beats by {round(m_base - m_debiased, 4)}" if debiased_beats else
                   "NO measured skill")
        print(f"  {stat:16s} {len(pred):6d} {excluded:6d} {str(c):>8s} {m_model:>10.4f} "
              f"{m_base:>9.4f} {m_debiased:>10.4f} {bias:>+8.4f} {verdict}")
        if oos.get("available"):
            print(f"  {'':16s} {oos['n_score']:6d} {'':>6s} {str(oos['correlation']):>8s} "
                  f"{oos['mae_model']:>10.4f} {oos['mae_constant_baseline']:>9.4f} {oos['mae_debiased']:>10.4f} "
                  f"{'':>8s} OUT-OF-SAMPLE ({oos['fit_range']} -> {oos['score_range']}) -- "
                  f"de-biased {'BEATS' if oos['debiased_beats_baseline'] else 'LOSES TO'} baseline")
        else:
            print(f"  {'':16s} {'':6s} {'':6s} out-of-sample NOT COMPUTED: {oos['reason']}")

        out[stat] = {
            "n": len(pred), "excluded_zero_engagement": excluded, "correlation": c,
            "mae_model": m_model, "mae_constant_baseline": m_base, "mae_debiased": m_debiased,
            "mean_bias": round(bias, 4), "baseline_value": round(baseline, 4),
            "beats_constant_baseline": beats, "debiased_beats_baseline": debiased_beats,
            "verdict": verdict, "validation": "in_sample", "out_of_sample": oos,
        }
    return out


def _prob_outcome_pairs_for_stat(raw_rows: list[dict[str, Any]], stat: str) -> tuple[list[float], list[int]]:
    """At 5 synthetic thresholds per row (mean -1sd/-0.5sd/mean/+0.5sd/+1sd
    for count/yardage stats; the rate itself for anytime_td), the model's
    predicted probability paired with the real outcome -- ONE stat at a
    time. This is the closest thing to grading a real ladder (MLB's
    k_ladder pattern) that a mean+stdev model without a real simulated
    distribution supports -- see the module docstring."""
    probs: list[float] = []
    outcomes: list[int] = []
    offsets = (-1.0, -0.5, 0.0, 0.5, 1.0)
    for row in raw_rows:
        if row["stat"] != stat:
            continue
        mean, stdev, n, actual = row["pred_mean"], row["pred_stdev"], row["n"], row["actual"]
        if stat == "anytime_td":
            p = nfl_props._nfl_prop_model_probability(stat=stat, mean=mean, stdev=stdev, n=n, line=None)
            if p is None:
                continue
            probs.append(p)
            outcomes.append(1 if actual >= 1 else 0)
            continue
        if stdev is None or stdev <= 0:
            continue
        for offset in offsets:
            line = mean + offset * stdev
            p = nfl_props._nfl_prop_model_probability(stat=stat, mean=mean, stdev=stdev, n=n, line=line)
            if p is None:
                continue
            probs.append(p)
            outcomes.append(1 if actual > line else 0)
    return probs, outcomes


def _reliability_buckets(probs: list[float], outcomes: list[int], n_buckets: int = 10) -> list[dict[str, Any]]:
    # Sort by PROBABILITY ONLY. `sorted(zip(probs, outcomes))` looks
    # equivalent but is not: it sorts (prob, outcome) as a tuple, so ties
    # in probability -- and there are massive ties here, because the
    # offset=0 synthetic threshold (line == the player's own mean) always
    # produces exactly p=0.5 -- get their SECONDARY key sorted by outcome
    # (False < True). That silently pushes every outcome=0 row before
    # every outcome=1 row within a tied cluster, so a bucket boundary
    # landing inside that cluster manufactures a fake 0%-then-100% swing
    # that is a sort artifact, not a calibration finding. Measured on the
    # first run: bucket 5 (avg predicted 0.500) read actual hit rate
    # 0.000, bucket 6 (also 0.500) read 0.923 -- both buckets sat entirely
    # inside the offset=0 tie cluster.
    paired = sorted(zip(probs, outcomes), key=lambda pair: pair[0])
    bucket_size = len(paired) // n_buckets
    buckets = []
    for i in range(n_buckets):
        start = i * bucket_size
        end = (i + 1) * bucket_size if i < n_buckets - 1 else len(paired)
        chunk = paired[start:end]
        if not chunk:
            continue
        avg_pred = fmean(p for p, _ in chunk)
        hit_rate = fmean(o for _, o in chunk)
        buckets.append({"bucket": i + 1, "n": len(chunk), "avg_predicted": round(avg_pred, 4),
                         "actual_hit_rate": round(hit_rate, 4), "gap": round(avg_pred - hit_rate, 4)})
    return buckets


def ladder_calibration_report(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reliability (predicted probability vs actual hit rate), PER MARKET.

    Pooling every market into one set of deciles was the first version of
    this function and it was wrong -- exactly the "pooled denominator"
    trap the module docstring already warns about for section 1
    (learnings.md 2026-08-13). Different markets have structurally
    different probability distributions (anytime_td sits low, ~0.05-0.35;
    passing_attempts sits close to 0.5 at every offset because it is the
    most stable rate), so a global decile mixes them and produces gaps
    that swing sign bucket to bucket for no reason a reader can act on --
    measured on the first run: bucket 5 read predicted 0.463/actual 0.157,
    bucket 6 (right next to it) read 0.500/0.629. That is not a smooth
    reliability curve, it is markets colliding. Reporting per-market makes
    each curve internally comparable; a small pooled summary is still
    printed but explicitly labeled as not to be read alone."""
    print("\n" + "=" * 78)
    print("SECTION 2 -- LADDER CALIBRATION (reliability across the whole population,")
    print("             not just weeks with a real quoted line), PER MARKET")
    print("=" * 78)

    out: dict[str, Any] = {"markets": {}}
    all_probs: list[float] = []
    all_outcomes: list[int] = []
    for stat in STAT_KEYS:
        probs, outcomes = _prob_outcome_pairs_for_stat(raw_rows, stat)
        all_probs.extend(probs)
        all_outcomes.extend(outcomes)
        if len(probs) < 100:
            print(f"  {stat:16s} n={len(probs)}, below 100 -- not measurable")
            out["markets"][stat] = {"n": len(probs), "verdict": "not measurable (sample too small)"}
            continue
        buckets = _reliability_buckets(probs, outcomes)
        b = brier(probs, outcomes)
        print(f"  {stat:16s} n={len(probs)}, Brier={b}")
        print(f"    {'bucket':>8s} {'n':>7s} {'avg predicted':>14s} {'actual hit rate':>16s} {'gap':>8s}")
        for bucket in buckets:
            print(f"    {bucket['bucket']:>8d} {bucket['n']:>7d} {bucket['avg_predicted']:>14.3f} "
                  f"{bucket['actual_hit_rate']:>16.3f} {bucket['gap']:>+8.3f}")
        out["markets"][stat] = {"n": len(probs), "brier_score": b, "buckets": buckets}

    print(f"\n  POOLED ACROSS ALL MARKETS (n={len(all_probs)}, Brier={brier(all_probs, all_outcomes) if all_probs else None}) --")
    print("  informational only, do not read this alone: see the per-market breakdown above")
    out["pooled_all_markets_informational_only"] = {
        "n": len(all_probs),
        "brier_score": brier(all_probs, all_outcomes) if all_probs else None,
        "buckets": _reliability_buckets(all_probs, all_outcomes) if len(all_probs) >= 100 else [],
    }
    return out


def real_market_hit_rate_report(raw_rows: list[dict[str, Any]], seasons: list[int], min_games: int = 10) -> dict[str, Any]:
    """Wherever a real quoted line exists for this exact (player, market,
    week), score the model's actual over/under CALL -- not just its
    probability -- against the real settled outcome. Small by
    construction (real prop odds only cover 2025 wk10-22), which is
    exactly why section 1 does not depend on this."""
    print("\n" + "=" * 78)
    print("SECTION 3 -- REAL MARKET HIT RATE (wherever a real quoted line exists)")
    print("=" * 78)

    rate_index: dict[tuple[int, int, str, str], dict[str, Any]] = {
        (row["season"], row["week"], row["player_id"], row["stat"]): row for row in raw_rows
    }

    by_market: dict[str, dict[str, list]] = {}
    no_resolvable_player = no_resolvable_rate = pushes = 0
    for season in seasons:
        for week in nfl_props.nfl_props_available_weeks(season):
            for odds_row in nfl_props._nfl_raw_player_props(season, week):
                stat = nfl_props._NFL_PROP_MARKET_TO_STAT.get(str(odds_row.get("market") or "").strip())
                if stat is None:
                    continue
                player_name = str(odds_row.get("player") or "").strip()
                player_id = player_stats.resolve_player_id(season, player_name)
                if player_id is None:
                    no_resolvable_player += 1
                    continue
                rate = rate_index.get((season, week, player_id, stat))
                if rate is None:
                    no_resolvable_rate += 1
                    continue
                line = nfl_props._safe_float(odds_row.get("line"))
                actual = rate["actual"]
                if stat == "anytime_td":
                    prob = nfl_props._nfl_prop_model_probability(stat=stat, mean=rate["pred_mean"], stdev=rate["pred_stdev"], n=rate["n"], line=None)
                    outcome = 1 if actual >= 1 else 0
                else:
                    if line is None:
                        continue
                    prob = nfl_props._nfl_prop_model_probability(stat=stat, mean=rate["pred_mean"], stdev=rate["pred_stdev"], n=rate["n"], line=line)
                    if actual == line:
                        pushes += 1
                        continue
                    outcome = 1 if actual > line else 0
                if prob is None or prob == 0.5:
                    continue
                predicted_side_hit = (1 if prob > 0.5 else 0) == outcome
                slot = by_market.setdefault(stat, {"probs": [], "outcomes": [], "hits": []})
                slot["probs"].append(prob)
                slot["outcomes"].append(outcome)
                slot["hits"].append(predicted_side_hit)

    print(f"  real quoted rows with no resolvable player id : {no_resolvable_player}")
    print(f"  real quoted rows with no resolvable model rate: {no_resolvable_rate}")
    print(f"  pushes excluded (actual == line)               : {pushes}")
    print(f"  {'market':16s} {'n':>6s} {'hit rate':>10s} {'brier':>8s}")
    out: dict[str, Any] = {"no_resolvable_player": no_resolvable_player, "no_resolvable_rate": no_resolvable_rate,
                            "pushes_excluded": pushes, "markets": {}}
    for stat, slot in by_market.items():
        n = len(slot["hits"])
        if n < min_games:
            print(f"  {stat:16s} {n:6d} below {min_games}, not measurable")
            out["markets"][stat] = {"n": n, "verdict": "not measurable (sample too small)"}
            continue
        hit_rate = round(fmean(slot["hits"]), 4)
        b = brier(slot["probs"], slot["outcomes"])
        print(f"  {stat:16s} {n:6d} {hit_rate:>10.4f} {b:>8.4f}")
        out["markets"][stat] = {"n": n, "hit_rate": hit_rate, "brier_score": b}
    if not by_market:
        print("  (no real quoted line joined to a resolvable player + a resolvable model rate)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", default="2022,2023,2024,2025", help="comma-separated seasons")
    parser.add_argument("--min-games", type=int, default=100, help="per-market minimum before a skill number is emitted")
    parser.add_argument("--min-split-games", type=int, default=10, help="minimum distinct (season,week) pairs per half before an out-of-sample number is emitted")
    parser.add_argument("--out", default="", help="write the MEASURED_SKILL JSON block to this path too")
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    print(f"Loading real nflverse play-by-play for seasons: {seasons} ...")
    raw_rows, coverage = collect_raw(seasons)

    print("\nCOVERAGE")
    print(f"  seasons                                : {seasons}")
    print(f"  distinct players (passer/rusher/rcvr id): {coverage['player_ids']}")
    print(f"  player-game-weeks (played, any role)    : {coverage['player_game_weeks']}")
    print(f"  player-stat-weeks with no resolvable rate (n<2): {coverage['player_stat_weeks_no_rate']}")
    print(f"  raw (player, week, stat) rows with a rate: {len(raw_rows)}")

    if not raw_rows:
        print("\nNothing collected. Nothing to measure -- check SYNDICATE_NFL_SOURCE_ROOT.")
        return 1

    results: dict[str, Any] = {
        "sport": "nfl", "scope": "player props (rate model)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seasons": seasons, "coverage": coverage,
        "section_1_point_accuracy": point_accuracy_report(raw_rows, args.min_games, args.min_split_games),
        "section_2_ladder_calibration": ladder_calibration_report(raw_rows),
        "section_3_real_market_hit_rate": real_market_hit_rate_report(raw_rows, seasons),
    }

    print("\n" + "=" * 78)
    print("MEASURED_SKILL block:")
    print(json.dumps(results, indent=2))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWritten to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
