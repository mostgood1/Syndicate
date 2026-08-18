"""Turn the local Statcast pitch-splits CACHE into a publishable ARTIFACT.

`#440`. Measured 2026-08-17: pitch-type effectiveness is fully built, actively
sampled by the sim, and **100% unfed** — `pitch_type_whiff_mult` and
`vs_pitch_type` are empty on 449/450 profiles, so `.get(pitch_type, 1.0)` makes
a slider and a fastball interchangeable.

The data exists (`tools/statcast/fetch_pitcher_pitch_splits_x64.py` fills a
`DiskCache`). **It cannot reach Render**, for three structural reasons recorded
in `deploys.md`:

  1. `default_statcast_cache()` resolves inside the **ephemeral repo checkout**
     (`vendor/mlb_bettingv2/data/cache/statcast`) — the `#389` failure shape;
  2. `vendor/*/data/` is **gitignored**, so it cannot ride a deploy;
  3. nothing on the worker populates it, and the loader is cache-only.

THIS SCRIPT FIXES (1) AND (2). It reads the hash-keyed cache and writes ONE
artifact keyed by pitcher id, in the mirrored artifact tree, where
`artifact_publisher` can ship it and `/api/ops/artifacts/*` can inspect it.

**A `DiskCache` is the wrong shape to publish** — hash-named files carry no
readable key, cannot be diffed, and cannot be validated. The artifact is a plain
`{season, generated_at, pitchers: {id: {...}}}` document on purpose.

(3) remains open: a scheduled populator on the worker. Pitch mix drifts through
a season, so a one-off fill goes stale.

Usage:
  py -3 scripts/build_mlb_pitch_splits_artifact.py --season 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CACHE_DIR = REPO_ROOT / "vendor/mlb_bettingv2/data/cache/statcast/pitcher_pitch_splits"
# Mirrored artifact tree, so `artifact_publisher` + the mirror refresh see it.
REL_OUT = "mlb_source/source_artifacts/data/pitch_splits"


def _data_root() -> Path:
    """The MOUNTED DISK on Render, the repo `data/` locally.

    Uses the same `SYNDICATE_DATA_ROOT` contract as
    `refresh_state_store.data_root()`. Read via env rather than importing that
    module so this stays runnable from the vendor-only context too.
    """
    import os
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(override).expanduser().resolve() if override else (REPO_ROOT / "data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-pitches", type=int, default=200,
                        help="drop thin samples rather than publish a noisy multiplier")
    args = parser.parse_args()

    if not args.cache_dir.is_dir():
        print(f"no cache at {args.cache_dir} — run the x64 populator first")
        return 1

    pitchers: dict[str, dict] = {}
    read = skipped_season = skipped_thin = unreadable = 0
    for path in sorted(args.cache_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            unreadable += 1
            continue
        read += 1
        body = payload.get("value") if isinstance(payload.get("value"), dict) else payload
        try:
            pid = int(body.get("pitcher_id") or 0)
            season = int(body.get("season") or 0)
            n = int(body.get("n_pitches") or 0)
        except (TypeError, ValueError):
            unreadable += 1
            continue
        if pid <= 0 or season != args.season:
            skipped_season += 1
            continue
        if n < args.min_pitches:
            skipped_thin += 1
            continue
        pitchers[str(pid)] = {
            "n_pitches": n,
            "pitch_mix": body.get("pitch_mix") or {},
            "whiff_mult": body.get("whiff_mult") or {},
            "inplay_mult": body.get("inplay_mult") or {},
            "source": body.get("source") or "",
            "start_date": body.get("start_date") or "",
            "end_date": body.get("end_date") or "",
        }

    if not pitchers:
        print(f"REFUSED: read {read} cache files and produced ZERO pitchers "
              f"(season mismatch {skipped_season}, thin {skipped_thin}, "
              f"unreadable {unreadable}). Not writing an empty artifact.")
        return 1

    artifact = {
        "schema_version": 1,
        "season": args.season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "statcast via tools/statcast/fetch_pitcher_pitch_splits_x64.py",
        "min_pitches": args.min_pitches,
        "counts": {"pitchers": len(pitchers), "cache_files_read": read,
                   "skipped_wrong_season": skipped_season,
                   "skipped_thin": skipped_thin, "unreadable": unreadable},
        "pitchers": pitchers,
    }

    out = args.out or (_data_root() / REL_OUT / f"pitch_splits_{args.season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    print("=" * 84)
    print("MLB PITCH-SPLITS ARTIFACT")
    print("=" * 84)
    print(f"\n  cache files read      {read}")
    print(f"  pitchers published    {len(pitchers)}")
    print(f"  skipped wrong season  {skipped_season}")
    print(f"  skipped thin (<{args.min_pitches})  {skipped_thin}")
    print(f"  unreadable            {unreadable}")
    sample = next(iter(pitchers.values()))
    print(f"\n  sample whiff_mult: {json.dumps(sample['whiff_mult'])[:120]}")
    print(f"\nwrote {out}")
    print("\n  NOT YET LIVE: the worker has no populator for this, and the loader")
    print("  must be pointed at the artifact. See deploys.md 2026-08-17.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
