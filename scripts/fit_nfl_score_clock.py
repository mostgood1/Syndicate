"""Fit NFL's live margin model from SCORE AND CLOCK alone.

WHY THIS EXISTS. smartsim2's live re-sim LOSES to a frozen baseline -- measured
2026-09-27, MAE 9.596 against 7.522 over 32 games, and it still loses after its
too-narrow distribution is corrected by propagating rating uncertainty
(`nfl/live_resim.rating_uncertainty_for_source`). The reason is in the ratings
themselves: their implied uncertainty (net sd ~0.51-0.99) is the SAME ORDER as
their own dispersion (net sd 0.381 / 0.866 / 0.329 for 2026 wk1/2/3), so they
carry about as much noise as signal. A model that leans on them inherits that.

So this fits the opposite thing: the rest-of-game margin as a function of the
two quantities that are OBSERVED rather than estimated -- the scoreboard and the
clock. No ratings at all. If that beats both frozen and the re-sim, the live
product's information was never in the ratings.

WHAT IT FITS. For each cutoff at the end of quarter `p`, the final margin is

    final_margin = margin_at_cutoff + REST

and this estimates the empirical distribution of REST, conditioned on `p` and on
the margin already on the board. The second conditioner is not decoration: a
team trailing by 21 in the fourth throws on every down and a team leading by 21
runs the clock out, so REST is NOT independent of the margin it follows. The fit
reports that correlation rather than assuming it, and falls back to the
quarter-only distribution for any cell too thin to stand on its own.

OUT OF SAMPLE BY CONSTRUCTION. Fit seasons and grade seasons are separate
arguments and the artifact records which seasons produced it, so a grade can
assert it never saw its own games. That is the discipline the NCAAF totals
correction skipped on 2026-09-26, when constants fitted on 22-day-stale ratings
went to production and had to be withdrawn the same night.

EXCLUDE 2020 FROM ANY FIT THAT CARES ABOUT HOME ADVANTAGE. That season was
played in empty or near-empty stadiums and home-field advantage was measurably
reduced, so it is not a sample from the same process as the seasons this model
is applied to. Schema 2 exists specifically to stop averaging home advantage
away; feeding it a season where the advantage was suppressed would put the
distortion back by a different route.

    py -3 scripts/fit_nfl_score_clock.py --seasons 2023,2024,2025 \
        --out data/nfl_source/score_clock_margin_2023_2025.json
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest_nfl_live_totals import completed_games  # noqa: E402

SCHEMA_VERSION = 2

# Cutoffs are quarter boundaries, for the same reason the replay harness uses
# them: the score is exact and the clock is 0:00, so no play-by-play is needed
# and one game yields three independent-ish observations.
CUTOFF_PERIODS = (1, 2, 3)

# |margin| buckets. Coarse on purpose -- three seasons is ~800 observations per
# quarter, and a finer grid buys resolution the sample cannot support.
MARGIN_BUCKETS: tuple[tuple[int, int], ...] = ((0, 3), (4, 10), (11, 17), (18, 99))

# A cell must hold at least this many observations to be used instead of the
# quarter-only pooled distribution. Below it the cell IS reported, with its n,
# but the model falls back -- the same power discipline the calibration harness
# applies to its buckets, for the same reason.
MIN_CELL_N = 60


def margin_bucket(margin: int) -> str:
    """SIGNED bucket in the HOME-POSITIVE frame. `H4-10`, `A11-17`, `TIED`.

    SCHEMA 2 STOPPED FOLDING, and the reason is measured. Schema 1 mirrored
    every observation onto "the leader's perspective" to double its cells, which
    assumes leading-home and leading-away are mirror images. On 2025 they are
    not: rest-of-game margin is HOME-POSITIVE regardless of who leads --

        home leading  n=394  mean REST +1.076
        away leading  n=329  mean REST +1.176
        tied          n= 93  mean REST -0.011

    -- so the fold discarded about +2.25 points of home-field advantage, and no
    amount of conditioning on |margin| could recover it because the information
    was destroyed before bucketing. Unfolded, home advantage simply lives in the
    data: an `A4-10` cell already knows the trailing home team tends to gain.

    The cost is cells roughly half the size, which is why `MIN_CELL_N` still
    guards them and thin cells still fall back to the pooled quarter.
    """
    m = int(margin)
    if m == 0:
        return "TIED"
    side = "H" if m > 0 else "A"
    a = abs(m)
    for lo, hi in MARGIN_BUCKETS:
        if lo <= a <= hi:
            return f"{side}{lo}-{hi}"
    return f"{side}{MARGIN_BUCKETS[-1][0]}-{MARGIN_BUCKETS[-1][1]}"


def observations(seasons: list[int], weeks: list[int], *, seasontype: int = 2
                 ) -> list[dict[str, Any]]:
    """(period, margin_at_cutoff, rest_of_game_margin) for every completed game."""
    out: list[dict[str, Any]] = []
    for season in seasons:
        for week in weeks:
            try:
                games = completed_games(season, week, seasontype=seasontype)
            except Exception as exc:  # noqa: BLE001
                print(f"[fit] season={season} week={week} fetch failed: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                continue
            for g in games:
                hl, al = g["home_line"], g["away_line"]
                final = int(g["home_final"]) - int(g["away_final"])
                for p in CUTOFF_PERIODS:
                    at = sum(hl[:p]) - sum(al[:p])
                    out.append({
                        "season": season, "week": week, "event_id": g["event_id"],
                        "period": p, "margin_at": at, "rest": final - at,
                    })
            print(f"[fit] season={season} week={week} games={len(games)}", flush=True)
    return out


def _histogram(values: list[int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(int(v))] = out.get(str(int(v)), 0) + 1
    return out


def fit(obs: list[dict[str, Any]]) -> dict[str, Any]:
    """The artifact: rest-of-game margin distributions by (period, SIGNED bucket).

    EVERYTHING IS HOME-POSITIVE AND NOTHING IS MIRRORED. A caller adds the cell's
    draw to the margin on the board and is done -- there is no sign to unfold and
    therefore no sign to get backwards.
    """
    cells: dict[str, list[int]] = collections.defaultdict(list)
    pooled: dict[int, list[int]] = collections.defaultdict(list)
    corr_input: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)

    for o in obs:
        p, at, rest = int(o["period"]), int(o["margin_at"]), int(o["rest"])
        corr_input[p].append((at, rest))
        # NO FOLD. Everything stays in the HOME-POSITIVE frame, so home-field
        # advantage is carried by the cells instead of being averaged out of
        # them -- see `margin_bucket` for the measurement that forced this.
        pooled[p].append(rest)
        cells[f"{p}|{margin_bucket(at)}"].append(rest)

    correlation: dict[str, Any] = {}
    for p, pairs in sorted(corr_input.items()):
        if len(pairs) > 2:
            xs = [a for a, _ in pairs]
            ys = [b for _, b in pairs]
            try:
                correlation[str(p)] = round(statistics.correlation(xs, ys), 4)
            except Exception:  # noqa: BLE001
                correlation[str(p)] = None

    return {
        "schema_version": SCHEMA_VERSION,
        "fit_seasons": sorted({int(o["season"]) for o in obs}),
        "observations": len(obs),
        "games": len({o["event_id"] for o in obs}),
        "min_cell_n": MIN_CELL_N,
        # THE SIGNED LABELS, i.e. exactly the keys `cells` is bucketed by.
        # Emitting the UNSIGNED list here while keying cells signed made the
        # consumer's lookup miss every cell and fall back to the pooled quarter
        # -- silently, because falling back is legitimate behaviour. Measured
        # before the fix: 86 of 99 graded requests answered from the pool
        # despite only 2 of 27 cells being underpowered.
        "margin_buckets": (["TIED"]
                           + [f"H{lo}-{hi}" for lo, hi in MARGIN_BUCKETS]
                           + [f"A{lo}-{hi}" for lo, hi in MARGIN_BUCKETS]),
        # THE CORRELATION IS PUBLISHED, not assumed. If it is ~0 the margin
        # conditioner is buying nothing and a reader should say so rather than
        # inheriting a model that carries a dimension it does not need.
        "margin_rest_correlation_by_period": correlation,
        "pooled_by_period": {str(p): _histogram(v) for p, v in sorted(pooled.items())},
        "pooled_n_by_period": {str(p): len(v) for p, v in sorted(pooled.items())},
        "cells": {k: _histogram(v) for k, v in sorted(cells.items())},
        "cell_n": {k: len(v) for k, v in sorted(cells.items())},
    }


def grade(model_path: Path, season: int, weeks: list[int], *, seasontype: int = 2
          ) -> dict[str, Any]:
    """Cutoff-replay the fitted model on a season it never saw.

    Scored through the SAME `score()` the re-sim harness uses, on the SAME
    frozen-margin line ladder, so the two models' numbers are comparable. A
    grade computed with its own scorer would be comparing rulers.
    """
    from syndicate.features.nfl.score_clock import load_score_clock_model
    from scripts.backtest_nfl_live_totals import score as harness_score

    model = load_score_clock_model(model_path)
    if model is None:
        raise SystemExit(f"no usable model at {model_path}")
    if season in model.fit_seasons:
        raise SystemExit(
            f"REFUSING: season {season} is in the fit seasons {model.fit_seasons}. "
            f"A model graded on its own training games measures memorisation.")

    rows: list[dict[str, Any]] = []
    sources: dict[str, int] = {}
    refusals: dict[str, int] = {}
    for week in weeks:
        for g in completed_games(season, week, seasontype=seasontype):
            hl, al = g["home_line"], g["away_line"]
            final = int(g["home_final"]) - int(g["away_final"])
            total_final = int(g["home_final"]) + int(g["away_final"])
            for p in CUTOFF_PERIODS:
                at = sum(hl[:p]) - sum(al[:p])
                got = model.margin_distribution(period=p, margin_at=at)
                if got is None:
                    refusals["no_distribution"] = refusals.get("no_distribution", 0) + 1
                    continue
                dist, source = got
                sources[source.split(":")[0]] = sources.get(source.split(":")[0], 0) + 1
                n = sum(int(v) for v in dist.values())
                mean = sum(float(k) * int(v) for k, v in dist.items()) / n
                rows.append({
                    "event_id": g["event_id"], "week": week, "date": g["date"],
                    "cutoff_period": p,
                    "score_at_cutoff": [sum(al[:p]), sum(hl[:p])],
                    "actual_margin": final,
                    "actual_total": total_final,
                    "total_at_cutoff": sum(hl[:p]) + sum(al[:p]),
                    "projected_margin": mean,
                    "projected_total": None,
                    "margin_dist": dist,
                    "total_dist": {},
                    "possession_unknown": True,
                    "model_home_win_prob": model.home_win_probability(period=p, margin_at=at),
                    "band_bypassed": False,
                })
    result = harness_score(rows, lines=[], market="margin")
    result["scored_rows"] = len(rows)
    result["distribution_source_counts"] = sources
    result["refusals"] = refusals
    result["fit_seasons"] = list(model.fit_seasons)
    result["graded_season"] = season
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seasons", default="2023,2024,2025")
    ap.add_argument("--weeks", default=",".join(str(w) for w in range(1, 19)))
    ap.add_argument("--seasontype", type=int, default=2)
    ap.add_argument("--out")
    ap.add_argument("--grade-season", type=int, default=None,
                    help="cutoff-replay an EXISTING fit on this season; refuses "
                         "if it is one of the fit seasons")
    ap.add_argument("--grade-weeks", default="1,2,3")
    ap.add_argument("--model", default=None, help="fitted artifact to grade")
    args = ap.parse_args(argv)

    if args.grade_season is not None:
        res = grade(Path(args.model), args.grade_season,
                    [int(w) for w in args.grade_weeks.split(",") if w.strip()],
                    seasontype=args.seasontype)
        print(json.dumps(res, indent=1, sort_keys=True))
        return 0
    if not args.out:
        print("--out is required when fitting", flush=True)
        return 2

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
    weeks = [int(w) for w in args.weeks.split(",") if w.strip()]
    obs = observations(seasons, weeks, seasontype=args.seasontype)
    if not obs:
        print("no observations; refusing to write an empty fit", flush=True)
        return 2
    art = fit(obs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, sort_keys=True), encoding="utf-8")

    print(f"\nFIT seasons={art['fit_seasons']} games={art['games']} "
          f"observations={art['observations']} -> {out}")
    print(f"  margin/rest correlation by period: {art['margin_rest_correlation_by_period']}")
    print(f"  pooled n by period: {art['pooled_n_by_period']}")
    thin = {k: n for k, n in art["cell_n"].items() if n < MIN_CELL_N}
    print(f"  cells: {len(art['cell_n'])}, of which UNDERPOWERED (<{MIN_CELL_N}): {len(thin)}")
    for k in sorted(thin):
        print(f"     thin {k}: n={thin[k]} -> falls back to the pooled quarter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
