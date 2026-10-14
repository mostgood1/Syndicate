"""Keep the registered forward tests' quote-log inputs past book_quotes retention (lane `forward-input-preservation`).

User 2026-10-14: "yes set up the quote file copy job". `artifact_retention`'s `book_quotes` rule deletes
`*_source/tracking/book_quotes/<date>.*` after 120 days, while several forward tests read a whole season of them:

  nba    H7, H7-late, R1-NBA   read 2027-04-11      wnba   R1-WNBA      read 2027-09-30
  nhl    K1-K5, S1F            read 2026-12-31 / after 2027-04-18
  mlb    M1, M2                read after 2027-10-03
  nfl / ncaaf  F9, F10a, F10b  read ~2027-01 (weekly files; their names carry no date retention can parse, mirrored anyway)

WHAT IT DOES. Daily: every CLOSED day's (or week's) quote file in the test windows is filtered to `kind == "prop"` rows of
the markets those tests read, gzipped, and written to `<data root>/research/forward_inputs/<sport>/quotes/<name>.jsonl.gz`.
THE MIRROR PATH CARRIES NO `_source/tracking/book_quotes/`: retention matches with `fnmatch`, whose `*` crosses `/`, so a
mirror under the original relative path would be deleted by the same rule (tested against `artifact_retention._rule_for`).
Filtering keeps every row of a kept market, so the graders' change-log rule ("the points present at the book's latest
capture") reads a mirrored file exactly as it reads the original. When a plain shard and its `.gz` both exist, the one with
MORE lines is mirrored (the fuller-copy rule). A file is re-mirrored when its source is newer than the mirror.

  --restore   before a final read: for every mirrored file whose original (plain or .gz) is gone, write the mirror back to
              `<sport>_source/tracking/book_quotes/<name>.jsonl.gz`, where the graders look. Never overwrites an original.

    python3 scripts/preserve_forward_inputs.py --data-root ~/syndicate-prod/data
    python3 scripts/preserve_forward_inputs.py --data-root ~/syndicate-prod/data --restore
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FAMILIES: dict[str, dict[str, Any]] = {
    "nba": {"markets": {"player_threes", "player_rebounds", "player_rebounds_assists", "player_assists"},
            "tests": "H7, H7-late, R1-NBA"},
    "wnba": {"markets": {"player_rebounds"}, "tests": "R1-WNBA"},
    "nhl": {"markets": {"SOG", "POINTS", "ASSISTS", "GOALS", "SAVES"}, "tests": "K1-K5, S1F"},
    "mlb": {"markets": {"batter_hits", "batter_total_bases", "strikeouts"}, "tests": "M1, M2"},
    "nfl": {"markets": {"Receptions", "Receiving Yards", "Rushing Attempts", "Rushing Yards"}, "tests": "F9, F10a"},
    "ncaaf": {"markets": {"Rushing Yards"}, "tests": "F10b"},
}
FIRST_DAY, LAST_DAY = "2026-10-13", "2027-10-05"
WEEK_SEASONS = ("2026",)
MIRROR = Path("research") / "forward_inputs"
_DAILY = re.compile(r"^(\d{4}-\d{2}-\d{2})$")
_WEEKLY = re.compile(r"^(\d{4})_wk(\d+)$")


def _name(path: Path) -> str | None:
    name = path.name
    for suffix in (".jsonl.gz", ".jsonl"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def candidates(root: Path, sport: str, today: str, now: float) -> dict[str, list[Path]]:
    """name -> source paths, for CLOSED files inside the test windows."""
    out: dict[str, list[Path]] = defaultdict(list)
    directory = root / f"{sport}_source" / "tracking" / "book_quotes"
    if not directory.is_dir():
        return out
    for path in directory.iterdir():
        name = _name(path)
        if name is None:
            continue
        daily, weekly = _DAILY.match(name), _WEEKLY.match(name)
        if daily:
            if not (FIRST_DAY <= name <= LAST_DAY) or name >= today:  # today's file is still being written
                continue
        elif weekly:
            if weekly.group(1) not in WEEK_SEASONS or now - path.stat().st_mtime < 2 * 86400:  # a week still open
                continue
        else:
            continue
        out[name].append(path)
    return out


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


def fuller(paths: list[Path]) -> Path:
    if len(paths) == 1:
        return paths[0]
    def lines(p: Path) -> int:
        try:
            with _open(p) as fh:
                return sum(1 for _ in fh)
        except (OSError, EOFError):
            return -1
    return max(paths, key=lambda p: (lines(p), p.suffix != ".gz"))  # more lines wins; plain wins a tie


def mirror_one(src: Path, dest: Path, markets: set[str]) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    kept = 0
    with _open(src) as fh, gzip.open(tmp, "wt", encoding="utf-8") as out:
        for line in fh:
            try:
                q = json.loads(line)
            except ValueError:
                continue
            if q.get("kind") == "prop" and q.get("market") in markets:
                out.write(line if line.endswith("\n") else line + "\n")
                kept += 1
    os.replace(tmp, dest)
    return kept


def preserve(root: Path, *, today: str | None = None, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    today = today or (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()
    summary: dict[str, Any] = {}
    for sport, fam in FAMILIES.items():
        s = {"mirrored": 0, "fresh": 0, "rows": 0}
        for name, paths in sorted(candidates(root, sport, today, now).items()):
            dest = root / MIRROR / sport / "quotes" / f"{name}.jsonl.gz"
            newest = max(p.stat().st_mtime for p in paths)
            if dest.is_file() and dest.stat().st_mtime >= newest:
                s["fresh"] += 1
                continue
            s["rows"] += mirror_one(fuller(paths), dest, fam["markets"])
            s["mirrored"] += 1
        s["held"] = len(list((root / MIRROR / sport / "quotes").glob("*.jsonl.gz")))
        summary[sport] = s
    return summary


def restore(root: Path) -> dict[str, int]:
    restored: dict[str, int] = defaultdict(int)
    for sport in FAMILIES:
        live = root / f"{sport}_source" / "tracking" / "book_quotes"
        for dest in sorted((root / MIRROR / sport / "quotes").glob("*.jsonl.gz")):
            name = _name(dest)
            if (live / f"{name}.jsonl").exists() or (live / f"{name}.jsonl.gz").exists():
                continue
            live.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, live / f"{name}.jsonl.gz")
            restored[sport] += 1
    return dict(restored)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    if args.restore:
        print(f"FORWARD_INPUTS_RESTORE {json.dumps(restore(root), sort_keys=True)}", flush=True)
        return 0
    summary = preserve(root)
    status = {"ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "summary": summary,
              "families": {k: {"markets": sorted(v["markets"]), "tests": v["tests"]} for k, v in FAMILIES.items()}}
    (root / MIRROR).mkdir(parents=True, exist_ok=True)
    (root / MIRROR / "_status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
    print(f"FORWARD_INPUTS {json.dumps(summary, sort_keys=True)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
