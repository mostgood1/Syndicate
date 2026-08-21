"""Select the NFL fantasy engine's tunable constants on a FIT season only.

The discipline here is copied deliberately from the NFL prop model's six tuned
constants (``state.md [nfl-player-props-model]``): SELECT on one half, and only
ever REPORT on the other, which is never used to choose anything.

    SELECT on 2024   (projected from 2022-2023)
    REPORT on 2025   (projected from 2022-2024) via
                     scripts/backtest_nfl_fantasy_projections.py

Anything this script touches is a value the backtest is then allowed to be
surprised by. A constant that is chosen on 2025 and reported on 2025 is not a
measurement, and this repo has a standing rule about exactly that.

Sweeps ONE parameter at a time (coordinate descent, one pass). Deliberately a
small search: with 233 gradeable players a wide grid would fit the noise, and
the point of a prior-heavy engine is that it should not need a big search to
work.

    python scripts/calibrate_nfl_fantasy_projections.py
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Imported by file path rather than as `scripts.backtest_...`: `scripts/` is
# deliberately NOT a package in this repo, and adding an `__init__.py` to make
# one import work would change module resolution for every script in the tree.
_backtest = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        "_nfl_fantasy_backtest",
        Path(__file__).resolve().parent / "backtest_nfl_fantasy_projections.py",
    )
)
_backtest.__loader__.exec_module(_backtest)  # type: ignore[union-attr]
_mean = _backtest._mean
_spearman = _backtest._spearman
actual_points = _backtest.actual_points
from syndicate.features.nfl.fantasy_projection import EngineConfig  # noqa: E402
from syndicate.features.nfl.fantasy_projection import project_season  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import resolve_scoring  # noqa: E402


#: One pass, one parameter at a time. Candidate values bracket the hand-set
#: default rather than exploring freely -- see the module docstring.
#: Grids widened 2026-08-21 wherever the previous pass SELECTED A GRID EDGE.
#: An edge selection is not an optimum -- it is the search telling you it ran
#: out of room, and banking it as "fitted" claims a measurement the sweep did
#: not make. `ypc`/`ypt` had bottomed out and `team_volume_prior_games` had
#: topped out, so all three now extend past where they landed.
SWEEPS: tuple[tuple[str, tuple], ...] = (
    ("role_curve_strength", (0.0, 0.25, 0.4, 0.5, 0.65, 0.8, 1.0)),
    ("share_history_half_games", (2.0, 4.0, 6.0, 8.0, 12.0, 18.0, 26.0)),
    (
        "season_recency_weights",
        (
            (1.0,),
            (1.0, 0.4),
            (1.0, 0.55, 0.30),
            (1.0, 0.7, 0.5),
            (1.0, 0.85, 0.7),
        ),
    ),
    ("ypc_prior_opportunities", (5.0, 15.0, 30.0, 60.0, 90.0, 150.0, 250.0)),
    ("ypt_prior_opportunities", (2.0, 6.0, 15.0, 30.0, 45.0, 80.0, 140.0)),
    ("catch_rate_prior_opportunities", (5.0, 15.0, 40.0, 90.0, 200.0)),
    ("ypa_prior_opportunities", (30.0, 90.0, 180.0, 400.0, 900.0)),
    ("team_volume_prior_games", (2.0, 8.0, 16.0, 32.0, 64.0, 128.0)),
    ("availability_history_half_games", (0.0, 2.0, 5.0, 12.0, 25.0, 60.0)),
    ("rz_weight_receiving", (0.0, 0.3, 0.55, 0.8, 1.0)),
    ("gl_weight_rushing", (0.0, 0.35, 0.65, 0.85, 1.0)),
)


def score(config: EngineConfig, season: int, scoring, truth, min_games: int) -> dict[str, float]:
    """Objective on the FIT season. Lower is better.

    Combines normalised season-total MAE with rank correlation, because a draft
    board is used for BOTH: the absolute number sets your expectations and the
    order sets your picks. Optimising MAE alone rewards shrinking everything to
    the mean, which flattens exactly the ordering a draft needs.
    """
    projected = project_season(season, scoring, config)
    predictions = {row.player_id: row.fantasy_points for row in projected}
    rows = [
        (predictions[player_id], total)
        for player_id, (total, _, games) in truth.items()
        if games >= min_games and player_id in predictions
    ]
    if len(rows) < 30:
        return {"objective": float("inf"), "n": len(rows), "mae": 0.0, "spearman": 0.0}
    mae = _mean(abs(p - a) for p, a in rows)
    spearman = _spearman(rows)
    mean_actual = _mean(a for _, a in rows) or 1.0
    return {
        "objective": (mae / mean_actual) - spearman,
        "n": len(rows),
        "mae": round(mae, 2),
        "spearman": round(spearman, 4),
        "bias": round(_mean(p - a for p, a in rows), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-season", type=int, default=2024)
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--min-games", type=int, default=8)
    parser.add_argument("--out", default="reports/nfl_fantasy_calibration.json")
    args = parser.parse_args()

    scoring = resolve_scoring(args.scoring)
    truth = actual_points(args.fit_season, scoring)
    if not truth:
        print(f"no usage for {args.fit_season} on this substrate -- UNMEASURED", flush=True)
        return 1

    config = EngineConfig()
    baseline = score(config, args.fit_season, scoring, truth, args.min_games)
    print(f"=== calibrating on {args.fit_season} ONLY ({scoring.label}) ===")
    print(
        f"start  objective={baseline['objective']:.4f}  MAE={baseline['mae']}  "
        f"spearman={baseline['spearman']}  n={baseline['n']}"
    )
    print()

    trail: list[dict[str, object]] = []
    for name, candidates in SWEEPS:
        current = getattr(config, name)
        results = []
        for value in candidates:
            trial = dataclasses.replace(config, **{name: value})
            outcome = score(trial, args.fit_season, scoring, truth, args.min_games)
            results.append((value, outcome))
            marker = "  <- current" if value == current else ""
            print(
                f"  {name:<28} {str(value):<20} objective={outcome['objective']:.4f} "
                f"MAE={outcome['mae']:<7} rho={outcome['spearman']}{marker}"
            )
        best_value, best = min(results, key=lambda item: item[1]["objective"])
        config = dataclasses.replace(config, **{name: best_value})
        print(f"  --> {name} = {best_value}  (objective {best['objective']:.4f})")
        print()
        trail.append(
            {
                "parameter": name,
                "selected": best_value,
                "candidates": [
                    {"value": value, **{k: v for k, v in outcome.items()}}
                    for value, outcome in results
                ],
            }
        )

    final = score(config, args.fit_season, scoring, truth, args.min_games)
    print("=== SELECTED (on the fit season only) ===")
    for name, _ in SWEEPS:
        print(f"  {name} = {getattr(config, name)}")
    print()
    print(
        f"fit-season objective {baseline['objective']:.4f} -> {final['objective']:.4f} "
        f"| MAE {baseline['mae']} -> {final['mae']} "
        f"| spearman {baseline['spearman']} -> {final['spearman']}"
    )
    print()
    print("These are FIT numbers and prove nothing on their own.")
    print("Run scripts/backtest_nfl_fantasy_projections.py --season 2025 to report.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "fit_season": args.fit_season,
                "scoring": scoring.key,
                "min_games": args.min_games,
                "start": baseline,
                "final": final,
                "selected": {name: getattr(config, name) for name, _ in SWEEPS},
                "trail": trail,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
