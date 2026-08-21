from __future__ import annotations

import datetime as dt
import filecmp
import logging
import os
import subprocess
import shutil
import sys
from subprocess import DEVNULL
from pathlib import Path
from typing import Dict

from syndicate.features.shared.timezone import central_today_iso


logging.basicConfig()
logger = logging.getLogger("bootstrap_data_root")
logger.setLevel(logging.INFO)

BOOTSTRAP_ROOTS = (
    Path("data/mlb_source/source_artifacts"),
    Path("data/mlb_source/manifests"),
    Path("data/nba_source/source_artifacts"),
    Path("data/nba_source/manifests"),
    Path("data/nhl_source/source_artifacts"),
    Path("data/nhl_source/manifests"),
    # NFL/NCAAF: the whole top-level source root, not just source_artifacts/
    # manifests -- both sports' real SmartSim 2.0 projection artifacts
    # (smartsim2_projections_{season}_wk{week}.csv) and NFL's real
    # schedule_{season}.csv live directly under the top level (confirmed
    # 2026-08-01: neither was ever reaching the web service's persistent
    # disk, since only the two narrower subdirectories were synced -- the
    # committed git checkout only ever contains files git itself tracks, so
    # syncing the whole tree here is safe, not a bulk-copy-everything risk).
    Path("data/nfl_source"),
    Path("data/ncaaf_source"),
    Path("data/ncaab_source/source_artifacts"),
    Path("data/ncaab_source/manifests"),
    Path("data/wnba_source/source_artifacts"),
    Path("data/wnba_source/manifests"),
    Path("data/soccer_source"),
    Path("reports/odds_control_plane"),
    Path("reports/daily_update/latest"),
    Path("reports/refresh_status/latest"),
)

BOOTSTRAP_VENDOR_ROOTS = (
    (Path("vendor/wnba_betting_repo/src"), Path("wnba_source/src")),
)

# NOTHING FROM `reports/intelligence/` IS BOOTSTRAPPED, AND IT MUST STAY THAT WAY.
#
# There used to be a `BOOTSTRAP_FILES` tuple of 8 named intelligence files here,
# plus a block below that globbed `board_snapshot_*.json`,
# `intelligence_state_*.json`, `intelligence_state_history_*.jsonl` and
# `board_state_*.json` into per-date pairs. **Neither ever copied a single
# byte**: both produced FILE pairs, and `_sync_tree` returns immediately for a
# non-directory. They were logged as `Syncing <file> -> <file>` on every boot
# for months with nothing behind it.
#
# They were deleted rather than repaired, because repairing them would have made
# production worse. On the keyvalue backend -- `SYNDICATE_REFRESH_STATE_BACKEND=
# keyvalue` on web AND refresh-worker, read live 2026-08-20 -- every
# `reports/intelligence/**` path is keyvalue-backed: `refresh_state_store.
# _KEYVALUE_EXCLUDED_PATH_MARKERS` is `("migration_runs/",)` and nothing else.
# `read_json_file` on such a path returns from Redis with NO filesystem
# fallback. So a seeded file carries no readable CONTENT.
#
# What it does carry is a FILENAME and an MTIME, and two readers derive dates
# from exactly those:
#   - `pipeline/intelligence_state.py::_intelligence_state_daily_candidates`
#     globs this directory and `_intelligence_state_read_path` returns the first
#     path that EXISTS -- selecting a key by filesystem presence, then reading
#     its value from Redis.
#   - `syndicate/blueprints/intelligence.py` globs it too and, when the keyvalue
#     read misses, falls back to `path.stem` and `st_mtime` to decide what the
#     LATEST date is.
# Seeding the committed mirror's months-old copies would hand both readers dates
# with nothing behind them -- worst on exactly the cold disk the seeding exists
# to help. The date-scoped keyvalue TTL guarantees the matching keys are long
# gone.
#
# THE HISTORY, because it explains why this is safe to delete and why the guard
# test is worth more than the code was. `2fc3673e` (2026-07-03, "Avoid
# bootstrapping the intelligence ledger") was a real incident fix:
# `docs/fix_notes_log.md` records Render instances failing deploy/startup with
# OOM because this script synced the WHOLE `reports/intelligence` tree,
# including a **3.2 GB `evaluation_ledger.jsonl`** the web dyno never needs at
# boot. The fix replaced the directory root with "a small file allowlist for the
# artifacts the app actually reads at runtime".
#
# The allowlist never copied anything. So since 2026-07-03, across every deploy,
# **zero intelligence files have been bootstrapped** -- and no incident has been
# attributed to a missing intelligence seed in the seven weeks since. The
# cold-start story these entries told about themselves is falsified by that
# alone, independently of the keyvalue argument above.
#
# `test_no_bootstrap_pair_points_into_reports_intelligence` is therefore
# STRICTLY SAFER than what it replaces: it forbids the directory root whose
# return would resurrect the 3.2 GB OOM, not just the file pairs.
#
# `test_no_bootstrap_pair_points_into_reports_intelligence` fails if any of it
# comes back.


# The git-tracked `data/**` trees are a COLD-START SAFETY NET, not a snapshot
# of what production computed (CLAUDE.md says so in those words). Everything
# under them is produced by the pipeline on a worker and lands on a service's
# mounted disk; the committed copy is a periodically-refreshed mirror of that,
# and it is routinely weeks old.
#
# So for those roots the DISK WINS. A destination file that already exists was
# put there by the pipeline (or by an earlier cold-start seed of this same
# mirror), and a boot-time copy from the checkout can only ever make it older.
#
# THE INCIDENT THIS COMES FROM, 2026-08-20 (soccer, La Liga). Web's boot-time
# bootstrap ran 21:42:31Z -> 21:43:28Z, reaching `data/soccer_source` at
# 21:43:28.245Z, and overwrote
#   soccer_source/la_liga/api/recommendations/recommendations_2026-08-20.json
# with the committed mirror: `generated_at 2026-07-20T21:33:36`, a MONTH stale,
# `status_state "pre"`, both scores "0". The match (Alaves v Rayo Vallecano) had
# finished 1-1 hours earlier. The same endpoint had served that match correctly
# at 21:42:5xZ -- inside this sync's own window -- and served the month-old copy
# from 21:45Z onward across six consecutive reads. Byte-identical to the
# checkout (sha256 70dbdc0c35585db..., 36,898 bytes), so the provenance is not
# in question. Measured the same evening: 1,114 of the 8,016 hot artifacts web
# was serving were the checkout's copy, across mlb/wnba/nba/nhl/nfl/soccer.
#
# `copy2` PRESERVES THE SOURCE MTIME, which is what made this so hard to see:
# the clobbered file's mtime reads 21:36:27Z -- the checkout's own mtime, six
# minutes BEFORE the last good read of the file it replaced. An mtime that
# predates the write is the fingerprint; a whole-second mtime (Render's checkout
# has 1s granularity, a runtime write has nanoseconds) is the other half of it.
#
# VENDORED CODE IS THE EXCEPTION and keeps the old overwrite behaviour: git owns
# it, no pipeline writes it, and pinning a stale copy on the disk would be the
# bug in the other direction.
SEED_ONLY = "seed_only"        # disk wins: never overwrite an existing file
OVERWRITE = "overwrite"        # git wins: refresh the destination in place


def _force_overwrite_enabled() -> bool:
    """One-shot escape hatch to restore the pre-2026-08-20 behaviour.

    For a DELIBERATE reseed of a disk believed to be corrupt -- not for routine
    operation. It re-arms the overwrite on every root, including the artifact
    trees, so a boot with this set will happily replace live pipeline output
    with the committed mirror.
    """
    return _env_bool("SYNDICATE_BOOTSTRAP_FORCE_OVERWRITE")


def _copy_file_if_needed(src: Path, dst: Path, *, overwrite_existing: bool) -> str:
    """Returns the outcome: "copied", "unchanged", or "kept".

    "kept" means the destination existed, differed from the checkout, and was
    LEFT ALONE because this root is seed-only. That is the whole point of the
    return value -- see `_sync_bootstrap_roots`, which reports it. The counter
    this replaced incremented once per file VISITED and was logged as "files
    copied", so a run that overwrote one file and a run that overwrote thirty
    thousand printed the same number. Nothing anywhere distinguished them.
    """
    if dst.exists() and dst.is_file():
        try:
            if filecmp.cmp(src, dst, shallow=False):
                logger.debug("skipped unchanged file %s", src)
                return "unchanged"
        except Exception:
            pass
        if not overwrite_existing:
            logger.debug("kept existing %s (seed-only root)", dst)
            return "kept"
    shutil.copy2(src, dst)
    logger.debug("copied %s -> %s", src, dst)
    return "copied"


def _sync_tree(
    src: Path,
    dst: Path,
    counters: Dict[str, Dict[str, int]],
    key: str,
    *,
    overwrite_existing: bool,
) -> None:
    if not src.exists() or not src.is_dir():
        logger.debug("source root missing or not a dir: %s", src)
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _sync_tree(item, target, counters, key, overwrite_existing=overwrite_existing)
        else:
            outcome = _copy_file_if_needed(item, target, overwrite_existing=overwrite_existing)
            counters.setdefault(key, {})[outcome] = counters.setdefault(key, {}).get(outcome, 0) + 1


def _bootstrap_root_pairs(
    repo_root: Path, data_root: Path
) -> list[tuple[Path, Path, str, str]]:
    """(source, destination, key, policy) per root.

    The return annotation used to say `list[tuple[Path, Path]]` while the body
    appended 3-tuples, so it never described what a caller got.
    """
    pairs: list[tuple[Path, Path, str, str]] = []
    for relative_root in BOOTSTRAP_ROOTS:
        src = repo_root / relative_root
        # If the relative root begins with a leading 'data' segment, strip it when
        # composing the destination under the mounted data root so we don't create
        # a duplicated 'data/data/...' path. Example: repo 'data/mlb_source' ->
        # dest '/opt/render/project/data/mlb_source'
        parts = list(relative_root.parts)
        if parts and parts[0] == "data":
            dest_relative = Path(*parts[1:]) if len(parts) > 1 else Path('.')
        else:
            dest_relative = relative_root
        dst = data_root / dest_relative
        pairs.append((src, dst, str(relative_root), SEED_ONLY))
    for relative_root, data_relative_root in BOOTSTRAP_VENDOR_ROOTS:
        src = repo_root / relative_root
        dst = data_root / data_relative_root
        pairs.append((src, dst, str(relative_root), OVERWRITE))
    return pairs


def _sync_bootstrap_roots(repo_root: Path, data_root: Path) -> Dict[str, Dict[str, int]]:
    # Each root synced independently, on purpose: app.py's caller wraps the
    # whole of main() in a bare `except Exception: pass`, so one unhandled
    # exception here used to silently abort every root after it in
    # BOOTSTRAP_ROOTS -- confirmed live 2026-08-01: soccer_source (listed
    # last among the per-sport roots, after mlb/nba/nhl/nfl/ncaaf/ncaab) was
    # never reaching web's disk, including its players_<season>.csv roster
    # seed -- degrading MLS player-prop generation to zero rows with no
    # error visible anywhere (build_soccer_artifacts.py's own
    # SOCCER_PLAYER_ROWS_MISSING print exists for exactly this shape, but
    # never printed because the sync never got that far). Nothing upstream
    # of soccer was ever proven to be the actual failure; isolating each
    # root removes the whole class of "root N's failure hides root N+1..end"
    # bug regardless of which root eventually throws.
    counters: Dict[str, Dict[str, int]] = {}
    forced = _force_overwrite_enabled()
    if forced:
        logger.warning(
            "SYNDICATE_BOOTSTRAP_FORCE_OVERWRITE is set: EVERY root will overwrite existing "
            "destination files, including live pipeline output, with the committed mirror."
        )
    for source_root, destination_root, key, policy in _bootstrap_root_pairs(repo_root, data_root):
        overwrite_existing = forced or policy == OVERWRITE
        logger.info(
            "Syncing %s -> %s (policy=%s)",
            source_root,
            destination_root,
            OVERWRITE if overwrite_existing else SEED_ONLY,
        )
        if source_root.exists() and not source_root.is_dir():
            # A TRIPWIRE, not a feature. `_sync_tree` returns immediately for
            # a non-directory, so any FILE pair added to this list silently
            # copies nothing while still logging "Syncing ..." above -- which is
            # how the intelligence entries deleted at the top of this file sat
            # inert for months looking busy. No pair produces a file today; if
            # one ever does, it says so instead of vanishing.
            counters.setdefault(key, {})["inert_file_entry"] = 1
            continue
        try:
            _sync_tree(source_root, destination_root, counters, key, overwrite_existing=overwrite_existing)
        except Exception as exc:
            logger.warning("Bootstrap sync failed for root %s (%s -> %s): %s", key, source_root, destination_root, exc)
    return counters


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _prepend_pythonpath(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    repo_root_text = str(repo_root)
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    if existing_pythonpath:
        env["PYTHONPATH"] = repo_root_text + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = repo_root_text
    return env


def _wnba_today_props_path(data_root: Path, date_str: str) -> Path:
    return data_root / "wnba_source" / "source_artifacts" / "data" / "processed" / f"props_recommendations_top_by_game_{date_str}.json"


def _wnba_today_bundle_paths(data_root: Path, date_str: str) -> list[Path]:
    processed_root = data_root / "wnba_source" / "source_artifacts" / "data" / "processed"
    return [
        processed_root / f"game_cards_{date_str}.csv",
        processed_root / f"recommendations_slate_{date_str}.json",
        processed_root / f"cards_sim_detail_{date_str}.json",
        processed_root / f"cards_props_snapshot_{date_str}.json",
    ]


def _wnba_today_bundle_ready(data_root: Path, date_str: str) -> bool:
    required_paths = [_wnba_today_props_path(data_root, date_str), *_wnba_today_bundle_paths(data_root, date_str)]
    for path in required_paths:
        try:
            if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
                return False
        except OSError:
            return False
    return True


def _wnba_refresh_source_root(repo_root: Path) -> Path:
    vendor_root = repo_root / "vendor" / "wnba_betting_repo"
    if vendor_root.exists() and vendor_root.is_dir():
        return vendor_root
    return repo_root / "data" / "wnba_source"


def _bootstrap_wnba_today_artifacts(repo_root: Path, data_root: Path) -> bool:
    if not _env_bool("SYNDICATE_BOOTSTRAP_ON_START"):
        return False
    if not _env_bool("SYNDICATE_BOOTSTRAP_WNBA_TODAY"):
        return False

    today = central_today_iso()
    if _wnba_today_bundle_ready(data_root, today):
        return False

    target_path = _wnba_today_props_path(data_root, today)

    refresh_script = repo_root / "scripts" / "refresh_odds_sources.py"
    if not refresh_script.exists():
        logger.warning("WNBA bootstrap refresh skipped because %s is missing", refresh_script)
        return False

    logger.info("WNBA props artifact missing at %s; refreshing today's WNBA bundle", target_path)
    env = _prepend_pythonpath(repo_root)
    env["SYNDICATE_WNBA_SOURCE_APP_FALLBACK"] = "1"
    env["SYNDICATE_SOURCE_ROOT_WNBA"] = str(_wnba_refresh_source_root(repo_root))
    subprocess.Popen(
        [
            sys.executable,
            str(refresh_script),
            "--date",
            today,
            "--sports",
            "wnba",
            "--phase",
            "all",
            "--execution-mode",
            "source",
            "--skip-mirror",
            "--mode",
            "full",
        ],
        cwd=str(repo_root),
        env=env,
        stdout=DEVNULL,
        stderr=DEVNULL,
        start_new_session=True,
    )
    return True


def _intelligence_latest_state_path(data_root: Path) -> Path:
    return data_root / "reports" / "intelligence" / "latest_state.json"


def main() -> int:
    data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data").expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]

    intelligence_latest_state_path = _intelligence_latest_state_path(data_root)
    if intelligence_latest_state_path.exists():
        logger.info("Intelligence state already exists at %s; continuing bootstrap sync", intelligence_latest_state_path)

    # Merge the Render-critical published artifact roots into the mounted data root on startup.
    logger.info("Bootstrapping data root: repo=%s data_root=%s", repo_root, data_root)
    counters = _sync_bootstrap_roots(repo_root, data_root)
    if _env_bool("SYNDICATE_BOOTSTRAP_ON_START"):
        _bootstrap_wnba_today_artifacts(repo_root, data_root)

    # Log summary counts.
    #
    # The line this replaces read "  %s: %d files copied" against a counter
    # incremented once per file VISITED, so it reported 33,379 "copied" on a run
    # that copied a handful. That number is in the production logs for every
    # deploy this year and it never meant what it said -- which is why a boot
    # that replaced a live artifact with a month-old mirror looked exactly like
    # a boot that did nothing.
    if counters:
        logger.info("Bootstrap copy summary (copied = written, kept = existing file left alone):")
        totals: Dict[str, int] = {}
        for key, outcomes in counters.items():
            logger.info(
                "  %s: copied=%d unchanged=%d kept=%d%s",
                key,
                outcomes.get("copied", 0),
                outcomes.get("unchanged", 0),
                outcomes.get("kept", 0),
                "  [INERT: file entry, never synced]" if outcomes.get("inert_file_entry") else "",
            )
            for outcome, count in outcomes.items():
                totals[outcome] = totals.get(outcome, 0) + count
        logger.info(
            "Bootstrap totals: copied=%d unchanged=%d kept=%d",
            totals.get("copied", 0),
            totals.get("unchanged", 0),
            totals.get("kept", 0),
        )
        if totals.get("kept", 0):
            logger.info(
                "%d destination file(s) were NEWER-OR-DIFFERENT pipeline output and were not "
                "overwritten by the committed mirror.",
                totals["kept"],
            )
    else:
        logger.info("No files copied by bootstrap (no source roots present or empty)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
