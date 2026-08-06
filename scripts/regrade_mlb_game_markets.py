"""Re-grade MLB game markets against BEST price across books (#211).

THE QUESTION
------------
#205 claimed that grading every bet against one arbitrarily-chosen bookmaker
inflated apparent edge, drove worse selection, and settled at worse prices --
"three errors compounding the same direction". #206 scoped a best-price re-grade
as the one retroactive win available. Neither was ever measured, because the
books were never captured (#208). The #210 backfill bought them back, so this
measures it.

WHAT MAKES THIS APPLES-TO-APPLES
--------------------------------
The MODEL IS HELD FIXED. `daily_summary_*.json` stores the simulation's own
`home_win_prob` / `total_runs_dist` / `run_margin_dist` per game -- the actual
output of the actual sim on the day, not a re-run. The only thing that varies
between the two arms is which book's price the same model is priced against:

  arm SINGLE  -- one book per game, chosen the way capture chose (preferred-book
                 order, else whatever came first). This reproduces what
                 #186-#204 actually graded.
  arm BEST    -- best available price across every book quoted at that instant.

Same games, same probabilities, same threshold, same stake. Any difference is
attributable to price alone. That is the whole design; if you change the
selection rule between arms, the comparison stops meaning anything.

OUTCOMES come from MLB StatsAPI (free, no OddsAPI credits) rather than from our
own graded artifacts, because our graded rows carry the same single-book price
contamination this script exists to measure.

WHAT IT DOES NOT SHOW
---------------------
Nothing here rehabilitates the prop verdicts. Props are excluded entirely: their
book dimension was never captured live, and while #210 backfilled prop quotes,
the BETS were selected on a single arbitrary book, so a prop re-grade would
measure a counterfactual selection rather than a re-pricing. Game markets are
the honest scope, exactly as #206 said.

Report `n` and the date count with every number -- per this repo's standing rule
and the #208 epistemic warning, a ratio without a denominator is not a result.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.mlb.cards import _MLB_TEAM_META_BY_ABBR  # noqa: E402
from syndicate.features.shared.odds_book_quotes import read_book_quotes  # noqa: E402

NAME_BY_ABBR = {abbr: str(meta.get("name") or "") for abbr, meta in _MLB_TEAM_META_BY_ABBR.items()}

# The order capture used when it kept exactly one book, so arm SINGLE
# reproduces the real historical choice rather than a strawman.
PREFERRED_BOOKS = ["fanduel", "draftkings", "betmgm", "williamhill_us", "fanatics", "betrivers"]

STATSAPI = "https://statsapi.mlb.com/api/v1/schedule"


def _american_to_decimal(price: int) -> float:
    price = int(price)
    return 1.0 + (price / 100.0 if price > 0 else 100.0 / abs(price))


def _american_to_implied(price: int) -> float:
    price = int(price)
    return (100.0 / (price + 100.0)) if price > 0 else (abs(price) / (abs(price) + 100.0))


def _http_json(url: str, timeout: int = 120) -> Any:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as response:
            return json.loads(response.read())
    except Exception:
        return None


def _final_scores_for_date(date_str: str) -> dict[tuple[str, str], tuple[int, int]]:
    """(away_name, home_name) -> (away_runs, home_runs) for finals only.

    Free StatsAPI, deliberately not our own graded artifacts: those carry the
    same single-book price this script is measuring against.
    """
    url = f"{STATSAPI}?sportId=1&date={date_str}&hydrate=linescore"
    payload = _http_json(url)
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for day in ((payload or {}).get("dates") or []):
        for game in (day.get("games") or []):
            status = str(((game.get("status") or {}).get("abstractGameState")) or "")
            if status != "Final":
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_name = str(((away.get("team") or {}).get("name")) or "").strip()
            home_name = str(((home.get("team") or {}).get("name")) or "").strip()
            away_runs, home_runs = away.get("score"), home.get("score")
            if not away_name or not home_name or away_runs is None or home_runs is None:
                continue
            out[(away_name, home_name)] = (int(away_runs), int(home_runs))
    return out


def _load_summary(date_str: str, *, admin_token: str | None) -> dict[str, Any] | None:
    token = date_str.replace("-", "_")
    local = Path("data/mlb_source/source_artifacts/data/daily") / f"daily_summary_{token}.json"
    if local.is_file():
        try:
            return json.loads(local.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not admin_token:
        return None
    path = f"mlb_source/source_artifacts/data/daily/daily_summary_{token}.json"
    url = "https://syndicate-an21.onrender.com/api/ops/artifacts/stream?path=" + urllib.parse.quote(path)
    request = urllib.request.Request(url, headers={"X-Admin-Token": admin_token})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except Exception:
        return None


def _model_probabilities(output: dict[str, Any]) -> dict[str, Any] | None:
    """Moneyline and total probabilities straight from the stored sim, with the
    tie mass renormalised out of the h2h price (MLB h2h has no draw)."""
    full = output.get("full")
    if not isinstance(full, dict):
        return None
    home_prob = full.get("home_win_prob")
    away_prob = full.get("away_win_prob")
    if home_prob is None or away_prob is None:
        return None
    total = float(home_prob) + float(away_prob)
    if total <= 0:
        return None
    dist = full.get("total_runs_dist")
    return {
        "home_win": float(home_prob) / total,
        "away_win": float(away_prob) / total,
        "total_runs_dist": dist if isinstance(dist, dict) else None,
    }


def _total_over_probability(dist: dict[str, Any], line: float) -> float | None:
    """P(total runs > line) from the sim's own histogram. A whole-number line
    can push; that mass is excluded from both numerator and denominator, which
    is how a push actually settles."""
    try:
        counts = {float(key): float(value) for key, value in dist.items()}
    except Exception:
        return None
    total = sum(counts.values())
    if total <= 0:
        return None
    over = sum(value for key, value in counts.items() if key > line)
    push = sum(value for key, value in counts.items() if abs(key - line) < 1e-9)
    live = total - push
    if live <= 0:
        return None
    return over / live


def _quotes_at_close(rows: list[dict[str, Any]]) -> dict[tuple, dict[str, dict[str, Any]]]:
    """Last pre-commence quote per (event, market, selection, line) per book."""
    best: dict[tuple, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row.get("kind") != "game" or row.get("segment") != "full":
            continue
        market = row.get("market")
        if market not in {"h2h", "totals"}:
            continue
        price = row.get("price")
        commence = str(row.get("commence_time") or "")
        observed = str(row.get("snapshot_ts") or row.get("captured_at") or "")
        if price is None or not commence or not observed or observed >= commence:
            continue
        key = (row.get("home_team"), row.get("away_team"), market, row.get("selection"), row.get("line"))
        book = str(row.get("bookmaker") or "")
        bucket = best.setdefault(key, {})
        previous = bucket.get(book)
        if previous is None or observed > str(previous.get("snapshot_ts") or ""):
            bucket[book] = row
    return best


def _pick_single_book(quotes_by_book: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for preferred in PREFERRED_BOOKS:
        if preferred in quotes_by_book:
            return quotes_by_book[preferred]
    return next(iter(quotes_by_book.values()), None)


def _pick_best_price(quotes_by_book: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not quotes_by_book:
        return None
    return max(quotes_by_book.values(), key=lambda row: int(row.get("price") or -10**9))


def _bootstrap_ci(values: list[float], iterations: int = 4000, seed: int = 20260806) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iterations):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * iterations)], means[int(0.975 * iterations)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-grade MLB game markets against best price across books")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--edge", type=float, default=0.03, help="minimum model-minus-implied edge to bet")
    parser.add_argument("--out", default="reports/mlb_regrade/best_price_regrade.json")
    args = parser.parse_args(argv)

    admin_token = os.environ.get("ADMIN_TOKEN")

    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()
    dates: list[str] = []
    cursor = start
    while cursor <= end:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)

    arms: dict[str, list[float]] = {"single": [], "best": []}
    arm_prices: dict[str, list[int]] = {"single": [], "best": []}
    # The headline single-vs-best delta conflates TWO mechanisms: the same bet
    # settled at a better price (re-pricing) and extra bets clearing the edge
    # threshold because a better price raises the measured edge (selection).
    # Reporting only the combined number would repeat exactly the kind of
    # compounded-claim error #208's epistemic warning is about, so these keep
    # the per-bet profit under both arms for the bets BOTH arms took.
    paired: dict[tuple, dict[str, float]] = {}
    book_choice = collections.Counter()
    per_market = collections.defaultdict(lambda: {"single": [], "best": []})
    dates_used: set[str] = set()
    games_considered = 0
    games_joined = 0
    skipped_no_quotes = skipped_no_outcome = skipped_no_model = 0

    for date_str in dates:
        summary = _load_summary(date_str, admin_token=admin_token)
        if not isinstance(summary, dict):
            continue
        # Quote shards are keyed by UTC date; StatsAPI and daily_summary use the
        # US game date. A 7:40pm Central first pitch is 00:40 UTC the NEXT day,
        # so a night game's quotes routinely sit in the neighbouring shard --
        # the same timezone trap _parse_game_date_token documents for the
        # tracking snapshots. Merge the neighbours rather than silently losing
        # every late game to a non-join.
        previous_day = (datetime.fromisoformat(date_str) - timedelta(days=1)).date().isoformat()
        next_day = (datetime.fromisoformat(date_str) + timedelta(days=1)).date().isoformat()
        rows = read_book_quotes("mlb", date_str) + read_book_quotes("mlb", next_day) + read_book_quotes("mlb", previous_day)
        if not rows:
            continue
        closes = _quotes_at_close(rows)
        finals = _final_scores_for_date(date_str)
        if not finals:
            continue

        for output in (summary.get("outputs") or []):
            if not isinstance(output, dict):
                continue
            games_considered += 1
            home_name = NAME_BY_ABBR.get(str(output.get("home") or "").strip())
            away_name = NAME_BY_ABBR.get(str(output.get("away") or "").strip())
            if not home_name or not away_name:
                continue
            score = finals.get((away_name, home_name))
            if score is None:
                skipped_no_outcome += 1
                continue
            model = _model_probabilities(output)
            if model is None:
                skipped_no_model += 1
                continue
            away_runs, home_runs = score
            joined_any = False

            # --- moneyline ---
            for selection, probability in (("home", model["home_win"]), ("away", model["away_win"])):
                quotes = closes.get((home_name, away_name, "h2h", selection, None))
                if not quotes:
                    continue
                joined_any = True
                won = (home_runs > away_runs) if selection == "home" else (away_runs > home_runs)
                for arm, picker in (("single", _pick_single_book), ("best", _pick_best_price)):
                    quote = picker(quotes)
                    if quote is None:
                        continue
                    price = int(quote["price"])
                    if probability - _american_to_implied(price) < args.edge:
                        continue
                    profit = (_american_to_decimal(price) - 1.0) if won else -1.0
                    arms[arm].append(profit)
                    arm_prices[arm].append(price)
                    per_market["h2h"][arm].append(profit)
                    paired.setdefault((date_str, home_name, away_name, "h2h", selection, None), {})[arm] = profit
                    if arm == "single":
                        book_choice[str(quote.get("bookmaker"))] += 1

            # --- totals ---
            dist = model.get("total_runs_dist")
            if dist:
                total_keys = [key for key in closes if key[0] == home_name and key[1] == away_name and key[2] == "totals"]
                for key in total_keys:
                    line = key[4]
                    selection = key[3]
                    if line is None or selection not in {"over", "under"}:
                        continue
                    over_probability = _total_over_probability(dist, float(line))
                    if over_probability is None:
                        continue
                    probability = over_probability if selection == "over" else 1.0 - over_probability
                    quotes = closes.get(key)
                    if not quotes:
                        continue
                    joined_any = True
                    actual = away_runs + home_runs
                    if abs(actual - float(line)) < 1e-9:
                        continue  # push
                    won = (actual > float(line)) if selection == "over" else (actual < float(line))
                    for arm, picker in (("single", _pick_single_book), ("best", _pick_best_price)):
                        quote = picker(quotes)
                        if quote is None:
                            continue
                        price = int(quote["price"])
                        if probability - _american_to_implied(price) < args.edge:
                            continue
                        profit = (_american_to_decimal(price) - 1.0) if won else -1.0
                        arms[arm].append(profit)
                        arm_prices[arm].append(price)
                        per_market["totals"][arm].append(profit)
                        paired.setdefault((date_str, home_name, away_name, "totals", selection, line), {})[arm] = profit
                        if arm == "single":
                            book_choice[str(quote.get("bookmaker"))] += 1

            if joined_any:
                games_joined += 1
                dates_used.add(date_str)
            else:
                skipped_no_quotes += 1

    def summarize(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0}
        roi = sum(values) / len(values)
        low, high = _bootstrap_ci(values)
        return {
            "n": len(values),
            "roi_pct": round(roi * 100, 2),
            "ci95_pct": [round(low * 100, 2), round(high * 100, 2)],
            "units": round(sum(values), 2),
        }

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": args.start, "end": args.end, "dates_requested": len(dates)},
        "coverage": {
            "dates_with_bets": len(dates_used),
            "games_considered": games_considered,
            "games_joined": games_joined,
            "skipped_no_quotes": skipped_no_quotes,
            "skipped_no_outcome": skipped_no_outcome,
            "skipped_no_model": skipped_no_model,
        },
        "edge_threshold": args.edge,
        "arms": {arm: summarize(values) for arm, values in arms.items()},
        "per_market": {market: {arm: summarize(values) for arm, values in by_arm.items()} for market, by_arm in per_market.items()},
        "single_arm_book_mix": dict(book_choice.most_common()),
        "mean_price": {arm: (round(statistics.mean(prices), 1) if prices else None) for arm, prices in arm_prices.items()},
    }
    single, best = report["arms"]["single"], report["arms"]["best"]
    if single.get("n") and best.get("n"):
        report["delta_roi_pct_combined"] = round(best["roi_pct"] - single["roi_pct"], 2)

    # Re-pricing effect, isolated: only bets BOTH arms placed, so the game set,
    # the selection and the stake are identical and the only difference is the
    # price. This is the number that is genuinely attributable to price alone.
    both = [value for value in paired.values() if "single" in value and "best" in value]
    deltas = [value["best"] - value["single"] for value in both]
    report["repricing_only"] = {
        "n": len(both),
        "single_roi_pct": round(sum(v["single"] for v in both) / len(both) * 100, 2) if both else None,
        "best_roi_pct": round(sum(v["best"] for v in both) / len(both) * 100, 2) if both else None,
        "delta_roi_pct": round(sum(deltas) / len(deltas) * 100, 2) if deltas else None,
        "delta_ci95_pct": [round(x * 100, 2) for x in _bootstrap_ci(deltas)] if deltas else None,
        "bets_only_best_took": sum(1 for value in paired.values() if "best" in value and "single" not in value),
        "bets_only_single_took": sum(1 for value in paired.values() if "single" in value and "best" not in value),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=1, sort_keys=True))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
