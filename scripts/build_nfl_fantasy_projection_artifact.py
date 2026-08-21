"""Build and publish the NFL fantasy projection artifact. WORKER JOB.

Runs the whole engine once -- full season plus all 18 weeks -- and writes one
document the web service can serve directly. Then pushes it to the web dyno via
``artifact_publisher.publish_hot_artifact``, because Render disks are
per-service and the web dyno has none of the nflverse inputs.

This must NEVER run on the web service. It reads ~61 MB of play-by-play,
rosters and depth charts and takes a few seconds; that is precisely the heavy
computation the worker-split rule keeps out of a request handler.

    python scripts/build_nfl_fantasy_projection_artifact.py --season 2026
    python scripts/build_nfl_fantasy_projection_artifact.py --season 2026 --publish

Prerequisite: ``scripts/build_nfl_fantasy_usage.py`` must have run for the
history seasons, and ``scripts/fetch_nfl_rosters_depth_charts.py`` for the
roster and depth chart. Both are checked here and named in the failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy import build_basis  # noqa: E402
from syndicate.features.nfl.fantasy_artifact import artifact_output_path  # noqa: E402
from syndicate.features.nfl.fantasy_artifact import build_artifact_payload  # noqa: E402
from syndicate.features.nfl.fantasy_news import load_news_adjustments  # noqa: E402
from syndicate.features.nfl.fantasy_players import load_fantasy_players  # noqa: E402
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG  # noqa: E402
from syndicate.features.nfl.fantasy_projection import _history_seasons  # noqa: E402
from syndicate.features.nfl.fantasy_projection import project_season  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import ESPN_PPR  # noqa: E402
from syndicate.features.nfl.fantasy_usage import usage_substrate  # noqa: E402

#: `artifact_publisher._PUBLISH_MAX_BYTES`. Checked here so an oversized build
#: fails on the worker with a clear message instead of being silently refused at
#: publish time -- `{'too_large': N}` in a log is exactly the kind of counter
#: this repo has misread before.
PUBLISH_MAX_BYTES = 12 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--weeks", default="1-18", help="e.g. 1-18, or 1,2,3, or none")
    parser.add_argument("--publish", action="store_true", help="push to the web service")
    # `publish_hot_artifact` defaults to 10s, which is tuned for the small
    # per-date JSON most callers push. This artifact is ~2.8 MB and a 10s
    # ceiling drops the TLS connection mid-upload ("EOF occurred in violation
    # of protocol"), which surfaces only as `publish -> False`.
    parser.add_argument("--publish-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    season = args.season
    history = _history_seasons(season, len(DEFAULT_CONFIG.season_recency_weights))

    # ---- inputs must be present, and say WHICH one is not
    missing: list[str] = []
    if not load_fantasy_players(season):
        missing.append(
            f"roster/depth chart for {season} "
            "(scripts/fetch_nfl_rosters_depth_charts.py --seasons {season})"
        )
    for value in history:
        if not usage_substrate(value)["exists"]:
            from syndicate.features.nfl.fantasy_usage import usage_artifact_path

            if not usage_artifact_path(value).is_file():
                missing.append(
                    f"usage for {value} (scripts/build_nfl_fantasy_usage.py --seasons {value})"
                )
    if missing:
        print("CANNOT BUILD -- missing inputs on this substrate:", flush=True)
        for entry in missing:
            print(f"  - {entry}", flush=True)
        return 1

    weeks: list[int] = []
    raw = (args.weeks or "").strip().lower()
    if raw and raw != "none":
        if "-" in raw:
            low, high = raw.split("-", 1)
            weeks = list(range(int(low), int(high) + 1))
        else:
            weeks = [int(value) for value in raw.split(",") if value.strip()]

    started = time.monotonic()
    # Scoring profile is irrelevant to the STAT LINES this artifact stores --
    # see fantasy_artifact's module docstring. PPR is passed only because the
    # engine's signature requires one; nothing scoring-dependent is persisted.
    news = load_news_adjustments(season)
    season_rows = project_season(season, ESPN_PPR, DEFAULT_CONFIG)
    print(f"season: {len(season_rows)} projections in {time.monotonic() - started:.1f}s", flush=True)

    weekly: dict[int, list] = {}
    for week in weeks:
        rows = project_season(season, ESPN_PPR, DEFAULT_CONFIG, week=week)
        if rows:
            weekly[week] = rows
    if weeks:
        print(f"weeks: {len(weekly)} built ({sum(len(v) for v in weekly.values())} rows)", flush=True)

    payload = build_artifact_payload(
        season,
        season_rows,
        weekly,
        build_basis(season, DEFAULT_CONFIG, news, applied_news=False),
    )
    target = artifact_output_path(season)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size = target.stat().st_size
    elapsed = time.monotonic() - started

    print(
        f"wrote {target} -- {size / 1_000_000:.2f} MB, "
        f"{len(payload['players'])} players, {len(weekly)} weeks, {elapsed:.1f}s",
        flush=True,
    )
    if size > PUBLISH_MAX_BYTES:
        print(
            f"REFUSING TO PUBLISH: {size} bytes exceeds the publisher's "
            f"{PUBLISH_MAX_BYTES} ceiling. Drop weeks or trim columns.",
            flush=True,
        )
        return 1

    published = None
    if args.publish:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(target, timeout_seconds=args.publish_timeout)
        print(f"publish -> {published}", flush=True)
        if not published:
            print(
                "  publish returned False. It never raises by design, so check the "
                "worker log for SKIP_NOT_ALLOWLISTED / too_large / budget lines.",
                flush=True,
            )

    if args.json:
        print(
            json.dumps(
                {
                    "season": season,
                    "path": str(target),
                    "bytes": size,
                    "players": len(payload["players"]),
                    "weeks": sorted(weekly),
                    "published": published,
                },
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
