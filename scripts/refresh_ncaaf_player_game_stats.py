"""Keep the NCAAF player-game-stats snapshot current for the active season.

`scripts/build_ncaaf_player_game_stats_snapshot.py` builds ONE week of ONE
season on demand. This is the recurring job around it: resolve the season and
the week window, refresh each week, and never damage what is already there.

    # what the autorun runs (gated -- exits 0 and does nothing unless armed)
    python scripts/refresh_ncaaf_player_game_stats.py

    # an operator catching the artifact up by hand
    python scripts/refresh_ncaaf_player_game_stats.py --force --weeks 1,2

GATED BY DEFAULT. Without `NCAAF_PLAYER_STATS_ENABLE_REFRESH_WORKER_AUTORUN`
set to a true value this prints a skip line and exits 0 without making a
single CFBD call -- the same absent-means-off contract every sibling autorun
in `scripts/run_refresh_worker.py` follows. `--force` is the manual override
and is what an operator or a backfill uses; it does not change the flag.

Exit codes: 0 success (including a legitimately gated or no-op run), 1
validation issues in the fetched rows, 2 the job could not run at all (no
CFBD key, no resolvable week window, history loss).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.cfbd import CfbdClient  # noqa: E402
from syndicate.features.ncaaf.player_stats_refresh import (  # noqa: E402
    AUTORUN_ENV_VAR,
    DEFAULT_LOOKBACK_WEEKS,
    NcaafPlayerStatsHistoryLoss,
    player_stats_autorun_enabled,
    player_stats_refresh_interval_seconds,
    refresh_player_game_stats,
    weeks_to_refresh,
)
from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path  # noqa: E402


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _parse_weeks(text: str) -> tuple[int, ...]:
    weeks: list[int] = []
    for chunk in str(text or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        weeks.append(int(chunk))
    return tuple(weeks)


def _resolve_season(explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    from syndicate.features.ncaaf.sources import default_season

    return int(default_season())


def _resolve_weeks(args: argparse.Namespace, season: int) -> tuple[int, ...]:
    if args.weeks:
        return _parse_weeks(args.weeks)
    target_week = args.target_week
    if target_week is None:
        from syndicate.features.ncaaf.sources import ncaaf_target_week

        target_week = ncaaf_target_week(season)
    return weeks_to_refresh(target_week, lookback_weeks=args.lookback_weeks)


def _emit(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
        return
    print(f"[ncaaf_player_stats] {payload.get('status')} {payload}", flush=True)


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=None, help="Season to refresh (default: NCAAF active season).")
    parser.add_argument(
        "--weeks",
        type=str,
        default="",
        help="Explicit comma-separated weeks, e.g. '1,2'. Overrides the target-week window.",
    )
    parser.add_argument(
        "--target-week",
        type=int,
        default=None,
        help="Newest week of the refresh window (default: sources.ncaaf_target_week).",
    )
    parser.add_argument(
        "--lookback-weeks",
        type=int,
        default=DEFAULT_LOOKBACK_WEEKS,
        help=f"How many weeks back from the target week to re-fetch (default {DEFAULT_LOOKBACK_WEEKS}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Run even though {AUTORUN_ENV_VAR} is not set -- the manual/backfill override.",
    )
    parser.add_argument("--output-path", type=Path, default=None, help="Snapshot CSV path override.")
    parser.add_argument("--season-type", type=str, default="regular", help="CFBD seasonType (regular/postseason).")
    parser.add_argument("--source-snapshot-date", type=str, default=None, help="Provenance date stamped on new rows.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com", help="CFBD base URL.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Emit the run report as JSON.")
    args = parser.parse_args(argv)

    output_path = args.output_path or player_game_stats_snapshot_path()

    if not args.force and not player_stats_autorun_enabled():
        _emit(
            {
                "status": "gated",
                "reason": "disabled",
                "env": AUTORUN_ENV_VAR,
                "detail": f"{AUTORUN_ENV_VAR} is not true -- set it (and deploy) to arm this, or pass --force.",
                "interval_seconds": player_stats_refresh_interval_seconds(),
            },
            as_json=args.json,
        )
        return 0

    try:
        season = _resolve_season(args.season)
    except Exception as exc:  # noqa: BLE001 -- reported, never a traceback in a scheduled job
        _emit({"status": "error", "reason": "season_unresolved", "error": f"{type(exc).__name__}: {exc}"}, as_json=args.json)
        return 2

    try:
        weeks = _resolve_weeks(args, season)
    except Exception as exc:  # noqa: BLE001
        _emit({"status": "error", "reason": "weeks_unresolved", "error": f"{type(exc).__name__}: {exc}"}, as_json=args.json)
        return 2

    if not weeks:
        # No resolvable week window is a real, benign state (season not
        # loaded yet, or every game complete). It is NOT a reason to fetch a
        # guessed week, and it is NOT a failure.
        _emit(
            {"status": "noop", "reason": "no_week_window", "season": season, "output_path": str(output_path)},
            as_json=args.json,
        )
        return 0

    try:
        client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        _emit(
            {
                "status": "error",
                "reason": "cfbd_key_missing",
                "error": f"{type(exc).__name__}: {exc}",
                "detail": "CFBD_API_KEY must be present in this service's environment. No scheduling change fixes this.",
            },
            as_json=args.json,
        )
        return 2

    try:
        report = refresh_player_game_stats(
            client=client,
            season=season,
            weeks=weeks,
            output_path=output_path,
            season_type=args.season_type,
            source_snapshot_date=args.source_snapshot_date,
        )
    except NcaafPlayerStatsHistoryLoss as exc:
        _emit({"status": "error", "reason": "history_loss", "error": str(exc)}, as_json=args.json)
        return 2

    payload = report.as_dict()
    payload["status"] = "ok" if report.ok else "validation_issues"
    payload["requested_weeks"] = list(weeks)

    # PUBLISH TO WEB, or none of this reaches a reader.
    #
    # This job runs on refresh-worker and writes to THAT service's disk;
    # `_ncaaf_player_box_section` reads WEB's. Render disks are per-service, and
    # **there is no blanket sweep on refresh-worker** --
    # `sweep_changed_hot_artifacts`'s only production caller is `live_lens_loop`,
    # on another service. So the `HOT_ARTIFACT_PATTERNS` entry for this snapshot
    # PERMITS the transfer and nothing else; without this call the allowlist
    # entry is inert and the card stays empty with every stage upstream of it
    # reporting success (`#208`, and the two watchers who burned ~35 minutes on
    # exactly that shape).
    #
    # UNCONDITIONAL ON A COMPLETED RUN, not gated on rows_written. A run where
    # every week is a legitimate no-op still has to converge web onto whatever
    # this disk holds -- otherwise a stale bootstrapped copy on web can never be
    # corrected once the weeks it needed have gone quiet. Cost of that choice,
    # stated rather than hidden: `_LAST_PUBLISHED_CHECKSUM` is per-PROCESS and
    # this is a fresh subprocess each run, so the de-dup never hits here and a
    # daily armed run re-uploads the whole file -- ~4.2 MB today, ~13 MB by the
    # end of the season. Once a day, against a `book_grid` that ships 12.7 MB
    # every cycle.
    #
    # Best-effort and never fatal: `publish_hot_artifact` returns False rather
    # than raising for every condition (unconfigured, not allowlisted, network),
    # and a transfer failure must not turn a good refresh into a non-zero exit.
    # Same shape `scripts/build_nfl_roster_snapshot.py` already uses.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        payload["artifact_published"] = bool(publish_hot_artifact(output_path, timeout_seconds=120))
    except Exception as exc:  # noqa: BLE001 - the transfer must never fail the refresh
        payload["artifact_published"] = False
        payload["artifact_publish_error"] = f"{type(exc).__name__}: {exc}"
    payload["artifact_published_path"] = str(output_path)

    _emit(payload, as_json=args.json)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
