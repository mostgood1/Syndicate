"""Shared helper for computing a cache-busting `?v=` asset_version value
from the mtimes of a sport's own cards-source static assets.

Added 2026-08-03 (Phase 3 item 10, shell consolidation). mlb.py/nba.py/
nhl.py each had their own copy of the exact same mtime-hashing logic --
pure duplication -- differing only in which files they hash (a genuinely
sport-specific list: MLB and NHL include shared/polling.js, NBA doesn't;
each includes its own sport-specific CSS/JS bundle). This replaces the
duplicated mechanics while keeping each caller's file list separate.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_ROOT = Path(__file__).resolve().parents[2] / "static"


def cards_source_asset_version(*relative_paths: str) -> str:
    """Latest mtime (nanoseconds, as a string) across the given paths,
    each relative to the static/ root (e.g. "mlb/cards_source.js").
    "1" if none of the paths exist -- same fallback every prior copy of
    this logic used."""
    mtimes: list[int] = []
    for relative_path in relative_paths:
        try:
            mtimes.append(int((_STATIC_ROOT / relative_path).stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "1"


__all__ = ["cards_source_asset_version"]
