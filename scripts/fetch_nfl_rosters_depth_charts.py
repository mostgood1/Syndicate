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

FEEDS: dict[str, tuple[str, str]] = {
    # local subdirectory -> (release tag, filename stem)
    "roster": ("rosters", "roster"),
    "depth_charts": ("depth_charts", "depth_charts"),
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--kinds", default="roster,depth_charts")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    failures = 0
    for kind in [value.strip() for value in args.kinds.split(",") if value.strip()]:
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
