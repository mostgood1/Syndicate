"""Fetch nflverse injury reports for one season onto the mounted disk.

WHY THIS EXISTS. `syndicate.features.nfl.injury_adjustment` -- the one
place real player-level data reaches the NFL sim engine today (it excludes
a specific injured player's own real EPA contribution from their team's
rating, with a real depth-chart backup substitution) -- depends entirely
on `injuries_{season}.csv`. There was NO ingestion path for it anywhere in
this repo: the only copy found was on one dev machine, git-untracked, and
for **2025** (last season), dated 2026-08-01. Nothing kept it current and
nothing would have noticed it going stale, because it was also never
allowlisted in `HOT_ARTIFACT_PATTERNS` -- production presence was
unauditable from web. This creates the fetch side; the companion fix in
`syndicate/features/nfl/sources.py` (`nfl_injuries_path`) and
`injury_adjustment.py` fixes the READ side, which had the exact same
root-resolution bug `#441` already found and fixed for play-by-play.

THE REAL SOURCE (confirmed live by content, not assumed from convention):
    https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv
A plain CSV (unlike pbp, which is gzipped) -- but this still handles a
gzipped response gracefully, same rationale `fetch_nfl_pbp.py` uses: the
release format is upstream's to change, not this script's to assume.

A season that has not started yet 404s -- this is NORMAL, not a failure
(nflverse publishes injury reports as real practice/game reports accrue,
so a season several weeks from kickoff genuinely has none yet). Unlike
pbp, injuries have NO sensible "prior season fallback": who was hurt last
year says nothing about who is hurt this week, so this fetches only the
requested season, never season-1 by default.

Writes under `nfl_artifact_output_root()`, NOT `default_nfl_source_root()`
-- the latter picks a root by probing for an unrelated file
(`upcoming_recs_*.csv`) and can resolve to the ephemeral repo checkout
instead of the mounted disk, which is `#389`'s and `#441`'s shared root
cause, applied here before it ever ships broken.

Usage:
    py -3 scripts/fetch_nfl_injuries.py --season 2026
    py -3 scripts/fetch_nfl_injuries.py --season 2025 --force
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.sources import nfl_artifact_output_root  # noqa: E402

INJURIES_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"

USER_AGENT = "syndicate-nfl-injuries/1.0"

# EXACTLY the columns `injury_adjustment._injured_players_for_team` reads
# (team, week, report_status, gsis_id, position, full_name) plus the two
# that identify the file's own scope (season, season_type). Confirmed
# against the real release, 2026-08-19:
#     season,season_type,game_type,team,week,gsis_id,position,full_name,
#     first_name,last_name,report_primary_injury,report_secondary_injury,
#     report_status,practice_primary_injury,practice_secondary_injury,
#     practice_status
REQUIRED_COLUMNS: tuple[str, ...] = (
    "season",
    "season_type",
    "team",
    "week",
    "gsis_id",
    "position",
    "full_name",
    "report_status",
)

# A floor against TRUNCATION, not a completeness check -- deliberately low
# so an early-season fetch (a handful of weeks of real reports) is never
# rejected. The one full real season measured locally (2025) has 6,069
# rows; a single real week across 32 teams is already in the hundreds.
MIN_ROWS = 100

_CHUNK = 1024 * 1024


def _injuries_destination(season: int) -> Path:
    return nfl_artifact_output_root() / "tracking" / "nflverse" / "injuries" / f"injuries_{season}.csv"


def _download_to(season: int, destination: Path, *, timeout: int) -> None:
    """Stream the release to *destination*. Same graceful gzip-or-plain
    handling as `fetch_nfl_pbp.py` -- the format is upstream's to change,
    and confirming it is plain CSV today does not mean it stays that way."""
    url = INJURIES_URL_TEMPLATE.format(season=season)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        head = response.read(2)
        gzipped = head[:2] == b"\x1f\x8b"
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


def _validate_file(path: Path, season: int) -> tuple[int, list[str]]:
    """(row_count, problems). Streams; never raises on content."""
    problems: list[str] = []
    rows = 0
    seasons_seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
            if missing:
                problems.append(f"missing required column(s): {missing}")
            for row in reader:
                rows += 1
                season_value = str(row.get("season") or "").strip()
                if season_value:
                    seasons_seen.add(season_value)
    except Exception as exc:  # noqa: BLE001
        return rows, problems + [f"unreadable download: {type(exc).__name__}: {exc}"]
    if rows < MIN_ROWS:
        problems.append(f"only {rows} rows (floor {MIN_ROWS}) -- looks truncated")
    # A season mismatch (e.g. the URL redirected to the wrong release, or
    # upstream's per-season split changed) would silently install a file
    # every future read call resolves as the WRONG season's reports. Never
    # trust the filename alone.
    if seasons_seen and str(season) not in seasons_seen:
        problems.append(f"file's own season column says {sorted(seasons_seen)}, requested {season}")
    return rows, problems


def fetch_season(season: int, *, force: bool, timeout: int) -> dict[str, object]:
    """Download -> validate -> atomically install, entirely on disk.

    Same atomic-replace-via-same-filesystem-temp-file discipline as
    `fetch_nfl_pbp.py::fetch_season` -- see that function's docstring for
    why the staging file lives in the destination directory rather than
    the system temp dir."""
    destination = _injuries_destination(season)
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
        # A season with no injury reports published yet (too early, or not
        # started) is NORMAL, not a failure.
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
    rows, problems = _validate_file(staging, season)
    result["rows"] = rows
    if problems:
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

    # PUBLISH TO WEB -- `nfl-artifact-publish-wiring`: this file had NO
    # publish call site at all before this. `HOT_ARTIFACT_PATTERNS` was
    # fixed to allowlist it (`nfl-artifact-allowlist-add`), but the
    # allowlist only PERMITS the transfer -- confirmed live 2026-08-20,
    # `/api/ops/artifacts/export` returned `count: 0` because nothing
    # ever called the push. Same pattern
    # `generate_smartsim2_nfl_projections.py` already uses: best-effort,
    # never fails the fetch itself.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(destination)
    except Exception as exc:  # noqa: BLE001 - transfer must never fail the fetch
        published = False
        result["publish_error"] = f"{type(exc).__name__}: {exc}"
    result["published"] = published
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--force", action="store_true", help="refetch even when the file already exists")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = fetch_season(args.season, force=args.force, timeout=args.timeout)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifact_root": str(nfl_artifact_output_root()),
        "result": result,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"NFL injuries fetch -> {payload['artifact_root']}")
        status = result.get("status")
        extra = ""
        if status == "written":
            extra = f"{result.get('rows')} rows, {result.get('bytes')} bytes, published={result.get('published')}"
        elif status == "rejected":
            extra = "; ".join(result.get("problems") or [])
        elif status in {"unavailable", "http_error", "download_failed"}:
            extra = str(result.get("detail") or "")
        print(f"  season {result['season']}: {status}  {extra}")
        print(f"    {result['path']}")

    # "unavailable" (no release yet for a season that has not started) must
    # not fail a scheduled autorun -- same convention as fetch_nfl_pbp.py.
    if result.get("status") in {"rejected", "http_error", "download_failed"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
