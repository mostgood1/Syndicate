"""Phase 7: score MLB sim projections against realized outcomes (`#440`).

Reads `daily_summary_<date>.json`, joins each simulated DISTRIBUTION to the
real box score, and scores it with `projection_score`. No bet, no grading, no
settlement -- which is the entire point: production has settled ZERO records,
and this instrument does not care.

WHAT IS SCORED, AND WHY ONLY THIS.

  pitcher props  so / outs / pitches / hits / earned_runs / walks
                 EXACT join on (date, game_pk, player_id). Six of the seven
                 PMF markets: `batters_faced` has no column in the game log,
                 so it is REPORTED AS UNJOINABLE rather than quietly dropped.

  game totals    total_runs, from `outputs[].full.total_runs_dist`
                 The outcome is DERIVED (every run scored is charged to some
                 pitcher), so it is cross-checked against an independent
                 source -- the batter log's runs -- and any game where the two
                 disagree is dropped AND COUNTED, never reconciled.

  NOT SCORED     run_margin_dist. The PMF is there and it is tempting, but the
                 sign convention (home-away vs away-home) is not stated in the
                 artifact and guessing it would produce a confident wrong
                 number rather than an error. Verify the convention first.

COVERAGE IS PRINTED BEFORE ANY SCORE. CLAUDE.md's standing trap: per-family
windows do not line up, and a backtest can look like months while resting on
one date. The intersection is the denominator and it is reported first.

THE MIRROR CAVEAT. `--source local` reads `data/mlb_source/**`, which is a
LOSSY MIRROR of production, not a snapshot of what production computed. Every
number carries the source and the date count. Use `--source production` for a
citable result.

Usage:
  py -3 scripts/score_projections.py
  py -3 scripts/score_projections.py --min-sample 50 --json reports/phase7.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.projection_score import (  # noqa: E402
    DEFAULT_MIN_SAMPLE,
    ProjectionObservation,
    score_projections,
)

MLB_DATA = REPO_ROOT / "data/mlb_source/source_artifacts/data"
DATE_RE = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")

BASE = "https://syndicate-an21.onrender.com"
ARTIFACT_PREFIX = "mlb_source/source_artifacts/data"
CACHE = REPO_ROOT / "reports/phase7_cache"

# THE TWO SOURCES ARE NEARLY DISJOINT IN TIME, and that is the opposite of what
# "production has more history than the checkout" would lead you to expect.
# Measured 2026-08-17: production's game logs hold 2026-07-19..08-16 (29 dates)
# and the checkout's hold 2026-05-28..07-14 (47 dates). The logs are a ROLLING
# WINDOW that production trims, and the mirror is preserving history production
# has already dropped. So `--source both` is not redundancy -- it is two
# independent samples separated in time, and a finding that reproduces across
# them is far stronger than one that does not.

# artifact dist key -> (market label, game-log column)
PITCHER_MARKETS = {
    "so_dist": ("strikeouts", "k"),
    "outs_dist": ("outs", "outs"),
    "pitches_dist": ("pitches", "pitches"),
    "hits_dist": ("hits_allowed", "h"),
    "earned_runs_dist": ("earned_runs", "er"),
    "walks_dist": ("walks_allowed", "bb"),
}
# Present in the artifact, absent from the outcome source. Named, not dropped.
PITCHER_MARKETS_UNJOINABLE = {"batters_faced_dist": "no batters_faced column in mlb_pitcher_game_log"}


def _date_from(name: str) -> str | None:
    match = DATE_RE.search(name)
    return "-".join(match.groups()) if match else None


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _admin_token() -> str:
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in .env -- needed for --source production")


def _stream(path: str, token: str, timeout: int = 180) -> bytes:
    url = f"{BASE}/api/ops/artifacts/stream?path={urllib.parse.quote(path)}"
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"X-Admin-Token": token}), timeout=timeout
    ).read()


def _cached_stream(path: str, token: str) -> bytes | None:
    """Production reads are cached on disk: the artifacts are megabytes each and
    a re-run should not re-spend the egress."""
    target = CACHE / path.replace("/", "__")
    if target.is_file():
        return target.read_bytes()
    try:
        raw = _stream(path, token)
    except Exception:  # noqa: BLE001
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return raw


def _accumulate_outcomes(text: str, pitcher_rows, pitcher_runs, batter_runs, dates, *, is_pitcher):
    for row in csv.DictReader(io.StringIO(text)):
        date, game_pk = row.get("date"), row.get("game_pk")
        if not (date and game_pk):
            continue
        runs = _to_float(row.get("r"))
        if is_pitcher:
            player_id = row.get("player_id")
            if not player_id:
                continue
            dates.add(date)
            pitcher_rows[(date, game_pk, player_id)] = row
            if runs is not None:
                pitcher_runs[(date, game_pk)] += runs
        elif runs is not None:
            batter_runs[(date, game_pk)] += runs


def load_outcomes(source: str, token: str | None) -> tuple[dict, dict, dict, set]:
    """Returns (pitcher_rows, pitcher_runs_by_game, batter_runs_by_game, dates)."""
    pitcher_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    pitcher_runs: dict[tuple[str, str], float] = defaultdict(float)
    batter_runs: dict[tuple[str, str], float] = defaultdict(float)
    dates: set[str] = set()

    for name, is_pitcher in (("mlb_pitcher_game_log.csv", True), ("mlb_batter_game_log.csv", False)):
        text = None
        if source == "local":
            path = MLB_DATA / "processed" / name
            if path.exists():
                text = path.read_text(encoding="utf-8")
        else:
            raw = _cached_stream(f"{ARTIFACT_PREFIX}/processed/{name}", token or "")
            if raw is not None:
                text = raw.decode("utf-8", errors="replace")
        if text:
            _accumulate_outcomes(
                text, pitcher_rows, pitcher_runs, batter_runs, dates, is_pitcher=is_pitcher
            )

    return pitcher_rows, dict(pitcher_runs), dict(batter_runs), dates


def local_artifact_paths() -> dict[str, Path]:
    by_date: dict[str, Path] = {}
    for family in ("daily", "daily_pitcher_props"):
        base = MLB_DATA / family
        if not base.exists():
            continue
        for path in sorted(base.glob("daily_summary_*.json")):
            date = _date_from(path.name)
            if date:
                by_date.setdefault(date, path)
    return by_date


def load_artifact(source: str, date: str, local_paths: dict[str, Path], token: str | None):
    if source == "local":
        path = local_paths.get(date)
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    raw = _cached_stream(
        f"{ARTIFACT_PREFIX}/daily/daily_summary_{date.replace('-', '_')}.json", token or ""
    )
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def build_observations(
    min_sample: int, source: str
) -> tuple[list[ProjectionObservation], dict[str, Any]]:
    token = _admin_token() if source == "production" else None
    pitcher_rows, pitcher_runs, batter_runs, outcome_dates = load_outcomes(source, token)
    local_paths = local_artifact_paths()

    if source == "local":
        artifact_dates = set(local_paths)
    else:
        # No cheap listing endpoint; the outcome dates bound the work, and a
        # date whose artifact 404s is COUNTED rather than silently skipped.
        artifact_dates = set(outcome_dates)

    counters: dict[str, Any] = {
        "source": source,
        "artifact_loaded": 0,
        "artifact_unavailable": 0,
        "artifact_dates": len(artifact_dates),
        "outcome_dates": len(outcome_dates),
        "intersection_dates": len(artifact_dates & outcome_dates),
        "games_seen": 0,
        "pitcher_projections_seen": 0,
        "pitcher_joined": 0,
        "pitcher_no_outcome_row": 0,
        "pitcher_not_a_starter_in_log": 0,
        "total_runs_joined": 0,
        "total_runs_dropped_source_disagreement": 0,
        "total_runs_no_outcome": 0,
        "markets_unjoinable": PITCHER_MARKETS_UNJOINABLE,
    }

    observations: list[ProjectionObservation] = []
    usable = sorted(artifact_dates & outcome_dates)

    for date in usable:
        payload = load_artifact(source, date, local_paths, token)
        if payload is None:
            counters["artifact_unavailable"] += 1
            continue
        counters["artifact_loaded"] += 1
        for game in payload.get("outputs") or []:
            counters["games_seen"] += 1
            game_pk = str(game.get("game_pk") or "")
            if not game_pk:
                continue

            for player_id, props in (game.get("pitcher_props") or {}).items():
                if not isinstance(props, dict):
                    continue
                outcome_row = pitcher_rows.get((date, game_pk, str(player_id)))
                for dist_key, (market, column) in PITCHER_MARKETS.items():
                    distribution = props.get(dist_key)
                    if not isinstance(distribution, dict) or not distribution:
                        continue
                    counters["pitcher_projections_seen"] += 1
                    if outcome_row is None:
                        counters["pitcher_no_outcome_row"] += 1
                        continue
                    actual = _to_float(outcome_row.get(column))
                    if actual is None:
                        continue
                    counters["pitcher_joined"] += 1
                    observations.append(
                        ProjectionObservation(
                            sport="mlb",
                            market=f"pitcher_{market}",
                            segment="full",
                            actual=actual,
                            distribution=distribution,
                            subject_id=str(player_id),
                            date=date,
                        )
                    )
                if outcome_row is not None and outcome_row.get("is_starter") not in ("1", 1, "True"):
                    counters["pitcher_not_a_starter_in_log"] += 1

            full = game.get("full") or {}
            total_dist = full.get("total_runs_dist")
            if isinstance(total_dist, dict) and total_dist:
                from_pitchers = pitcher_runs.get((date, game_pk))
                from_batters = batter_runs.get((date, game_pk))
                if from_pitchers is None or from_batters is None:
                    counters["total_runs_no_outcome"] += 1
                elif abs(from_pitchers - from_batters) > 1e-6:
                    # Two independent derivations disagree -> refuse the row.
                    counters["total_runs_dropped_source_disagreement"] += 1
                else:
                    counters["total_runs_joined"] += 1
                    observations.append(
                        ProjectionObservation(
                            sport="mlb",
                            market="game_total_runs",
                            segment="full",
                            actual=from_pitchers,
                            distribution=total_dist,
                            subject_id=game_pk,
                            date=date,
                        )
                    )

    counters["date_span_scored"] = [usable[0], usable[-1]] if usable else None
    return observations, counters


def run_one(source: str, min_sample: int) -> dict[str, Any]:
    observations, counters = build_observations(min_sample, source)

    label = {
        "local": "LOCAL MIRROR -- lossy, a lower bound, NOT what production computed",
        "production": "PRODUCTION via /api/ops/artifacts/stream -- citable",
    }[source]
    print("\n" + "=" * 104)
    print(f"PHASE 7 -- MLB PROJECTION SCORING  [{label}]")
    print("=" * 104)
    print("\nCOVERAGE FIRST (the denominator, per CLAUDE.md's intersection trap)")
    print(f"  artifact dates       {counters['artifact_dates']}")
    print(f"  outcome dates        {counters['outcome_dates']}")
    print(f"  INTERSECTION         {counters['intersection_dates']}   span={counters['date_span_scored']}")
    print(f"  artifacts loaded     {counters['artifact_loaded']}   unavailable={counters['artifact_unavailable']}")
    print(f"  games seen           {counters['games_seen']}")
    print("\nJOIN COUNTERS (what was dropped is reported, not only what was kept)")
    for key in (
        "pitcher_projections_seen",
        "pitcher_joined",
        "pitcher_no_outcome_row",
        "total_runs_joined",
        "total_runs_dropped_source_disagreement",
        "total_runs_no_outcome",
    ):
        print(f"  {key:42s} {counters[key]}")
    for key, reason in counters["markets_unjoinable"].items():
        print(f"  UNJOINABLE {key:32s} {reason}")

    result = score_projections(observations, min_sample=min_sample)

    print("\nSCORED CELLS")
    header = (
        f"  {'market':26s} {'n':>6s} {'CRPS':>8s} {'CRPSn':>8s} {'gap':>7s} "
        f"{'bias':>8s} {'MAE':>7s} {'base':>7s} {'beat':>5s} {'disp':>6s} verdict"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for cell in result["cells"]:
        def fmt(value, width=8, places=3):
            return f"{value:>{width}.{places}f}" if isinstance(value, (int, float)) else f"{'-':>{width}}"

        beat = cell["beats_constant_baseline"]
        beat_text = "-" if beat is None else ("YES" if beat else "no")
        print(
            f"  {cell['market']:26s} {cell['sample_size']:6d} "
            f"{fmt(cell['crps_empirical'])} {fmt(cell['crps_normal_approx'])} "
            f"{fmt(cell['normal_minus_empirical'], 7)} "
            f"{fmt(cell['mean_signed_error'])} {fmt(cell['mean_absolute_error'], 7)} "
            f"{fmt(cell['baseline_constant_mae'], 7)} {beat_text:>5s} "
            f"{fmt(cell['dispersion_ratio'], 6, 2)} "
            f"{cell['verdict']}"
            + (f" / {cell['dispersion_verdict']}" if cell["dispersion_verdict"] else "")
        )

    print("\n  CRPS  = empirical, scored against the sim's own 1000-draw PMF (the evidence)")
    print("  CRPSn = the same forecast summarised as a Normal (a DIAGNOSTIC, not the score)")
    print("  gap   = CRPSn - CRPS. Large => the predictive distribution is materially non-Normal.")
    print(f"  disp  = mean|error|/sigma; a calibrated sigma sits near {result['cells'][0]['expected_dispersion_ratio'] if result['cells'] else 0.7979}")
    print(f"\nCOUNTERS {json.dumps(result['counters'])}")
    return {"source": source, "join_counters": counters, **result}


def compare(runs: list[dict[str, Any]]) -> None:
    """Does the finding REPRODUCE across two near-disjoint time windows?

    This is the whole value of running both: a bias that shows up in
    2026-05/07 and again in 2026-07/08, on samples that barely share a date,
    is not an artefact of one stretch of baseball.
    """
    if len(runs) < 2:
        return
    print("\n" + "=" * 104)
    print("REPRODUCIBILITY ACROSS TWO NEAR-DISJOINT WINDOWS")
    print("=" * 104)
    by_source = {
        run["source"]: {c["market"]: c for c in run["cells"] if c["verdict"] == "measured"}
        for run in runs
    }
    spans = {run["source"]: run["join_counters"]["date_span_scored"] for run in runs}
    for source, span in spans.items():
        print(f"  {source:11s} span={span}")
    markets = sorted(set().union(*(set(cells) for cells in by_source.values())))
    print(f"\n  {'market':26s} {'bias(local)':>12s} {'bias(prod)':>12s} {'same sign?':>11s} "
          f"{'disp(local)':>12s} {'disp(prod)':>11s}")
    print("  " + "-" * 90)
    for market in markets:
        local = by_source.get("local", {}).get(market)
        prod = by_source.get("production", {}).get(market)
        lb = local["mean_signed_error"] if local else None
        pb = prod["mean_signed_error"] if prod else None
        agree = "-"
        if isinstance(lb, (int, float)) and isinstance(pb, (int, float)):
            agree = "YES" if (lb < 0) == (pb < 0) else "** NO **"

        def cell(value, width=12):
            return f"{value:>{width}.3f}" if isinstance(value, (int, float)) else f"{'-':>{width}}"

        print(f"  {market:26s} {cell(lb)} {cell(pb)} {agree:>11s} "
              f"{cell(local['dispersion_ratio'] if local else None)} "
              f"{cell(prod['dispersion_ratio'] if prod else None, 11)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE)
    parser.add_argument("--source", choices=("local", "production", "both"), default="local")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    sources = ["local", "production"] if args.source == "both" else [args.source]
    runs = [run_one(source, args.min_sample) for source in sources]
    compare(runs)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
