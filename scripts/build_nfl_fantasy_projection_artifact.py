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



def _clear_input_caches() -> None:
    """Drop the memoised views of inputs that `--prepare` may have just changed."""
    from syndicate.features.nfl import fantasy_players, fantasy_schedule, fantasy_usage

    for target in (
        fantasy_usage.load_season_usage,
        fantasy_usage.load_season_game_lines,
        fantasy_usage._load_usage_payload,
        fantasy_players.load_fantasy_players,
        fantasy_players.latest_depth_chart,
        fantasy_schedule.load_schedule_rows,
        fantasy_schedule.market_team_ratings,
    ):
        try:
            target.cache_clear()
        except AttributeError:
            pass


def _run(label: str, args: list[str]) -> bool:
    """Run one preparation step as a SUBPROCESS, and say what happened.

    Subprocess rather than an import, so each step's memory returns to the OS
    when it exits. The projection build alone peaks at ~725 MB (measured
    2026-08-21); stacking the usage builds into the same process on a shared
    4 GB worker is how `#241` happened.
    """
    import subprocess

    print(f"[fantasy_artifact] PREPARE_STEP {label} launching", flush=True)
    try:
        completed = subprocess.run(args, check=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[fantasy_artifact] PREPARE_STEP {label} FAILED {type(exc).__name__}: {exc}", flush=True)
        return False
    print(f"[fantasy_artifact] PREPARE_STEP {label} rc={completed.returncode}", flush=True)
    return completed.returncode == 0


def _prepare_inputs(season: int, history: tuple) -> None:
    """Fetch the raw roster/depth chart, and build any usage artifact missing.

    NOTHING ELSE ON THE WORKER PRODUCES THESE, and one near-miss is worth
    naming so this is not "de-duplicated" later. `fetch_nfl_pbp.py` brings down
    the play-by-play. `_launch_autorun_nfl_roster_snapshot` sounds like it
    covers the roster and does NOT: it writes a PROCESSED
    `source_artifacts/data/processed/rosters/roster_{season}_snapshot.csv`,
    while this engine reads the RAW nflverse releases under
    `tracking/nflverse/roster/` and `tracking/nflverse/depth_charts/`.
    Different files, different shape, and only one of them has `pos_rank`.

    The roster and depth chart are re-fetched every run because they change
    daily in camp and in-season; usage is built only when its artifact is
    absent, because it derives from play-by-play that changes weekly.
    """
    from syndicate.features.nfl.fantasy_usage import usage_artifact_path

    scripts = Path(__file__).resolve().parent

    _run(
        "roster_depth_charts_schedule",
        [
            sys.executable,
            str(scripts / "fetch_nfl_rosters_depth_charts.py"),
            "--seasons",
            str(season),
            "--kinds",
            "roster,depth_charts,schedule",
            "--force",
        ],
    )

    missing = [value for value in history if not usage_artifact_path(value).is_file()]
    if missing:
        _run(
            "usage",
            [
                sys.executable,
                str(scripts / "build_nfl_fantasy_usage.py"),
                "--seasons",
                ",".join(str(value) for value in missing),
            ],
        )
    else:
        print("[fantasy_artifact] PREPARE_STEP usage skipped -- all artifacts present", flush=True)



#: A real ESPN-PPR season leader lands near 350-400; this engine's own top row
#: is 326. The ceiling is 480, not 600, and the difference matters: the
#: degenerate artifact that reached production had its top player at 525.5,
#: which a 600 ceiling waves through. A band wide enough to admit the failure
#: it was written for is not a check. 480 still leaves ~20% of headroom over a
#: genuinely exceptional projected season.
PLAUSIBLE_TOP_SEASON_POINTS = (150.0, 480.0)


def degenerate_reasons(season_rows, weekly, weeks) -> list[str]:
    """Why this artifact must NOT be published, or an empty list.

    CHECKS THE OUTPUT, NOT THE INPUTS, and that distinction is the whole point.
    The pre-flight input check verifies the roster and the usage documents --
    and the schedule was simply not on its list, so the first worker run sailed
    through it and published an artifact with `weeks: []`, 318 KB against a
    normal 2.83 MB, and Christian McCaffrey at 525 PPR points against a correct
    ~270. Nothing raised, it overwrote a correct artifact, and the board it
    produced looked entirely plausible.

    An input checklist can only ever cover the inputs someone thought of. The
    output has to be right regardless of which input was missing.
    """
    problems: list[str] = []
    if weeks and not weekly:
        problems.append(
            f"{len(weeks)} weeks requested but 0 produced -- no schedule, so no game environments"
        )
    if not season_rows:
        problems.append("no season projections produced")
        return problems
    top = max(row.fantasy_points for row in season_rows)
    low, high = PLAUSIBLE_TOP_SEASON_POINTS
    if not low <= top <= high:
        problems.append(f"top season projection {top:.1f} is outside the plausible {low:.0f}-{high:.0f} band")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--weeks", default="1-18", help="e.g. 1-18, or 1,2,3, or none")
    parser.add_argument("--publish", action="store_true", help="push to the web service")
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="fetch the roster/depth chart and build any missing usage artifact first",
    )
    # `publish_hot_artifact` defaults to 10s, which is tuned for the small
    # per-date JSON most callers push. This artifact is ~2.8 MB and a 10s
    # ceiling drops the TLS connection mid-upload ("EOF occurred in violation
    # of protocol"), which surfaces only as `publish -> False`.
    parser.add_argument("--publish-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    season = args.season
    history = _history_seasons(season, len(DEFAULT_CONFIG.season_recency_weights))

    if args.prepare:
        _prepare_inputs(season, history)
        # The loaders memoise per season, and `--prepare` has just changed what
        # is on disk underneath them. Without this the run would build from the
        # state observed BEFORE preparing -- which on a first run is nothing.
        _clear_input_caches()
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
    # PASSED, not merely loaded. The first version of this bound `news` and
    # then called `project_season` without it, so the graded injury-availability
    # multipliers were computed, published as part of `basis`, and applied to
    # nothing -- `model_engine_standard.md` s4.3's inert feature, in the one
    # place where nothing would ever have raised. `use_injury_availability`
    # decides whether they are USED; passing them decides whether they are
    # REACHABLE, and those are different questions.
    news = load_news_adjustments(season)
    season_rows = project_season(season, ESPN_PPR, DEFAULT_CONFIG, news)
    print(f"season: {len(season_rows)} projections in {time.monotonic() - started:.1f}s", flush=True)

    weekly: dict[int, list] = {}
    for week in weeks:
        rows = project_season(season, ESPN_PPR, DEFAULT_CONFIG, news, week=week)
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

    problems = degenerate_reasons(season_rows, weekly, weeks)
    if problems:
        print("REFUSING TO PUBLISH -- the artifact is degenerate:", flush=True)
        for entry in problems:
            print(f"  - {entry}", flush=True)
        print(f"  the file at {target} was still written, for inspection.", flush=True)
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
