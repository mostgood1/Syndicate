"""Fit and TEST a sharpening calibration for the soccer win-probability model.

Why this exists
---------------
`backtest_soccer_h2h_calibration.py` measured the defect and named it:
soccer's model is well calibrated in AGGREGATE (mean P(home) 0.4525 against a
real base rate of ~44-46%) and **under-dispersed** -- mean stdev(P home)
0.1575 against the market's 0.1811, narrower in 8 of 9 leagues, and too timid
at both extremes (predicted 0.144 -> actual 0.000; predicted 0.823 -> actual
1.000). A model that shrinks toward the base rate disagrees with the market
most exactly where the market is most confident, which is the worst possible
place to source a betting edge.

Under-dispersion is the one model defect that can be repaired WITHOUT touching
the simulation, because it is a property of the output distribution rather than
of the process that generated it. Temperature (power) scaling:

    p_i' = p_i**(1/T) / sum_j p_j**(1/T)

`T < 1` sharpens, `T > 1` flattens, `T == 1` is the identity. One parameter,
fitted on past matches, applied to future ones.

THE RULE THIS SCRIPT EXISTS TO ENFORCE
--------------------------------------
**A calibration fitted and scored on the same matches is not a result.** It is
guaranteed to improve the number it was fitted on, which is why tuning against
the headline Brier would manufacture an improvement out of nothing. So:

- The split is **CHRONOLOGICAL, never random.** Train on the earlier matches,
  test on the later ones. A random split leaks the future into the fit through
  the league's own season-to-season drift, which is the same leakage class
  `soccer-backtest-leakage` was opened for -- and the same class the DD/MM/YYYY
  bug hid for a day.
- **Only the held-out number is reported as the result.** The in-sample number
  is printed beside it precisely so the gap between them is visible; when they
  diverge, the fit is memorising.
- The market benchmark is recomputed **on the test slice only**, so model and
  market are always compared on identical matches.

A calibration that helps in-sample and not out-of-sample is a NEGATIVE result
and should be reported as one. That outcome is a real possibility here: 300
simulations per match put +/-2.9pp of pure Monte Carlo noise on every input
probability, and no post-hoc transform can sharpen noise into signal.

HOW TO READ THE RESULT -- this is a DIAGNOSTIC, not only a fix
--------------------------------------------------------------
Temperature scaling is the **cheap upper bound on what any pure-dispersion fix
can achieve**, because it stretches the distribution optimally while leaving the
model's ORDERING of matches untouched. That makes the outcome informative either
way, and it decides where the next (expensive) work should go:

- **If sharpening closes much of the gap**, the defect really is dispersion, and
  the durable fix is upstream in the ratings -- `_RATING_SCALE = 0.55` and
  `_RATING_CAP = 0.35` in `features/loaders.py` compress real team-strength
  differences before they ever reach the simulation. Worth re-simulating a
  sweep of those constants.
- **If sharpening does NOT close the gap**, the defect is DISCRIMINATION, not
  dispersion: the model ranks matches worse than the market does, and no
  rescaling of its output can repair a ranking. Sweeping the rating constants
  would then be wasted compute, and the real work is the feature set (xG
  quality, lineups, rest, home advantage per league).

So a negative result here SAVES the more expensive experiment rather than
merely failing. Report it as such.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

OUTCOMES = ("home", "draw", "away")


def load_matches(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sharpen(probabilities: dict[str, float], temperature: float) -> dict[str, float]:
    """Temperature-scale a 3-way distribution.

    Guards the two inputs that make the power undefined or degenerate: a
    non-positive temperature, and a zero probability (``0 ** large`` is 0, which
    is fine, but ``0 ** 0`` is 1 and would resurrect an impossible outcome).
    """
    if temperature <= 0:
        raise ValueError("temperature must be > 0")
    powered = {key: max(value, 0.0) ** (1.0 / temperature) for key, value in probabilities.items()}
    total = sum(powered.values())
    if total <= 0:
        return dict(probabilities)
    return {key: value / total for key, value in powered.items()}


def brier(probabilities: dict[str, float], actual: str) -> float:
    return sum((probabilities[outcome] - (1.0 if outcome == actual else 0.0)) ** 2 for outcome in OUTCOMES)


def log_loss(probabilities: dict[str, float], actual: str) -> float:
    return -math.log(max(probabilities.get(actual, 0.0), 1e-12))


def _model_of(row: dict[str, Any]) -> dict[str, float]:
    return {outcome: float(row[f"model_{outcome}"]) for outcome in OUTCOMES}


def _market_of(row: dict[str, Any]) -> dict[str, float]:
    return {outcome: float(row[f"market_{outcome}"]) for outcome in OUTCOMES}


def mean_brier(rows: list[dict[str, Any]], temperature: float) -> float:
    if not rows:
        return float("nan")
    return sum(brier(sharpen(_model_of(row), temperature), row["actual"]) for row in rows) / len(rows)


def mean_log_loss(rows: list[dict[str, Any]], temperature: float) -> float:
    if not rows:
        return float("nan")
    return sum(log_loss(sharpen(_model_of(row), temperature), row["actual"]) for row in rows) / len(rows)


def fit_temperature(
    rows: list[dict[str, Any]],
    *,
    objective: str = "log_loss",
    low: float = 0.30,
    high: float = 2.50,
    steps: int = 111,
) -> float:
    """Grid-search the temperature that minimises the objective on ``rows``.

    A grid rather than a solver on purpose: the objective is one-dimensional and
    cheap, a grid cannot diverge, and the returned value is reproducible without
    pinning a solver's tolerances. ``log_loss`` is the default because it
    penalises overconfidence far more sharply than Brier, which is the failure
    mode sharpening can introduce.
    """
    score = mean_log_loss if objective == "log_loss" else mean_brier
    best_temperature = 1.0
    best_score = float("inf")
    for index in range(steps):
        temperature = low + (high - low) * index / (steps - 1)
        value = score(rows, temperature)
        if value < best_score:
            best_score = value
            best_temperature = temperature
    return round(best_temperature, 4)


def stdev_home(rows: list[dict[str, Any]], temperature: float) -> float:
    if not rows:
        return float("nan")
    values = [sharpen(_model_of(row), temperature)["home"] for row in rows]
    mu = sum(values) / len(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / len(values))


def auc(scores: list[float], labels: list[bool]) -> float:
    """One-vs-rest AUC via the rank-sum identity, ties averaged.

    THE POINT OF REPORTING THIS: AUC depends only on the ORDER of the scores, so
    temperature scaling cannot change it by even a rounding step. It therefore
    separates the two defects that Brier confounds:

    - model AUC ~ market AUC  -> the ranking is fine, the miscalibration is the
      problem, and sharpening is the right lever.
    - model AUC < market AUC  -> the model ranks matches worse than the price
      does. No monotone transform can repair that, so no calibration and no
      rating-constant sweep will close the Brier gap.

    Returns NaN when a class is absent, because AUC is undefined there rather
    than 0.5 -- an undefined value must not be reported as a coin flip.
    """
    positives = [score for score, label in zip(scores, labels) if label]
    negatives = [score for score, label in zip(scores, labels) if not label]
    if not positives or not negatives:
        return float("nan")
    ordered = sorted(range(len(scores)), key=lambda index: scores[index])
    ranks = [0.0] * len(scores)
    position = 0
    while position < len(ordered):
        end = position
        while end + 1 < len(ordered) and scores[ordered[end + 1]] == scores[ordered[position]]:
            end += 1
        average_rank = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[ordered[index]] = average_rank
        position = end + 1
    positive_rank_sum = sum(rank for rank, label in zip(ranks, labels) if label)
    return (positive_rank_sum - len(positives) * (len(positives) + 1) / 2.0) / (len(positives) * len(negatives))


def chronological_split(rows: list[dict[str, Any]], train_fraction: float) -> tuple[list, list]:
    """Split by DATE, not by index, so a single day never straddles the split.

    Sorting by date alone would still let two matches on the same day land on
    opposite sides, which leaks that day's ratings context across the boundary.
    """
    ordered = sorted(rows, key=lambda row: (str(row.get("date") or ""), str(row.get("home_team") or "")))
    days = sorted({str(row.get("date") or "") for row in ordered})
    if len(days) < 2:
        return ordered, []
    cut_index = max(1, min(len(days) - 1, int(round(len(days) * train_fraction))))
    cutoff = days[cut_index]
    train = [row for row in ordered if str(row.get("date") or "") < cutoff]
    test = [row for row in ordered if str(row.get("date") or "") >= cutoff]
    return train, test


def evaluate(rows: list[dict[str, Any]], temperature: float) -> dict[str, Any]:
    market_brier = sum(brier(_market_of(row), row["actual"]) for row in rows) / len(rows) if rows else float("nan")
    home_labels = [row["actual"] == "home" for row in rows]
    model_auc = auc([_model_of(row)["home"] for row in rows], home_labels)
    market_auc = auc([_market_of(row)["home"] for row in rows], home_labels)
    return {
        "n": len(rows),
        # Invariant to `temperature` by construction -- see `auc`. If these two
        # differ, the gap is discrimination and no calibration can close it.
        "model_auc_home": round(model_auc, 4),
        "market_auc_home": round(market_auc, 4),
        "auc_gap_model_minus_market": round(model_auc - market_auc, 4),
        "model_brier_raw": round(mean_brier(rows, 1.0), 4),
        "model_brier_calibrated": round(mean_brier(rows, temperature), 4),
        "market_brier": round(market_brier, 4),
        "gap_raw": round(mean_brier(rows, 1.0) - market_brier, 4),
        "gap_calibrated": round(mean_brier(rows, temperature) - market_brier, 4),
        "model_log_loss_raw": round(mean_log_loss(rows, 1.0), 4),
        "model_log_loss_calibrated": round(mean_log_loss(rows, temperature), 4),
        "model_stdev_home_raw": round(stdev_home(rows, 1.0), 4),
        "model_stdev_home_calibrated": round(stdev_home(rows, temperature), 4),
        "market_stdev_home": round(
            (lambda v: math.sqrt(sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)))(
                [_market_of(row)["home"] for row in rows]
            )
            if rows
            else float("nan"),
            4,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matches", type=Path, required=True, help="per-match JSONL from backtest_soccer_h2h_calibration.py")
    parser.add_argument("--train-fraction", type=float, default=0.6)
    parser.add_argument("--objective", choices=("log_loss", "brier"), default="log_loss")
    parser.add_argument("--per-league", action="store_true", help="also fit one temperature per league")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows = load_matches(args.matches)
    if not rows:
        print("no matches loaded", flush=True)
        return 1

    train, test = chronological_split(rows, args.train_fraction)
    if not test:
        print("chronological split produced no test slice", flush=True)
        return 1

    temperature = fit_temperature(train, objective=args.objective)
    result: dict[str, Any] = {
        "matches_total": len(rows),
        "objective": args.objective,
        "train_fraction": args.train_fraction,
        "train_dates": [train[0]["date"], train[-1]["date"]] if train else None,
        "test_dates": [test[0]["date"], test[-1]["date"]],
        "fitted_temperature": temperature,
        "in_sample_train": evaluate(train, temperature),
        "HELD_OUT_test": evaluate(test, temperature),
    }

    if args.per_league:
        by_league: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_league[str(row.get("league"))].append(row)
        per_league = {}
        for league, league_rows in sorted(by_league.items()):
            league_train, league_test = chronological_split(league_rows, args.train_fraction)
            if not league_train or not league_test:
                continue
            league_temperature = fit_temperature(league_train, objective=args.objective)
            per_league[league] = {
                "fitted_temperature": league_temperature,
                "HELD_OUT_test": evaluate(league_test, league_temperature),
                "HELD_OUT_test_with_global_temperature": evaluate(league_test, temperature),
            }
        result["per_league"] = per_league

    print(json.dumps(result, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
