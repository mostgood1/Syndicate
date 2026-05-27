from __future__ import annotations

import os
import shutil
from pathlib import Path


def _copy_tree_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    if dst.exists() and any(dst.iterdir()):
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def main() -> int:
    data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data").expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    bundled_data = (repo_root / "data").resolve()

    # Seed the persistent data root from repo-bundled artifacts only when empty.
    _copy_tree_if_missing(bundled_data, data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
