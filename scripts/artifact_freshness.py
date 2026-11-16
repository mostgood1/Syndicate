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

HOW IT READS PRODUCTION SAFELY. It does NOT call `/api/ops/artifacts/export`, which
globs the entire artifact tree before filtering and has OOM-killed the 2Gi web
service. Production is the local WSL fleet, whose roles share ONE data root, so it
lists each family's files THERE (one read-only `python3` on the fleet host, file
NAMES only) and reports the newest date per family. Costs web nothing.

UNTIL 2026-11-15 it read refresh-worker's `PUBLISH_OK` lines from the Render logs
API instead (lane render-retirement). That signal does not exist on the fleet:
publishing onto a shared disk is a no-op, and 0 of the last 20,000 refresh-worker
log lines carried it when the tool was moved. A log-window column would have read
"not seen" for every family, for ever.

THE LIMIT, STATED PLAINLY: production's newest date is a date IN A FILE NAME, so a
family whose names carry no date reads as having none, and an empty production
cell means "no file matched the pattern", never "the pipeline did not run".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._pipeline_diag import (  # noqa: E402
    REPO_ROOT,
    banner,
    fleet_role_env,
    utcnow,
)

_DATE_RE = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")
FLEET_DATA_ROOT_DEFAULT = "~/syndicate-prod/data"
FLEET_PYTHON = os.environ.get("SYNDICATE_FLEET_SYSTEM_PYTHON", "python3")
FLEET_WSL_DISTRO = os.environ.get("SYNDICATE_FLEET_WSL_DISTRO", "Ubuntu-24.04")

# Runs ON the fleet host. Reads argv[1] as JSON {label: [root, relative_glob]} and prints
# {label: {"files": n, "dates": [...]}}. File NAMES only; nothing is opened. A `.jsonl`
# pattern also matches its gzipped `.jsonl.gz` siblings, which the fleet compresses.
_FLEET_LISTER = r'''
import glob, json, os, re, sys
date_re = re.compile(r"(20\d{2})[-_](\d{2})[-_](\d{2})")
out = {}
for label, (root, pattern) in json.loads(sys.argv[1]).items():
    base = os.path.expanduser(root)
    paths = glob.glob(os.path.join(base, pattern), recursive=True)
    if pattern.endswith(".jsonl"):
        paths += glob.glob(os.path.join(base, pattern + ".gz"), recursive=True)
    dates = set()
    for path in paths:
        found = date_re.search(os.path.basename(path)) or date_re.search(path)
        if found:
            dates.add("-".join(found.groups()))
    out[label] = {"files": len(paths), "dates": sorted(dates)}
print(json.dumps(out))
'''

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


def production_dates(families: list[tuple[str, str]]) -> tuple[dict[str, dict], str, str]:
    """({label: {files, dates}}, data_root, error) from the fleet's shared data root.

    The roots are refresh-worker's own `SYNDICATE_DATA_ROOT` / `SYNDICATE_REPORTS_ROOT`
    (path keys only), so a moved root is followed rather than guessed. An error means
    production was NOT read: every production cell is then unknown, not empty.
    """
    roots, env_error = fleet_role_env("refresh-worker", ["SYNDICATE_DATA_ROOT", "SYNDICATE_REPORTS_ROOT"])
    data_root = roots.get("SYNDICATE_DATA_ROOT") or FLEET_DATA_ROOT_DEFAULT
    reports_root = roots.get("SYNDICATE_REPORTS_ROOT") or f"{data_root}/reports"
    request: dict[str, list[str]] = {}
    for label, pattern in families:
        if pattern.startswith("data/"):
            request[label] = [data_root, pattern[len("data/"):]]
        elif pattern.startswith("reports/"):
            request[label] = [reports_root, pattern[len("reports/"):]]
    argv = [FLEET_PYTHON, "-c", _FLEET_LISTER, json.dumps(request)]
    if os.name == "nt":
        argv = ["wsl.exe", "-d", FLEET_WSL_DISTRO, "-e", *argv]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, data_root, f"fleet listing failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return {}, data_root, f"fleet listing rc {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    try:
        listed = json.loads(proc.stdout)
    except ValueError:
        return {}, data_root, "fleet listing printed no JSON"
    shown = f"{data_root} (default: {env_error})" if env_error else data_root
    return listed, shown, ""


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
    args = parser.parse_args()

    families = [f for f in FAMILIES if not args.sport or args.sport.lower() in f[0].lower()]
    production, prod_root, prod_error = production_dates(families)
    rows = []
    for label, pattern in families:
        on_disk = local_dates(pattern)
        tracked = git_dates(pattern)
        prod = production.get(label) or {}
        newest_disk = max(on_disk) if on_disk else None
        newest_git = max(tracked) if tracked else None
        prod_dates = list(prod.get("dates") or [])
        newest_prod = prod_dates[-1] if prod_dates else None
        rows.append(
            {
                "family": label,
                "disk_files": len(on_disk),
                "disk_newest": newest_disk,
                "disk_age_days": _age_days(newest_disk),
                "git_files": len(tracked),
                "git_newest": newest_git,
                # None = production was not read (see production.error); 0 = read, nothing matched.
                "production_files": prod.get("files") if not prod_error else None,
                "production_newest": newest_prod,
                "production_dates": len(prod_dates),
            }
        )

    if args.json:
        print(json.dumps({"production": {"data_root": prod_root, "error": prod_error}, "families": rows}, indent=2))
    else:
        print(banner(f"ARTIFACT FRESHNESS   (production = the fleet data root {prod_root})"))
        if prod_error:
            print(f"  !! could not read production: {prod_error}")
            print("     the 'prod' columns below are UNKNOWN, not empty.")
        print(f"  {'family':22} {'disk':>5} {'disk newest':>12} {'age':>6} {'git':>4} {'git newest':>12} {'prod':>6} {'prod newest':>12}")
        for row in rows:
            age = row["disk_age_days"]
            age_text = f"{age:.1f}d" if age is not None else "-"
            flag = ""
            if age is not None and age > args.max_age_days:
                flag = "  <-- STALE"
            if row["production_newest"] and (row["disk_newest"] or "") < row["production_newest"]:
                flag += "  <-- BEHIND PRODUCTION"
            prod_files = "?" if row["production_files"] is None else row["production_files"]
            print(
                f"  {row['family']:22} {row['disk_files']:>5} {str(row['disk_newest'] or '-'):>12} {age_text:>6} "
                f"{row['git_files']:>4} {str(row['git_newest'] or '-'):>12} {prod_files:>6} "
                f"{str(row['production_newest'] or '-'):>12}{flag}"
            )
        print()
        print("  disk = files present locally (tracked OR untracked -- mirror output of unknown vintage)")
        print("  git  = files actually committed; routinely a SMALLER set than disk")
        print("  prod = files on the fleet's shared data root, newest by the date in the file name")
        print("  An empty 'prod' cell means no file matched the pattern -- never 'the pipeline did not run'.")

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
