"""Where live-lens JSONL artifacts actually live, versus where readers looked.

**The defect this exists to fix, measured 2026-08-31 (lane
`wnba-accuracy-assessment`).** Every WNBA live-accuracy endpoint reported
`signals.exists: false` on every date sampled, while **34 consecutive days of
signals -- 106KB to 1.23MB each, 2026-07-28..2026-08-30 -- sat on the Render
disk**. The producer was healthy the whole time. The readers were opening the
wrong directory.

The split is a real configuration, not a typo. The vendored writer resolves its
output directory from `<SPORT>_LIVE_LENS_DIR`
(`vendor/wnba_betting_repo/app.py::_live_lens_artifacts_dir`), and production
sets it on both the web service and refresh-worker to::

    WNBA_LIVE_LENS_DIR=/opt/render/project/data/wnba_source/source_artifacts/data/live_lens

The Syndicate-side readers, meanwhile, derive their root from
`processed_root()` / `processed_roots()` and append the bare filename, giving
`.../data/processed/live_lens_signals_<date>.jsonl`. Both halves are internally
consistent; they simply never pointed at the same directory. `data/processed/`
is the writer's *default* when the env var is unset, which is why this reads
correctly on a laptop and silently returns nothing in production.

So the rule is: **live-lens JSONL lives in the `live_lens` sibling of
`data/processed`, and CSV artifacts live in `data/processed` itself.** This
module is the single place that knows that, so a reader cannot get it wrong by
constructing a path by hand.

Resolution is ADDITIVE and ordered -- it only ever turns a miss into a hit:

1. `<SPORT>_LIVE_LENS_DIR`, when the root identifies a sport and the env names a
   directory. The sport is taken from the ``<sport>_source`` path component so a
   WNBA read can never resolve against `MLB_LIVE_LENS_DIR`; a filename carries a
   date but not a sport, and cross-sport contamination here would be silent.
2. the `live_lens` sibling of the passed `data/processed` root, which is what
   production's env var resolves to anyway.
3. the passed root itself, which is the local-checkout layout and the writer's
   own default.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Sequence

# Filenames the writer puts in `live_lens/` rather than `processed/`. Matching on
# the filename (not the caller) keeps CSV resolution untouched: no
# `recommendations_*.csv` or `recon_*.csv` has ever lived under `live_lens/`, so
# these extra candidates cannot shadow one.
LIVE_LENS_FILE_PREFIXES = (
    "live_lens_signals_",
    "live_lens_projections_",
)

_LIVE_LENS_DIR_NAME = "live_lens"
_SPORT_ROOT_RE = re.compile(r"([a-z0-9]+)_source", re.IGNORECASE)


def is_live_lens_filename(filename: str) -> bool:
    """True when `filename` belongs in the `live_lens` directory."""
    return str(filename or "").startswith(LIVE_LENS_FILE_PREFIXES)


def _sport_from_root(root: Path) -> str | None:
    """`.../wnba_source/data/processed` -> `wnba`.

    Read from the path rather than passed in, because every caller already has
    the root and none of them has the sport to hand.
    """
    for part in reversed(root.parts):
        match = _SPORT_ROOT_RE.fullmatch(str(part))
        if match:
            return match.group(1).lower()
    return None


def _env_live_lens_dir(root: Path) -> Path | None:
    sport = _sport_from_root(root)
    if not sport:
        return None
    raw = (os.getenv(f"{sport.upper()}_LIVE_LENS_DIR") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser()
    except Exception:
        return None


def live_lens_dirs(root: Path) -> list[Path]:
    """Candidate directories for a live-lens file, given one `data/processed` root.

    Ordered most- to least-likely, de-duplicated, and never empty.
    """
    candidates: list[Path] = []
    env_dir = _env_live_lens_dir(root)
    if env_dir is not None:
        candidates.append(env_dir)
    # `.../data/processed` -> `.../data/live_lens`
    candidates.append(root.parent / _LIVE_LENS_DIR_NAME)
    # Local checkouts and the writer's own default, where the two coincide.
    candidates.append(root)

    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return ordered


def candidate_paths(root: Path | Sequence[Path], filename: str) -> list[Path]:
    """Every path worth trying for `filename`, across every candidate root.

    For a non-live-lens filename this is exactly `root / filename` per root --
    i.e. the previous behaviour, unchanged.
    """
    roots = [Path(root)] if isinstance(root, (str, Path)) else [Path(item) for item in root]
    if not roots:
        raise ValueError("candidate_paths requires at least one candidate root")

    paths: list[Path] = []
    seen: set[str] = set()
    for item in roots:
        directories = live_lens_dirs(item) if is_live_lens_filename(filename) else [item]
        for directory in directories:
            candidate = directory / filename
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            paths.append(candidate)
    return paths


def resolve(root: Path | Sequence[Path], filename: str) -> Path:
    """First candidate that is a real file, else the most likely candidate.

    The fallback matters: several callers report the resolved path in their
    diagnostics on a MISS, and returning `data/processed/...` there is what made
    this defect read as "the producer never ran" for five weeks. The first
    candidate is now the directory the file would be in if it existed.
    """
    candidates = candidate_paths(root, filename)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return candidates[0]
