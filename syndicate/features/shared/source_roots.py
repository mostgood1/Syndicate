from __future__ import annotations

import os
from pathlib import Path


def repo_root_from(file_path: str | Path) -> Path:
    return Path(file_path).resolve().parents[3]

def _strict_hosted_storage_enabled() -> bool:
    raw_value = str(os.environ.get("SYNDICATE_REQUIRE_HOSTED_STORAGE") or "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    return str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}


def preferred_source_roots(
    file_path: str | Path,
    *,
    env_var: str,
    local_dir_name: str,
) -> list[Path]:
    env_value = str(os.environ.get(env_var) or "").strip()
    def _has_files(path: Path) -> bool:
        try:
            return path.exists() and path.is_dir() and any(path.iterdir())
        except Exception:
            return path.exists()

    if env_value:
        env_root = Path(env_value).resolve()
        candidates: list[Path] = [env_root]
        if _strict_hosted_storage_enabled() and str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
            repo_fallback = (repo_root_from(file_path) / "data" / local_dir_name).resolve()
            if not _has_files(env_root):
                candidates.append(repo_fallback)
        return candidates

    repo_root = repo_root_from(file_path)
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    candidates: list[Path] = []
    if data_root:
        candidates.append((Path(data_root).resolve() / local_dir_name).resolve())
    if not _strict_hosted_storage_enabled():
        local_mirror = (repo_root / "data" / local_dir_name).resolve()
        candidates.append(local_mirror)
    elif not candidates:
        if str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
            candidates.append((repo_root / "data" / local_dir_name).resolve())
        else:
            raise RuntimeError(
                f"SYNDICATE_DATA_ROOT must be set when strict hosted storage is enabled for {local_dir_name}."
            )
    elif _strict_hosted_storage_enabled() and str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
        if not any(path.exists() and path.is_dir() and any(path.iterdir()) for path in candidates if path.exists() and path.is_dir()):
            repo_mirror = (repo_root / "data" / local_dir_name).resolve()
            if repo_mirror not in candidates:
                candidates.append(repo_mirror)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def preferred_artifact_roots(
    file_path: str | Path,
    *,
    env_var: str,
    local_dir_name: str,
) -> list[Path]:
    env_value = str(os.environ.get(env_var) or "").strip()
    repo_root = repo_root_from(file_path)
    candidates: list[Path] = []

    def _has_files(path: Path) -> bool:
        try:
            return path.exists() and path.is_dir() and any(path.iterdir())
        except Exception:
            return path.exists()

    def _append_root(root: Path) -> None:
        resolved = root.resolve()
        if resolved not in candidates:
            candidates.append(resolved)

    if env_value:
        env_root = Path(env_value).resolve()
        if env_root.name == "source_artifacts":
            _append_root(env_root)
        else:
            _append_root(env_root / "source_artifacts")
            _append_root(env_root)

    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if data_root:
        base_root = (Path(data_root).resolve() / local_dir_name).resolve()
        _append_root(base_root / "source_artifacts")
        _append_root(base_root)

    if not _strict_hosted_storage_enabled():
        local_mirror = (repo_root / "data" / local_dir_name).resolve()
        _append_root(local_mirror / "source_artifacts")
        _append_root(local_mirror)
    elif not candidates:
        if str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
            local_mirror = (repo_root / "data" / local_dir_name).resolve()
            _append_root(local_mirror / "source_artifacts")
            _append_root(local_mirror)
        else:
            raise RuntimeError(
                f"SYNDICATE_DATA_ROOT must be set when strict hosted storage is enabled for {local_dir_name}."
            )

    if _strict_hosted_storage_enabled() and str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}:
        if not any(_has_files(candidate) for candidate in candidates if candidate.exists() and candidate.is_dir()):
            local_mirror = (repo_root / "data" / local_dir_name).resolve()
            _append_root(local_mirror / "source_artifacts")
            _append_root(local_mirror)

    return candidates
