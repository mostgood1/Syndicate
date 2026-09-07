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
# MODULE SCOPE, and this file just proved why: `_data_root()` read
# `os.environ` before `os` was imported, and `py_compile` reported OK because
# a NameError is a RUNTIME error. Compiling is not a smoke test. The MLB
# checklist carries the same warning from its own incident, where a
# function-local `import os` shadowed the module-scope name and turned a
# diagnostic print into an UnboundLocalError on exactly the failing path.
import os
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


def _data_root() -> Path:
    """The root the app actually reads from.

    THE BUG THIS FIXES, and it is why this file has produced nothing since
    2026-05-12 despite its trigger being live. Every path below used to be
    `REPO_ROOT / "data" / ...` -- the EPHEMERAL CHECKOUT. On the worker that is
    `/opt/render/project/src/data`, which every deploy replaces from git. So:

      * anything this script built was erased by the next deploy, and
      * `is_stale()` read the GIT MIRROR to decide whether to run, and the
        mirror is a checked-in 2026-05-12 file, so the answer was "stale"
        forever and the scrape re-attempted on every eligible tick.

    A job that can never record its own success is a job that runs forever and
    delivers nothing. Same failure shape as the SP+ ratings cache.
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO_ROOT / "data")


def _feature_dirs() -> tuple[Path, ...]:
    """Both candidates get written so whichever one
    `syndicate.features.intelligence._mlb_repo_artifact_path` resolves to
    (source_artifacts-first, then plain root -- see its docstring) is current.

    A FUNCTION, not a module constant, deliberately: the worker imports
    `is_stale` from this module, and a constant computed at import time would
    freeze whatever `SYNDICATE_DATA_ROOT` was when the module first loaded.
    """
    base = _data_root() / "mlb_source"
    return (
        base / "source_artifacts" / "data" / "statcast" / "features",
        base / "data" / "statcast" / "features",
    )


def _raw_pitch_root() -> Path:
    """Where the raw per-week Statcast chunks live.

    ON THE MOUNTED DISK, not the vendor tree, and that is what makes
    `--skip-existing on` mean anything: the chunks survive deploys, so a run
    fetches only the weeks it does not already have. Under the old vendor path
    (`vendor/mlb_bettingv2/data/...`, gitignored AND inside the ephemeral
    checkout) every run re-downloaded the whole season from scratch.

    Deliberately NOT allowlisted for publish -- these are large and nothing off
    this disk reads them. Only the built feature file crosses the wire.
    """
    return (_data_root() / "mlb_source" / "source_artifacts" / "data"
            / "statcast" / "raw_pitches")


def _latest_json_path() -> Path:
    dirs = _feature_dirs()
    for root in dirs:
        candidate = root / "player_features_latest.json"
        if candidate.exists():
            return candidate
    return dirs[0] / "player_features_latest.json"


def is_stale(max_age_days: int, *, season: int | None = None) -> bool:
    """True when the feature file is missing, too old, or FOR THE WRONG SEASON.

    THE SEASON CHECK IS NOT DEFENSIVE PADDING -- it is the actual production
    failure. The file sitting in production reads `"season": 2025` with a
    `generated_at` of 2026-05-12, i.e. LAST season's data. An age-only test
    would have called that current the moment anything rewrote it with a fresh
    timestamp, and the sole consumer (`hr_targets.py`) would still refuse it,
    because it has its own season-match guard. Age and correctness are
    different questions and this now asks both.
    """
    path = _latest_json_path()
    if not path.exists():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta") or {}
        generated_at = datetime.fromisoformat(str(meta["generated_at"]))
    except Exception:
        return True
    if season is not None:
        try:
            if int(meta.get("season")) != int(season):
                return True
        except Exception:
            return True
    return (datetime.now() - generated_at).days > max(0, int(max_age_days))


def _run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def refresh(*, season: int, start_date: str, end_date: str) -> None:
    raw_root = _raw_pitch_root()
    raw_root.mkdir(parents=True, exist_ok=True)
    # `--out-root` / `--raw-root` are passed EXPLICITLY. Both vendor scripts
    # default to `vendor/mlb_bettingv2/data/...`, resolved off `__file__` --
    # gitignored and inside the ephemeral checkout. Letting either default is
    # the whole defect. The vendor scripts themselves are unchanged; they
    # already take these flags.
    _run([
        sys.executable, str(FETCH_SCRIPT),
        "--start-date", start_date, "--end-date", end_date,
        "--out-root", str(raw_root),
        "--skip-existing", "on",
    ])
    _run([
        sys.executable, str(BUILD_SCRIPT),
        "--season", str(season),
        "--start-date", start_date, "--end-date", end_date,
        "--raw-root", str(raw_root),
        "--write-latest",
    ])
    for name in (f"player_features_{season}.json", "player_features_latest.json"):
        src = VENDOR_FEATURES_DIR / name
        if not src.exists():
            print(f"expected build output missing: {src}", flush=True)
            continue
        for dest_root in _feature_dirs():
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_root / name)
            print(f"copied {name} -> {dest_root}", flush=True)


def publish_latest(*, timeout_seconds: int = 180) -> bool | None:
    """Push `player_features_latest.json` to web. None when not configured.

    WHY PUBLISHING IS PART OF THE JOB. Writing the mounted disk makes the file
    survive a deploy on THIS service and nowhere else -- Render gives each
    service its own volume. web serves `/api/ops/artifacts/*`, so without this
    step the artifact is invisible to every reader outside this process, which
    is indistinguishable from never having built it.

    Only `player_features_latest.json` is allowlisted in
    `HOT_ARTIFACT_PATTERNS` (checked with the real predicate, not by eye); the
    season-suffixed copy and the raw pitch chunks are not, and should not be --
    the chunks are large and nothing off this disk reads them.
    """
    rel = "mlb_source/source_artifacts/data/statcast/features/player_features_latest.json"
    src = _data_root() / rel
    if not src.is_file():
        print(f"[statcast_refresh] NOT PUBLISHED -- {src} absent", flush=True)
        return False
    try:
        from syndicate.features.shared import artifact_publisher as ap
    except Exception as exc:
        print(f"[statcast_refresh] publish import failed: {type(exc).__name__}", flush=True)
        return None
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    url = ap._publish_url() or ""  # noqa: SLF001
    if not token or not url:
        # NOT an error: a laptop run has neither, and should still build.
        print("[statcast_refresh] publish skipped -- no ADMIN_TOKEN or publish URL",
              flush=True)
        return None
    ok = ap._publish_streamed(  # noqa: SLF001
        src, relative_path=rel, url=url, token=token, timeout_seconds=timeout_seconds,
        # Name the TOOL when there is no service lane -- this script
        # runs wherever an operator runs it, so every artifact it published
        # reached the receiver as `publisher=unknown` (measured 2026-09-07).
        publisher=ap.publisher_identity_for_tool("refresh_mlb_statcast_features"))
    print(f"[statcast_refresh] publish {rel} -> {ok}", flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=date.today().year)
    ap.add_argument("--start-date", default=f"{date.today().year}-03-01")
    ap.add_argument("--end-date", default=date.today().isoformat())
    ap.add_argument("--max-age-days", type=int, default=7)
    ap.add_argument("--force", action="store_true", help="Skip the staleness check and refresh anyway")
    args = ap.parse_args()

    print(f"[statcast_refresh] data_root {_data_root()}", flush=True)
    print(f"[statcast_refresh] raw_root  {_raw_pitch_root()}", flush=True)
    print(f"[statcast_refresh] features  {_feature_dirs()[0]}", flush=True)

    # `season=` is passed now, so a fresh file for the WRONG season no longer
    # reads as current. That is the actual production state: season 2025.
    if not args.force and not is_stale(args.max_age_days, season=args.season):
        print(f"player_features_latest.json is under {args.max_age_days}d old "
              f"and is for season {args.season}, skipping", flush=True)
        return 0

    refresh(season=args.season, start_date=args.start_date, end_date=args.end_date)
    publish_latest()

    # VERIFY, rather than trust the copy. `refresh()` prints "copied" for each
    # destination, but that is the writer's account of itself -- the same class
    # of claim that let a four-month-old file look maintained.
    after = _latest_json_path()
    try:
        meta = (json.loads(after.read_text(encoding="utf-8")).get("meta") or {})
        print(f"[statcast_refresh] RESULT season={meta.get('season')} "
              f"generated_at={meta.get('generated_at')} path={after}", flush=True)
        if int(meta.get("season") or 0) != int(args.season):
            print(f"[statcast_refresh] FAILED: built season {meta.get('season')}, "
                  f"wanted {args.season}", flush=True)
            return 2
    except Exception as exc:
        print(f"[statcast_refresh] FAILED: cannot read back {after} "
              f"({type(exc).__name__})", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
