from __future__ import annotations

import datetime as dt
import filecmp
import logging
import os
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Dict


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
    Path("data/nfl_source/source_artifacts"),
    Path("data/nfl_source/manifests"),
    Path("data/ncaaf_source/source_artifacts"),
    Path("data/ncaaf_source/manifests"),
    Path("data/ncaab_source/source_artifacts"),
    Path("data/ncaab_source/manifests"),
    Path("data/wnba_source/source_artifacts"),
    Path("data/wnba_source/manifests"),
    Path("reports/odds_control_plane"),
    Path("reports/intelligence"),
    Path("reports/daily_update/latest"),
    Path("reports/refresh_status/latest"),
)


def _copy_file_if_needed(src: Path, dst: Path) -> None:
    if dst.exists() and dst.is_file():
        try:
            if filecmp.cmp(src, dst, shallow=False):
                logger.debug("skipped unchanged file %s", src)
                return
        except Exception:
            pass
    shutil.copy2(src, dst)
    logger.debug("copied %s -> %s", src, dst)


def _sync_tree(src: Path, dst: Path, counters: Dict[str, int], key: str) -> None:
    if not src.exists() or not src.is_dir():
        logger.debug("source root missing or not a dir: %s", src)
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _sync_tree(item, target, counters, key)
        else:
            _copy_file_if_needed(item, target)
            counters[key] = counters.get(key, 0) + 1


def _bootstrap_root_pairs(repo_root: Path, data_root: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
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
        pairs.append((src, dst, str(relative_root)))
    return pairs


def _sync_bootstrap_roots(repo_root: Path, data_root: Path) -> Dict[str, int]:
    counters: Dict[str, int] = {}
    for source_root, destination_root, key in _bootstrap_root_pairs(repo_root, data_root):
        logger.info("Syncing %s -> %s", source_root, destination_root)
        _sync_tree(source_root, destination_root, counters, key)
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


def _bootstrap_wnba_today_artifacts(repo_root: Path, data_root: Path) -> bool:
    if not _env_bool("SYNDICATE_BOOTSTRAP_ON_START"):
        return False

    today = dt.datetime.now().strftime("%Y-%m-%d")
    target_path = _wnba_today_props_path(data_root, today)
    if target_path.exists():
        return False

    refresh_script = repo_root / "scripts" / "refresh_odds_sources.py"
    if not refresh_script.exists():
        logger.warning("WNBA bootstrap refresh skipped because %s is missing", refresh_script)
        return False

    logger.info("WNBA props artifact missing at %s; refreshing today's WNBA bundle", target_path)
    subprocess.run(
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
            "fast",
        ],
        cwd=str(repo_root),
        env=_prepend_pythonpath(repo_root),
        check=False,
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
    if _env_bool("SYNDICATE_BOOTSTRAP_WNBA_TODAY"):
        _bootstrap_wnba_today_artifacts(repo_root, data_root)

    # Log summary counts
    if counters:
        logger.info("Bootstrap copy summary:")
        total = 0
        for key, count in counters.items():
            logger.info("  %s: %d files copied", key, count)
            total += count
        logger.info("Total files copied: %d", total)
    else:
        logger.info("No files copied by bootstrap (no source roots present or empty)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
