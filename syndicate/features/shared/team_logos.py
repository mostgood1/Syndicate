"""Team logo URLs for every sport, from the committed ESPN branding snapshots.

`[2026-10-08, user item 8: "ensure we have all player images and team logos
available to add to each opportunity line", lane layer2-board-ui-redesign]`

ONE place, so the Layer 2 rows and the game chips cannot disagree. Each sport
already ships `team_branding/<sport>_team_branding.csv` (written by
`scripts/build_team_branding_snapshot.py`; columns `team_id, abbreviation,
location, display_name, ..., logo_url`), and soccer one per league. Read ONCE per
process and cached: no network, and no file IO after the first call -- the
condition the game-chip loan (web-restart-healthz) was granted on, and the only
shape that is safe on web's request path.

Lookup order per name: the normalised display name, location or abbreviation;
then `team_aliases.canonical_team` (the one alias map -- nflverse `LA`/`WAS` vs
ESPN `LAR`/`WSH`, short club names) and the same index again. Unknown -> None,
never a guess: a wrong crest on a betting row reads as a different game.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from syndicate.features.shared.team_branding import read_team_branding_snapshot

_SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab")
_REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _candidate_roots(sport: str) -> list[Path]:
    """Every root the sport's own readers would try, then the repo's `data/`."""
    roots: list[Path] = []
    try:
        if sport == "mlb":
            from syndicate.features.mlb.sources import default_mlb_source_root

            roots.append(default_mlb_source_root())
        elif sport == "nfl":
            from syndicate.features.nfl.sources import default_nfl_source_root

            roots.append(default_nfl_source_root())
        elif sport == "ncaaf":
            from syndicate.features.ncaaf.sources import default_ncaaf_source_root

            roots.append(default_ncaaf_source_root())
        else:
            from syndicate.features.shared.source_roots import preferred_source_roots

            roots.extend(preferred_source_roots(
                __file__, env_var=f"SYNDICATE_{sport.upper()}_SOURCE_ROOT", local_dir_name=f"{sport}_source"
            ))
    except Exception:  # noqa: BLE001 -- a missing root is "no logo", never an error
        pass
    roots.append(_REPO_DATA / f"{sport}_source")
    return roots


def _branding_files(sport: str) -> Iterable[Path]:
    for root in _candidate_roots(sport):
        if sport == "soccer":
            found = sorted(Path(root).glob("*/source_artifacts/data/processed/team_branding/*_team_branding.csv"))
            if found:
                return found
            continue
        path = Path(root) / "source_artifacts" / "data" / "processed" / "team_branding" / f"{sport}_team_branding.csv"
        if path.exists():
            return [path]
    return []


@lru_cache(maxsize=16)
def _index(sport: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _branding_files(sport):
        for row in read_team_branding_snapshot(path):
            url = str(getattr(row, "logo_url", "") or "").strip()
            if not url:
                continue
            for key in (row.display_name, row.location, row.abbreviation):
                normalized = _norm(key)
                if normalized:
                    index.setdefault(normalized, url)
    return index


def logo_url(sport: Any, *names: Any) -> str | None:
    """The team's logo URL from the first name that resolves, else None."""
    slug = str(sport or "").strip().lower()
    if slug not in _SPORTS and slug != "soccer":
        return None
    index = _index(slug)
    if not index:
        return None
    for name in names:
        hit = index.get(_norm(name))
        if hit:
            return hit
    try:
        from syndicate.features.shared.team_aliases import canonical_team
    except Exception:  # noqa: BLE001
        return None
    for name in names:
        if not str(name or "").strip():
            continue
        try:
            canonical = canonical_team(slug, name)
        except Exception:  # noqa: BLE001
            canonical = None
        if canonical:
            hit = index.get(_norm(canonical))
            if hit:
                return hit
    return None


def stamp_row_logos(rows: Any) -> int:
    """Add `home_logo` / `away_logo` to board rows in place. Returns rows stamped.

    Additive keys only; a row that already carries a logo keeps it.
    """
    stamped = 0
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        sport = row.get("sport_slug") or row.get("sport")
        touched = False
        for side in ("home", "away"):
            field = f"{side}_logo"
            if row.get(field):
                continue
            url = logo_url(sport, row.get(f"{side}_team"), row.get(f"{side}_key"))
            if url:
                row[field] = url
                touched = True
        stamped += int(touched)
    return stamped


__all__ = ["logo_url", "stamp_row_logos"]
