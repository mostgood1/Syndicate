"""Team branding (logo URL + primary/secondary colors) shared across every sport.

Single source for team branding data: ESPN's public, unauthenticated site API
(``site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams``), which
returns both a logo image URL and hex brand colors for every team in one
response. This module only fetches and parses that response and reads/writes
a per-sport CSV snapshot from it -- it does not know about any individual
sport's own source-root conventions (see ``scripts/build_team_branding_snapshot.py``
for the per-sport wiring) and does not embed or upload any image assets;
every logo is a URL pointing back to ESPN's CDN.

Snapshots are generated periodically (like every other CFBD/roster-style
snapshot in this project), not fetched live in the request path -- a sport's
``cards.py`` reads the CSV, it never calls ESPN directly.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

ESPN_SITE_API_BASE = "https://site.api.espn.com/apis/site/v2/sports"

BRANDING_CSV_COLUMNS: tuple[str, ...] = (
    "team_id",
    "abbreviation",
    "location",
    "display_name",
    "primary_color",
    "secondary_color",
    "logo_url",
    "source_snapshot_date",
)


@dataclass(frozen=True)
class TeamBranding:
    team_id: str
    abbreviation: str
    location: str
    display_name: str
    primary_color: str | None
    secondary_color: str | None
    logo_url: str | None
    source_snapshot_date: str

    def to_csv_row(self) -> dict[str, str]:
        payload = asdict(self)
        return {column: str(payload[column] if payload[column] is not None else "") for column in BRANDING_CSV_COLUMNS}

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "TeamBranding":
        return cls(
            team_id=str(row["team_id"]),
            abbreviation=str(row["abbreviation"]),
            location=str(row["location"]),
            display_name=str(row["display_name"]),
            primary_color=(row.get("primary_color") or None),
            secondary_color=(row.get("secondary_color") or None),
            logo_url=(row.get("logo_url") or None),
            source_snapshot_date=str(row["source_snapshot_date"]),
        )


def _normalize_hex_color(value: Any) -> str | None:
    text = str(value or "").strip().lstrip("#").lower()
    if not text or not re.fullmatch(r"[0-9a-f]{6}", text):
        return None
    return f"#{text}"


def _default_logo_url(logos: Any) -> str | None:
    if not isinstance(logos, list):
        return None
    for logo in logos:
        if isinstance(logo, dict) and "default" in (logo.get("rel") or []):
            href = logo.get("href")
            if href:
                return str(href)
    for logo in logos:
        if isinstance(logo, dict) and logo.get("href"):
            return str(logo["href"])
    return None


def parse_espn_teams_payload(payload: dict[str, Any], *, snapshot_date: str) -> list[TeamBranding]:
    rows: list[TeamBranding] = []
    sports = payload.get("sports") if isinstance(payload, dict) else None
    if not isinstance(sports, list):
        return rows
    for sport in sports:
        leagues = (sport or {}).get("leagues") if isinstance(sport, dict) else None
        if not isinstance(leagues, list):
            continue
        for league in leagues:
            teams = (league or {}).get("teams") if isinstance(league, dict) else None
            if not isinstance(teams, list):
                continue
            for entry in teams:
                team = (entry or {}).get("team") if isinstance(entry, dict) else None
                if not isinstance(team, dict) or not team.get("id"):
                    continue
                rows.append(
                    TeamBranding(
                        team_id=str(team["id"]),
                        abbreviation=str(team.get("abbreviation") or ""),
                        location=str(team.get("location") or ""),
                        display_name=str(team.get("displayName") or ""),
                        primary_color=_normalize_hex_color(team.get("color")),
                        secondary_color=_normalize_hex_color(team.get("alternateColor")),
                        logo_url=_default_logo_url(team.get("logos")),
                        source_snapshot_date=snapshot_date,
                    )
                )
    return rows


def fetch_espn_teams(espn_sport_path: str, *, snapshot_date: str, timeout: float = 30.0) -> list[TeamBranding]:
    """``espn_sport_path`` is e.g. ``"basketball/nba"`` or ``"football/college-football"``."""
    url = f"{ESPN_SITE_API_BASE}/{espn_sport_path}/teams?limit=999"
    request = urllib.request.Request(url, headers={"User-Agent": "syndicate-team-branding/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_espn_teams_payload(payload, snapshot_date=snapshot_date)


def write_team_branding_snapshot(rows: Sequence[TeamBranding], *, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BRANDING_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())
    return path


def read_team_branding_snapshot(path: Path) -> tuple[TeamBranding, ...]:
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(TeamBranding.from_csv_row(row) for row in csv.DictReader(handle))


def team_branding_index_by_id(rows: Sequence[TeamBranding]) -> dict[str, TeamBranding]:
    return {row.team_id: row for row in rows}


def team_branding_index_by_abbreviation(rows: Sequence[TeamBranding]) -> dict[str, TeamBranding]:
    return {row.abbreviation.strip().upper(): row for row in rows if row.abbreviation.strip()}


__all__ = [
    "BRANDING_CSV_COLUMNS",
    "ESPN_SITE_API_BASE",
    "TeamBranding",
    "fetch_espn_teams",
    "parse_espn_teams_payload",
    "read_team_branding_snapshot",
    "team_branding_index_by_abbreviation",
    "team_branding_index_by_id",
    "write_team_branding_snapshot",
]
