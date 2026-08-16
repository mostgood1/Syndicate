"""Leak-free calibration of SoccerSim's three-way match probabilities.

WHY THIS EXISTS. `soccer-backtest-leakage` retired every
`data/soccer_source/*/validation/*_backtest_*.csv` as uncitable and left an
explicit debt: **there is no leak-free soccer backtest number for any league.**
`SoccerSimulationOutput.evaluation` has carried
`{"calibration": {"win_probability": {"brier": None}}}` since it was written --
the slot exists and has never been filled. This fills it.

WHAT MAKES IT LEAK-FREE, and why that took a code fix first. Ratings are
recomputed for **each match day** with `as_of` set to that day, and
`compute_team_ratings` excludes rows dated on or after the cutoff. That was
already true in the source and was **inert for every league this script can
run on**: the `history/*.csv` files are `DD/MM/YYYY` and the filter compared
raw text, so a rating "as of September 2023" was built from May 2026 results.
Fixed in `loaders._as_iso_day`; running this script against the unfixed
function reproduces the leak.

THE MARKET IS THE BENCHMARK, NOT THE TARGET. Each match's closing odds ship in
the same file (`odds_home`/`odds_draw`/`odds_away`), so every model number is
reported beside a proportionally de-vigged market number over the identical
match set. A model's Brier score alone is close to meaningless in a sport whose
base rates are ~45/27/28 -- the only question that matters is whether it beats
the price, and a model that loses to the closing line has no business putting
an edge on a board.

SCOPE, stated rather than discovered later:

- Runs on the four goals-based leagues (eredivisie, primeira_liga,
  championship, belgian_pro_league) plus the five Understat leagues, from
  committed `history/` files. Goals stand in for xG there --
  `team_rows_from_match_history`'s documented fallback.
- **MLS is excluded and cannot be included.** `fetch_asa_mls_team_history`
  returns undated season aggregates; a season average already contains the
  season, so no as-of filter can repair it.
- Reports per-family date coverage and the intersection, and states the number
  of matches every figure actually rests on.

Usage:
    python scripts/backtest_soccer_h2h_calibration.py --league eredivisie
    python scripts/backtest_soccer_h2h_calibration.py --all --min-prior-matches 40
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from syndicate.features.soccer.adapters import build_soccer_simulation_adapter  # noqa: E402
from syndicate.features.soccer.features.loaders import (  # noqa: E402
    _as_iso_day,
    build_soccer_simulation_input,
    compute_team_ratings,
    team_rows_from_match_history,
)

OUTCOMES = ("home", "draw", "away")

# Leagues rated from football-data match results. MLS is deliberately absent:
# see the module docstring.
BACKTESTABLE_LEAGUES = (
    "eredivisie",
    "primeira_liga",
    "championship",
    "belgian_pro_league",
    "epl",
    "la_liga",
    "bundesliga",
    "serie_a",
    "ligue_1",
)


def _load_history(league: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(REPO_ROOT / "data" / "soccer_source" / league / "history" / "*.csv"))):
        rows.extend(pd.read_csv(path).to_dict("records"))
    return rows


def _outcome(row: dict[str, Any]) -> str | None:
    try:
        home, away = float(row["home_goals"]), float(row["away_goals"])
    except (KeyError, TypeError, ValueError):
        return None
    if math.isnan(home) or math.isnan(away):
        return None
    return "home" if home > away else ("away" if away > home else "draw")


def _market_probabilities(row: dict[str, Any]) -> dict[str, float] | None:
    """Proportionally de-vigged closing odds, or None if the set is incomplete.

    Proportional rather than Shin: it is the same method the board's own
    `_no_vig_over_probability` uses, so the benchmark is the one the product
    would actually compare against.
    """
    implied: dict[str, float] = {}
    for outcome, column in zip(OUTCOMES, ("odds_home", "odds_draw", "odds_away")):
        try:
            price = float(row[column])
        except (KeyError, TypeError, ValueError):
            return None
        if not price or price <= 1.0 or math.isnan(price):
            return None
        implied[outcome] = 1.0 / price
    total = sum(implied.values())
    if total <= 0:
        return None
    return {outcome: value / total for outcome, value in implied.items()}


def _brier(probabilities: dict[str, float], actual: str) -> float:
    """Multiclass (Brier) score: sum of squared error over the three outcomes."""
    return sum((probabilities[outcome] - (1.0 if outcome == actual else 0.0)) ** 2 for outcome in OUTCOMES)


def _log_loss(probabilities: dict[str, float], actual: str) -> float:
    return -math.log(max(probabilities[actual], 1e-12))


def _reliability(pairs: list[tuple[float, bool]], bins: int = 5) -> list[dict[str, Any]]:
    """Predicted vs realised frequency, bucketed. Where under-dispersion shows."""
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for probability, hit in pairs:
        buckets[min(bins - 1, int(probability * bins))].append((probability, hit))
    out = []
    for index in sorted(buckets):
        values = buckets[index]
        out.append(
            {
                "bucket": f"{index / bins:.1f}-{(index + 1) / bins:.1f}",
                "n": len(values),
                "mean_predicted": round(sum(p for p, _ in values) / len(values), 4),
                "actual_rate": round(sum(1 for _, hit in values if hit) / len(values), 4),
            }
        )
    return out


def backtest_league(league: str, *, simulations: int, min_prior_matches: int, limit: int | None) -> dict[str, Any]:
    history = _load_history(league)
    if not history:
        return {"league": league, "error": "no committed history"}

    team_rows = team_rows_from_match_history(history)

    # Coverage, printed rather than assumed -- the repo rule for anything built
    # on `data/**`.
    dated = [d for d in (_as_iso_day(row.get("date")) for row in history) if d]
    with_result = [row for row in history if _outcome(row)]
    with_odds = [row for row in history if _market_probabilities(row)]
    usable = [row for row in history if _outcome(row) and _market_probabilities(row) and _as_iso_day(row.get("date"))]
    coverage = {
        "history_rows": len(history),
        "dated": len(dated),
        "date_min": min(dated) if dated else None,
        "date_max": max(dated) if dated else None,
        "with_result": len(with_result),
        "with_complete_closing_odds": len(with_odds),
        "intersection_usable": len(usable),
    }

    # Group by match day: every fixture on a day shares one as-of ratings set,
    # which is both correct and what makes this affordable.
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        by_day[_as_iso_day(row.get("date"))].append(row)

    adapter = build_soccer_simulation_adapter(league)
    model_brier: list[float] = []
    market_brier: list[float] = []
    model_ll: list[float] = []
    market_ll: list[float] = []
    model_reliability: list[tuple[float, bool]] = []
    market_reliability: list[tuple[float, bool]] = []
    model_probs: list[float] = []
    # Per-match rows exist so a CALIBRATION can be fitted without paying for the
    # simulation again. The sim is the whole cost of this harness (~40 min for
    # nine leagues); a post-hoc transform on stored probabilities is instant,
    # which is what makes an honest train/test split affordable at all.
    per_match: list[dict[str, Any]] = []
    scored = 0
    skipped_thin_ratings = 0

    for day in sorted(by_day):
        if limit is not None and scored >= limit:
            break
        ratings = compute_team_ratings(team_rows, as_of=day, window=45)
        fixtures = by_day[day]
        # A team the as-of ratings have never seen gets a 0.0/0.0 default from
        # `_rating_for`, which is a prior, not a projection. Requiring prior
        # matches for BOTH sides is what keeps early-season rows from being
        # scored as if the model had an opinion.
        eligible = []
        for row in fixtures:
            home_rating = ratings.get(str(row.get("home_team")), {})
            away_rating = ratings.get(str(row.get("away_team")), {})
            if min(home_rating.get("matches", 0.0), away_rating.get("matches", 0.0)) < min_prior_matches:
                skipped_thin_ratings += 1
                continue
            eligible.append(row)
        if not eligible:
            continue

        simulation_input = build_soccer_simulation_input(
            league=league,
            date=day,
            fixtures=[
                {"home_team": row["home_team"], "away_team": row["away_team"], "match_id": str(row.get("match_id") or "")}
                for row in eligible
            ],
            ratings=ratings,
            simulations=simulations,
        )
        outputs = list(adapter.simulate_games(simulation_input).match_outputs)
        for row, output in zip(eligible, outputs):
            win = output.get("win_probability") or {}
            try:
                model = {outcome: float(win[outcome]) for outcome in OUTCOMES}
            except (KeyError, TypeError, ValueError):
                continue
            total = sum(model.values())
            if total <= 0:
                continue
            model = {outcome: value / total for outcome, value in model.items()}
            market = _market_probabilities(row)
            actual = _outcome(row)
            if market is None or actual is None:
                continue

            model_brier.append(_brier(model, actual))
            market_brier.append(_brier(market, actual))
            model_ll.append(_log_loss(model, actual))
            market_ll.append(_log_loss(market, actual))
            model_reliability.append((model["home"], actual == "home"))
            market_reliability.append((market["home"], actual == "home"))
            model_probs.append(model["home"])
            per_match.append(
                {
                    "league": league,
                    "date": day,
                    "home_team": row.get("home_team"),
                    "away_team": row.get("away_team"),
                    "model_home": round(model["home"], 6),
                    "model_draw": round(model["draw"], 6),
                    "model_away": round(model["away"], 6),
                    "market_home": round(market["home"], 6),
                    "market_draw": round(market["draw"], 6),
                    "market_away": round(market["away"], 6),
                    "actual": actual,
                }
            )
            scored += 1

    if not scored:
        return {"league": league, "coverage": coverage, "error": "no scoreable matches", "skipped_thin_ratings": skipped_thin_ratings}

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4)

    def _stdev(values: list[float]) -> float:
        mu = sum(values) / len(values)
        return round(math.sqrt(sum((v - mu) ** 2 for v in values) / len(values)), 4)

    return {
        "league": league,
        "coverage": coverage,
        "matches_scored": scored,
        "skipped_thin_ratings": skipped_thin_ratings,
        "simulations_per_match": simulations,
        "model_brier": _mean(model_brier),
        "market_brier": _mean(market_brier),
        "brier_gap_model_minus_market": round(_mean(model_brier) - _mean(market_brier), 4),
        "model_log_loss": _mean(model_ll),
        "market_log_loss": _mean(market_ll),
        "model_home_prob_stdev": _stdev(model_probs),
        "market_home_prob_stdev": _stdev([p for p, _ in market_reliability]),
        "model_reliability": _reliability(model_reliability),
        "market_reliability": _reliability(market_reliability),
        "per_match": per_match,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", choices=BACKTESTABLE_LEAGUES)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--simulations", type=int, default=300, help="matches production's _DEFAULT_SIMULATIONS")
    parser.add_argument("--min-prior-matches", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None, help="cap matches scored per league")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--dump-matches",
        type=Path,
        default=None,
        help="write per-match model/market probabilities + outcome as JSONL, so a "
        "calibration can be fitted and tested without re-running the simulation",
    )
    args = parser.parse_args()

    if not args.league and not args.all:
        parser.error("pass --league <name> or --all")
    leagues = list(BACKTESTABLE_LEAGUES) if args.all else [args.league]

    results = [
        backtest_league(
            league,
            simulations=args.simulations,
            min_prior_matches=args.min_prior_matches,
            limit=args.limit,
        )
        for league in leagues
    ]
    # Per-match rows go to their own file. Folding thousands of them into the
    # summary would make the artifact everyone reads unreadable for the sake of
    # a consumer that wants a flat table anyway.
    if args.dump_matches:
        args.dump_matches.parent.mkdir(parents=True, exist_ok=True)
        with args.dump_matches.open("w", encoding="utf-8", newline="\n") as handle:
            for result in results:
                for match in result.get("per_match") or []:
                    handle.write(json.dumps(match) + "\n")
    summaries = [{key: value for key, value in result.items() if key != "per_match"} for result in results]

    print(json.dumps(summaries, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
