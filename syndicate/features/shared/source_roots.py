from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# WHY THESE ARE CACHED  `[2026-08-29]`
#
# MEASURED, not inferred: a cProfile over soccer's `sport_branch` on
# refresh-worker (`1fbc7a62`, 15:28:22Z) put **`posix.lstat` at 5.050s of a
# 10.92s branch -- 46%**, reached like this:
#
#     build_cards_page_context (20)   7.487 s cum
#       _api_read_path        (177)   4.759
#         preferred_source_roots(177) 4.423
#           Path.resolve()   (1260)   5.624
#             posix.lstat   (7955)    5.050
#
# `Path.resolve()` walks every component of a path and `lstat`s each one. These
# functions call it 4-7 times PER INVOCATION -- `repo_root_from` resolves, the
# env root resolves, `Path(data_root).resolve() / name` resolves AGAIN, and the
# repo fallback resolves once more. 177 invocations became 7,955 syscalls.
#
# **The inputs cannot change inside a process.** `file_path` is a module's
# `__file__`, `env_var`/`local_dir_name` are literals at every call site, and
# Render env vars are injected at boot (a restart does not re-inject them; the
# service must be redeployed). So this is a pure function of things that are
# fixed for the process lifetime.
#
# WHY THE ENV IS IN THE KEY RATHER THAN ASSUMED CONSTANT. Reading four env vars
# is ~microseconds against 7 path resolves, and it keeps the cache CORRECT under
# `monkeypatch.setenv`, which the tests for this module rely on. A cache that is
# only correct in production is how a green suite ships a wrong root. The env
# read stays inside the cached body too -- the fingerprint is a key, not a
# substitute for the logic.
#
# NOT CACHED, deliberately: which root actually HAS a given file. These
# functions return CANDIDATES without probing the filesystem (see
# `preferred_artifact_roots`' own note), and callers do the `.exists()` per
# requested file. Caching the candidate LIST cannot pin a stale answer to
# "where is this artifact"; caching existence would.
def _root_env_fingerprint(env_var: str) -> tuple[str, str, str, str]:
    """Every env value that can change what the functions below return."""
    return (
        str(os.environ.get(env_var) or "").strip(),
        str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip(),
        str(os.environ.get("SYNDICATE_REQUIRE_HOSTED_STORAGE") or "").strip().lower(),
        str(os.environ.get("RENDER") or "").strip().lower(),
    )


def clear_source_root_caches() -> None:
    """For tests that change the filesystem rather than the environment."""
    _repo_root_from_cached.cache_clear()
    _preferred_source_roots_cached.cache_clear()
    _preferred_artifact_roots_cached.cache_clear()


@lru_cache(maxsize=256)
def _repo_root_from_cached(file_path_str: str) -> Path:
    return Path(file_path_str).resolve().parents[3]


def repo_root_from(file_path: str | Path) -> Path:
    # Path is immutable, so handing the same object to every caller is safe.
    return _repo_root_from_cached(str(file_path))

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
    # `list(...)` so every caller still gets its OWN mutable list, exactly as
    # before. Handing out the cached tuple's contents by reference would let one
    # caller's mutation reach every other.
    return list(
        _preferred_source_roots_cached(
            str(file_path), env_var, local_dir_name, _root_env_fingerprint(env_var)
        )
    )


@lru_cache(maxsize=512)
def _preferred_source_roots_cached(
    file_path: str,
    env_var: str,
    local_dir_name: str,
    _env: tuple[str, str, str, str],
) -> tuple[Path, ...]:
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
        return tuple(candidates)

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
    return tuple(deduped)


def preferred_artifact_roots(
    file_path: str | Path,
    *,
    env_var: str,
    local_dir_name: str,
) -> list[Path]:
    return list(
        _preferred_artifact_roots_cached(
            str(file_path), env_var, local_dir_name, _root_env_fingerprint(env_var)
        )
    )


@lru_cache(maxsize=512)
def _preferred_artifact_roots_cached(
    file_path: str,
    env_var: str,
    local_dir_name: str,
    _env: tuple[str, str, str, str],
) -> tuple[Path, ...]:
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

    return tuple(candidates)
