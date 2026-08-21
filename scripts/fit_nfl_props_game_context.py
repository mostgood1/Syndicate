#!/usr/bin/env python3
"""Give the NFL prop model the game context it was blind to, and measure it.

THE PROBLEM THIS ATTACKS. `report_nfl_props_roi.py` priced the model against
real closing lines over 64,007 bets: **-7.35%** at best price. Its ranking
carries real signal (held-out calibration is monotone, 0.500 -> 0.639) but the
projection itself is `Normal(rolling mean, rolling stdev)` off a player's own
prior games and NOTHING ELSE -- no opponent, no usage, and critically no game
total or spread, which is what books actually price props off.

THE MECHANISM. Two multipliers on the projected mean, both self-normalising
against the player's OWN history:

    adjusted = mean * ratio**alpha * exp(beta * spread_delta)

    ratio        = this game's implied team total / the player's average
                   implied team total over the games behind his rolling rate
    spread_delta = this game's spread minus that same historical average

Self-normalising is the load-bearing design choice, not a detail.
`model_engine_standard.md` 4.4: a rolling mean has ALREADY absorbed the average
game script of its own window, and re-applying it against a league baseline
double-counts -- the doc records two mechanisms doing exactly that and producing
a negative interaction in 4 of 4 markets. Here, `ratio == 1` and
`spread_delta == 0` when this week matches the player's history, so the
multiplier is exactly 1.0 and the mechanism moves a projection ONLY to the
extent the context differs from what calibration already carries.

TWO TERMS BECAUSE THEY DRIVE DIFFERENT THINGS. Implied total moves scoring
(yards, TDs, receptions). Spread moves the run/pass MIX -- a team favoured by
two touchdowns runs more and throws less at the same implied total. A single
term cannot represent both, and `passing_attempts` and `rushing_attempts` should
come out with opposite-signed betas if this is working.

THE RE-FIT OBLIGATION IS DISCHARGED HERE, not deferred: alpha and beta are
FITTED per market (never assumed 1.0 and 0.0), on 2023-2024, minimising MAE --
a proper scoring objective, not ROI, because fitting to ROI on 47k bets would
overfit to price noise. 2025 is a real holdout and is where every reported
number comes from.

Usage:
    py -3 scripts/fit_nfl_props_game_context.py
    py -3 scripts/fit_nfl_props_game_context.py --train 2023,2024 --test 2025
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import game_context as gc
from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props as nfl_props

STAT_KEYS = player_stats.STAT_KEYS


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def collect(seasons: list[int]) -> list[dict[str, Any]]:
    """One row per (season, week, player, stat) carrying the rolling rate AND
    the game context, so the fit and the baseline see identical rows."""
    rows: list[dict[str, Any]] = []
    backtest = _load("_bt", "scripts/backtest_nfl_props.py")
    for season in seasons:
        team_map = player_stats.player_team_by_week(season)
        ctx = gc.game_context(season)
        if not ctx:
            print(f"  season {season}: NO game context on disk -- skipping", flush=True)
            continue
        log_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}
        player_ids = backtest._all_player_ids(season)
        for player_id in player_ids:
            log = backtest._cached_game_log(log_cache, season, player_id)
            weeks = [row["week"] for row in log]
            by_week = team_map.get(player_id) or {}
            for entry in log:
                week = entry["week"]
                prior_weeks = [w for w in weeks if w < week]
                if len(prior_weeks) < 2:
                    continue
                ratio = gc.implied_total_ratio(season, week, by_week, prior_weeks=prior_weeks)
                delta = gc.favoured_by_delta(season, week, by_week, prior_weeks=prior_weeks)
                if ratio is None or delta is None:
                    continue
                for stat in STAT_KEYS:
                    mean, stdev, n = backtest._rate_from_log(log, week, stat)
                    if mean is None or stdev is None:
                        continue
                    rows.append({
                        "season": season, "week": week, "player_id": player_id,
                        "stat": stat, "pred_mean": mean, "pred_stdev": stdev, "n": n,
                        "actual": entry[stat], "ratio": ratio, "delta": delta,
                    })
    return rows


def fit_market(rows: list[dict[str, Any]], *, alphas: np.ndarray, betas: np.ndarray) -> tuple[float, float, float, float]:
    """Grid search (alpha, beta) minimising MAE. Returns (alpha, beta, mae_base, mae_fit)."""
    mean = np.array([r["pred_mean"] for r in rows], dtype=float)
    ratio = np.array([r["ratio"] for r in rows], dtype=float)
    delta = np.array([r["delta"] for r in rows], dtype=float)
    actual = np.array([r["actual"] for r in rows], dtype=float)

    mae_base = float(np.mean(np.abs(mean - actual)))
    log_ratio = np.log(np.clip(ratio, 1e-6, None))

    best = (0.0, 0.0, mae_base)
    for alpha in alphas:
        scaled = mean * np.exp(alpha * log_ratio)
        for beta in betas:
            pred = scaled * np.exp(beta * delta)
            mae = float(np.mean(np.abs(pred - actual)))
            if mae < best[2]:
                best = (float(alpha), float(beta), mae)
    return best[0], best[1], mae_base, best[2]


def adjust(row: dict[str, Any], alpha: float, beta: float) -> float:
    return float(row["pred_mean"]) * (row["ratio"] ** alpha) * math.exp(beta * row["delta"])


def price_and_grade(rows: list[dict[str, Any]], params: dict[str, tuple[float, float]],
                    *, seasons: list[int], roi_mod, use_context: bool) -> list[dict[str, Any]]:
    """Join the (optionally adjusted) projections to real closing quotes."""
    index = {(r["season"], r["week"], r["player_id"], r["stat"]): r for r in rows}
    graded: list[dict[str, Any]] = []
    for season in seasons:
        for week in range(1, 19):
            quotes = roi_mod.load_quotes(season, week)
            if not quotes:
                continue
            grouped: dict[tuple[str, str, Any], dict[str, dict[str, int]]] = defaultdict(
                lambda: defaultdict(dict))
            for q in quotes:
                player = str(q.get("player_name") or "").strip()
                market = str(q.get("market") or "").strip()
                price = q.get("price")
                if not player or not market or price is None:
                    continue
                side = str(q.get("selection") or "").strip().lower()
                side = "over" if side in ("over", "yes") else ("under" if side in ("under", "no") else side)
                grouped[(player, market, q.get("line"))][side][str(q.get("bookmaker") or "")] = int(price)

            for (player, market, line), sides in grouped.items():
                stat = nfl_props._NFL_PROP_MARKET_TO_STAT.get(market)
                if stat is None:
                    continue
                player_id = player_stats.resolve_player_id(season, player)
                if player_id is None:
                    continue
                row = index.get((season, week, player_id, stat))
                if row is None:
                    continue
                alpha, beta = params.get(stat, (0.0, 0.0))
                mean = adjust(row, alpha, beta) if use_context else float(row["pred_mean"])
                actual = row["actual"]
                if stat == "anytime_td":
                    prob = nfl_props._nfl_prop_model_probability(
                        stat=stat, mean=mean, stdev=row["pred_stdev"], n=row["n"], line=None)
                    outcome_over = 1 if actual >= 1 else 0
                else:
                    line_value = nfl_props._safe_float(line)
                    if line_value is None:
                        continue
                    prob = nfl_props._nfl_prop_model_probability(
                        stat=stat, mean=mean, stdev=row["pred_stdev"], n=row["n"], line=line_value)
                    if actual == line_value:
                        continue
                    outcome_over = 1 if actual > line_value else 0
                if prob is None or prob == 0.5:
                    continue
                side = "over" if prob > 0.5 else "under"
                prices = sides.get(side) or {}
                if not prices:
                    continue
                won = (outcome_over == 1) if side == "over" else (outcome_over == 0)
                graded.append({"key": (season, week, player_id, stat, line),
                               "stat": stat, "model_prob": prob if side == "over" else 1 - prob,
                               "won": bool(won), "prices": prices})
    return graded


def roi(graded: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not graded:
        return None
    profit = 0.0
    wins = 0
    for r in graded:
        price = max(r["prices"].values())
        if r["won"]:
            profit += (price / 100.0) if price > 0 else (100.0 / abs(price))
            wins += 1
        else:
            profit -= 1.0
    n = len(graded)
    return {"n": n, "hit_rate": round(wins / n, 4), "roi_pct": round(100.0 * profit / n, 2)}


def brier(graded: list[dict[str, Any]]) -> float | None:
    if not graded:
        return None
    return round(statistics.fmean((r["model_prob"] - (1.0 if r["won"] else 0.0)) ** 2 for r in graded), 5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit and measure NFL prop game-context adjustment")
    parser.add_argument("--train", default="2023,2024")
    parser.add_argument("--test", default="2025")
    parser.add_argument("--out", default="reports/nfl_props_game_context_fit.json")
    args = parser.parse_args()

    train_seasons = [int(s) for s in args.train.split(",") if s.strip()]
    test_seasons = [int(s) for s in args.test.split(",") if s.strip()]
    roi_mod = _load("_roi", "scripts/report_nfl_props_roi.py")

    print("collecting rows with game context ...", flush=True)
    train_rows = collect(train_seasons)
    test_rows = collect(test_seasons)
    print(f"  train rows {len(train_rows):,}   test rows {len(test_rows):,}")
    if not train_rows or not test_rows:
        print("nothing to fit")
        return 1

    # --- REACHABILITY FIRST (standard 4.3): off must differ from on ----------
    # A SYNTHETIC row with an explicitly non-zero mean, not train_rows[0].
    # The first attempt probed a real row and read off == on == 0.000000,
    # concluding the adjustment was inert. It was not: that row's pred_mean
    # was 0.0 (a passer's receiving_yards, say), and 0 * anything is 0 for
    # every alpha and beta. The guard was right to refuse, but the DIAGNOSIS
    # would have been wrong -- a fixture that takes a degenerate path makes a
    # live mechanism look dead. Pin the probe instead of sampling it.
    probe = {"pred_mean": 50.0, "ratio": 1.25, "delta": 3.0}
    off = adjust(probe, 0.0, 0.0)
    on = adjust(probe, 1.0, 0.02)
    print(f"REACHABILITY  off={off:.6f}  on={on:.6f}  differ={off != on}")
    if off == on or abs(off - 50.0) > 1e-9:
        print("  INERT, or the alpha=0/beta=0 identity is wrong -- refusing to fit")
        return 2
    # And the real rows must actually CARRY varying context, or every
    # multiplier is 1.0 in practice however live the function is.
    ratios = [r["ratio"] for r in train_rows[:20000]]
    spread = max(ratios) - min(ratios)
    nontrivial = sum(1 for r in ratios if abs(r - 1.0) > 0.01)
    print(f"  real ratio spread {spread:.4f} over {len(ratios):,} rows; "
          f"{nontrivial:,} ({nontrivial / len(ratios):.1%}) differ from 1.0 by >1%")
    if spread < 1e-6:
        print("  CONTEXT IS CONSTANT -- refusing to fit")
        return 2

    alphas = np.arange(-1.0, 3.01, 0.1)
    betas = np.arange(-0.06, 0.0601, 0.005)

    by_stat_train: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in train_rows:
        by_stat_train[row["stat"]].append(row)
    by_stat_test: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in test_rows:
        by_stat_test[row["stat"]].append(row)

    print("\n" + "=" * 92)
    print(f"FIT on {train_seasons} (MAE), REPORT on {test_seasons}")
    print("=" * 92)
    print(f"  {'market':18s} {'n train':>9s} {'alpha':>7s} {'beta':>7s} "
          f"{'MAE base':>10s} {'MAE fit':>10s} | {'n test':>8s} {'MAE base':>10s} {'MAE ctx':>10s} {'delta':>8s}")

    params: dict[str, tuple[float, float]] = {}
    report: dict[str, Any] = {"train": train_seasons, "test": test_seasons, "markets": {}}
    for stat in sorted(by_stat_train):
        rows = by_stat_train[stat]
        if len(rows) < 500:
            continue
        alpha, beta, mae_base, mae_fit = fit_market(rows, alphas=alphas, betas=betas)
        params[stat] = (alpha, beta)

        test_stat_rows = by_stat_test.get(stat) or []
        if test_stat_rows:
            actual = np.array([r["actual"] for r in test_stat_rows], dtype=float)
            base = np.array([r["pred_mean"] for r in test_stat_rows], dtype=float)
            ctx = np.array([adjust(r, alpha, beta) for r in test_stat_rows], dtype=float)
            t_base = float(np.mean(np.abs(base - actual)))
            t_ctx = float(np.mean(np.abs(ctx - actual)))
        else:
            t_base = t_ctx = float("nan")
        print(f"  {stat:18s} {len(rows):>9,d} {alpha:>7.2f} {beta:>7.3f} "
              f"{mae_base:>10.4f} {mae_fit:>10.4f} | {len(test_stat_rows):>8,d} "
              f"{t_base:>10.4f} {t_ctx:>10.4f} {t_ctx - t_base:>+8.4f}")
        report["markets"][stat] = {
            "alpha": alpha, "beta": beta, "train_n": len(rows),
            "train_mae_base": round(mae_base, 4), "train_mae_fit": round(mae_fit, 4),
            "test_n": len(test_stat_rows), "test_mae_base": round(t_base, 4),
            "test_mae_context": round(t_ctx, 4), "test_mae_delta": round(t_ctx - t_base, 4),
        }

    print("\n" + "=" * 92)
    print(f"PRICED on the {test_seasons} holdout, best price across books")
    print("=" * 92)
    base_graded = price_and_grade(test_rows, params, seasons=test_seasons, roi_mod=roi_mod, use_context=False)
    ctx_graded = price_and_grade(test_rows, params, seasons=test_seasons, roi_mod=roi_mod, use_context=True)
    base_roi = roi(base_graded)
    ctx_roi = roi(ctx_graded)
    print(f"  {'variant':14s} {'n':>8s} {'hit rate':>9s} {'brier':>8s} {'ROI %':>9s}")
    for label, graded, result in (("baseline", base_graded, base_roi), ("game context", ctx_graded, ctx_roi)):
        if result is None:
            print(f"  {label:14s} (no graded bets)")
            continue
        print(f"  {label:14s} {result['n']:>8,d} {result['hit_rate']:>9.4f} "
              f"{brier(graded):>8.5f} {result['roi_pct']:>+9.2f}")
    # PAIRED: identical bets only. The two variants above grade slightly
    # different populations, because adjusting the mean changes which rows land
    # exactly on prob == 0.5 and get dropped. An uncontrolled n is how a
    # difference in POPULATION gets reported as a difference in SKILL -- the
    # same trap the best-price vs single-book headline fell into earlier.
    base_by_key = {r["key"]: r for r in base_graded}
    ctx_by_key = {r["key"]: r for r in ctx_graded}
    shared = sorted(set(base_by_key) & set(ctx_by_key))
    paired_base = [base_by_key[k] for k in shared]
    paired_ctx = [ctx_by_key[k] for k in shared]
    pb, pc = roi(paired_base), roi(paired_ctx)
    print("")
    print(f"  PAIRED on the {len(shared):,} bets BOTH variants graded "
          f"(dropped {len(base_graded) - len(shared):,} base-only, "
          f"{len(ctx_graded) - len(shared):,} context-only):")
    print(f"  {'variant':14s} {'n':>8s} {'hit rate':>9s} {'brier':>8s} {'ROI %':>9s}")
    for label, g, r in (("baseline", paired_base, pb), ("game context", paired_ctx, pc)):
        if r:
            print(f"  {label:14s} {r['n']:>8,d} {r['hit_rate']:>9.4f} "
                  f"{brier(g):>8.5f} {r['roi_pct']:>+9.2f}")
    if pb and pc:
        print("")
        print(f"  PAIRED ROI change: {pc['roi_pct'] - pb['roi_pct']:+.2f} points")
        report["paired"] = {"n": len(shared),
                            "baseline": pb | {"brier": brier(paired_base)},
                            "game_context": pc | {"brier": brier(paired_ctx)},
                            "roi_delta_pts": round(pc["roi_pct"] - pb["roi_pct"], 2)}

    if base_roi and ctx_roi:
        print(f"\n  ROI change: {ctx_roi['roi_pct'] - base_roi['roi_pct']:+.2f} points")
        report["priced"] = {"baseline": base_roi | {"brier": brier(base_graded)},
                            "game_context": ctx_roi | {"brier": brier(ctx_graded)},
                            "roi_delta_pts": round(ctx_roi["roi_pct"] - base_roi["roi_pct"], 2)}

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
