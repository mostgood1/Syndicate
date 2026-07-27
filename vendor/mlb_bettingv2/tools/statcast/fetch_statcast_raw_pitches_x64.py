from __future__ import annotations

import argparse
import gzip
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List, Tuple

# Ensure the project root (mlb_bettingv2/) is importable when running this file directly.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _default_raw_root() -> Path:
    return _ROOT / "data" / "raw" / "statcast" / "pitches"


def _week_chunks(start: date, end: date) -> List[Tuple[date, date]]:
    """Split [start, end] into <=7-day chunks, matching pybaseball's own
    recommended query granularity (its statcast() call already chunks
    internally, but writing our own files at the same cadence keeps each
    statcast_{start}_{end}.csv.gz a manageable, resumable size)."""
    chunks: List[Tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=6), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _season_for(d: date) -> int:
    return int(d.year)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Bulk-fetch raw pitch-level Statcast data via pybaseball.statcast() and write it into the "
            "chunked statcast_{start}_{end}.csv.gz layout that sim_engine/data/statcast_bvp.py expects "
            "under data/raw/statcast/pitches/{season}/. Run under the x64 venv (.venv_x64) -- cryptography, "
            "a pybaseball dependency, has no prebuilt ARM64 wheel and fails to build from source here."
        )
    )
    ap.add_argument("--start-date", required=True, help="YYYY-MM-DD, inclusive.")
    ap.add_argument("--end-date", required=True, help="YYYY-MM-DD, inclusive.")
    ap.add_argument(
        "--out-root",
        default=str(_default_raw_root()),
        help="Root dir; files land under <out-root>/<season>/statcast_<start>_<end>.csv.gz",
    )
    ap.add_argument(
        "--skip-existing",
        choices=["on", "off"],
        default="on",
        help="If on, skip a week chunk whose output file already exists (resumable across interrupted runs).",
    )
    ap.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Pause between week-chunk requests to stay polite to the Baseball Savant endpoint pybaseball hits.",
    )
    args = ap.parse_args()

    try:
        from pybaseball import statcast  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "pybaseball import failed. Run this tool under vendor/mlb_bettingv2/.venv_x64/Scripts/python.exe."
        ) from e

    start = date.fromisoformat(str(args.start_date))
    end = date.fromisoformat(str(args.end_date))
    if end < start:
        print("--end-date must be >= --start-date")
        return 2

    out_root = Path(args.out_root)
    chunks = _week_chunks(start, end)
    print(f"Fetching {len(chunks)} week-chunk(s) from {start} to {end}")

    ok = 0
    skipped = 0
    failed = 0
    for i, (c0, c1) in enumerate(chunks, start=1):
        season = _season_for(c0)
        season_dir = out_root / str(season)
        out_path = season_dir / f"statcast_{c0.isoformat()}_{c1.isoformat()}.csv.gz"

        if str(args.skip_existing) == "on" and out_path.exists() and out_path.stat().st_size > 0:
            print(f"[{i}/{len(chunks)}] {c0}..{c1} -> skip (exists: {out_path.name})")
            skipped += 1
            continue

        print(f"[{i}/{len(chunks)}] {c0}..{c1} -> fetching...", flush=True)
        try:
            df = statcast(start_dt=c0.isoformat(), end_dt=c1.isoformat(), verbose=False)
        except Exception as e:
            print(f"[{i}/{len(chunks)}] fetch failed: {type(e).__name__}: {e}")
            failed += 1
            time.sleep(float(args.sleep_seconds))
            continue

        if df is None or len(df) == 0:
            print(f"[{i}/{len(chunks)}] {c0}..{c1} -> empty (no games), skipping write")
            skipped += 1
            time.sleep(float(args.sleep_seconds))
            continue

        season_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        with gzip.open(tmp_path, "wt", encoding="utf-8", newline="") as f:
            df.to_csv(f, index=False)
        tmp_path.replace(out_path)
        print(f"[{i}/{len(chunks)}] {c0}..{c1} -> wrote {len(df)} rows to {out_path.name}")
        ok += 1
        time.sleep(float(args.sleep_seconds))

    print(f"Done: {ok} written, {skipped} skipped, {failed} failed (of {len(chunks)} chunks)")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
