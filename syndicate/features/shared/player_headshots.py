"""Player headshot URLs for Layer 2 prop rows beyond MLB and NFL.

`[2026-10-08, user item 8: "ensure we have all player images ... available to
add to each opportunity line" -- then "build the charts and headshots", lane
layer2-board-ui-redesign]`

Each sport maps a player NAME to the id its image CDN uses, from files the fleet
already holds (verified on ~/syndicate-prod/data 2026-10-08), read once per
process and cached:

  * NHL   -- newest `roster_snapshot_*.csv` (`full_name, player_id`) ->
             `assets.nhle.com/mugs/nhl/latest/{id}.png`. NOT `/{year}/{TEAM}/`:
             `nhl/cards.py::_nhl_headshot_url` builds `/2026/TOR/...`, which
             answered 302 for Auston Matthews where `/latest/8479318.png` and
             `/20252026/TOR/...` answered 200 (measured 2026-10-08). `latest`
             also needs no team, so a traded player still resolves.
  * NBA / WNBA -- `home._basketball_resolve_player_id` (the existing index:
             nba player_ids.csv, wnba boxscores) -> cdn.nba.com / cdn.wnba.com.
  * NCAAF -- `ncaaf_roster_snapshot.csv` (`player_id` IS the ESPN athlete id:
             Arch Manning 4870906 -> 200 on the ESPN college-football path),
             disambiguated by the row's two teams through the ESPN team ids in
             the NCAAF branding CSV.
  * Soccer -- the league rosters' own `headshot_url` where ESPN filled it
             (partial: e.g. EPL 38/623); no constructed fallback, which 404s.
  * NCAAB -- no roster source exists; none.

A name that maps to more than one player is DROPPED, never guessed: a wrong
face on a betting row is worse than the team crest the page falls back to.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _roots(sport: str) -> list[Path]:
    roots: list[Path] = []
    try:
        if sport == "ncaaf":
            from syndicate.features.ncaaf.sources import default_ncaaf_source_root

            roots.append(default_ncaaf_source_root())
        else:
            from syndicate.features.shared.source_roots import preferred_source_roots

            roots.extend(preferred_source_roots(
                __file__, env_var=f"SYNDICATE_{sport.upper()}_SOURCE_ROOT", local_dir_name=f"{sport}_source"
            ))
    except Exception:  # noqa: BLE001
        pass
    roots.append(_REPO_DATA / f"{sport}_source")
    return roots


def _read_csv(path: Path) -> Iterable[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)
    except OSError:
        return


def _unique(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """name -> value, dropping any name seen with two different values."""
    out: dict[str, str] = {}
    clash: set[str] = set()
    for name, value in pairs:
        if not name or not value or name in clash:
            continue
        if name in out and out[name] != value:
            clash.add(name)
            out.pop(name, None)
            continue
        out[name] = value
    return out


@lru_cache(maxsize=1)
def _nhl_ids() -> dict[str, str]:
    for root in _roots("nhl"):
        found = sorted(Path(root).glob("source_artifacts/data/processed/roster_snapshot_*.csv"))
        found += sorted(Path(root).glob("data/processed/roster_snapshot_*.csv"))
        if found:
            newest = max(found, key=lambda p: p.name)
            return _unique((_norm(r.get("full_name") or r.get("player")), str(r.get("player_id") or "").strip())
                           for r in _read_csv(newest) if str(r.get("player_id") or "").strip().isdigit())
    return {}


@lru_cache(maxsize=1)
def _ncaaf_index() -> tuple[dict[tuple[str, str], str], dict[str, str], dict[str, str]]:
    """((team_id, name) -> id, name -> id if unique, team name -> team_id)."""
    by_team: dict[tuple[str, str], str] = {}
    pairs: list[tuple[str, str]] = []
    teams: dict[str, str] = {}
    for root in _roots("ncaaf"):
        roster = Path(root) / "source_artifacts" / "data" / "processed" / "roster" / "ncaaf_roster_snapshot.csv"
        if not roster.exists():
            continue
        for r in _read_csv(roster):
            pid, name, team = str(r.get("player_id") or "").strip(), _norm(r.get("player_name")), str(r.get("team_id") or "").strip()
            if pid.isdigit() and name:
                by_team.setdefault((team, name), pid)
                pairs.append((name, pid))
        branding = Path(root) / "source_artifacts" / "data" / "processed" / "team_branding" / "ncaaf_team_branding.csv"
        for r in _read_csv(branding):
            tid = str(r.get("team_id") or "").strip()
            for key in (r.get("display_name"), r.get("location")):
                if tid and _norm(key):
                    teams.setdefault(_norm(key), tid)
        break
    return by_team, _unique(pairs), teams


@lru_cache(maxsize=1)
def _soccer_urls() -> dict[str, str]:
    for root in _roots("soccer"):
        files = sorted(Path(root).glob("*/api/rosters/rosters_*.csv"))
        if files:
            return _unique((_norm(r.get("player_name")), str(r.get("headshot_url") or "").strip())
                           for path in files for r in _read_csv(path))
    return {}


def headshot_url(row: Mapping[str, Any]) -> str | None:
    """The player's headshot for a prop row, or None. Never raises."""
    try:
        player = str(row.get("player_name") or "").strip()
        sport = str(row.get("sport") or "").strip().lower()
        if not player:
            return None
        if sport == "nhl":
            pid = _nhl_ids().get(_norm(player))
            return f"https://assets.nhle.com/mugs/nhl/latest/{pid}.png" if pid else None
        if sport in {"nba", "wnba"}:
            from syndicate.blueprints.home import _basketball_resolve_player_id

            pid = _basketball_resolve_player_id(sport, player_name=player)
            if pid is None:
                return None
            if sport == "wnba":
                return f"https://cdn.wnba.com/headshots/wnba/latest/1040x760/{pid}.png"
            return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png"
        if sport == "ncaaf":
            by_team, unique, teams = _ncaaf_index()
            name = _norm(player)
            for side in ("home", "away"):
                tid = teams.get(_norm(row.get(f"{side}_team"))) or teams.get(_norm(row.get(f"{side}_key")))
                if tid and (tid, name) in by_team:
                    return f"https://a.espncdn.com/i/headshots/college-football/players/full/{by_team[(tid, name)]}.png"
            pid = unique.get(name)
            return f"https://a.espncdn.com/i/headshots/college-football/players/full/{pid}.png" if pid else None
        if sport == "soccer":
            return _soccer_urls().get(_norm(player)) or None
    except Exception:  # noqa: BLE001 -- a face must never break a card
        return None
    return None


__all__ = ["headshot_url"]
