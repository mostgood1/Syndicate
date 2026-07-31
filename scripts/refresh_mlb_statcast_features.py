from __future__ import annotations

"""Keep the MLB Statcast player-feature file (whiff/barrel/xwOBA/pitch-mix per
player, consumed by syndicate/features/intelligence.py and Ask The Syndicate)
current.

The vendor mlb_bettingv2 fetch+build pipeline always writes into
vendor/mlb_bettingv2/data/, not into the mlb_source artifact roots the app
actually reads from -- this script wraps that pipeline and copies the result
into place. Meant to run on a weekly cadence (the underlying Statcast scrape
is too slow/heavy for a daily job), gated by a staleness check so a run with
nothing new to do is a no-op.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPO_ROOT / "vendor" / "mlb_bettingv2"
FETCH_SCRIPT = VENDOR_ROOT / "tools" / "statcast" / "fetch_statcast_raw_pitches_x64.py"
BUILD_SCRIPT = VENDOR_ROOT / "tools" / "datasets" / "build_statcast_player_feature_set.py"
VENDOR_FEATURES_DIR = VENDOR_ROOT / "data" / "statcast" / "features"

# Both candidates get written so whichever one syndicate.features.intelligence
# ._mlb_repo_artifact_path resolves to (source_artifacts-first, then plain
# root -- see its docstring) is current.
MLB_SOURCE_CANDIDATES = (
    REPO_ROOT / "data" / "mlb_source" / "source_artifacts" / "data" / "statcast" / "features",
    REPO_ROOT / "data" / "mlb_source" / "data" / "statcast" / "features",
)


def _latest_json_path() -> Path:
    for root in MLB_SOURCE_CANDIDATES:
        candidate = root / "player_features_latest.json"
        if candidate.exists():
            return candidate
    return MLB_SOURCE_CANDIDATES[0] / "player_features_latest.json"


def is_stale(max_age_days: int) -> bool:
    """True when the feature file is missing or its generated_at is older
    than max_age_days."""
    path = _latest_json_path()
    if not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["meta"]["generated_at"]))
    except Exception:
        return True
    return (datetime.now() - generated_at).days > max(0, int(max_age_days))


def _run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def refresh(*, season: int, start_date: str, end_date: str) -> None:
    _run([
        sys.executable, str(FETCH_SCRIPT),
        "--start-date", start_date, "--end-date", end_date,
        "--skip-existing", "on",
    ])
    _run([
        sys.executable, str(BUILD_SCRIPT),
        "--season", str(season),
        "--start-date", start_date, "--end-date", end_date,
        "--write-latest",
    ])
    for name in (f"player_features_{season}.json", "player_features_latest.json"):
        src = VENDOR_FEATURES_DIR / name
        if not src.exists():
            print(f"expected build output missing: {src}", flush=True)
            continue
        for dest_root in MLB_SOURCE_CANDIDATES:
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_root / name)
            print(f"copied {name} -> {dest_root}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=date.today().year)
    ap.add_argument("--start-date", default=f"{date.today().year}-03-01")
    ap.add_argument("--end-date", default=date.today().isoformat())
    ap.add_argument("--max-age-days", type=int, default=7)
    ap.add_argument("--force", action="store_true", help="Skip the staleness check and refresh anyway")
    args = ap.parse_args()

    if not args.force and not is_stale(args.max_age_days):
        print(f"player_features_latest.json is under {args.max_age_days}d old, skipping", flush=True)
        return 0

    refresh(season=args.season, start_date=args.start_date, end_date=args.end_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
