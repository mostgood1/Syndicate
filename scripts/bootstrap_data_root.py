from __future__ import annotations

import os
import shutil
from pathlib import Path


BOOTSTRAP_ROOTS = (
    Path("data/mlb_source/source_artifacts"),
    Path("data/mlb_source/manifests"),
    Path("data/nhl_source/source_artifacts"),
    Path("data/nhl_source/manifests"),
    Path("reports/intelligence"),
    Path("reports/daily_update/latest"),
    Path("reports/refresh_status/latest"),
)


def _copy_file_if_needed(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)


def _sync_tree(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _sync_tree(item, target)
        else:
            _copy_file_if_needed(item, target)


def _bootstrap_root_pairs(repo_root: Path, data_root: Path) -> list[tuple[Path, Path]]:
    return [(repo_root / relative_root, data_root / relative_root) for relative_root in BOOTSTRAP_ROOTS]


def _sync_bootstrap_roots(repo_root: Path, data_root: Path) -> None:
    for source_root, destination_root in _bootstrap_root_pairs(repo_root, data_root):
        _sync_tree(source_root, destination_root)


def main() -> int:
    data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data").expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]

    # Merge the Render-critical published artifact roots into the mounted data root on startup.
    _sync_bootstrap_roots(repo_root, data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
