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
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    candidates: list[Path] = []
    if data_root:
        candidates.append((Path(data_root).resolve() / local_dir_name).resolve())
    local_mirror = (repo_root / "data" / local_dir_name).resolve()
    candidates.append(local_mirror)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped
