"""Grade the NFL fantasy projection engine against a real, completed season.

THE FALSIFICATION TEST for `lane nfl-fantasy-projections`. It projects a
target season using ONLY the seasons before it, then scores the projection
against what actually happened, and compares it to the naive baseline every
fantasy projection has to beat before it is worth anything:

    BASELINE: "what he did last year"

If the engine does not beat that on season-total error AND on rank
correlation, it is not a projection, it is an expensive way to copy a column,
and this script says so rather than being tuned until it passes.

LEAKAGE, stated up front
------------------------
``fantasy_schedule`` feeds team scoring environment from the market's posted
spreads and totals. For a COMPLETED season those are in-season closing lines,
which a preseason projection could not have had. So the headline run sets
``use_market_environment=False`` and the engine falls back to team scoring
history -- an honest preseason analogue.

The market-on run is reported alongside it and clearly labelled: it is an
upper reference contaminated by hindsight, NOT a result. The 2026 production
path is neither of these -- it uses LOOKAHEAD lines posted before the season,
which are genuinely available now (112 of 272 games) and carry no hindsight.

    python scripts/backtest_nfl_fantasy_projections.py --season 2025
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_players import load_fantasy_players  # noqa: E402
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG  # noqa: E402
from syndicate.features.nfl.fantasy_projection import EngineConfig  # noqa: E402
from syndicate.features.nfl.fantasy_projection import _usage_to_stat_line  # noqa: E402
from syndicate.features.nfl.fantasy_projection import project_season  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import resolve_scoring  # noqa: E402
from syndicate.features.nfl.fantasy_usage import load_season_usage  # noqa: E402


def actual_points(season: int, scoring) -> dict[str, tuple[float, float, int]]:
    """``player_id -> (season points, points per game, games)`` for *season*."""
    from syndicate.features.nfl.fantasy_scoring import score_stat_line

    players, _ = load_season_usage(season)
    out: dict[str, tuple[float, float, int]] = {}
    for player_id, usage in players.items():
        if not usage.games:
            continue
        total = score_stat_line(_usage_to_stat_line(usage), scoring)
        out[player_id] = (total, total / usage.games, usage.games)
    return out


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _spearman(pairs: list[tuple[float, float]]) -> float:
    """Rank correlation. Ties get average ranks."""
    if len(pairs) < 3:
        return 0.0

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        index = 0
        while index < len(order):
            stop = index
            while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
                stop += 1
            average = (index + stop) / 2.0 + 1.0
            for position in range(index, stop + 1):
                out[order[position]] = average
            index = stop + 1
        return out

    x_ranks = ranks([x for x, _ in pairs])
    y_ranks = ranks([y for _, y in pairs])
    mean_x, mean_y = _mean(x_ranks), _mean(y_ranks)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x_ranks, y_ranks))
    denominator = (
        sum((a - mean_x) ** 2 for a in x_ranks) * sum((b - mean_y) ** 2 for b in y_ranks)
    ) ** 0.5
    return numerator / denominator if denominator else 0.0


def grade(
    label: str,
    predictions: dict[str, float],
    truth: dict[str, tuple[float, float, int]],
    positions: dict[str, str],
    graded_ids: set[str],
    per_game: bool,
) -> dict[str, object]:
    """Score one set of predictions against reality, over a FIXED player set.

    ``graded_ids`` is passed in rather than derived here, and that is the point.
    Grading each method over whatever players it happened to produce is not a
    comparison: the first version of this script scored the baseline over 297
    players and the engine over 275 (62 tight ends against 29), so the two MAEs
    were measured on different populations and the difference between them was
    partly just the difference in who was in the set. Every method is now scored
    on the intersection, so the only thing that varies is the prediction.
    """
    rows: list[tuple[str, float, float]] = []
    for player_id in graded_ids:
        total, points_per_game, games = truth[player_id]
        predicted = predictions.get(player_id)
        if predicted is None:
            continue
        actual = points_per_game if per_game else total
        value = predicted / games if per_game else predicted
        rows.append((player_id, value, actual))

    if not rows:
        return {"label": label, "n": 0}

    errors = [abs(predicted - actual) for _, predicted, actual in rows]
    bias = _mean(predicted - actual for _, predicted, actual in rows)
    by_position: dict[str, dict[str, float]] = {}
    for position in sorted({positions.get(player_id, "?") for player_id, _, _ in rows}):
        subset = [row for row in rows if positions.get(row[0]) == position]
        if len(subset) < 5:
            continue
        by_position[position] = {
            "n": len(subset),
            "mae": round(_mean(abs(p - a) for _, p, a in subset), 2),
            "spearman": round(_spearman([(p, a) for _, p, a in subset]), 4),
        }

    return {
        "label": label,
        "n": len(rows),
        "mae": round(_mean(errors), 2),
        "bias": round(bias, 2),
        "spearman": round(_spearman([(p, a) for _, p, a in rows]), 4),
        "by_position": by_position,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025, help="season to grade")
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--min-games", type=int, default=8)
    parser.add_argument("--out", default="reports/nfl_fantasy_backtest.json")
    args = parser.parse_args()

    season = args.season
    scoring = resolve_scoring(args.scoring)
    truth = actual_points(season, scoring)
    positions = {
        player.player_id: player.position
        for player in load_fantasy_players(season)
        if player.player_id
    }
    if not truth:
        print(f"no usage on this substrate for {season} -- UNMEASURED, not zero", flush=True)
        return 1

    # ---- baseline: last season carried forward, unchanged
    previous = actual_points(season - 1, scoring)
    baseline = {player_id: total for player_id, (total, _, _) in previous.items()}

    methods: dict[str, dict[str, float]] = {"baseline_last_season_total": baseline}
    for label, config in (
        ("engine_no_market", EngineConfig(use_market_environment=False)),
        ("engine_with_market_LEAKY", DEFAULT_CONFIG),
    ):
        projected = project_season(season, scoring, config)
        methods[label] = {row.player_id: row.fantasy_points for row in projected}

    # The one population every method is scored on: real players who held a
    # role, and for whom every method produced a number.
    graded_ids = {
        player_id
        for player_id, (_, _, games) in truth.items()
        if games >= args.min_games and all(player_id in method for method in methods.values())
    }

    results = [
        grade(label, predictions, truth, positions, graded_ids, per_game=False)
        for label, predictions in methods.items()
    ]
    per_game_results = [
        grade(label, predictions, truth, positions, graded_ids, per_game=True)
        for label, predictions in methods.items()
    ]

    print(f"=== NFL fantasy backtest: {season}, {scoring.label}, >= {args.min_games} games ===")
    print(f"graded on ONE common set of {len(graded_ids)} players for every method")
    print()
    print("--- SEASON TOTAL points ---")
    for entry in results:
        if not entry.get("n"):
            print(f"{entry['label']}: NO ROWS")
            continue
        print(
            f"{entry['label']:<28} n={entry['n']:<5} MAE={entry['mae']:<8} "
            f"bias={entry['bias']:<8} spearman={entry['spearman']}"
        )
        for position, stats in entry["by_position"].items():
            print(
                f"    {position:<5} n={stats['n']:<4} MAE={stats['mae']:<8} "
                f"spearman={stats['spearman']}"
            )
        print()

    print("--- PER-GAME points (removes games-played prediction from the comparison) ---")
    for entry in per_game_results:
        if not entry.get("n"):
            continue
        print(
            f"{entry['label']:<28} n={entry['n']:<5} MAE={entry['mae']:<8} "
            f"bias={entry['bias']:<8} spearman={entry['spearman']}"
        )
        for position, stats in entry["by_position"].items():
            print(
                f"    {position:<5} n={stats['n']:<4} MAE={stats['mae']:<8} "
                f"spearman={stats['spearman']}"
            )
    print()

    engine = next(e for e in results if e["label"] == "engine_no_market")
    base = results[0]
    verdict = "PASS" if (engine["mae"] < base["mae"] and engine["spearman"] > base["spearman"]) else "FAIL"
    print(
        f"VERDICT ({verdict}): engine_no_market vs baseline -- "
        f"MAE {base['mae']} -> {engine['mae']}, "
        f"spearman {base['spearman']} -> {engine['spearman']}"
    )
    print("engine_with_market_LEAKY uses in-season closing lines and is NOT a result.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "season": season,
                "scoring": scoring.key,
                "min_games": args.min_games,
                "verdict": verdict,
                "graded_players": len(graded_ids),
                "results": results,
                "per_game_results": per_game_results,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
