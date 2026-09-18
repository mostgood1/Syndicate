"""Build the NCAAF player-prop projection artifact for one (season, week) --
and, with `--backtest`, score the same method against real outcomes.

    # what the player-stats refresh chains (target week, publish to web)
    python scripts/build_ncaaf_prop_projections.py

    # an operator building one week by hand, without publishing
    python scripts/build_ncaaf_prop_projections.py --season 2026 --week 4 --no-publish

    # score the method week by week over a season already in the snapshot
    python scripts/build_ncaaf_prop_projections.py --season 2025 --backtest --min-week 2 --max-week 16

The model lives in `syndicate/features/ncaaf/prop_projections.py`; this is only
its entry point. The build runs on refresh-worker (normally chained at the end
of `player_stats_refresh.refresh_player_game_stats`) and publishes
`ncaaf_source/data/ncaaf_prop_projections_{season}_wk{week}.json` to web. Web
never runs it.

WHAT THE BACKTEST CAN AND CANNOT SAY. For each graded week w the artifact is
rebuilt in memory from games with week < w only, and each projected (player,
market) is compared with his real week-w line. That is out-of-sample accuracy
against OUTCOMES, with the player's raw season-to-date mean as the baseline to
beat. It is NOT a market test: a market test needs the captured prop line for
the same player and week, and when `oddsapi_player_props_{season}_wk{w}.csv` is
on this disk the report adds line MAE and over-rate calibration for exactly
those rows. When it is not, the report says `lines: 0` and nothing about skill
against a price may be read from it.

Exit codes: 0 written (or backtest done), 1 nothing written (empty build or no
snapshot), 2 could not resolve a season/week.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import prop_projections as pp  # noqa: E402


def _resolve_season(explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    from syndicate.features.ncaaf.sources import default_season

    return int(default_season())


def _resolve_week(explicit: int | None, season: int) -> int | None:
    if explicit is not None:
        return int(explicit)
    from syndicate.features.ncaaf.sources import ncaaf_target_week

    week = ncaaf_target_week(season)
    return int(week) if week else None


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _read_lines(season: int, week: int) -> dict[tuple[str, str], dict[str, Any]]:
    """(name_key, stat) -> {line (median across books), teams} from the captured
    props CSV for the week, or {} when it is not on this disk."""
    from syndicate.features.ncaaf.sources import ncaaf_player_props_path

    path = ncaaf_player_props_path(season, week)
    if not path.is_file():
        return {}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("is_ladder") or "").strip().lower() in {"true", "1"}:
                continue
            stat = pp.MARKET_LABEL_TO_STAT.get(str(row.get("market") or "").strip().casefold())
            try:
                line = float(row.get("line") or "")
            except ValueError:
                continue
            if stat is None:
                continue
            for key in pp.name_keys(row.get("player")):
                cell = grouped.setdefault((key, stat), {"lines": [], "teams": set()})
                cell["lines"].append(line)
                cell["teams"].update(t for t in (row.get("home_team"), row.get("away_team")) if t)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, cell in grouped.items():
        out[key] = {"line": _median(cell["lines"]), "teams": cell["teams"]}
    return out


def backtest(season: int, *, snapshot: Path, min_week: int, max_week: int) -> dict[str, Any]:
    players_by_season = pp.read_snapshot_players(snapshot, (season, season - 1))
    current = players_by_season.get(season, {})
    previous = players_by_season.get(season - 1, {})
    stats: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    calib: dict[str, list[tuple[float, int]]] = defaultdict(list)
    line_stats: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    line_calib: dict[str, list[tuple[float, int]]] = defaultdict(list)
    weeks_scored: list[int] = []
    weeks_with_lines: list[int] = []
    for week in range(int(min_week), int(max_week) + 1):
        actual: dict[str, dict[str, float]] = {}
        for player_id, player in current.items():
            for game in player.games:
                if game.week == week:
                    actual[player_id] = game.stats
        if not actual:
            continue
        payload = pp.payload_from_players(season=season, week=week, current=current, previous=previous,
                                          snapshot_name=snapshot.name)
        lines = _read_lines(season, week)
        if lines:
            weeks_with_lines.append(week)
        weeks_scored.append(week)
        for player in payload["players"]:
            outcome = actual.get(player["player_id"])
            if outcome is None:
                continue  # did not appear in week w: no line to score (see KNOWN BIAS)
            for market, entry in player["markets"].items():
                y = outcome[market]
                cell = stats[market]
                cell["n"] += 1
                cell["abs_model"] += abs(entry["mean"] - y)
                cell["abs_player_mean"] += abs(entry["season_mean"] - y)
                cell["sq_model"] += (entry["mean"] - y) ** 2
                cell["sq_player_mean"] += (entry["season_mean"] - y) ** 2
                # PROXY LINE for calibration when no price exists: the player's
                # raw season mean, snapped to the half point below it. Tests the
                # DISTRIBUTION, not skill against a market.
                proxy = math.floor(entry["season_mean"]) + 0.5
                p = pp.prob_over(entry, proxy)
                if p is not None:
                    calib[market].append((p, 1 if y > proxy else 0))
                found = None
                for key in pp.name_keys(player["name"]):
                    candidate = lines.get((key, market))
                    if candidate is not None:
                        found = candidate
                        break
                if found is None or found["line"] is None:
                    continue
                line = float(found["line"])
                lcell = line_stats[market]
                lcell["n"] += 1
                lcell["abs_model"] += abs(entry["mean"] - y)
                lcell["abs_line"] += abs(line - y)
                lcell["abs_player_mean"] += abs(entry["season_mean"] - y)
                p_line = pp.prob_over(entry, line)
                if p_line is not None:
                    line_calib[market].append((p_line, 1 if y > line else 0))

    def _bins(pairs: list[tuple[float, int]]) -> list[dict[str, Any]]:
        edges = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0001]
        out = []
        for lo, hi in zip(edges, edges[1:]):
            chunk = [(p, y) for p, y in pairs if lo <= p < hi]
            if chunk:
                out.append({"bin": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(chunk),
                            "mean_p": round(sum(p for p, _ in chunk) / len(chunk), 3),
                            "observed": round(sum(y for _, y in chunk) / len(chunk), 3)})
        return out

    def _brier(pairs: list[tuple[float, int]]) -> float | None:
        return round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4) if pairs else None

    report: dict[str, Any] = {
        "season": season,
        "snapshot": str(snapshot),
        "weeks_scored": weeks_scored,
        "prior_season_in_snapshot": bool(previous),
        "outcomes": {},
        "lines": {"weeks_with_lines": weeks_with_lines},
    }
    for market, cell in sorted(stats.items()):
        n = cell["n"]
        pairs = calib[market]
        report["outcomes"][market] = {
            "n": int(n),
            "mae_model": round(cell["abs_model"] / n, 3),
            "mae_player_mean": round(cell["abs_player_mean"] / n, 3),
            "rmse_model": round(math.sqrt(cell["sq_model"] / n), 3),
            "rmse_player_mean": round(math.sqrt(cell["sq_player_mean"] / n), 3),
            "proxy_line_brier": _brier(pairs),
            "proxy_line_calibration": _bins(pairs),
        }
    for market, cell in sorted(line_stats.items()):
        n = cell["n"]
        pairs = line_calib[market]
        report["lines"][market] = {
            "n": int(n),
            "mae_model": round(cell["abs_model"] / n, 3),
            "mae_line": round(cell["abs_line"] / n, 3),
            "mae_player_mean": round(cell["abs_player_mean"] / n, 3),
            "over_rate_brier": _brier(pairs),
            "over_rate_calibration": _bins(pairs),
        }
    return report


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=None, help="Season (default: NCAAF active season).")
    parser.add_argument("--week", type=int, default=None, help="Week to build (default: sources.ncaaf_target_week).")
    parser.add_argument("--snapshot", type=Path, default=None, help="Player-game-stats snapshot CSV override.")
    parser.add_argument("--output", type=Path, default=None, help="Artifact path override.")
    parser.add_argument("--no-publish", action="store_true", help="Write locally; do not push to web.")
    parser.add_argument("--backtest", action="store_true", help="Score the method week by week instead of building.")
    parser.add_argument("--min-week", type=int, default=2)
    parser.add_argument("--max-week", type=int, default=16)
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    args = parser.parse_args(argv)

    from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

    snapshot = args.snapshot or player_game_stats_snapshot_path()
    try:
        season = _resolve_season(args.season)
    except Exception as exc:  # noqa: BLE001
        print(f"[ncaaf_prop_projections] ERROR season_unresolved {type(exc).__name__}: {exc}", flush=True)
        return 2

    if args.backtest:
        if not snapshot.is_file():
            print(f"[ncaaf_prop_projections] ERROR snapshot_missing {snapshot}", flush=True)
            return 1
        report = backtest(season, snapshot=snapshot, min_week=args.min_week, max_week=args.max_week)
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        return 0

    week = _resolve_week(args.week, season)
    if not week:
        print(f"[ncaaf_prop_projections] NOOP no_target_week season={season}", flush=True)
        return 2
    result = pp.build_prop_projections(season=season, week=week, snapshot_path=snapshot,
                                       output_path=args.output, publish=not args.no_publish)
    if args.json:
        print(json.dumps({k: v for k, v in result.__dict__.items() if k != "payload"}, default=str, indent=2), flush=True)
    else:
        print(result.summary_line(), flush=True)
    return 0 if result.written else 1


if __name__ == "__main__":
    raise SystemExit(main())
