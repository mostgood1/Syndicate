"""Build the per-season NFL fantasy USAGE artifacts from nflverse play-by-play.

This is a WORKER job, not a request-path operation. It parses ~46,000 plays x
372 columns per season; the web service must never do that inside a route
handler (``CLAUDE.md``, the worker-split rule). The web service reads the JSON
this writes.

    python scripts/build_nfl_fantasy_usage.py --seasons 2022,2023,2024,2025

Writes ``<nfl_source>/fantasy/nfl_fantasy_usage_{season}.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_usage import usage_artifact_path  # noqa: E402
from syndicate.features.nfl.fantasy_usage import usage_substrate  # noqa: E402
from syndicate.features.nfl.fantasy_usage import write_usage_artifact  # noqa: E402


def publish(path: Path, *, timeout_seconds: int = 180) -> bool | None:
    """Push one usage document to web. None when publishing is not configured.

    **PUBLISHING A KEPT ARTIFACT IS THE POINT, not an edge case.** `#671`:
    `nfl_fantasy_usage_*.json` has been in `HOT_ARTIFACT_PATTERNS` all along and
    production web holds ZERO of them, so every NFL prop answer's recent-form
    layer reads `artifact_missing` (measured over 40 board rows, 2026-09-17).
    The steady state on the worker is "already built", so a publisher that only
    fired on a fresh build would leave that exactly as it is.
    """
    try:
        from syndicate.features.shared import artifact_publisher as ap
    except Exception as exc:
        print(f"[usage] publish import failed: {type(exc).__name__}", flush=True)
        return None
    if ap.relative_to_data_root(path) is None:
        # The `#389` shape: a file outside SYNDICATE_DATA_ROOT cannot be addressed.
        print(f"[usage] NOT PUBLISHED -- {path} is not under the data root", flush=True)
        return False
    ok = ap.publish_hot_artifact(path, timeout_seconds=timeout_seconds)
    print(f"[usage] publish {path.name} -> {ok}", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--force", action="store_true", help="rebuild even when the artifact exists")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    parser.add_argument("--no-publish", action="store_true", help="build only; do not push to web")
    args = parser.parse_args()

    seasons = [int(value) for value in args.seasons.split(",") if value.strip()]
    results: list[dict[str, object]] = []
    failures = 0

    for season in seasons:
        substrate = usage_substrate(season)
        target = usage_artifact_path(season)
        if not substrate["exists"]:
            # `model_engine_standard.md` s3b: this is UNMEASURED, not zero.
            print(f"[skip] {season}: no pbp on this substrate ({substrate['path']})", flush=True)
            results.append({"season": season, "status": "no_substrate", **substrate})
            failures += 1
            continue
        if target.is_file() and not args.force:
            print(f"[keep] {season}: {target} already exists (--force to rebuild)", flush=True)
            published = None if args.no_publish else publish(target)
            results.append({"season": season, "status": "kept", "path": str(target), "published": published})
            if published is False:
                failures += 1
            continue

        started = time.monotonic()
        path = write_usage_artifact(season)
        elapsed = time.monotonic() - started
        payload = json.loads(path.read_text(encoding="utf-8"))
        players = len(payload.get("players") or {})
        teams = len(payload.get("teams") or {})
        print(
            f"[built] {season}: {players} players, {teams} teams, "
            f"{path.stat().st_size / 1_000_000:.1f} MB, {elapsed:.1f}s -> {path}",
            flush=True,
        )
        published = None if args.no_publish else publish(path)
        if published is False:
            failures += 1
        results.append(
            {
                "season": season,
                "status": "built",
                "path": str(path),
                "players": players,
                "teams": teams,
                "seconds": round(elapsed, 1),
                "published": published,
            }
        )
        if teams != 32:
            print(f"  WARNING: {teams} teams, expected 32", flush=True)

    if args.json:
        print(json.dumps({"results": results}, indent=1))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
