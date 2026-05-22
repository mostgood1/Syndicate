from __future__ import annotations

import os
from pathlib import Path


def repo_root_from(file_path: str | Path) -> Path:
    return Path(file_path).resolve().parents[3]


def preferred_source_roots(
    file_path: str | Path,
    *,
    env_var: str,
    local_dir_name: str,
) -> list[Path]:
    env_value = str(os.environ.get(env_var) or "").strip()
    if env_value:
        return [Path(env_value).resolve()]

    repo_root = repo_root_from(file_path)
    local_mirror = (repo_root / "data" / local_dir_name).resolve()
    return [local_mirror]
