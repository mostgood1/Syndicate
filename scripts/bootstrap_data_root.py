from __future__ import annotations

import logging
import os
import shutil
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
    return [(repo_root / relative_root, data_root / relative_root, str(relative_root)) for relative_root in BOOTSTRAP_ROOTS]


def _sync_bootstrap_roots(repo_root: Path, data_root: Path) -> Dict[str, int]:
    counters: Dict[str, int] = {}
    for source_root, destination_root, key in _bootstrap_root_pairs(repo_root, data_root):
        logger.info("Syncing %s -> %s", source_root, destination_root)
        _sync_tree(source_root, destination_root, counters, key)
    return counters


def main() -> int:
    data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data").expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]

    # Merge the Render-critical published artifact roots into the mounted data root on startup.
    logger.info("Bootstrapping data root: repo=%s data_root=%s", repo_root, data_root)
    counters = _sync_bootstrap_roots(repo_root, data_root)

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
