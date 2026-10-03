"""Backtest: do NFL game lines and NFL player props beat a naive baseline AND the book?

Lane `nfl-lines-props-backtest` (2026-10-02). Same method and output shape as
`scripts/backtest_nhl_props.py` (lane `nhl-player-props-projection`) and the NCAAF
twin (lane `ncaaf-lines-props-backtest`): per market n, MAE and bias vs the actual
result, dMAE vs a naive AS-OF baseline with a GAME-clustered bootstrap 95% CI, and
Brier / log-loss vs the DE-VIGGED book on the same rows with a paired CI. A market
may carry a board probability/edge only if it beats BOTH.

WHAT IS GRADED IS PRODUCTION'S OWN CODE, CALLED, NOT COPIED.
  * Game lines: `scripts/generate_smartsim2_nfl_projections.build_projection`
    (300 seeds, the shipped `nfl_v1` profile, PPG ratings, K=4 prior-season blend,
    total level shrink 0.3) over plays STRICTLY BEFORE the game's week (the
    function's own `before_week` filter), then the board's probability functions:
    moneyline = raw `home_win_rate` (`nfl/cards.py`), spread/total cover =
    `shared/football_cards.cover_probability` = Normal(sim mean, sim pstdev).
    `--reproduce` re-runs a week production already wrote and compares field by
    field -- the harness is only evidence about the deployment if it reproduces
    the deployment's artifact.
  * Props: the computed branch of `nfl/props.nfl_props_rows_for_week`:
    `resolve_player_id_with_prior` -> the team check -> `player_rate_with_prior`
    (or `anytime_td_rate_with_prior`) -> `nfl_game_context_multiplier` ->
    `_nfl_prop_model_probability`. `--selfcheck` writes one week's quotes in the
    production CSV contract and asserts `nfl_props_rows_for_week(use_artifact=False)`
    returns the same probability for every (player, market, line) this harness
    scored.
  * The only process-local change: `player_stats.player_game_log` is wrapped in a
    cache (it rescans a whole season per call). Pure function of (season, id);
    nothing it returns is mutated by any caller used here.

ENV. Production's refresh-worker was READ on the local fleet 2026-10-02
(`/proc/<pid>/environ`, NFL keys only): `SYNDICATE_NFL_PPG_RATINGS=1`,
`SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS=1`, every other NFL model knob ABSENT
(code defaults). This script sets exactly that and REFUSES to run if any other
knob is set in its own environment.

AS-OF RULES.
  * Team ratings, player rates, player teams, league priors: plays before the week.
  * Book: nflverse `schedules_games.csv` closing spread/total/moneyline WITH juice
    (spread_line is HOME-MARGIN-POSITIVE); props: OddsAPI historical snapshots at
    kickoff - 10 min (`tracking/book_quotes/<season>_wk<N>.jsonl`). De-vig is
    proportional over the two sides of ONE book. One-sided rows are excluded and
    COUNTED (anytime TD is one-sided by construction).
  * Naive baselines, as-of: margin = league mean home margin, total = league mean
    total, P(home win)/P(home cover)/P(over) = league rates, all over completed
    REG games of the prior season plus this season before this week. Props =
    the player's OWN as-of average (production's estimator with the game-context
    multiplier OFF -- so for NFL, model-vs-baseline isolates the context term),
    plus a last-4 average.
  * KNOWN NON-AS-OF INPUTS, stated: the props game-context multiplier reads the
    CLOSING spread/total from the schedule (production reads whatever line exists
    at build time); `_COVER_PROBABILITY_BLEND_WEIGHT`, spread-shrinkage k and the
    anytime-TD k were fitted on 2022-23 (in-sample for 2022-23, out-of-sample for
    2024+); the sim profile constants are frozen.

HONESTY RULES (ported from the NHL harness): the INTERSECTION is scored and every
drop is counted with its reason; `n` travels with every number; no verdict below
`--min-n`; "no skill" is printed as a result.

Usage:
  py -3 scripts/backtest_nfl_lines_props.py --root C:/tmp/nflbt/root/nfl_source \\
      --out C:/tmp/nflbt/out --seasons 2023,2024,2025,2026 --parts lines,props --workers 6
  py -3 scripts/backtest_nfl_lines_props.py ... --reproduce 2026:4     # fidelity check
  py -3 scripts/backtest_nfl_lines_props.py ... --analyze-only          # re-score caches
"""
from __future__ import annotations

import argparse
import csv
import functools
import glob
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Measured on the fleet's refresh-worker 2026-10-02 (see module docstring).
PRODUCTION_ENV = {"SYNDICATE_NFL_PPG_RATINGS": "1", "SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS": "1"}
MUST_BE_ABSENT = (
    "SYNDICATE_NFL_BLOWOUT_DAMPING", "SYNDICATE_NFL_DRIVE_PRIORS", "SYNDICATE_NFL_PROPS_GAME_CONTEXT",
    "SYNDICATE_NFL_PROP_ZERO_GAMES", "SYNDICATE_NFL_RATING_PRIOR_GAMES", "SYNDICATE_NFL_SPREAD_SHRINKAGE",
    "SYNDICATE_NFL_TOTAL_DIFF_CORRECTION", "SYNDICATE_NFL_TOTAL_LEVEL_SHRINK",
)
PROP_STATS = ("passing_yards", "passing_attempts", "passing_tds", "rushing_yards", "rushing_attempts",
              "receptions", "receiving_yards", "interceptions", "anytime_td")


def configure_env(root: Path) -> Dict[str, Any]:
    set_knobs = [k for k in MUST_BE_ABSENT if os.environ.get(k) not in (None, "")]
    if set_knobs:
        raise SystemExit(f"refusing: {set_knobs} set in this environment; production has them ABSENT")
    os.environ["SYNDICATE_NFL_SOURCE_ROOT"] = str(root)
    # Keeps every resolver off the checkout's data/ and off the fleet disk.
    os.environ["SYNDICATE_DATA_ROOT"] = str(root.parent)
    os.environ.update(PRODUCTION_ENV)
    return {"SYNDICATE_NFL_SOURCE_ROOT": str(root), "SYNDICATE_DATA_ROOT": str(root.parent),
            **PRODUCTION_ENV, "absent": list(MUST_BE_ABSENT)}


# ---------------------------------------------------------------------------
# small stats
# ---------------------------------------------------------------------------

def _clip(p: float, lo: float = 1e-3) -> float:
    return min(1 - lo, max(lo, p))


def _logloss(p: float, y: int) -> float:
    p = _clip(p)
    return -(math.log(p) if y else math.log(1 - p))


def boot_ci(rows: List[Tuple[str, float]], n_boot: int = 1000, seed: int = 7) -> Tuple[float, float, float]:
    """Mean of per-row values with a GAME-clustered bootstrap 95% CI (NHL harness's estimator)."""
    by_g: Dict[str, List[float]] = defaultdict(list)
    for g, v in rows:
        by_g[g].append(v)
    keys = list(by_g)
    if not keys:
        return (float("nan"),) * 3  # type: ignore[return-value]
    sums = [sum(by_g[k]) for k in keys]
    cnts = [len(by_g[k]) for k in keys]
    point = sum(sums) / sum(cnts)
    rng = random.Random(seed)
    n = len(keys)
    stats = []
    for _ in range(n_boot):
        s = c = 0.0
        for _j in range(n):
            i = rng.randrange(n)
            s += sums[i]
            c += cnts[i]
        stats.append(s / c)
    stats.sort()
    return point, stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]


def _ci(rows: List[Tuple[str, float]], nd: int = 4) -> Dict[str, Any]:
    p, lo, hi = boot_ci(rows)
    return {"point": round(p, nd), "ci95": [round(lo, nd), round(hi, nd)]}


def american_to_dec(o: float) -> float:
    return 1 + (o / 100.0 if o > 0 else 100.0 / -o)


def implied(o: float) -> float:
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def devig(p_side: float, p_other: float) -> float:
    return p_side / (p_side + p_other)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def reliability(ps: List[float], ys: List[int], bins: int = 10) -> List[Dict[str, Any]]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    n = len(order)
    out = []
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if idx:
            out.append({"mean_pred": round(sum(ps[i] for i in idx) / len(idx), 4),
                        "obs": round(sum(ys[i] for i in idx) / len(idx), 4), "n": len(idx)})
    return out


def prob_block(rows: List[Dict[str, Any]], keys: Tuple[str, ...], min_n: int, model_key: str = "p_model",
               book_key: Optional[str] = "p_book", base_key: Optional[str] = "p_base",
               ev_odds: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Brier/LL for each probability column on the SAME rows, paired deltas with game-clustered CIs."""
    n = len(rows)
    out: Dict[str, Any] = {"n": n, "games": len({r["gid"] for r in rows})}
    if n == 0:
        out["verdict_vs_book"] = out["verdict_vs_base"] = "NO_ROWS"
        return out
    out["base_rate"] = round(sum(r["y"] for r in rows) / n, 4)
    for k in keys:
        out[k] = {"mean_p": round(sum(r[k] for r in rows) / n, 4),
                  "brier": round(sum((r[k] - r["y"]) ** 2 for r in rows) / n, 5),
                  "logloss": round(sum(_logloss(r[k], r["y"]) for r in rows) / n, 5)}
    for other, tag in ((book_key, "book"), (base_key, "base")):
        if not other:
            continue
        db = boot_ci([(r["gid"], (r[model_key] - r["y"]) ** 2 - (r[other] - r["y"]) ** 2) for r in rows])
        dl = boot_ci([(r["gid"], _logloss(r[model_key], r["y"]) - _logloss(r[other], r["y"])) for r in rows])
        out[f"dbrier_model_vs_{tag}"] = {"point": round(db[0], 5), "ci95": [round(db[1], 5), round(db[2], 5)]}
        out[f"dlogloss_model_vs_{tag}"] = {"point": round(dl[0], 5), "ci95": [round(dl[1], 5), round(dl[2], 5)]}
        out[f"verdict_vs_{tag}"] = ("INSUFFICIENT_N" if n < min_n else
                                    "MODEL_BETTER" if db[2] < 0 else "MODEL_WORSE" if db[1] > 0 else "NO_DIFFERENCE")
    out["reliability_model"] = reliability([r[model_key] for r in rows], [r["y"] for r in rows])
    if ev_odds:
        bets = []
        for r in rows:
            d_yes, d_no = r[ev_odds[0]], r[ev_odds[1]]
            ev_y = r[model_key] * d_yes - 1
            ev_n = (1 - r[model_key]) * d_no - 1
            if max(ev_y, ev_n) <= 0:
                continue
            if ev_y >= ev_n:
                bets.append((r["gid"], (d_yes - 1) if r["y"] == 1 else -1.0, r["y"] == 1))
            else:
                bets.append((r["gid"], (d_no - 1) if r["y"] == 0 else -1.0, r["y"] == 0))
        if bets:
            roi = boot_ci([(g, p) for g, p, _ in bets])
            out["ev_bets"] = {"n": len(bets), "hit_rate": round(sum(w for *_, w in bets) / len(bets), 4),
                              "roi": round(roi[0], 4), "roi_ci95": [round(roi[1], 4), round(roi[2], 4)]}
        else:
            out["ev_bets"] = {"n": 0}
    return out


def point_block(rows: List[Dict[str, Any]], preds: Tuple[str, ...], min_n: int) -> Dict[str, Any]:
    """MAE/bias/RMSE per predictor on the SAME rows; dMAE model-minus-each with a game-clustered CI."""
    n = len(rows)
    out: Dict[str, Any] = {"n": n, "games": len({r["gid"] for r in rows})}
    if n == 0:
        out["verdict_vs_base"] = "NO_ROWS"
        return out
    out["mean_actual"] = round(sum(r["y"] for r in rows) / n, 4)
    for k in preds:
        err = [r[k] - r["y"] for r in rows]
        out[k] = {"mean_pred": round(sum(r[k] for r in rows) / n, 4), "bias": round(sum(err) / n, 4),
                  "mae": round(sum(abs(e) for e in err) / n, 4),
                  "rmse": round(math.sqrt(sum(e * e for e in err) / n), 4)}
    for k in preds[1:]:
        d = boot_ci([(r["gid"], abs(r["model"] - r["y"]) - abs(r[k] - r["y"])) for r in rows])
        out[f"dmae_model_vs_{k}"] = {"point": round(d[0], 4), "ci95": [round(d[1], 4), round(d[2], 4)]}
    d = out.get("dmae_model_vs_base")
    if d:
        out["verdict_vs_base"] = ("INSUFFICIENT_N" if n < min_n else "MODEL_BETTER" if d["ci95"][1] < 0
                                  else "MODEL_WORSE" if d["ci95"][0] > 0 else "NO_DIFFERENCE")
    return out


# ---------------------------------------------------------------------------
# DIAGNOSIS: why a market loses, and which model change would close the gap.
#
# User decision 2026-10-02 (~7:05 PM CT, the app's prime directive): "every line is its own
# decision. we should have a model that is accurate that then helps inform each decision". A
# backtest therefore does NOT produce a market-level gate; it diagnoses the model. Every candidate
# change below is FITTED on the fit seasons and SCORED on held-out seasons, through production's
# own probability function, so "would help" is a measurement, not an argument.
# ---------------------------------------------------------------------------

# Wide on purpose: the first grid (0.7..2.0) put the fitted k AT ITS EDGE in 5 markets, which
# reads as "the optimum is outside", not as "k = 2.0".
K_GRID = (0.4, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0)
W_GRID = tuple(i / 10 for i in range(11))


def murphy(ps: List[float], ys: List[int], bins: int = 10) -> Dict[str, float]:
    """Brier = reliability - resolution + uncertainty (equal-count bins). A recalibration can only
    move `reliability`; a resolution deficit needs information the model does not have."""
    n = len(ps)
    if not n:
        return {}
    ybar = sum(ys) / n
    order = sorted(range(n), key=lambda i: ps[i])
    rel = res = 0.0
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if not idx:
            continue
        pb = sum(ps[i] for i in idx) / len(idx)
        ob = sum(ys[i] for i in idx) / len(idx)
        rel += len(idx) * (pb - ob) ** 2
        res += len(idx) * (ob - ybar) ** 2
    return {"reliability": round(rel / n, 5), "resolution": round(res / n, 5), "uncertainty": round(ybar * (1 - ybar), 5)}


def _sub(rows: List[Dict[str, Any]], cap: int = 20000, seed: int = 11) -> List[Dict[str, Any]]:
    if len(rows) <= cap:
        return rows
    return random.Random(seed).sample(rows, cap)


def _diag_market(F: List[Dict[str, Any]], T: List[Dict[str, Any]], prob, shift_fit: float,
                 anchor_key: str = "line") -> Dict[str, Any]:
    """`prob(row, shift, k, w)` -> probability. Fit shift (given), k, (shift,k), and the market-anchored
    w on F; report each on T with the model's and the book's Brier on the same rows."""
    def brier(rows, **kw):
        tot = cnt = 0
        for r in rows:
            p = prob(r, **kw)
            if p is None:
                continue
            tot += (_clip(p) - r["y"]) ** 2
            cnt += 1
        return tot / cnt if cnt else float("nan")

    Fs = _sub(F)
    k_best = min(K_GRID, key=lambda k: brier(Fs, shift=0.0, k=k, w=0.0))
    ks_best = min(K_GRID, key=lambda k: brier(Fs, shift=shift_fit, k=k, w=0.0))
    wk = min(((w, k) for w in W_GRID for k in K_GRID), key=lambda t: brier(Fs, shift=0.0, k=t[1], w=t[0]))
    b_model = brier(T, shift=0.0, k=1.0, w=0.0)
    b_book = sum((r["p_book"] - r["y"]) ** 2 for r in T) / len(T)
    gap = b_model - b_book

    def arm(name, **kw):
        b = brier(T, **kw)
        d = boot_ci([(r["gid"], (_clip(prob(r, **kw)) - r["y"]) ** 2 - (r["p_book"] - r["y"]) ** 2)
                     for r in T if prob(r, **kw) is not None])
        return {"arm": name, "params": kw, "brier": round(b, 5),
                "gap_closed_pct": round(100 * (b_model - b) / gap, 1) if gap > 0 else None,
                "dbrier_vs_book": {"point": round(d[0], 5), "ci95": [round(d[1], 5), round(d[2], 5)]}}

    arms = [arm("shift_mean", shift=shift_fit, k=1.0, w=0.0), arm("scale_sd", shift=0.0, k=k_best, w=0.0),
            arm("shift_and_scale", shift=shift_fit, k=ks_best, w=0.0),
            arm("market_anchored_mean", shift=0.0, k=wk[1], w=wk[0])]
    ps = [_clip(prob(r, shift=0.0, k=1.0, w=0.0)) for r in T]
    return {"n_test": len(T), "games_test": len({r["gid"] for r in T}), "brier_model": round(b_model, 5),
            "brier_book": round(b_book, 5), "gap": round(gap, 5),
            "murphy_model": murphy(ps, [r["y"] for r in T]),
            "murphy_book": murphy([r["p_book"] for r in T], [r["y"] for r in T]),
            "arms": sorted(arms, key=lambda a: a["brier"])}


def diagnose_props(prob_rows: Dict[str, List[Dict[str, Any]]], td_rows: List[Dict[str, Any]],
                   fit: List[int], tests: Dict[str, List[int]]) -> Dict[str, Any]:
    from syndicate.features.nfl import props as P
    out: Dict[str, Any] = {"fit_seasons": fit, "tests": tests, "markets": {}}
    for stat, rows in sorted(prob_rows.items()):
        F = [r for r in rows if r["season"] in fit]
        uniq: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in F:
            uniq[(r["gid"], r["player"])] = r
        shift = statistics.fmean(u["actual"] - u["mean"] for u in uniq.values()) if uniq else 0.0

        def prob(r, shift=0.0, k=1.0, w=0.0, _stat=stat):
            mean = (1 - w) * (r["mean"] + shift) + w * r["line"]
            sd = None if r["sd"] is None else r["sd"] * k
            return P._nfl_prop_model_probability(stat=_stat, mean=mean, stdev=sd, n=r["n"], line=r["line"])

        M: Dict[str, Any] = {"fitted_mean_shift": round(shift, 4),
                             "discrete_poisson": stat in getattr(P, "_DISCRETE_COUNT_STATS", ())}
        for label, ss in tests.items():
            T = [r for r in rows if r["season"] in ss]
            if len(T) < 50 or len(F) < 200:
                M[label] = {"n_test": len(T), "status": "INSUFFICIENT_N"}
                continue
            tu: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for r in T:
                tu[(r["gid"], r["player"])] = r
            resid = [u["actual"] - u["mean"] for u in tu.values()]
            sds = [u["sd"] for u in tu.values() if u["sd"]]
            D = _diag_market(F, T, prob, shift)
            D["test_bias_actual_minus_mean"] = round(statistics.fmean(resid), 4)
            D["test_bias_pct_of_mean"] = round(100 * statistics.fmean(resid) / statistics.fmean(u["mean"] for u in tu.values()), 1)
            if sds:
                D["sd_ratio_model_over_empirical"] = round(statistics.fmean(sds) / math.sqrt(statistics.fmean(e * e for e in resid)), 3)
            M[label] = D
        out["markets"][stat] = M
    # anytime TD: one-sided; recalibration slope fitted on F, compared with the vig-INCLUSIVE yes price
    F = [r for r in td_rows if r["season"] in fit]
    if F:
        grid = tuple(x / 100 for x in range(60, 141, 5))
        a = min(grid, key=lambda a: sum((_clip(a * r["p_model"]) - r["y"]) ** 2 for r in F))
        T_out = {}
        for label, ss in tests.items():
            T = [r for r in td_rows if r["season"] in ss]
            if not T:
                continue
            bm = sum((r["p_model"] - r["y"]) ** 2 for r in T) / len(T)
            ba = sum((_clip(a * r["p_model"]) - r["y"]) ** 2 for r in T) / len(T)
            bb = sum((r["p_book_vig_inclusive"] - r["y"]) ** 2 for r in T) / len(T)
            d = boot_ci([(r["gid"], (_clip(a * r["p_model"]) - r["y"]) ** 2 - (r["p_book_vig_inclusive"] - r["y"]) ** 2) for r in T])
            T_out[label] = {"n_test": len(T), "brier_model": round(bm, 5), "brier_recalibrated": round(ba, 5),
                            "brier_book_vig_inclusive": round(bb, 5),
                            "dbrier_recalibrated_vs_book": {"point": round(d[0], 5), "ci95": [round(d[1], 5), round(d[2], 5)]},
                            "mean_p_model": round(statistics.fmean(r["p_model"] for r in T), 4),
                            "observed_rate": round(statistics.fmean(r["y"] for r in T), 4),
                            "murphy_model": murphy([r["p_model"] for r in T], [r["y"] for r in T]),
                            "murphy_book": murphy([r["p_book_vig_inclusive"] for r in T], [r["y"] for r in T])}
        out["markets"]["anytime_td"] = {"fitted_scale": a, **T_out}
    return out


def diagnose_lines(rows_by_market: Dict[str, List[Dict[str, Any]]], fit: List[int],
                   tests: Dict[str, List[int]]) -> Dict[str, Any]:
    """Margin/total: Normal(sim mean, sim sd), as the board prices. Moneyline is diagnosed through the
    same Normal on the margin (line 0) next to the raw `home_win_rate` the board actually serves."""
    from syndicate.features.shared.football_cards import cover_probability
    out: Dict[str, Any] = {"fit_seasons": fit, "tests": tests, "markets": {}}
    for m in ("spread", "total", "moneyline"):
        rows = rows_by_market.get(m, [])
        F = [r for r in rows if r["season"] in fit]
        if len(F) < 100:
            out["markets"][m] = {"status": "INSUFFICIENT_FIT_N", "n_fit": len(F)}
            continue
        shift = statistics.fmean(r["actual"] - r["mean"] for r in F)

        def prob(r, shift=0.0, k=1.0, w=0.0):
            mean = (1 - w) * (r["mean"] + shift) + w * r["anchor"]
            return cover_probability(line=r["line"], mean=mean, stdev=r["sd"] * k)

        M: Dict[str, Any] = {"fitted_mean_shift": round(shift, 4)}
        for label, ss in tests.items():
            T = [r for r in rows if r["season"] in ss]
            if len(T) < 30:
                M[label] = {"n_test": len(T), "status": "INSUFFICIENT_N"}
                continue
            resid = [r["actual"] - r["mean"] for r in T]
            D = _diag_market(F, T, prob, shift)
            D["test_bias_actual_minus_mean"] = round(statistics.fmean(resid), 3)
            D["sd_ratio_model_over_empirical"] = round(statistics.fmean(r["sd"] for r in T) / math.sqrt(statistics.fmean(e * e for e in resid)), 3)
            D["corr_model_mean_vs_actual"] = _corr([r["mean"] for r in T], [r["actual"] for r in T])
            D["corr_market_line_vs_actual"] = _corr([r["anchor"] for r in T], [r["actual"] for r in T])
            if m == "moneyline":
                D["brier_served_home_win_rate"] = round(sum((r["p_model"] - r["y"]) ** 2 for r in T) / len(T), 5)
            M[label] = D
        out["markets"][m] = M
    return out


def _corr(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(num / (dx * dy), 4) if dx and dy else None


# ---------------------------------------------------------------------------
# schedule / coverage
# ---------------------------------------------------------------------------

def load_schedule(root: Path) -> Dict[str, Dict[str, Any]]:
    path = root / "tracking" / "nflverse" / "schedules_games.csv"
    out = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type") != "REG":
                continue
            r["season_i"], r["week_i"] = int(r["season"]), int(r["week"])
            r["completed"] = r.get("home_score", "") != "" and r.get("away_score", "") != ""
            out[r["game_id"]] = r
    return out


def pbp_weeks(root: Path, season: int) -> Dict[int, int]:
    """REG games per week present in the pbp file (one cheap column scan)."""
    path = root / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    if not path.exists():
        return {}
    games: Dict[int, set] = defaultdict(set)
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") == "REG":
                games[int(r["week"])].add(r["game_id"])
    return {w: len(g) for w, g in sorted(games.items())}


# ---------------------------------------------------------------------------
# GAME LINES -- simulation (worker side)
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _worker_init(root: str) -> None:
    configure_env(Path(root))
    try:
        import psutil  # be a polite neighbour: production runs on this machine
        p = psutil.Process()
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:
        pass
    from scripts import generate_smartsim2_nfl_projections as gen
    _W["gen"] = gen
    _W["plays"] = {}


def _plays(season: int):
    if season not in _W["plays"]:
        _W["plays"][season] = _W["gen"].load_pbp_plays(season)
    return _W["plays"][season]


def sim_game(task: Dict[str, Any]) -> Dict[str, Any]:
    gen = _W["gen"]
    s = task["season"]
    proj, _ = gen.build_projection(season=s, week=task["week"], home_team=task["home"], away_team=task["away"],
                                   game_id=task["game_id"], current_plays=_plays(s), prior_plays=_plays(s - 1),
                                   seeds=task["seeds"])
    d = {k: getattr(proj, k) for k in ("game_id", "season", "week", "home_team", "away_team", "home_score_mean",
                                        "away_score_mean", "margin_mean", "total_mean", "margin_stdev",
                                        "total_stdev", "home_win_rate", "seeds_used", "rating_source")}
    return d


def run_sims(root: Path, out: Path, tasks: List[Dict[str, Any]], workers: int) -> Dict[str, Dict[str, Any]]:
    cache = out / "lines_sims.jsonl"
    done: Dict[str, Dict[str, Any]] = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[f"{d['game_id']}|{d['seeds_used']}"] = d
    todo = [t for t in tasks if f"{t['game_id']}|{t['seeds']}" not in done]
    print(f"[lines] {len(tasks)} games, {len(tasks) - len(todo)} cached, {len(todo)} to simulate on {workers} workers", flush=True)
    if todo:
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=(str(root),)) as ex, \
                cache.open("a", encoding="utf-8") as fh:
            futs = {ex.submit(sim_game, t): t for t in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                d = fut.result()
                fh.write(json.dumps(d) + "\n")
                fh.flush()
                done[f"{d['game_id']}|{d['seeds_used']}"] = d
                if i % 20 == 0 or i == len(todo):
                    el = time.time() - t0
                    print(f"[lines] {i}/{len(todo)} simulated, {el / 60:.1f} min, eta {el / i * (len(todo) - i) / 60:.1f} min", flush=True)
    return {k.split("|")[0]: v for k, v in done.items()}


# ---------------------------------------------------------------------------
# GAME LINES -- scoring
# ---------------------------------------------------------------------------

class LeagueAsOf:
    """As-of league rates from completed REG games of the prior season + this season before this week."""

    def __init__(self, sched: Dict[str, Dict[str, Any]]) -> None:
        self.games = [g for g in sched.values() if g["completed"]]

    @functools.lru_cache(maxsize=None)
    def rates(self, season: int, week: int) -> Optional[Dict[str, float]]:
        pool = [g for g in self.games if g["season_i"] == season - 1 or (g["season_i"] == season and g["week_i"] < week)]
        if not pool:
            return None
        m = [float(g["home_score"]) - float(g["away_score"]) for g in pool]
        t = [float(g["home_score"]) + float(g["away_score"]) for g in pool]
        dec = [x for x in m if x != 0]
        cov = [(x, _f(g["spread_line"])) for x, g in zip(m, pool) if _f(g["spread_line"]) is not None and x != _f(g["spread_line"])]
        ov = [(x, _f(g["total_line"])) for x, g in zip(t, pool) if _f(g["total_line"]) is not None and x != _f(g["total_line"])]
        return {"margin": statistics.fmean(m), "total": statistics.fmean(t),
                "p_home_win": sum(1 for x in dec if x > 0) / len(dec) if dec else 0.5,
                "p_home_cover": sum(1 for x, l in cov if x > l) / len(cov) if cov else 0.5,
                "p_over": sum(1 for x, l in ov if x > l) / len(ov) if ov else 0.5, "n_games": len(pool)}


def score_lines(sched: Dict[str, Dict[str, Any]], sims: Dict[str, Dict[str, Any]], season_groups: Dict[str, List[int]],
                min_n: int) -> Dict[str, Any]:
    from syndicate.features.shared.football_cards import cover_probability
    league = LeagueAsOf(sched)
    drops = Counter()
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # market -> rows
    for gid, g in sched.items():
        if gid not in sims or not g["completed"]:
            continue
        s = sims[gid]
        base = league.rates(g["season_i"], g["week_i"])
        if base is None:
            drops["no_asof_baseline"] += 1
            continue
        hs, as_ = float(g["home_score"]), float(g["away_score"])
        margin, total = hs - as_, hs + as_
        common = {"gid": gid, "season": g["season_i"], "week": g["week_i"]}
        spread, tot_line = _f(g["spread_line"]), _f(g["total_line"])
        rows["margin_point"].append({**common, "y": margin, "model": s["margin_mean"], "base": base["margin"],
                                     **({"book": spread} if spread is not None else {})})
        rows["total_point"].append({**common, "y": total, "model": s["total_mean"], "base": base["total"],
                                    **({"book": tot_line} if tot_line is not None else {})})
        # moneyline
        hml, aml = _f(g["home_moneyline"]), _f(g["away_moneyline"])
        if margin == 0:
            drops["moneyline_tie_excluded"] += 1
        elif hml is None or aml is None:
            drops["moneyline_no_two_sided_price"] += 1
        else:
            rows["moneyline"].append({**common, "y": int(margin > 0), "p_model": s["home_win_rate"],
                                      "mean": s["margin_mean"], "sd": s["margin_stdev"], "line": 0.0,
                                      "anchor": spread if spread is not None else s["margin_mean"], "actual": margin,
                                      "p_book": devig(implied(hml), implied(aml)), "p_base": base["p_home_win"],
                                      "dec_yes": american_to_dec(hml), "dec_no": american_to_dec(aml)})
        # spread: P(home covers) = P(margin > spread_line), spread_line home-margin-positive
        hso, aso = _f(g["home_spread_odds"]), _f(g["away_spread_odds"])
        if spread is None or hso is None or aso is None:
            drops["spread_no_two_sided_price"] += 1
        elif margin == spread:
            drops["spread_push_excluded"] += 1
        else:
            p = cover_probability(line=spread, mean=s["margin_mean"], stdev=s["margin_stdev"])
            rows["spread"].append({**common, "y": int(margin > spread), "p_model": p,
                                   "mean": s["margin_mean"], "sd": s["margin_stdev"], "line": spread, "anchor": spread,
                                   "actual": margin,
                                   "p_book": devig(implied(hso), implied(aso)), "p_base": base["p_home_cover"],
                                   "dec_yes": american_to_dec(hso), "dec_no": american_to_dec(aso)})
        oo, uo = _f(g["over_odds"]), _f(g["under_odds"])
        if tot_line is None or oo is None or uo is None:
            drops["total_no_two_sided_price"] += 1
        elif total == tot_line:
            drops["total_push_excluded"] += 1
        else:
            p = cover_probability(line=tot_line, mean=s["total_mean"], stdev=s["total_stdev"])
            rows["total"].append({**common, "y": int(total > tot_line), "p_model": p,
                                  "mean": s["total_mean"], "sd": s["total_stdev"], "line": tot_line, "anchor": tot_line,
                                  "actual": total,
                                  "p_book": devig(implied(oo), implied(uo)), "p_base": base["p_over"],
                                  "dec_yes": american_to_dec(oo), "dec_no": american_to_dec(uo)})
    report: Dict[str, Any] = {"drops": dict(drops), "groups": {}}
    _SELF["line_rows"] = rows
    for label, seasons in season_groups.items():
        G: Dict[str, Any] = {"seasons": seasons}
        sel = {m: [r for r in rr if r["season"] in seasons] for m, rr in rows.items()}
        for m in ("margin_point", "total_point"):
            rr = [r for r in sel.get(m, []) if "book" in r]
            G[m] = point_block(rr, ("model", "base", "book"), min_n)
        for m in ("moneyline", "spread", "total"):
            G[m] = prob_block(sel.get(m, []), ("p_model", "p_book", "p_base"), min_n, ev_odds=("dec_yes", "dec_no"))
        G["weeks"] = sorted({(r["season"], r["week"]) for r in sel.get("margin_point", [])})
        G["n_weeks"] = len(G["weeks"])
        G["weeks"] = [f"{s}w{w}" for s, w in G["weeks"]]
        # the gate
        G["beats_baseline_and_book"] = {
            "spread": G["margin_point"].get("verdict_vs_base") == "MODEL_BETTER" and G["spread"].get("verdict_vs_book") == "MODEL_BETTER",
            "total": G["total_point"].get("verdict_vs_base") == "MODEL_BETTER" and G["total"].get("verdict_vs_book") == "MODEL_BETTER",
            "moneyline": G["moneyline"].get("verdict_vs_base") == "MODEL_BETTER" and G["moneyline"].get("verdict_vs_book") == "MODEL_BETTER",
        }
        report["groups"][label] = G
    return report


def reproduce(root: Path, out: Path, season: int, week: int, sched: Dict[str, Dict[str, Any]], workers: int) -> Dict[str, Any]:
    """Re-run a week production already wrote; compare every numeric field."""
    prod_path = root / "fleet_snapshot" / f"smartsim2_projections_{season}_wk{week}.csv"
    with prod_path.open(encoding="utf-8", newline="") as fh:
        prod = {r["game_id"]: r for r in csv.DictReader(fh)}
    tasks = [{"season": season, "week": week, "home": r["home_team"], "away": r["away_team"], "game_id": gid,
              "seeds": int(float(r.get("seeds_used") or 300))} for gid, r in prod.items()]
    sims = run_sims(root, out, tasks, workers)
    fields = ("home_score_mean", "away_score_mean", "margin_mean", "total_mean", "margin_stdev", "total_stdev", "home_win_rate")
    diffs = []
    for gid, r in prod.items():
        s = sims[gid]
        diffs.append({"game_id": gid, "rating_source_prod": r.get("rating_source"), "rating_source_harness": s["rating_source"],
                      **{f: round(s[f] - float(r[f]), 4) for f in fields if r.get(f) not in (None, "")}})
    maxabs = {f: max(abs(d.get(f, 0.0)) for d in diffs) for f in fields}
    return {"week": f"{season}w{week}", "games": len(diffs), "max_abs_diff": maxabs,
            "rating_source_mismatch": sum(1 for d in diffs if d["rating_source_prod"] != d["rating_source_harness"]),
            "exact": all(v == 0 for v in maxabs.values()), "per_game": diffs}


# ---------------------------------------------------------------------------
# PROPS
# ---------------------------------------------------------------------------

def _patch_game_log_cache() -> None:
    from syndicate.features.nfl import player_stats
    if not getattr(player_stats.player_game_log, "_bt_cached", False):
        cached = functools.lru_cache(maxsize=None)(player_stats.player_game_log)
        cached._bt_cached = True  # type: ignore[attr-defined]
        player_stats.player_game_log = cached  # module global: player_rate / final_stat_value look it up here


def load_quotes(root: Path, seasons: List[int]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Normalised quote rows: one per (event, book, market, player, line, selection), latest snapshot."""
    from syndicate.features.nfl.props import _NFL_PROP_MARKET_TO_STAT
    raw: List[Dict[str, Any]] = []
    src: Dict[str, Any] = {}
    for s in seasons:
        files = sorted(glob.glob(str(root / "tracking" / "book_quotes" / f"{s}_wk*.jsonl")))
        for f in files:
            for line in open(f, encoding="utf-8"):
                if not line.strip():
                    continue
                q = json.loads(line)
                if q.get("kind") != "prop" or (q.get("segment") or "full") != "full":
                    continue
                raw.append({"season_hint": s, "home": q["home_team"], "away": q["away_team"], "commence": q["commence_time"],
                            "book": q["bookmaker"], "market": q["market"], "player": q["player_name"],
                            "line": _f(q.get("line")), "sel": str(q.get("selection") or "").lower(), "price": _f(q.get("price")),
                            "snap": q.get("snapshot_ts") or "", "src": "book_quotes"})
        if files:
            src[str(s)] = {"source": "tracking/book_quotes/<season>_wk<N>.jsonl (OddsAPI historical, kickoff-10min)", "files": len(files)}
    # 2026: the only surviving in-season capture (see findings; named wk1, holds week 2).
    if 2026 in seasons:
        for f in sorted(glob.glob(str(root / "odds_2026" / "*.csv"))):
            with open(f, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    for sel, col in (("over", "over_price"), ("under", "under_price")):
                        price = _f(r.get(col))
                        if price is None:
                            continue
                        if r["market"] == "Anytime TD":
                            sel = "yes" if sel == "over" else "no"
                        raw.append({"season_hint": 2026, "home": r["home_team"], "away": r["away_team"], "commence": r["game_time"],
                                    "book": r["book"], "market": r["market"], "player": r["player"], "line": _f(r.get("line")),
                                    "sel": sel, "price": price, "snap": "", "src": Path(f).name})
            src.setdefault("2026", {"source": [], "files": 0})
            src["2026"]["source"].append(Path(f).name)
            src["2026"]["files"] += 1
    latest: Dict[Tuple, Dict[str, Any]] = {}
    for q in raw:
        if q["price"] is None or q["market"] not in _NFL_PROP_MARKET_TO_STAT:
            continue
        k = (q["home"], q["away"], q["commence"], q["book"], q["market"], q["player"], q["line"], q["sel"])
        if k not in latest or q["snap"] > latest[k]["snap"]:
            latest[k] = q
    return list(latest.values()), src


def map_events(quotes: List[Dict[str, Any]], sched: Dict[str, Dict[str, Any]]) -> Tuple[Dict[Tuple, str], Counter]:
    from syndicate.features.shared.team_aliases import canonical_team
    idx: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for g in sched.values():
        idx[(canonical_team("nfl", g["home_team"]), canonical_team("nfl", g["away_team"]))].append(g)
    out: Dict[Tuple, str] = {}
    miss = Counter()
    for q in quotes:
        ek = (q["home"], q["away"], q["commence"])
        if ek in out:
            continue
        cands = idx.get((canonical_team("nfl", q["home"]), canonical_team("nfl", q["away"])), [])
        try:
            d = datetime.fromisoformat(q["commence"].replace("Z", "+00:00")).date()
        except ValueError:
            miss["bad_commence"] += 1
            continue
        hit = [g for g in cands if abs((_date.fromisoformat(g["gameday"]) - d).days) <= 1]
        if len(hit) == 1:
            out[ek] = hit[0]["game_id"]
        else:
            miss["no_unique_schedule_game" if not hit else "ambiguous_schedule_game"] += 1
    return out, miss


def score_props(root: Path, sched: Dict[str, Dict[str, Any]], seasons: List[int], season_groups: Dict[str, List[int]],
                min_n: int) -> Dict[str, Any]:
    _patch_game_log_cache()
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P
    from syndicate.features.shared.team_aliases import canonical_team

    # THE CONTEXT TERM MUST BE FED, or "model" silently equals "own average" on every row.
    # First run of this harness (2026-10-02): the scratch root had no `upcoming_recs_*.csv`,
    # `default_nfl_source_root()` probed past it, `game_context()` read no schedule, and the
    # multiplier was exactly 1.0 on 100% of rows -- while the production-equivalence selfcheck
    # still PASSED, because harness and production code shared the same mis-resolved root.
    from syndicate.features.nfl.game_context import game_context
    unfed = [s for s in seasons if not game_context(s)]
    if unfed:
        raise SystemExit(f"refusing: game_context() resolves no schedule for {unfed} under "
                         f"{os.environ.get('SYNDICATE_NFL_SOURCE_ROOT')} -- the props context multiplier would be a "
                         "silent 1.0. Production's root carries upcoming_recs_*.csv, which is what the resolver probes for.")
    quotes, sources = load_quotes(root, seasons)
    ev_map, ev_miss = map_events(quotes, sched)
    drops = Counter()
    for k, v in ev_miss.items():
        drops[f"event_{k}"] += v

    # resolve each (game, player, stat) ONCE: model mean/sd/n, baseline mean, actual
    resolved: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}

    def resolve(gid: str, name: str, stat: str) -> Optional[Dict[str, Any]]:
        key = (gid, name, stat)
        if key in resolved:
            return resolved[key]
        g = sched[gid]
        season, week = g["season_i"], g["week_i"]
        res: Optional[Dict[str, Any]] = None
        pid, id_src = ps.resolve_player_id_with_prior(season, name)
        if pid is None:
            drops["player_unresolved"] += 1
        else:
            team, _ = ps.player_team_with_prior(season, week, pid)
            canon = canonical_team("nfl", team) if team else None
            game = {canonical_team("nfl", g["home_team"]), canonical_team("nfl", g["away_team"])}
            if canon is None:
                drops["player_team_unknown_refused"] += 1
            elif canon not in game:
                drops["player_wrong_team_refused"] += 1
            else:
                if stat == "anytime_td":
                    mean, n, rsrc = ps.anytime_td_rate_with_prior(season, week, pid)
                    sd = None
                    bmean, _bsd, bn, _ = ps.player_rate_with_prior(season, week, pid, "anytime_td")  # raw own average
                else:
                    mean, sd, n, rsrc = ps.player_rate_with_prior(season, week, pid, stat)
                    bmean, bn = mean, n
                if mean is None or bmean is None:
                    drops["no_model_rate"] += 1
                else:
                    mult = P.nfl_game_context_multiplier(season, week, pid, stat)
                    actual = ps.final_stat_value(season, gid, pid, stat)
                    if actual is None:
                        drops["no_pbp_line_for_player_in_game_void"] += 1
                    else:
                        log = [r for r in ps.player_game_log(season, pid) if r["week"] < week][-4:]
                        last4 = statistics.fmean(r[stat] for r in log) if len(log) >= 2 else None
                        res = {"pid": pid, "season": season, "week": week, "mean_model": float(mean) * mult, "ctx": mult,
                               "mean_base": float(bmean), "base_n": bn, "sd": sd, "n": n, "rate_source": rsrc,
                               "actual": float(actual), "last4": last4}
        resolved[key] = res
        return res

    # pair sides per (game, book, market, player, line)
    pairs: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for q in quotes:
        gid = ev_map.get((q["home"], q["away"], q["commence"]))
        if gid is None:
            continue
        if not sched[gid]["completed"]:
            drops["game_not_completed"] += 1
            continue
        pairs[(gid, q["book"], q["market"], q["player"], q["line"])][q["sel"]] = q["price"]

    prob_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    td_rows: List[Dict[str, Any]] = []
    point_seen: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    line_by_gps: Dict[Tuple[str, str, str], Dict[str, List[Tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    for (gid, book, market, player, line), sides in pairs.items():
        stat = P._NFL_PROP_MARKET_TO_STAT[market]
        r = resolve(gid, player, stat)
        if r is None:
            continue
        point_seen[(gid, player, stat)] = r
        if stat == "anytime_td":
            if "yes" not in sides:
                continue
            p_model = P._nfl_prop_model_probability(stat=stat, mean=r["mean_model"], stdev=None, n=r["n"], line=None)
            p_base = P._nfl_prop_model_probability(stat=stat, mean=r["mean_base"], stdev=None, n=max(2, r["base_n"]), line=None)
            if p_model is None or p_base is None:
                drops["td_no_probability"] += 1
                continue
            row = {"gid": gid, "season": r["season"], "y": int(r["actual"] >= 1), "p_model": p_model, "p_base": p_base,
                   "n": r["n"],
                   "p_book_vig_inclusive": implied(sides["yes"]), "book": book}
            if "no" in sides:
                row["p_book"] = devig(implied(sides["yes"]), implied(sides["no"]))
            td_rows.append(row)
            continue
        if line is None:
            drops["no_line"] += 1
            continue
        if "over" not in sides or "under" not in sides:
            drops["one_sided_excluded"] += 1
            continue
        if r["actual"] == line:
            drops["push_excluded"] += 1
            continue
        p_model = P._nfl_prop_model_probability(stat=stat, mean=r["mean_model"], stdev=r["sd"], n=r["n"], line=line)
        p_base = P._nfl_prop_model_probability(stat=stat, mean=r["mean_base"], stdev=r["sd"], n=r["n"], line=line)
        if p_model is None or p_base is None:
            drops["no_model_probability"] += 1
            continue
        pb = devig(implied(sides["over"]), implied(sides["under"]))
        line_by_gps[(gid, player, stat)][book].append((abs(pb - 0.5), line))
        prob_rows[stat].append({"gid": gid, "season": r["season"], "y": int(r["actual"] > line), "p_model": p_model,
                                "p_base": p_base, "p_book": pb, "dec_yes": american_to_dec(sides["over"]),
                                "dec_no": american_to_dec(sides["under"]), "book": book, "line": line,
                                "player": player, "mean": r["mean_model"], "sd": r["sd"], "n": r["n"],
                                "actual": r["actual"], "pid": r["pid"], "week": r["week"], "ctx": r["ctx"]})

    # point rows: one per (game, player, stat); book point = median over books of each book's most-balanced line
    point_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for (gid, player, stat), r in point_seen.items():
        row = {"gid": gid, "season": r["season"], "y": r["actual"], "model": r["mean_model"], "base": r["mean_base"],
               "ctx": r["ctx"], "src": r["rate_source"]}
        if r["last4"] is not None:
            row["last4"] = r["last4"]
        by_book = line_by_gps.get((gid, player, stat))
        if by_book:
            # each book's MOST BALANCED line (its main line, not an alt), then the median across books
            row["book"] = statistics.median(min(c)[1] for c in by_book.values())
        point_rows[stat].append(row)

    report: Dict[str, Any] = {"sources": sources, "drops": dict(drops), "n_quotes": len(quotes),
                              "events_mapped": len(ev_map), "groups": {}}
    for label, ss in season_groups.items():
        G: Dict[str, Any] = {"seasons": ss, "markets": {}}
        for stat in PROP_STATS:
            M: Dict[str, Any] = {}
            pr = [r for r in point_rows.get(stat, []) if r["season"] in ss]
            M["point_all"] = point_block(pr, ("model", "base"), min_n)
            M["point_vs_book_line"] = point_block([r for r in pr if "book" in r], ("model", "base", "book"), min_n)
            M["point_vs_last4"] = point_block([r for r in pr if "last4" in r], ("model", "base", "last4"), min_n)
            M["ctx_multiplier"] = ({"mean": round(statistics.fmean(r["ctx"] for r in pr), 4),
                                    "share_not_1": round(sum(1 for r in pr if r["ctx"] != 1.0) / len(pr), 4)} if pr else {})
            M["rate_source"] = dict(Counter(r["src"] for r in pr))
            if stat == "anytime_td":
                tr = [r for r in td_rows if r["season"] in ss]
                M["prob_vs_actual"] = prob_block(tr, ("p_model", "p_base", "p_book_vig_inclusive"), min_n,
                                                 book_key=None, base_key="p_base")
                # One-sided: the YES price still carries the vig, so this comparator is TILTED toward
                # over-stating P(score). A model that loses to it is not rescued by de-vigging.
                M["prob_vs_book_vig_inclusive"] = prob_block(tr, ("p_model", "p_book_vig_inclusive", "p_base"), min_n,
                                                             book_key="p_book_vig_inclusive", base_key=None)
                two = [r for r in tr if "p_book" in r]
                M["prob_vs_book"] = prob_block(two, ("p_model", "p_book", "p_base"), min_n)
                M["two_sided_rows"] = len(two)
                M["beats_baseline_and_book"] = (M["prob_vs_actual"].get("verdict_vs_base") == "MODEL_BETTER"
                                 and M["prob_vs_book"].get("verdict_vs_book") == "MODEL_BETTER")
            else:
                rr = [r for r in prob_rows.get(stat, []) if r["season"] in ss]
                M["prob_vs_book"] = prob_block(rr, ("p_model", "p_book", "p_base"), min_n, ev_odds=("dec_yes", "dec_no"))
                M["beats_baseline_and_book"] = (M["point_all"].get("verdict_vs_base") == "MODEL_BETTER"
                                 and M["prob_vs_book"].get("verdict_vs_book") == "MODEL_BETTER")
            G["markets"][stat] = M
        G["weeks"] = sorted({f"{sched[r['gid']]['season_i']}w{sched[r['gid']]['week_i']}"
                             for rr in point_rows.values() for r in rr if r["season"] in ss})
        G["n_weeks"] = len(G["weeks"])
        G["games"] = len({r["gid"] for rr in point_rows.values() for r in rr if r["season"] in ss})
        report["groups"][label] = G
    report["player_market_games_resolved"] = sum(1 for v in resolved.values() if v is not None)
    report["player_market_games_attempted"] = len(resolved)
    _SELF["prob_rows"] = prob_rows
    _SELF["td_rows"] = td_rows
    return report


_SELF: Dict[str, Any] = {}


def selfcheck(root: Path, sched: Dict[str, Dict[str, Any]], season: int, week: int) -> Dict[str, Any]:
    """Write one week's scored quotes in the production CSV contract; production must agree on every probability."""
    from syndicate.features.nfl import props as P
    inv = {v: k for k, v in P._NFL_PROP_MARKET_TO_STAT.items()}
    rows = [r for rr in _SELF["prob_rows"].values() for r in rr
            if sched[r["gid"]]["season_i"] == season and sched[r["gid"]]["week_i"] == week]
    if not rows:
        return {"week": f"{season}w{week}", "status": "NO_ROWS"}
    stat_of = {id(r): s for s, rr in _SELF["prob_rows"].items() for r in rr}
    path = root / f"oddsapi_player_props_{season}_wk{week}.csv"
    if path.exists():
        return {"week": f"{season}w{week}", "status": f"REFUSED: {path.name} exists"}
    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["player", "team", "market", "line", "over_price", "under_price", "book", "event", "game_time",
                        "home_team", "away_team", "is_ladder"])
            for r in rows:
                g = sched[r["gid"]]
                w.writerow([r["player"], "", inv[stat_of[id(r)]], r["line"], 100, -120, r["book"], "",
                            f"{g['gameday']}T17:00:00Z", g["home_team"], g["away_team"], "False"])
        P._nfl_raw_player_props.cache_clear()
        _odds, sim_rows = P.nfl_props_rows_for_week(season, week, use_artifact=False)
        prod = {}
        for s in sim_rows:
            prod[(s["entity"], s["market"])] = s["sim_projection"]
        mism = checked = 0
        examples = []
        for r in rows:
            key = (r["player"], P._nfl_prop_join_market_key(stat_of[id(r)], r["player"], r["line"]))
            if key not in prod:
                continue
            checked += 1
            if abs(prod[key] - r["p_model"]) > 1e-9:
                mism += 1
                if len(examples) < 5:
                    examples.append({"key": list(key), "prod": prod[key], "harness": r["p_model"]})
        return {"week": f"{season}w{week}", "harness_rows": len(rows), "checked": checked, "mismatch": mism,
                "examples": examples, "status": "PASS" if checked and not mism else "FAIL"}
    finally:
        path.unlink(missing_ok=True)
        P._nfl_raw_player_props.cache_clear()


# ---------------------------------------------------------------------------
# coverage + report
# ---------------------------------------------------------------------------

def coverage(root: Path, sched: Dict[str, Dict[str, Any]], seasons: List[int], sims: Dict[str, Any],
             quotes_games: Dict[int, set]) -> Dict[str, Any]:
    out = {}
    for s in seasons:
        sg = [g for g in sched.values() if g["season_i"] == s]
        done = [g for g in sg if g["completed"]]
        pw = pbp_weeks(root, s)
        fam = {
            "schedule_completed_games": len(done),
            "final_scores_weeks": sorted({g["week_i"] for g in done}),
            "pbp_games": sum(pw.values()), "pbp_weeks": sorted(pw),
            "closing_two_sided_ml": sum(1 for g in done if _f(g["home_moneyline"]) is not None and _f(g["away_moneyline"]) is not None),
            "closing_two_sided_spread": sum(1 for g in done if _f(g["home_spread_odds"]) is not None and _f(g["spread_line"]) is not None),
            "closing_two_sided_total": sum(1 for g in done if _f(g["over_odds"]) is not None and _f(g["total_line"]) is not None),
            "projections_simulated": sum(1 for g in done if g["game_id"] in sims),
            "prop_quote_games": len(quotes_games.get(s, set())),
            "prop_quote_weeks": sorted({sched[x]["week_i"] for x in quotes_games.get(s, set())}),
        }
        lines_int = [g for g in done if g["game_id"] in sims and _f(g["spread_line"]) is not None]
        props_int = [g for g in done if g["game_id"] in quotes_games.get(s, set()) and g["week_i"] in pw]
        fam["INTERSECTION_lines_games"] = len(lines_int)
        fam["INTERSECTION_lines_weeks"] = len({g["week_i"] for g in lines_int})
        fam["INTERSECTION_props_games"] = len(props_int)
        fam["INTERSECTION_props_weeks"] = len({g["week_i"] for g in props_int})
        out[str(s)] = fam
    return out


def _fmt_ci(d: Optional[Dict[str, Any]]) -> str:
    return "" if not d else f"{d['point']} [{d['ci95'][0]}, {d['ci95'][1]}]"


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L = ["# NFL game lines + player props backtest (as-of)", "",
         f"generated {rep['generated_at']}; min_n {rep['min_n']}; env `{json.dumps(rep['env'])}`", "",
         "## coverage per family, and the intersection", "", "```", json.dumps(rep["coverage"], indent=1), "```", ""]
    if rep.get("reproduce"):
        r = rep["reproduce"]
        L += ["## fidelity: harness vs production's own artifact", "",
              f"{r['week']}: {r['games']} games, exact={r['exact']}, max |diff| `{json.dumps(r['max_abs_diff'])}`, "
              f"rating_source mismatches {r['rating_source_mismatch']}", ""]
    for sc in rep.get("selfcheck", []):
        L.append(f"- props selfcheck {sc}")
    L.append("")
    lines = rep.get("lines")
    if lines:
        L += ["## game lines", "", f"drops `{json.dumps(lines['drops'])}`", ""]
        for label, G in lines["groups"].items():
            L += [f"### {label} ({G['n_weeks']} weeks)", "",
                  "| market | n | MAE model | MAE base | MAE book | bias model | dMAE vs base [CI] | dMAE vs book [CI] | verdict vs base |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for m in ("margin_point", "total_point"):
                v = G[m]
                if not v.get("n"):
                    continue
                L.append(f"| {m} | {v['n']} | {v['model']['mae']} | {v['base']['mae']} | {v['book']['mae']} | {v['model']['bias']} | "
                         f"{_fmt_ci(v.get('dmae_model_vs_base'))} | {_fmt_ci(v.get('dmae_model_vs_book'))} | {v.get('verdict_vs_base')} |")
            L += ["", "| market | n | base rate | Brier model | Brier book | Brier base | dBrier vs book [CI] | dLL vs book [CI] | dBrier vs base [CI] | EV bets n / ROI [CI] | vs book | vs base |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for m in ("moneyline", "spread", "total"):
                v = G[m]
                if not v.get("n"):
                    continue
                e = v.get("ev_bets", {})
                L.append(f"| {m} | {v['n']} | {v['base_rate']} | {v['p_model']['brier']} | {v['p_book']['brier']} | {v['p_base']['brier']} | "
                         f"{_fmt_ci(v.get('dbrier_model_vs_book'))} | {_fmt_ci(v.get('dlogloss_model_vs_book'))} | {_fmt_ci(v.get('dbrier_model_vs_base'))} | "
                         f"{e.get('n')} / {e.get('roi', '')} {e.get('roi_ci95', '')} | {v.get('verdict_vs_book')} | {v.get('verdict_vs_base')} |")
            L += ["", f"beats baseline AND book (a description, not a gate -- every line is its own decision): `{json.dumps(G['beats_baseline_and_book'])}`", ""]
    props = rep.get("props")
    if props:
        L += ["## player props", "", f"quotes {props['n_quotes']}, events mapped {props['events_mapped']}; sources `{json.dumps(props['sources'])}`",
              "", f"drops `{json.dumps(props['drops'])}`", ""]
        for label, G in props["groups"].items():
            L += [f"### {label} ({G['n_weeks']} weeks, {G['games']} games)", "",
                  "| market | n | MAE model | MAE own-avg | dMAE vs own-avg [CI] | bias model | n w/ book | MAE book line | dMAE vs book line [CI] | dMAE vs last-4 [CI] | ctx mean / share!=1 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for stat, M in G["markets"].items():
                a, b, c = M["point_all"], M["point_vs_book_line"], M["point_vs_last4"]
                if not a.get("n"):
                    continue
                ctx = M.get("ctx_multiplier") or {}
                L.append(f"| {stat} | {a['n']} | {a['model']['mae']} | {a['base']['mae']} | {_fmt_ci(a.get('dmae_model_vs_base'))} | {a['model']['bias']} | "
                         f"{b.get('n', 0)} | {b.get('book', {}).get('mae', '')} | {_fmt_ci(b.get('dmae_model_vs_book'))} | {_fmt_ci(c.get('dmae_model_vs_last4'))} | "
                         f"{ctx.get('mean', '')} / {ctx.get('share_not_1', '')} |")
            L += ["", "| market | n rows | games | over rate | Brier model | Brier book | Brier own-avg | dBrier vs book [CI] | dLL vs book [CI] | dBrier vs own-avg [CI] | EV bets n / ROI [CI] | vs book | beats both |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for stat, M in G["markets"].items():
                v = M["prob_vs_book"]
                if not v.get("n"):
                    if stat == "anytime_td":
                        t = M["prob_vs_actual"]
                        if t.get("n"):
                            L.append(f"| anytime_td (one-sided: {M['two_sided_rows']} two-sided) | {t['n']} | {t['games']} | {t['base_rate']} | {t['p_model']['brier']} | "
                                     f"vig-incl {t['p_book_vig_inclusive']['brier']} | {t['p_base']['brier']} | NOT DE-VIGGABLE | | {_fmt_ci(t.get('dbrier_model_vs_base'))} | | n/a | {M['beats_baseline_and_book']} |")
                    continue
                e = v.get("ev_bets", {})
                L.append(f"| {stat} | {v['n']} | {v['games']} | {v['base_rate']} | {v['p_model']['brier']} | {v['p_book']['brier']} | {v['p_base']['brier']} | "
                         f"{_fmt_ci(v.get('dbrier_model_vs_book'))} | {_fmt_ci(v.get('dlogloss_model_vs_book'))} | {_fmt_ci(v.get('dbrier_model_vs_base'))} | "
                         f"{e.get('n')} / {e.get('roi', '')} {e.get('roi_ci95', '')} | {v.get('verdict_vs_book')} | {M['beats_baseline_and_book']} |")
            L.append("")
    for key, title in (("lines_diagnosis", "game lines"), ("props_diagnosis", "player props")):
        D = rep.get(key)
        if not D:
            continue
        L += [f"## diagnosis: {title} (fit {D['fit_seasons']}, scored on held-out seasons)", "",
              "Arms are model changes fitted on the fit seasons and scored on held-out rows through production's "
              "probability function. gap closed = share of the model-minus-book Brier gap removed.", "",
              "| market | test | n | Brier model / book | bias (actual-mean) | sd ratio model/empirical | Murphy rel/res model | Murphy rel/res book | best arm: params, Brier, gap closed %, dBrier vs book [CI] | other arms (gap closed %) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for m, M in D["markets"].items():
            for t, v in M.items():
                if not isinstance(v, dict) or "arms" not in v:
                    continue
                b = v["arms"][0]
                mm, mb = v["murphy_model"], v["murphy_book"]
                others = "; ".join(f"{x['arm']} {x['gap_closed_pct']}" for x in v["arms"][1:])
                L.append(f"| {m} | {t} | {v['n_test']} | {v['brier_model']} / {v['brier_book']} | {v.get('test_bias_actual_minus_mean')} | "
                         f"{v.get('sd_ratio_model_over_empirical', '')} | {mm.get('reliability')} / {mm.get('resolution')} | "
                         f"{mb.get('reliability')} / {mb.get('resolution')} | {b['arm']} `{json.dumps(b['params'])}` {b['brier']}, "
                         f"{b['gap_closed_pct']}%, {_fmt_ci(b['dbrier_vs_book'])} | {others} |")
        td = D["markets"].get("anytime_td") if key == "props_diagnosis" else None
        if td:
            L.append(f"anytime_td: `{json.dumps(td)}`")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="nfl_source root holding tracking/nflverse + tracking/book_quotes")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seasons", default="2023,2024,2025,2026")
    ap.add_argument("--current-season", type=int, default=2026)
    ap.add_argument("--parts", default="lines,props")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--reproduce", default="", help="SEASON:WEEK of a production artifact in <root>/fleet_snapshot")
    ap.add_argument("--selfcheck", default="", help="comma list of SEASON:WEEK for the props production-equivalence check")
    ap.add_argument("--analyze-only", action="store_true", help="score cached sims; simulate nothing")
    a = ap.parse_args()
    root = a.root.resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    env = configure_env(root)
    seasons = [int(x) for x in a.seasons.split(",") if x]
    hist = [s for s in seasons if s != a.current_season]
    groups: Dict[str, List[int]] = {f"{a.current_season} in-season": [a.current_season]} if a.current_season in seasons else {}
    for s in hist:
        groups[f"{s}"] = [s]
    if len(hist) > 1:
        groups[f"historical {min(hist)}-{max(hist)} pooled"] = hist
    sched = load_schedule(root)
    rep: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "min_n": a.min_n, "env": env,
                           "git_head": os.popen(f'git -C "{REPO}" rev-parse --short HEAD').read().strip()}
    if a.reproduce:
        s, w = (int(x) for x in a.reproduce.split(":"))
        rep["reproduce"] = reproduce(root, a.out, s, w, sched, a.workers)
        print(json.dumps({k: v for k, v in rep["reproduce"].items() if k != "per_game"}), flush=True)
    sims: Dict[str, Any] = {}
    parts = set(a.parts.split(","))
    if "lines" in parts:
        tasks = [{"season": g["season_i"], "week": g["week_i"], "home": g["home_team"], "away": g["away_team"],
                  "game_id": gid, "seeds": a.seeds} for gid, g in sorted(sched.items())
                 if g["season_i"] in seasons and g["completed"]]
        if a.analyze_only:
            cache = a.out / "lines_sims.jsonl"
            for line in (cache.read_text(encoding="utf-8").splitlines() if cache.exists() else []):
                d = json.loads(line)
                if d["seeds_used"] == a.seeds:
                    sims[d["game_id"]] = d
        else:
            sims = run_sims(root, a.out, tasks, a.workers)
        rep["lines"] = score_lines(sched, sims, groups, a.min_n)
        fit_l = [x for x in hist if x < max(hist)] if hist else []
        tests_l = {f"{max(hist)} holdout": [max(hist)]} if hist else {}
        if a.current_season in seasons:
            tests_l[f"{a.current_season} in-season"] = [a.current_season]
        if fit_l:
            rep["lines_diagnosis"] = diagnose_lines(_SELF["line_rows"], fit_l, tests_l)
    qgames: Dict[int, set] = defaultdict(set)
    if "props" in parts:
        rep["props"] = score_props(root, sched, seasons, groups, a.min_n)
        for rr in _SELF["prob_rows"].values():
            for r in rr:
                qgames[r["season"]].add(r["gid"])
        rep["selfcheck"] = [selfcheck(root, sched, *(int(x) for x in sw.split(":"))) for sw in a.selfcheck.split(",") if sw]
        fit_p = [x for x in hist if x < max(hist)] if hist else []
        tests_p = {f"{max(hist)} holdout": [max(hist)]} if hist else {}
        if a.current_season in seasons:
            tests_p[f"{a.current_season} in-season"] = [a.current_season]
        if fit_p:
            rep["props_diagnosis"] = diagnose_props(_SELF["prob_rows"], _SELF["td_rows"], fit_p, tests_p)
    rep["coverage"] = coverage(root, sched, seasons, sims, qgames)
    (a.out / "nfl_lines_props_backtest.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    write_md(rep, a.out / "nfl_lines_props_backtest.md")
    print(f"wrote {a.out / 'nfl_lines_props_backtest.json'} and .md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
