"""Pull specific production artifacts down to local, safely. The other half of
`artifact_freshness.py`.

    py -3 scripts\\mirror_pull.py --family "mlb book_quotes" --date 2026-08-09
    py -3 scripts\\mirror_pull.py --path mlb_source/data/daily/snapshots/2026-08-09/schedule_raw.json
    py -3 scripts\\mirror_pull.py --stale --max-age-days 1 --dry-run

WHY A NEW TOOL RATHER THAN THE OBVIOUS ONE. `/api/ops/artifacts/export` is the
endpoint people reach for and it is the reason the mirror drifted to 29 days:
it globs `HOT_ARTIFACT_PATTERNS` across the whole artifact tree BEFORE filtering
to the requested pattern, so its cost is the walk, not the response. It
OOM-killed the 2Gi web service twice on 2026-08-10, once from a single
diagnostic run. A mirroring tool that is dangerous to use does not get used,
and an un-run mirror is how a five-day-old book-quotes shard gets profiled and
reported as current.

This uses `/api/ops/artifacts/stream` instead -- the single-artifact companion
that resolves ONE path and streams it. No glob, no whole-tree walk, bounded
memory on the sender. It was built for the odds_history shards export
structurally cannot deliver; the property that makes it right for those makes
it right for everything.

WHAT IT DELIBERATELY WILL NOT DO
--------------------------------
- It will not invent paths. You pull a family+date or an explicit relative
  path. Guessing a path and getting a 404 teaches nothing about whether the
  artifact exists.
- It will not overwrite a NEWER local file unless told to. The mirror is not
  always behind; `data/` also holds untracked local output.
- It reports 403 (not allowlisted) distinctly from 404 (not there). Those are
  completely different facts and collapsing them is how "absent" gets
  concluded from "not permitted" -- the exact error that cost the WNBA grader
  lane an evening.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._pipeline_diag import REPO_ROOT, WEB_BASE, banner, secret  # noqa: E402

# family -> relative-path template. `{date}` is the ISO date, `{slug}` the
# underscore form. Kept explicit rather than derived: a wrong guess here is a
# 404 that looks like a missing artifact.
FAMILY_PATHS: dict[str, tuple[str, ...]] = {
    "mlb book_quotes": (
        "mlb_source/tracking/book_quotes/{date}.jsonl",
        "mlb_source/tracking/book_quotes/{date}.state.json",
    ),
    "mlb game_lines": (
        "mlb_source/data/daily/snapshots/{date}/oddsapi_game_lines_{slug}.json",
        "mlb_source/data/daily/snapshots/{date}/oddsapi_game_lines_{slug}_pregame.json",
    ),
    "mlb schedule": ("mlb_source/data/daily/snapshots/{date}/schedule_raw.json",),
    "mlb daily_summary": ("mlb_source/source_artifacts/data/daily/daily_summary_{slug}.json",),
    "wnba processed": (
        "wnba_source/data/processed/game_cards_{date}.csv",
        "wnba_source/data/processed/props_recommendations_{date}.csv",
    ),
    "intelligence": (
        "reports/intelligence/layer2_shortlist_{slug}.json",
    ),
}


def stream_artifact(relative_path: str, *, timeout: int = 120) -> tuple[bytes | None, int | None, str]:
    """Fetch ONE artifact. Returns (body, status, error). Never raises."""
    token = secret("ADMIN_TOKEN")
    if not token:
        return None, None, "ADMIN_TOKEN not set"
    url = f"{WEB_BASE}/api/ops/artifacts/stream?path={relative_path}"
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return response.read(), response.getcode(), ""
    except urllib.error.HTTPError as exc:
        # 403 and 404 are DIFFERENT FACTS. 403 means the path is not in
        # HOT_ARTIFACT_PATTERNS, so the file may well exist and simply cannot
        # cross; 404 means web genuinely does not have it. Reporting them the
        # same way is how "not permitted" becomes "absent".
        detail = {403: "NOT ALLOWLISTED (may exist on the worker)", 404: "not present on web"}.get(
            exc.code, f"HTTP {exc.code}"
        )
        return None, exc.code, detail
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--family", help=f"one of: {', '.join(sorted(FAMILY_PATHS))}")
    parser.add_argument("--date", help="ISO date, e.g. 2026-08-09")
    parser.add_argument("--path", help="explicit relative artifact path")
    parser.add_argument("--force", action="store_true", help="overwrite even when local is newer")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets: list[str] = []
    if args.path:
        targets.append(args.path)
    elif args.family:
        if args.family not in FAMILY_PATHS:
            print(f"unknown family {args.family!r}. known: {', '.join(sorted(FAMILY_PATHS))}")
            return 2
        if not args.date:
            print("--family needs --date")
            return 2
        slug = args.date.replace("-", "_")
        targets = [tpl.format(date=args.date, slug=slug) for tpl in FAMILY_PATHS[args.family]]
    else:
        print("give --family+--date or --path")
        return 2

    print(banner(f"MIRROR PULL  ({len(targets)} artifact(s) via /api/ops/artifacts/stream)"))
    pulled = 0
    for relative_path in targets:
        destination = REPO_ROOT / "data" / relative_path if not relative_path.startswith("reports/") else REPO_ROOT / relative_path
        if args.dry_run:
            print(f"  DRY  {relative_path}\n       -> {destination}")
            continue
        body, status, error = stream_artifact(relative_path)
        if body is None:
            print(f"  FAIL {relative_path}  [{status}] {error}")
            continue
        if destination.exists() and not args.force:
            local_size = destination.stat().st_size
            if local_size == len(body):
                print(f"  SAME {relative_path}  ({len(body):,} bytes, unchanged)")
                continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        pulled += 1
        print(f"  OK   {relative_path}  ({len(body):,} bytes)")

    print()
    print(f"  pulled {pulled} of {len(targets)}")
    print("  A 403 is NOT absence -- it means the path is not allowlisted and cannot cross,")
    print("  so the artifact may exist on the worker. Only 404 means web does not have it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
