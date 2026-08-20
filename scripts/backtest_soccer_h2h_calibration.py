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

- Match fixtures/results/closing-odds always come from committed `history/`
  files, for all nine backtestable leagues.
- **Team RATINGS branch by league, matching `build_soccer_artifacts.
  _load_team_ratings` exactly (fixed 2026-08-19; previously this backtest
  used the goals-as-xG fallback for every league, which measured a DIFFERENT
  pipeline than production runs for five of them):**
  - eredivisie, primeira_liga, championship, belgian_pro_league: goals stand
    in for xG, `team_rows_from_match_history`'s documented fallback,
    `window=90`.
  - epl, la_liga, bundesliga, serie_a, ligue_1: real Understat xG and ppda
    from committed `team_history/*.csv`, `window=45` -- no goals conversion,
    matching what production actually reads for these five.
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
    _EspnStatsIndex,
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


# Mirrors `build_soccer_artifacts._GOALS_BASED_RATING_LEAGUES` EXACTLY --
# checked against it directly, not re-derived, when this branch was added.
_GOALS_BASED_RATING_LEAGUES = {"eredivisie", "primeira_liga", "championship", "belgian_pro_league"}


def _load_team_history(league: str) -> list[dict[str, Any]]:
    """Real Understat team-match rows (`team`, `xg_for`, `xg_against`, `ppda`,
    ...) for the five non-goals-based leagues. `compute_team_ratings`'s own
    docstring says these "match directly" -- no goals-as-xG conversion.

    THIS BRANCH WAS MISSING HERE UNTIL NOW, and it was not a silent oversight
    -- the module docstring above explicitly scoped "plus the five Understat
    leagues" through `team_rows_from_match_history`'s goals-as-xG fallback,
    stated as a deliberate choice. It just never matched what
    `build_soccer_artifacts._load_team_ratings` actually does in PRODUCTION
    for these same five leagues: reads `team_history/teams_*.csv` directly,
    real xG and real ppda, `window=45` (vs `window=90` for the goals-based
    four -- xG is smoother than raw goals, so it needs less smoothing).
    A backtest measuring a DIFFERENT pipeline than production runs is not
    measuring production, whatever its own internal leak-freedom. `ppda`'s
    "CONSUMED, container has none" alarm on this path was a symptom of the
    same gap, not a separate problem -- this fixes both at once."""
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(REPO_ROOT / "data" / "soccer_source" / league / "team_history" / "*.csv"))):
        rows.extend(pd.read_csv(path).to_dict("records"))
    return rows


def _load_espn_match_stats(league: str) -> list[dict[str, Any]]:
    """Possession%/set-piece-goal-share rows, if a backfill exists for this
    league (`espn_match_stats.py`, run offline via
    `aggregate_season_match_stats` -- not fetched live here, same reasoning
    `_load_history` already has for reading pre-fetched CSVs rather than
    hitting a market API per run). Absent file -> empty list -> `espn_stats=`
    is optional at the call site, so a league with no backfill yet degrades
    to exactly today's behaviour rather than failing."""
    path = REPO_ROOT / "data" / "soccer_source" / league / "history" / "espn_match_stats.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


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


def backtest_league(
    league: str, *, simulations: int, min_prior_matches: int, limit: int | None,
    wire_market_confidence: bool = False,
) -> dict[str, Any]:
    history = _load_history(league)
    if not history:
        return {"league": league, "error": "no committed history"}

    espn_stats = _load_espn_match_stats(league)
    # MATCHES `build_soccer_artifacts._load_team_ratings` EXACTLY, branch for
    # branch -- this backtest previously used the goals-as-xG fallback for
    # every league including these five, which is NOT what production does
    # for them (production reads real Understat xG+ppda here). A backtest
    # measuring a different pipeline than production runs is not measuring
    # production. Deliberately reproduces production's CURRENT gap too: the
    # Understat branch does not fold in ESPN possession/set-piece the way
    # `team_rows_from_match_history` does for the goals-based four, even
    # though `espn_match_stats.json` exists for all five of these leagues
    # (confirmed 918-1145 rows each) -- that is a real, separate opportunity
    # in PRODUCTION, not something to silently fix inside a backtest whose
    # whole point is measuring what production actually does today.
    if league in _GOALS_BASED_RATING_LEAGUES:
        team_rows = team_rows_from_match_history(history, espn_stats=espn_stats)
        rating_window = 90
    else:
        team_rows = _load_team_history(league)
        rating_window = 45
    # SEPARATE from the `team_rows` join above on purpose. `possession_share`/
    # `set_piece_goal_share` are ratings-derived (rolling team averages, via
    # `compute_team_ratings`); `starters_available_share` is PER-FIXTURE (this
    # match's actual lineup against the team's historical core), so it is
    # looked up per fixture below, not folded into a team-level average. Same
    # underlying artifact, same fuzzy-match index, different consumption
    # shape -- reusing `_EspnStatsIndex` rather than building a second one.
    espn_index = _EspnStatsIndex(espn_stats)

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
        ratings = compute_team_ratings(team_rows, as_of=day, window=rating_window)
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

        def _fixture(row: dict[str, Any]) -> dict[str, Any]:
            fx: dict[str, Any] = {
                "home_team": row["home_team"], "away_team": row["away_team"],
                "match_id": str(row.get("match_id") or ""),
            }
            espn_row = espn_index.lookup(str(row["home_team"]), str(row["away_team"]), str(row.get("date") or ""))
            if espn_row is not None:
                if espn_row.get("home_starters_available_share") is not None:
                    fx["home_starters_available_share"] = espn_row["home_starters_available_share"]
                if espn_row.get("away_starters_available_share") is not None:
                    fx["away_starters_available_share"] = espn_row["away_starters_available_share"]
            # `market_features.confidence` is match-level, not per-side (see
            # `_market_prior_index` -- no `side=` on its `_first_float` call),
            # so ONE value applies to both teams' priors, same as tempo. Reuses
            # `_market_probabilities`, the SAME devig this script already uses
            # for the market benchmark -- CLI-gated (`--wire-market-confidence`,
            # default off) specifically so a plain re-run of this script never
            # silently starts leaking the benchmark into the model.
            if wire_market_confidence:
                market = _market_probabilities(row)
                if market is not None:
                    fx["market_features"] = {"confidence": max(market.values())}
            return fx

        simulation_input = build_soccer_simulation_input(
            league=league,
            date=day,
            fixtures=[_fixture(row) for row in eligible],
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
    parser.add_argument(
        "--wire-market-confidence",
        action="store_true",
        help="feed market_features.confidence (max de-vigged closing-odds probability) into the "
        "sim's market_prior_index. OFF by default. NOTE: this reuses the SAME closing odds this "
        "script benchmarks the model against, so a Brier improvement with this flag on reflects "
        "shrinkage toward the market, not independent model skill -- see possession_priors.py's "
        "_market_prior_index docstring and the soccer-model-dispersion lane's log for why that "
        "distinction matters here specifically.",
    )
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
            wire_market_confidence=args.wire_market_confidence,
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
