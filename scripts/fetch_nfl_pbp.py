"""Fetch nflverse play-by-play for one season onto the mounted disk. `#441`.

WHY THIS EXISTS. `generate_smartsim2_nfl_projections.py` derives every team's
rating from this file, and there was NO ingestion path for it anywhere in the
repo -- ten scripts reference `pbp`, all of them reads. Measured in production
2026-08-16 (`a775e372` diagnostic, 17:10:45Z), the guard refused for 2.79 days
because the file is absent from all four candidate roots:

    strict_hosted_storage_resolves_to = True
    candidate[0] /opt/render/project/data/nfl_source/source_artifacts/.../pbp_2026.csv  exists=False
    candidate[1] /opt/render/project/data/nfl_source/.../pbp_2026.csv                    exists=False
    candidate[2..3] /opt/render/project/src/data/.../pbp_2026.csv                        exists=False

Root selection was ruled out (candidates 0/1 ARE the mounted disk and WERE
searched) and so was the environment (all three root vars present). The file
simply does not exist and nothing could create it. This creates it.

**THE SEASON THAT MATTERS IS USUALLY THE PRIOR ONE.** For week 1 there are no
current-season regular-season plays yet, and `assert_ratings_data_available`
accepts current OR prior; NFL wk1 ratings come from `prior_season_fallback`. A
fetcher that pulled only the current season would ship and change nothing, so
`--season` defaults to fetching BOTH the requested season and the one before it.

**IT REFUSES TO INSTALL A DEGENERATE FILE**, deliberately mirroring the guard it
feeds. A truncated download or an upstream schema change that silently dropped
`epa` would produce a file whose every team rates `neutral_no_data` -- the exact
league-average artifact that reached the board on 2026-08-13. So the download is
validated for required columns and a non-zero REG play count BEFORE it is allowed
to replace an existing file, and the replace is atomic.

Writes under `nfl_artifact_output_root()` (the `#389` resolver), NOT under
`default_nfl_source_root()` -- the latter picks a root by probing for
`upcoming_recs_*.csv` and resolves to the ephemeral repo checkout on
refresh-worker, which is where `#389` found the projections being written and
discarded on every deploy.

Usage:
    py -3 scripts/fetch_nfl_pbp.py --season 2026
    py -3 scripts/fetch_nfl_pbp.py --season 2026 --only-season   # skip the prior year
    py -3 scripts/fetch_nfl_pbp.py --season 2025 --force         # refetch even if fresh
"""

from __future__ import annotations

import argparse
import csv
import gzip
import zlib
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.sources import nfl_artifact_output_root  # noqa: E402

# nflverse publishes play-by-play as a per-season gzipped CSV on the
# nflverse-data releases. Same host and release convention the roster and
# depth-chart fetchers already use.
PBP_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"

USER_AGENT = "syndicate-nfl-pbp/1.0"

# EXACTLY the columns `generate_smartsim2_nfl_projections.py` reads. Kept as the
# validation set rather than a projection set: the file is written whole, because
# a second consumer (`backtest_nfl_injury_adjustment.py`) reads the same path and
# narrowing the schema here would break it silently. These are asserted PRESENT.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "season_type",
    "play_type",
    "posteam",
    "defteam",
    "epa",
    "week",
    "game_id",
    "home_team",
    "away_team",
)

# A real NFL season is ~45k plays; a preseason-only or in-progress season is far
# fewer. This is a floor against TRUNCATION, not a season-completeness check --
# it must not reject a legitimately young season, so it is deliberately low.
MIN_REG_PLAYS = 500


def _pbp_destination(season: int) -> Path:
    return nfl_artifact_output_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"


# 1 MiB. Chunked because the 2025 release is ~98MB DECOMPRESSED (measured
# 2026-08-16: 97,951,481 bytes, 46,452 REG plays) and this runs on
# refresh-worker, which was measured the same day at 95.3% of its 4096MB cap
# with 190MB headroom. A read-it-all implementation held the gzip bytes, the
# decompressed bytes AND a decoded str simultaneously -- a ~300MB transient on a
# service with 190MB to spare, i.e. a self-inflicted OOM. Everything below
# streams: peak memory is one chunk plus one CSV row.
_CHUNK = 1024 * 1024


def _download_to(season: int, destination: Path, *, timeout: int) -> None:
    """Stream the release to *destination*, decompressing on the fly."""
    url = PBP_URL_TEMPLATE.format(season=season)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        head = response.read(2)
        gzipped = head[:2] == b"\x1f\x8b"
        # Not gzipped is accepted rather than fatal -- the release format is
        # upstream's to change, and a plain CSV body is still usable.
        # zlib, not gzip: `gzip` has no decompressobj. wbits 32+15 auto-detects
        # the gzip header, which is what lets this stream instead of buffering.
        decompressor = zlib.decompressobj(32 + 15) if gzipped else None
        with destination.open("wb") as handle:
            pending = head
            while True:
                if pending:
                    chunk, pending = pending, b""
                else:
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                handle.write(decompressor.decompress(chunk) if decompressor else chunk)
            if decompressor is not None:
                handle.write(decompressor.flush())


def _validate_file(path: Path) -> tuple[int, list[str]]:
    """(reg_play_count, problems). Streams; never raises on content."""
    problems: list[str] = []
    reg = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
            if missing:
                # Still count what we can, so the report distinguishes "schema
                # changed" from "schema changed AND empty".
                problems.append(f"missing required column(s): {missing}")
            for row in reader:
                if row.get("season_type") == "REG":
                    reg += 1
    except Exception as exc:  # noqa: BLE001
        return reg, problems + [f"unreadable download: {type(exc).__name__}: {exc}"]
    if reg < MIN_REG_PLAYS:
        problems.append(f"only {reg} REG plays (floor {MIN_REG_PLAYS}) -- looks truncated")
    return reg, problems


def fetch_season(season: int, *, force: bool, timeout: int) -> dict[str, object]:
    """Download -> validate -> atomically install, entirely on disk.

    The temp file lives in the DESTINATION directory on purpose: `os.replace` is
    only atomic within one filesystem, and the mounted disk is not the same
    device as the system temp dir on Render. It also means a rejected download
    never occupies a second filesystem's space.
    """
    destination = _pbp_destination(season)
    result: dict[str, object] = {"season": season, "path": str(destination)}
    existed = destination.is_file()
    result["existed"] = existed
    if existed and not force:
        try:
            result["existing_bytes"] = destination.stat().st_size
        except OSError:
            pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(destination.parent), prefix=destination.name + ".", suffix=".tmp"
    )
    handle.close()
    staging = Path(handle.name)

    def _discard() -> None:
        try:
            staging.unlink()
        except OSError:
            pass

    try:
        _download_to(season, staging, timeout=timeout)
    except urllib.error.HTTPError as exc:
        _discard()
        # A season with no release yet (one that has not kicked off) is a NORMAL
        # outcome, not a failure -- so a caller fetching {season, season-1} does
        # not treat the young season as an error.
        result["status"] = "unavailable" if exc.code == 404 else "http_error"
        result["detail"] = f"HTTP {exc.code}"
        return result
    except Exception as exc:  # noqa: BLE001
        _discard()
        result["status"] = "download_failed"
        result["detail"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        result["bytes"] = staging.stat().st_size
    except OSError:
        result["bytes"] = None
    reg_plays, problems = _validate_file(staging)
    result["reg_plays"] = reg_plays
    if problems:
        # REFUSE rather than overwrite. A bad file here reproduces exactly the
        # degenerate artifact the downstream guard exists to prevent, and the
        # staged copy is discarded so the good file survives untouched.
        _discard()
        result["status"] = "rejected"
        result["problems"] = problems
        result["existing_file_left_intact"] = existed
        return result

    try:
        os.replace(staging, destination)
    except BaseException:
        _discard()
        raise
    result["status"] = "written"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--only-season",
        action="store_true",
        help="fetch only --season; by default the PRIOR season is fetched too, because week-1 ratings come from it",
    )
    parser.add_argument("--force", action="store_true", help="refetch even when the file already exists")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    seasons = [args.season] if args.only_season else [args.season, args.season - 1]
    results = [fetch_season(season, force=args.force, timeout=args.timeout) for season in seasons]

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifact_root": str(nfl_artifact_output_root()),
        "results": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"NFL pbp fetch -> {payload['artifact_root']}")
        for item in results:
            status = item.get("status")
            extra = ""
            if status == "written":
                extra = f"{item.get('reg_plays')} REG plays, {item.get('bytes')} bytes"
            elif status == "rejected":
                extra = "; ".join(item.get("problems") or [])
            elif status in {"unavailable", "http_error", "download_failed"}:
                extra = str(item.get("detail") or "")
            print(f"  season {item['season']}: {status}  {extra}")
            print(f"    {item['path']}")

    # Exit non-zero only when a season we could have had was REJECTED or errored.
    # "unavailable" is normal for a season that has not started and must not fail
    # a scheduled run.
    bad = [r for r in results if r.get("status") in {"rejected", "http_error", "download_failed"}]
    if bad and not any(r.get("status") == "written" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
