"""Build the MLB batter-vs-pitcher index Ask reads, on the WORKER, in 64 small shards.

WHY THIS EXISTS -- two production defects, both measured 2026-09-17.

1. **Web aggregated ~70 MB of JSON per pitcher per Ask.** `_mlb_bvp_evidence`
   calls `_bvp_counts_for_pitcher` for the opposing starter AND up to six
   bullpen arms, and each cold call re-read all 47 `statcast_bvp_file_daily`
   index files (72.85 MB in git). Production MLB prop Asks took 16.8 s, 17.1 s
   and 26.0 s (Brett Baty, Nolan McLean, Salvador Perez) against 3.8 s for a
   pitcher prop that skips the bullpen table. `CLAUDE.md`: the web service does
   no heavy computation.

2. **The table said "career, through <today>" over data that ends 2026-05-11.**
   Those index files are a git-tracked cache last written 2026-06-28; measured
   over all 47 files: 1,158 dates, 2021-03-15 .. 2026-05-11, 384,382 pairs. Web
   has no other BvP source -- the daily sim carries no BvP fields at all
   (`daily_summary_2026_09_17*`, 0 matches).

WHAT THIS DOES. Sums per-(pitcher, batter) plate-appearance counts from:

    raw   <data_root>/mlb_source/source_artifacts/data/statcast/raw_pitches/**/statcast_*.csv.gz
          the weekly Statcast job's chunks, ON THE MOUNTED DISK (they survive
          deploys; `refresh_mlb_statcast_features._raw_pitch_root`)
    legacy  the git-tracked daily index files above, for every date the raw
          chunks do not cover (prior seasons, today)

and writes `<data_root>/mlb_source/source_artifacts/data/statcast/bvp/bvp_pairs_NN.json`
for NN = pitcher_id % 64. Web reads one ~150 KB shard per pitcher.

A DATE IS COUNTED FROM ONE SOURCE ONLY. Raw wins for every date it covers;
legacy files overlap each other, so the first legacy file to carry a date owns
it. Double counting would inflate every career line silently.

Memory: one raw chunk or one legacy file is parsed at a time; the accumulator
holds ~384k small tuples (measured pair count), well under the weekly job's
own feature build.
"""

from __future__ import annotations

import argparse
import gzip
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "mlb_bvp_pairs_v1"
SHARDS = 64
FIELDS = ("pa", "hits", "hr", "so", "bb", "hbp", "inplay_pa", "inplay_hits")
INDEX_RELATIVE = Path("mlb_source") / "source_artifacts" / "data" / "statcast" / "bvp"
LEGACY_RELATIVE = Path("mlb_source") / "source_artifacts" / "data" / "cache" / "statcast" / "bvp" / "statcast_bvp_file_daily"
RAW_RELATIVE = Path("mlb_source") / "source_artifacts" / "data" / "statcast" / "raw_pitches"

_HIT = {"single", "double", "triple", "home_run"}
_INPLAY_HIT = {"single", "double", "triple"}
_WALK = {"walk", "intent_walk"}
_HBP = {"hit_by_pitch"}


def data_root() -> Path:
    raw = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(raw).expanduser().resolve() if raw else (REPO_ROOT / "data")


def shard_path(root: Path, pitcher_id: int) -> Path:
    return root / INDEX_RELATIVE / f"bvp_pairs_{int(pitcher_id) % SHARDS:02d}.json"


def _add(acc: dict[tuple[int, int], list[int]], pid: int, bid: int, counts: Iterable[int]) -> None:
    bucket = acc.get((pid, bid))
    if bucket is None:
        acc[(pid, bid)] = list(counts)
        return
    for i, value in enumerate(counts):
        bucket[i] += value


def scan_raw_chunk(path: Path) -> dict[str, dict[tuple[int, int], list[int]]]:
    """date -> (pitcher, batter) -> counts, from one Statcast pitch-level chunk.

    Same event rules as `vendor/mlb_bettingv2/sim_engine/data/statcast_bvp.py`
    `_scan_statcast_file_daily_index`, which wrote the legacy files: a PA is a
    row with a non-empty `events` (the terminal pitch).
    """
    out: dict[str, dict[tuple[int, int], list[int]]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            event = str(row.get("events") or "").strip().lower()
            day = str(row.get("game_date") or "").strip()[:10]
            if not event or len(day) != 10:
                continue
            try:
                pid = int(float(row.get("pitcher") or 0))
                bid = int(float(row.get("batter") or 0))
            except ValueError:
                continue
            if pid <= 0 or bid <= 0:
                continue
            # Exactly the vendor's if/elif chain, so raw and legacy dates count alike:
            # HR, else walk, else HBP, else strikeout*, else a ball in play.
            is_hr = event == "home_run"
            is_bb = not is_hr and event in _WALK
            is_hbp = not is_hr and not is_bb and event in _HBP
            is_so = not (is_hr or is_bb or is_hbp) and event.startswith("strikeout")
            in_play = not (is_hr or is_bb or is_hbp or is_so)
            counts = (
                1,
                1 if event in _HIT else 0,
                1 if is_hr else 0,
                1 if is_so else 0,
                1 if is_bb else 0,
                1 if is_hbp else 0,
                1 if in_play else 0,
                1 if in_play and event in _INPLAY_HIT else 0,
            )
            _add(out.setdefault(day, {}), pid, bid, counts)
    return out


def _legacy_dirs(root: Path) -> list[Path]:
    seen: list[Path] = []
    for candidate in (root / LEGACY_RELATIVE, REPO_ROOT / "data" / LEGACY_RELATIVE):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in seen:
            seen.append(resolved)
    return seen


def build(root: Path, *, raw_root: Path | None = None, legacy_dirs: list[Path] | None = None) -> dict[str, Any]:
    raw_root = raw_root if raw_root is not None else root / RAW_RELATIVE
    legacy_dirs = legacy_dirs if legacy_dirs is not None else _legacy_dirs(root)
    acc: dict[tuple[int, int], list[int]] = {}
    raw_dates: set[str] = set()
    raw_chunks = sorted(raw_root.glob("**/statcast_*.csv.gz")) if raw_root.is_dir() else []
    for chunk in raw_chunks:
        per_date = scan_raw_chunk(chunk)
        for day, pairs in per_date.items():
            if day in raw_dates:
                continue  # overlapping chunk windows: a date counts once
            raw_dates.add(day)
            for (pid, bid), counts in pairs.items():
                _add(acc, pid, bid, counts)

    legacy_dates: set[str] = set()
    legacy_files = 0
    for directory in legacy_dirs:
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            by_date = payload.get("by_date") if isinstance(payload, dict) else None
            if not isinstance(by_date, dict):
                continue
            legacy_files += 1
            for day, pitcher_map in by_date.items():
                day = str(day)[:10]
                if day in raw_dates or day in legacy_dates or not isinstance(pitcher_map, dict):
                    continue
                legacy_dates.add(day)
                for pid_key, batters in pitcher_map.items():
                    if not isinstance(batters, dict):
                        continue
                    try:
                        pid = int(pid_key)
                    except ValueError:
                        continue
                    for bid_key, counts in batters.items():
                        if not isinstance(counts, dict):
                            continue
                        try:
                            bid = int(bid_key)
                            values = tuple(int(counts.get(field) or 0) for field in FIELDS)
                        except (TypeError, ValueError):
                            continue
                        if values[0] > 0:
                            _add(acc, pid, bid, values)
            del payload, by_date

    all_dates = raw_dates | legacy_dates
    shards: list[dict[str, dict[str, list[int]]]] = [{} for _ in range(SHARDS)]
    for (pid, bid), counts in acc.items():
        shards[pid % SHARDS].setdefault(str(pid), {})[str(bid)] = counts
    meta = {
        "schema": SCHEMA,
        "shards": SHARDS,
        "fields": list(FIELDS),
        "first_date": min(all_dates) if all_dates else None,
        "through": max(all_dates) if all_dates else None,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pairs": len(acc),
        "sources": {
            "raw_chunks": len(raw_chunks),
            "raw_dates": [min(raw_dates), max(raw_dates)] if raw_dates else None,
            "legacy_files": legacy_files,
            "legacy_dates": [min(legacy_dates), max(legacy_dates)] if legacy_dates else None,
        },
    }
    if not acc:
        # NEVER write an empty index. Empty shards on disk read as "index
        # present", and Ask would then answer every matchup "no recorded
        # history" instead of falling back to the legacy files.
        return {**meta, "paths": []}
    out_dir = root / INDEX_RELATIVE
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, pitchers in enumerate(shards):
        path = out_dir / f"bvp_pairs_{index:02d}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({**meta, "shard": index, "pitchers": pitchers}, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
        written.append(path)
    return {**meta, "paths": [str(p) for p in written]}


def index_is_missing(root: Path | None = None) -> bool:
    root = root or data_root()
    return not all((root / INDEX_RELATIVE / f"bvp_pairs_{i:02d}.json").is_file() for i in range(SHARDS))


def publish(paths: list[str]) -> int | None:
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifacts
    except Exception as exc:
        print(f"[bvp_index] publish import failed: {type(exc).__name__}", flush=True)
        return None
    return publish_hot_artifacts([Path(p) for p in paths])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--raw-root", default=None)
    args = parser.parse_args(argv)
    root = data_root()
    started = time.time()
    result = build(root, raw_root=Path(args.raw_root) if args.raw_root else None)
    print(
        f"[bvp_index] BUILT pairs={result['pairs']} first={result['first_date']} through={result['through']} "
        f"raw_chunks={result['sources']['raw_chunks']} raw_dates={result['sources']['raw_dates']} "
        f"legacy_files={result['sources']['legacy_files']} legacy_dates={result['sources']['legacy_dates']} "
        f"seconds={time.time() - started:.1f}",
        flush=True,
    )
    if result["pairs"] <= 0:
        print("[bvp_index] FAILED: zero pairs -- no raw chunks and no legacy index found", flush=True)
        return 2
    if not args.no_publish:
        published = publish(result["paths"])
        print(f"[bvp_index] PUBLISHED {published} of {len(result['paths'])} shards", flush=True)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
