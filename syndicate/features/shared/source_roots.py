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

    def _append_repo_fallback(candidates: list[Path]) -> None:
        if not _strict_hosted_storage_enabled():
            return
        if str(os.environ.get("RENDER") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        repo_fallback = (repo_root_from(file_path) / "data" / local_dir_name).resolve()
        if repo_fallback not in candidates:
            candidates.append(repo_fallback)

    if env_value:
        env_root = Path(env_value).resolve()
        candidates: list[Path] = [env_root]
        _append_repo_fallback(candidates)
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
        repo_mirror = (repo_root / "data" / local_dir_name).resolve()
        if repo_mirror not in candidates:
            candidates.append(repo_mirror)

    _append_repo_fallback(candidates)

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
    # `#310`. A `_has_files()` helper was defined here (and again in
    # `preferred_source_roots`) and CALLED IN NEITHER. Removed rather than
    # documented: dead code shaped exactly like the guard every reader assumes
    # is already in place is worse than no code at all.
    #
    # It is plausibly why `17d4f203` hand-rolled `any(candidate.iterdir())` in
    # `current_odds_root_for_sport` -- reimplementing a helper that was already
    # present, already unused, and already the wrong test. "Does this directory
    # contain anything" is not "does it contain the file you asked for": on
    # production that check passed on a root holding 427 stale files while the
    # requested date's artifacts sat on the next candidate.
    #
    # These functions return CANDIDATES in preference order, deliberately
    # without probing the filesystem. Callers that need a real file resolve per
    # requested file across the list -- see `wnba/sources.py::_strict_artifact_path`
    # and `live_lens_local._artifact_path` (`#309`).
    env_value = str(os.environ.get(env_var) or "").strip()
    repo_root = repo_root_from(file_path)
    candidates: list[Path] = []

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
        local_mirror = (repo_root / "data" / local_dir_name).resolve()
        _append_root(local_mirror / "source_artifacts")
        _append_root(local_mirror)

    return candidates
