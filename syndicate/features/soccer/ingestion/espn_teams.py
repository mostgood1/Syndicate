"""Full-squad rosters via ESPN's public site API.

Team crest/color directory is NOT here -- it's covered by the shared
cross-sport ``syndicate/features/shared/team_branding.py`` pipeline (every
sport gets its crest/colors from the same ESPN teams endpoint, soccer
included; see ``scripts/build_team_branding_snapshot.py``). This module is
for the one thing that pipeline doesn't cover: a per-team roster endpoint
carrying the *entire* squad -- including reserves and backup keepers who
never accumulate meaningful minutes and so never show up in the Understat/
ASA-derived ``players_*.csv`` per-90 rows used for prop allocation. Same
unauthenticated ``site.api.espn.com`` surface already used by
``espn_lineups.py``.
"""

from __future__ import annotations

from typing import Any

import requests

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
# See espn_lineups.py's matching comment for the full history: this same
# custom header was confirmed live 2026-08-05 to 403 from Render for
# fetch_espn_scoreboard's date-ranged query, superseding an earlier,
# narrower probe that had cleared it. Dropped here too for the same
# already-proven-safe reason -- no custom header, same as the 3 other
# already-fixed call sites in this repo.


def fetch_team_roster(league: str, team_id: str, *, timeout: int = 20) -> list[dict[str, Any]]:
    """The full squad ESPN lists for a team -- every rostered player, not
    just those with accumulated per-90 stats."""
    slug = LEAGUE_ESPN_SLUGS[str(league).strip().lower()]
    response = requests.get(f"{_ESPN_BASE}/{slug}/teams/{team_id}/roster", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    athletes = payload.get("athletes") or []
    rows: list[dict[str, Any]] = []
    for athlete in athletes:
        if not isinstance(athlete, dict):
            continue
        position = athlete.get("position") or {}
        headshot = athlete.get("headshot") or {}
        rows.append(
            {
                "player_id": str(athlete.get("id") or ""),
                "player_name": athlete.get("displayName") or athlete.get("fullName") or "",
                "jersey": athlete.get("jersey") or "",
                "position": position.get("displayName") or position.get("name") or "",
                "position_abbreviation": position.get("abbreviation") or "",
                "age": athlete.get("age"),
                "height": athlete.get("height"),
                "weight": athlete.get("weight"),
                "date_of_birth": athlete.get("dateOfBirth") or "",
                "headshot_url": headshot.get("href") or "",
            }
        )
    return rows


__all__ = ["fetch_team_roster"]
