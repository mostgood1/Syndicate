"""Is my local data current? Answer it in one command, before analysing anything.

    py -3 scripts\\artifact_freshness.py
    py -3 scripts\\artifact_freshness.py --sport mlb --json
    py -3 scripts\\artifact_freshness.py --guard --max-age-days 1   # exit 1 if stale

WHY THIS EXISTS. `CLAUDE.md` already warns that `data/**` in git is a lossy
mirror. The warning did not stop the failure, because a warning tells you the
data MIGHT be stale and gives you no way to find out whether it IS.

Measured 2026-08-10: a book-quotes shard four days old was profiled and
reported as current. The contradicting evidence was in hand the whole time --
production said 122k rows, the local file had 34k -- and got explained away as
"today's shard is bigger" rather than "my file is four days old." Discipline
does not catch that. A table does.

HOW IT READS RENDER SAFELY. It does NOT call `/api/ops/artifacts/export`, which
globs the entire artifact tree before filtering and has OOM-killed the 2Gi web
service. Instead it reads the refresh-worker's own `PUBLISH_OK` log stream via
the Render logs API: every artifact the worker writes announces itself there
with its full path. Costs web nothing.

THE LIMIT OF THAT, STATED PLAINLY: the log stream is a WINDOW, not a census. An
artifact absent from it may simply not have been published inside the window.
So this tool reports `last seen published`, never `does not exist`, and every
row carries the window it was measured over. Absence here is not evidence of
absence -- it is the absence of evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._pipeline_diag import (  # noqa: E402
    REPO_ROOT,
    SERVICES,
    banner,
    fetch_logs,
    log_window,
    render_owner_id,
    utcnow,
)

_DATE_RE = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")
_PUBLISH_RE = re.compile(r"PUBLISH_OK path=(\S+)")

# Families worth tracking, as (label, local glob). Deliberately a short list of
# the artifacts that analyses actually join across -- the trap `CLAUDE.md`
# describes is a join collapsing to the intersection of mismatched windows, so
# these are exactly the ones whose date coverage must be comparable.
FAMILIES: tuple[tuple[str, str], ...] = (
    ("mlb book_quotes", "data/mlb_source/tracking/book_quotes/*.jsonl"),
    ("mlb game_lines", "data/mlb_source/data/daily/snapshots/*/oddsapi_game_lines_*.json"),
    ("mlb daily_summary", "data/mlb_source/**/daily_summary_*.json"),
    ("mlb sims", "data/mlb_source/**/sims/*/sim_*.json"),
    ("wnba processed", "data/wnba_source/**/processed/game_cards_*.csv"),
    ("wnba recon", "data/wnba_source/**/processed/recon_*_*.csv"),
    ("wnba boxscores", "data/wnba_source/**/processed/boxscores_*.csv"),
    ("soccer live_state", "data/soccer_source/*/api/live_state/live_state_*.json"),
    ("intelligence state", "reports/intelligence/intelligence_state_*.json"),
    ("layer2 shortlist", "reports/intelligence/layer2_shortlist_*.json"),
)


def _dates_from_paths(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        found = _DATE_RE.search(str(path))
        if found:
            out.add(f"{found.group(1)}-{found.group(2)}-{found.group(3)}")
    return out


def local_dates(pattern: str) -> set[str]:
    return _dates_from_paths([str(p) for p in REPO_ROOT.glob(pattern)])


def git_dates(pattern: str) -> set[str]:
    """Dates TRACKED IN GIT, which is a different set from what is on disk.

    Much of local `data/` is untracked mirror output of unknown vintage. An
    analysis that says "I used the repo's data" has not said which of these
    two it meant, and they routinely disagree.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", pattern],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return set()
    return _dates_from_paths(result.stdout.splitlines())


def render_published(limit: int, owner: str | None) -> tuple[dict[str, set[str]], str, str, float, str]:
    """What refresh-worker announced publishing, per family, inside the window."""
    logs, error = fetch_logs(SERVICES["refresh-worker"], limit=limit, owner_id=owner)
    first, last, minutes = log_window(logs)
    published: dict[str, set[str]] = defaultdict(set)
    for entry in logs:
        found = _PUBLISH_RE.search(str(entry.get("message") or ""))
        if not found:
            continue
        path = found.group(1)
        for label, _ in FAMILIES:
            key = label.split(" ", 1)[-1]
            if key.replace("_", "") in path.replace("_", "").replace("-", ""):
                published[label] |= _dates_from_paths([path])
    return published, first, last, minutes, error


def _age_days(newest: str | None) -> float | None:
    if not newest:
        return None
    try:
        parsed = datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (utcnow() - parsed).total_seconds() / 86400.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", default=None, help="substring filter on the family label")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--guard", action="store_true", help="exit 1 if any family is staler than --max-age-days")
    parser.add_argument("--max-age-days", type=float, default=1.0)
    parser.add_argument("--log-limit", type=int, default=1000, help="worker log lines (API caps at 1000)")
    args = parser.parse_args()

    owner = render_owner_id()
    published, first, last, minutes, log_error = render_published(args.log_limit, owner)

    families = [f for f in FAMILIES if not args.sport or args.sport.lower() in f[0].lower()]
    rows = []
    for label, pattern in families:
        on_disk = local_dates(pattern)
        tracked = git_dates(pattern)
        pub = published.get(label, set())
        newest_disk = max(on_disk) if on_disk else None
        newest_git = max(tracked) if tracked else None
        newest_pub = max(pub) if pub else None
        rows.append(
            {
                "family": label,
                "disk_files": len(on_disk),
                "disk_newest": newest_disk,
                "disk_age_days": _age_days(newest_disk),
                "git_files": len(tracked),
                "git_newest": newest_git,
                "published_in_window": sorted(pub),
                "published_newest": newest_pub,
            }
        )

    if args.json:
        print(json.dumps({"window": {"first": first, "last": last, "minutes": round(minutes, 1)}, "families": rows}, indent=2))
    else:
        print(banner(f"ARTIFACT FRESHNESS   (worker publish window {first} -> {last}, {minutes:.0f} min)"))
        if log_error:
            print(f"  !! could not read the worker log: {log_error}")
            print("     the 'published' column below is UNKNOWN, not empty.")
        print(f"  {'family':22} {'disk':>5} {'disk newest':>12} {'age':>6} {'git':>4} {'git newest':>12}  published in window")
        for row in rows:
            age = row["disk_age_days"]
            age_text = f"{age:.1f}d" if age is not None else "-"
            flag = ""
            if age is not None and age > args.max_age_days:
                flag = "  <-- STALE"
            print(
                f"  {row['family']:22} {row['disk_files']:>5} {str(row['disk_newest'] or '-'):>12} {age_text:>6} "
                f"{row['git_files']:>4} {str(row['git_newest'] or '-'):>12}  {', '.join(row['published_in_window']) or '-'}{flag}"
            )
        print()
        print("  disk = files present locally (tracked OR untracked -- mirror output of unknown vintage)")
        print("  git  = files actually committed; routinely a SMALLER set than disk")
        print("  published = what refresh-worker announced in THIS window only.")
        print("  An empty 'published' cell means NOT SEEN IN THE WINDOW -- never 'does not exist'.")

    if args.guard:
        stale = [r["family"] for r in rows if (r["disk_age_days"] or 0) > args.max_age_days]
        if stale:
            print()
            print(f"  GUARD FAILED: {len(stale)} family(ies) staler than {args.max_age_days}d -- {', '.join(stale)}")
            print("  Do not draw conclusions from these locally. Read production instead.")
            return 1
        print()
        print(f"  GUARD PASSED: every family within {args.max_age_days}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
