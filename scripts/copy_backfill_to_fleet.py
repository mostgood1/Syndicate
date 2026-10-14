"""Copy the dev-machine backfill sets onto the fleet data root, with a sha256 manifest per set.

Lane `news-collectors-backfill` (2026-10-13, user: "start ... the backfill copy -- this should spend no money").
Plan: `findings_2026-10-13_matchup_signal_plan.md` §1 item 2.

WHY. The matchup-signal studies are discovered on prior seasons, and every one of those sets lived only in
`C:\\tmp\\...` or in untracked folders of the primary checkout -- places a tmp cleanup, a `git clean` or a worktree prune
can delete. The fleet data root is where production keeps what it owns, and the nightly `data-backup` job snapshots it.

WHAT. Each SET is a source directory (optionally filtered by a filename pattern) copied to
`<data root>/backfill/<set>/` with its relative paths kept. For every file: sha256 at the source, copy, sha256 at the
destination, compare. A file already present with the same hash is skipped (re-runs are cheap and safe). The source is
never modified or deleted. `MANIFEST.json` per set records source, counts, bytes and every file's hash; a mismatch is
reported and the exit code is non-zero.

No network, no API, no credits.

    python3 scripts/copy_backfill_to_fleet.py --data-root ~/syndicate-prod/data            # all sets
    python3 scripts/copy_backfill_to_fleet.py --data-root ... --sets nba_props_2025_26 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PRIMARY = "/mnt/c/Users/tempadmin/OneDrive/Coding/Syndicate"

# name -> (source dir, filename regex or None, what it is)
SETS: dict[str, tuple[str, str | None, str]] = {
    "nba_props_2025_26": ("/mnt/c/tmp/nba_bt/out", None,
                          "NBA 2025-26 prop prices (OddsAPI historical, one snapshot ~45 min pre-tip) + as-of inputs + actuals"),
    "nhl_lines_2025_26": ("/mnt/c/tmp/nhllines", None, "NHL 2025-26 game-line closes / caches"),
    "nhl_source_dev": (f"{PRIMARY}/data/nhl_source/data", None,
                       "NHL 2023-26 box score / PBP / landing ingestion cache, truth, processed (incl. DFO goalie history)"),
    "nfl_prop_closes_2023_25": (f"{PRIMARY}/data/nfl_source/tracking/book_quotes", r"^20(23|24|25)_wk\d+\.",
                                "NFL 2023-25 prop closes (kickoff-10min book quotes, per week)"),
    "nfl_injuries_2009_25": (f"{PRIMARY}/data/nfl_source/tracking/nflverse/injuries", None, "nflverse weekly injury reports 2009-25"),
    "ncaaf_props_2024_25": ("/mnt/c/tmp/football_scenarios/ncaaf_props", None, "NCAAF 2024-25 props (1,095 games)"),
    "wnba_props_2026": ("/mnt/c/tmp/wnba_props_2026", r"^(?!player_game_log)",
                        "WNBA 2026 regular-season prop closes, 8 markets at tip - 10 min (bought 2026-10-14, "
                        "`wnba_props_pull.py`) + the per-day historical events; the game log is the fleet's own"),
}


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _listdir(directory: Path, attempts: int = 5) -> list[os.DirEntry]:
    """`scandir` with retries. Over the Windows 9p mount a listing can fail TRANSIENTLY with ENOMEM while the fleet
    holds most of WSL's memory in page cache (measured 2026-10-13: `/mnt/c/tmp/nhllines/...` failed once, listed
    fine seconds later). Give up loudly after `attempts`."""
    for attempt in range(attempts):
        try:
            with os.scandir(directory) as it:
                return list(it)
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return []


def iter_files(source: Path, pattern: str | None) -> Iterable[Path]:
    rx = re.compile(pattern) if pattern else None
    stack = [source]
    found: list[Path] = []
    while stack:
        directory = stack.pop()
        for entry in _listdir(directory):
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False) and (rx is None or rx.search(entry.name)):
                found.append(Path(entry.path))
    yield from sorted(found)


def copy_set(name: str, source: Path, pattern: str | None, dest_root: Path, *, dry_run: bool) -> dict[str, Any]:
    dest = dest_root / name
    report: dict[str, Any] = {"set": name, "source": str(source), "pattern": pattern, "files": 0, "bytes": 0,
                              "copied": 0, "skipped_identical": 0, "mismatches": [], "entries": []}
    if not source.is_dir():
        report["error"] = "source missing"
        return report
    for src in iter_files(source, pattern):
        rel = src.relative_to(source).as_posix()
        target = dest / rel
        src_hash = sha256(src)
        size = src.stat().st_size
        report["files"] += 1
        report["bytes"] += size
        if target.is_file() and target.stat().st_size == size and sha256(target) == src_hash:
            report["skipped_identical"] += 1
        elif not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            shutil.copyfile(src, tmp)
            os.replace(tmp, target)
            if sha256(target) != src_hash:
                report["mismatches"].append(rel)
            else:
                report["copied"] += 1
        report["entries"].append({"path": rel, "bytes": size, "sha256": src_hash})
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        manifest = dict(report, written_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        description=SETS.get(name, ("", None, ""))[2])
        (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root and no SYNDICATE_DATA_ROOT", flush=True)
        return 2
    dest_root = Path(os.path.expanduser(args.data_root)) / "backfill"
    bad = 0
    for name in [s.strip() for s in args.sets.split(",") if s.strip()]:
        if name not in SETS:
            print(f"UNKNOWN_SET {name}", flush=True)
            bad += 1
            continue
        source, pattern, _ = SETS[name]
        rep = copy_set(name, Path(source), pattern, dest_root, dry_run=args.dry_run)
        bad += len(rep["mismatches"]) + (1 if rep.get("error") else 0)
        print(f"BACKFILL {name} files={rep['files']} bytes={rep['bytes']} copied={rep['copied']} "
              f"skipped_identical={rep['skipped_identical']} mismatches={len(rep['mismatches'])} "
              f"error={rep.get('error')} dry_run={args.dry_run}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
