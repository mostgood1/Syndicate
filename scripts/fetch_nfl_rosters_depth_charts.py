"""Fetch historical nflverse rosters and depth charts.

The fantasy engine needs BOTH for every season it fits or grades on, and
locally only the current season's were present. That absence was not visible
as an error -- it showed up as a calibration run where every candidate scored
``inf`` because ``load_fantasy_players(2024)`` returned an empty roster and the
projection therefore produced nothing to grade.

Same release host and URL shape as
``syndicate/features/football/ingestion/nflverse_ingestion.py``; this script
exists so the files land in the tracking tree the read path already resolves
(``tracking/nflverse/roster`` and ``tracking/nflverse/depth_charts``) rather
than in that module's private cache.

    python scripts/fetch_nfl_rosters_depth_charts.py --seasons 2022,2023,2024,2025
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.sources import nfl_artifact_output_root  # noqa: E402

NFLVERSE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"

#: The schedule lives in a different repo and is NOT season-scoped -- one
#: file carries every season. NOTHING ELSE IN THIS REPO WRITES IT, which is
#: why it was absent on the worker while several modules read it
#: (`game_context.py` records the same "count 0" finding independently).
NFLVERSE_GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

FEEDS: dict[str, tuple[str, str]] = {
    # local subdirectory -> (release tag, filename stem)
    "roster": ("rosters", "roster"),
    "depth_charts": ("depth_charts", "depth_charts"),
}

#: Not season-scoped and not a release asset, so it does not fit `FEEDS`.
SCHEDULE_TARGET = ("tracking/nflverse", "schedules_games.csv")


def fetch(kind: str, season: int, *, force: bool) -> tuple[str, Path, int]:
    release, stem = FEEDS[kind]
    target = nfl_artifact_output_root() / "tracking" / "nflverse" / kind / f"{stem}_{season}.csv"
    if target.is_file() and not force:
        return "kept", target, target.stat().st_size
    url = f"{NFLVERSE_BASE_URL}/{release}/{stem}_{season}.csv"
    request = urllib.request.Request(url, headers={"User-Agent": "syndicate-fantasy/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        return f"failed: {error}", target, 0
    if not payload:
        return "failed: empty response", target, 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return "fetched", target, len(payload)


def fetch_schedule(*, force: bool) -> tuple[str, Path, int]:
    """Fetch the all-seasons nflverse schedule.

    THE FANTASY ENGINE CANNOT PROJECT WITHOUT IT and the failure is quiet: with
    no schedule there are no game environments, so every weekly projection is
    empty and the season falls back to a no-market path. Measured 2026-08-21 --
    the first autorun on the worker published an artifact with `weeks: []`,
    318 KB instead of 2.83 MB, and Christian McCaffrey at 525 PPR points
    against a correct ~270. It looked like a projection.
    """
    target = nfl_artifact_output_root() / "tracking" / "nflverse" / "schedules_games.csv"
    if target.is_file() and not force:
        return "kept", target, target.stat().st_size
    request = urllib.request.Request(
        NFLVERSE_GAMES_URL, headers={"User-Agent": "syndicate-fantasy/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        return f"failed: {error}", target, 0
    if not payload:
        return "failed: empty response", target, 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return "fetched", target, len(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--kinds", default="roster,depth_charts,schedule")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    failures = 0
    kinds = [value.strip() for value in args.kinds.split(",") if value.strip()]
    if "schedule" in kinds:
        status, path, size = fetch_schedule(force=args.force)
        print(f"[{status:<8}] schedule (all seasons): {size / 1_000_000:.1f} MB -> {path}", flush=True)
        if status.startswith("failed"):
            failures += 1
        kinds = [kind for kind in kinds if kind != "schedule"]

    for kind in kinds:
        if kind not in FEEDS:
            print(f"unknown feed {kind!r}; known: {sorted(FEEDS)}", flush=True)
            failures += 1
            continue
        for season in [int(value) for value in args.seasons.split(",") if value.strip()]:
            status, path, size = fetch(kind, season, force=args.force)
            print(f"[{status:<8}] {kind} {season}: {size / 1_000_000:.1f} MB -> {path}", flush=True)
            if status.startswith("failed"):
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
