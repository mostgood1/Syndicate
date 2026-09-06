#!/usr/bin/env python3
"""Price the NFL player-prop model: hit rate is not ROI.

WHY THIS IS SEPARATE FROM `backtest_nfl_props.py`. That script's Section 3
reports hit rate and Brier wherever a real quoted line exists. Neither is a
return. A 55% hit rate at -130 LOSES money; a 48% hit rate at +120 makes it.
Nothing in this repo has ever turned an NFL prop prediction into a P&L, because
until 2026-08-20 no real NFL prop line had ever been captured at all (wrong
endpoint + two invalid market keys -- see fetch_nfl_oddsapi_props_local.py).

WHAT IT MEASURES. For every (player, market, week) where a backfilled closing
quote joins a no-lookahead model rate:

    model probability -> pick a side -> take that side's real quoted price
    -> settle against the real box score -> profit in units

ROI = net profit / units staked. Reported per market, per book, and across a
sweep of minimum-edge thresholds, because "bet everything the model likes" and
"bet only where the model beats the vig by X" are different strategies with
different answers.

TWO PRICE BASES, BOTH REPORTED, because they bound the truth from either side:

  best_price  the best number available across all books at the snapshot. What
              a bettor with every account and no limits would have got. This is
              the OPTIMISTIC bound -- treat a positive ROI here as necessary,
              not sufficient.
  <book>      one book, held all season. The realistic bound, and the one to
              believe if the two disagree.

HONEST DENOMINATORS. Every table carries its own n. A market with 40 graded
bets is labelled as such and not averaged into a headline, per this repo's
standing rule against pooled denominators.

NO CLV HERE. One closing snapshot per game cannot measure line movement; that
needs the opening snapshot too and is a separate (and dearer) capture.

Usage:
    py -3 scripts/report_nfl_props_roi.py --seasons 2023,2024,2025
    py -3 scripts/report_nfl_props_roi.py --seasons 2025 --book draftkings
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props as nfl_props
from syndicate.features.nfl.sources import default_nfl_source_root


def american_to_profit(price: int) -> float:
    """Profit on a 1-unit win. -110 -> 0.909, +150 -> 1.5."""
    price = int(price)
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def american_to_implied(price: Any) -> float | None:
    """Implied probability INCLUDING vig -- the number the model must beat.

    SCORED 1 OF 5 in `scripts/probability_differential.py` when the registry
    first covered it `[2026-09-05]`, the weakest of the family, and every
    failure was a missing guard rather than wrong arithmetic:

      price=0   -> 0.0        a certainty, returned as a probability
      price=None-> TypeError  int(None)
      price=''  -> ValueError int('')
      -110.5    -> -110       int() truncated a half-point price

    `0` is the one worth naming: `abs(0)/(0+100)` is 0.0, so a missing price
    read as a 0% market rather than as no market -- and 0.0 is a number the
    caller will happily divide an edge by.
    """
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0.0:
        return None
    return 100.0 / (value + 100.0) if value > 0 else abs(value) / (abs(value) + 100.0)


def quote_path(season: int, week: int) -> Path:
    return default_nfl_source_root() / "tracking" / "book_quotes" / f"{season}_wk{week}.jsonl"


def load_quotes(season: int, week: int) -> list[dict[str, Any]]:
    path = quote_path(season, week)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if str(row.get("kind") or "") == "prop":
                rows.append(row)
    return rows


def build_rate_index(seasons: list[int]) -> dict[tuple[int, int, str, str], dict[str, Any]]:
    """Reuse the backtest's own substrate so the model numbers here are the
    SAME numbers `#471` reported -- not a re-implementation that could drift."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_backtest_nfl_props", REPO_ROOT / "scripts" / "backtest_nfl_props.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    raw_rows, _counts = module.collect_raw(seasons)
    return {
        (row["season"], row["week"], row["player_id"], row["stat"]): row
        for row in raw_rows
    }


def grade(seasons: list[int]) -> list[dict[str, Any]]:
    """One record per (season, week, player, market, line) the model has an
    opinion on AND a real book quoted."""
    rate_index = build_rate_index(seasons)
    graded: list[dict[str, Any]] = []
    unresolved_player = unresolved_rate = pushes = no_price = 0

    for season in seasons:
        for week in range(1, 19):
            quotes = load_quotes(season, week)
            if not quotes:
                continue
            # (player, market, line) -> {selection -> {book: price}}
            grouped: dict[tuple[str, str, Any], dict[str, dict[str, int]]] = defaultdict(
                lambda: defaultdict(dict)
            )
            for row in quotes:
                player = str(row.get("player_name") or "").strip()
                market = str(row.get("market") or "").strip()
                price = row.get("price")
                if not player or not market or price is None:
                    continue
                side = str(row.get("selection") or "").strip().lower()
                side = "over" if side in ("over", "yes") else ("under" if side in ("under", "no") else side)
                grouped[(player, market, row.get("line"))][side][
                    str(row.get("bookmaker") or "")
                ] = int(price)

            for (player, market, line), sides in grouped.items():
                stat = nfl_props._NFL_PROP_MARKET_TO_STAT.get(market)
                if stat is None:
                    continue
                player_id = player_stats.resolve_player_id(season, player)
                if player_id is None:
                    unresolved_player += 1
                    continue
                rate = rate_index.get((season, week, player_id, stat))
                if rate is None:
                    unresolved_rate += 1
                    continue

                actual = rate["actual"]
                if stat == "anytime_td":
                    prob = nfl_props._nfl_prop_model_probability(
                        stat=stat, mean=rate["pred_mean"], stdev=rate["pred_stdev"],
                        n=rate["n"], line=None,
                    )
                    outcome_over = 1 if actual >= 1 else 0
                    line_value = None
                else:
                    line_value = nfl_props._safe_float(line)
                    if line_value is None:
                        continue
                    prob = nfl_props._nfl_prop_model_probability(
                        stat=stat, mean=rate["pred_mean"], stdev=rate["pred_stdev"],
                        n=rate["n"], line=line_value,
                    )
                    if actual == line_value:
                        pushes += 1
                        continue
                    outcome_over = 1 if actual > line_value else 0
                if prob is None or prob == 0.5:
                    continue

                side = "over" if prob > 0.5 else "under"
                side_prob = prob if side == "over" else 1.0 - prob
                prices = sides.get(side) or {}
                if not prices:
                    # Anytime TD has no "under" at most books; a model that
                    # wants the under simply has no bet available.
                    no_price += 1
                    continue
                won = (outcome_over == 1) if side == "over" else (outcome_over == 0)
                graded.append({
                    "season": season, "week": week, "player": player, "market": market,
                    "stat": stat, "line": line_value, "side": side,
                    "model_prob": side_prob, "won": bool(won), "prices": prices,
                })

    print(f"  quotes with no resolvable player id : {unresolved_player:,}")
    print(f"  quotes with no resolvable model rate: {unresolved_rate:,}")
    print(f"  pushes excluded (actual == line)    : {pushes:,}")
    print(f"  model side had no quoted price      : {no_price:,}")
    return graded


def roi_for(records: list[dict[str, Any]], *, price_of, min_edge: float) -> dict[str, Any] | None:
    """Flat 1 unit per qualifying bet."""
    staked = 0.0
    profit = 0.0
    wins = 0
    for record in records:
        price = price_of(record)
        if price is None:
            continue
        implied = american_to_implied(price)
        if record["model_prob"] - implied < min_edge:
            continue
        staked += 1.0
        if record["won"]:
            profit += american_to_profit(price)
            wins += 1
        else:
            profit -= 1.0
    if staked == 0:
        return None
    return {
        "n": int(staked),
        "hit_rate": round(wins / staked, 4),
        "profit_units": round(profit, 2),
        "roi_pct": round(100.0 * profit / staked, 2),
    }


def best_price(record: dict[str, Any]) -> int | None:
    prices = record["prices"]
    return max(prices.values()) if prices else None


def book_price(book: str):
    def _inner(record: dict[str, Any]) -> int | None:
        return record["prices"].get(book)
    return _inner


def main() -> int:
    parser = argparse.ArgumentParser(description="ROI of the NFL player-prop model vs real closing prices")
    parser.add_argument("--seasons", default="2023,2024,2025")
    parser.add_argument("--book", default="draftkings", help="single-book realistic bound")
    parser.add_argument("--edges", default="0,0.02,0.05,0.10")
    parser.add_argument("--out", default="reports/nfl_props_roi.json")
    args = parser.parse_args()

    seasons = [int(s) for s in str(args.seasons).split(",") if s.strip()]
    edges = [float(e) for e in str(args.edges).split(",") if e.strip()]

    print("=" * 78)
    print(f"NFL PLAYER-PROP ROI -- seasons {seasons}")
    print("=" * 78)
    graded = grade(seasons)
    print(f"\n  GRADED BETS AVAILABLE: {len(graded):,}")
    if not graded:
        print("  nothing to price -- no quote joined a model rate.")
        return 1

    report: dict[str, Any] = {"seasons": seasons, "graded": len(graded), "bases": {}}

    for label, price_of in (("best_price", best_price), (args.book, book_price(args.book))):
        print("\n" + "-" * 78)
        print(f"PRICE BASIS: {label}")
        print("-" * 78)
        basis: dict[str, Any] = {"by_edge": {}, "by_market": {}}

        print(f"  {'min edge':>9s} {'n':>7s} {'hit rate':>9s} {'units':>9s} {'ROI %':>8s}")
        for edge in edges:
            result = roi_for(graded, price_of=price_of, min_edge=edge)
            if result is None:
                print(f"  {edge:>9.0%} {'0':>7s}  (no qualifying bets)")
                continue
            print(f"  {edge:>9.0%} {result['n']:>7,d} {result['hit_rate']:>9.4f} "
                  f"{result['profit_units']:>9.1f} {result['roi_pct']:>+8.2f}")
            basis["by_edge"][str(edge)] = result

        print(f"\n  per market at min edge 0 (every side the model favours):")
        print(f"  {'market':18s} {'n':>7s} {'hit rate':>9s} {'units':>9s} {'ROI %':>8s}")
        by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in graded:
            by_market[record["stat"]].append(record)
        for stat in sorted(by_market):
            result = roi_for(by_market[stat], price_of=price_of, min_edge=0.0)
            if result is None:
                continue
            flag = "" if result["n"] >= 100 else "   (thin)"
            print(f"  {stat:18s} {result['n']:>7,d} {result['hit_rate']:>9.4f} "
                  f"{result['profit_units']:>9.1f} {result['roi_pct']:>+8.2f}{flag}")
            basis["by_market"][stat] = result
        report["bases"][label] = basis

    # Which books were actually present -- a per-book ROI that silently rests
    # on 2 books is not the same claim as one resting on 8.
    books: dict[str, int] = defaultdict(int)
    for record in graded:
        for book in record["prices"]:
            books[book] += 1
    print("\n  books present across graded bets:")
    for book, count in sorted(books.items(), key=lambda kv: -kv[1]):
        print(f"    {book:20s} {count:>7,d}")
    report["book_coverage"] = dict(books)

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
