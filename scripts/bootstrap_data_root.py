from __future__ import annotations

import os
import shutil
from pathlib import Path


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


def main() -> int:
    data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data").expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    bundled_data = (repo_root / "data").resolve()

    # Merge the repo-bundled public artifacts into the data root on startup.
    _sync_tree(bundled_data, data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
