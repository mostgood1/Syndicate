from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


def _normalize_team_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper().strip())


@dataclass(frozen=True)
class TeamIdentity:
    team_abbr: str
    team_name: str
    franchise_name: str
    city: str
    conference: str
    division: str
    aliases: tuple[str, ...]


_TEAM_IDENTITY_ROWS: tuple[TeamIdentity, ...] = (
    TeamIdentity("ARI", "Arizona Cardinals", "Arizona Cardinals", "Arizona", "NFC", "NFC West", ("ARI", "ARIZONA CARDINALS", "ARIZONA", "CARDINALS")),
    TeamIdentity("ATL", "Atlanta Falcons", "Atlanta Falcons", "Atlanta", "NFC", "NFC South", ("ATL", "ATLANTA FALCONS", "ATLANTA", "FALCONS")),
    TeamIdentity("BAL", "Baltimore Ravens", "Baltimore Ravens", "Baltimore", "AFC", "AFC North", ("BAL", "BALTIMORE RAVENS", "BALTIMORE", "RAVENS")),
    TeamIdentity("BUF", "Buffalo Bills", "Buffalo Bills", "Buffalo", "AFC", "AFC East", ("BUF", "BUFFALO BILLS", "BUFFALO", "BILLS")),
    TeamIdentity("CAR", "Carolina Panthers", "Carolina Panthers", "Carolina", "NFC", "NFC South", ("CAR", "CAROLINA PANTHERS", "CAROLINA", "PANTHERS")),
    TeamIdentity("CHI", "Chicago Bears", "Chicago Bears", "Chicago", "NFC", "NFC North", ("CHI", "CHICAGO BEARS", "CHICAGO", "BEARS")),
    TeamIdentity("CIN", "Cincinnati Bengals", "Cincinnati Bengals", "Cincinnati", "AFC", "AFC North", ("CIN", "CINCINNATI BENGALS", "CINCINNATI", "BENGALS")),
    TeamIdentity("CLE", "Cleveland Browns", "Cleveland Browns", "Cleveland", "AFC", "AFC North", ("CLE", "CLEVELAND BROWNS", "CLEVELAND", "BROWNS")),
    TeamIdentity("DAL", "Dallas Cowboys", "Dallas Cowboys", "Dallas", "NFC", "NFC East", ("DAL", "DALLAS COWBOYS", "DALLAS", "COWBOYS")),
    TeamIdentity("DEN", "Denver Broncos", "Denver Broncos", "Denver", "AFC", "AFC West", ("DEN", "DENVER BRONCOS", "DENVER", "BRONCOS")),
    TeamIdentity("DET", "Detroit Lions", "Detroit Lions", "Detroit", "NFC", "NFC North", ("DET", "DETROIT LIONS", "DETROIT", "LIONS")),
    TeamIdentity("GB", "Green Bay Packers", "Green Bay Packers", "Green Bay", "NFC", "NFC North", ("GB", "GREEN BAY PACKERS", "GREEN BAY", "PACKERS")),
    TeamIdentity("HOU", "Houston Texans", "Houston Texans", "Houston", "AFC", "AFC South", ("HOU", "HOUSTON TEXANS", "HOUSTON", "TEXANS")),
    TeamIdentity("IND", "Indianapolis Colts", "Indianapolis Colts", "Indianapolis", "AFC", "AFC South", ("IND", "INDIANAPOLIS COLTS", "INDIANAPOLIS", "COLTS")),
    TeamIdentity("JAX", "Jacksonville Jaguars", "Jacksonville Jaguars", "Jacksonville", "AFC", "AFC South", ("JAX", "JACKSONVILLE JAGUARS", "JACKSONVILLE", "JAGUARS")),
    TeamIdentity("KC", "Kansas City Chiefs", "Kansas City Chiefs", "Kansas City", "AFC", "AFC West", ("KC", "KANSAS CITY CHIEFS", "KANSAS CITY", "CHIEFS")),
    TeamIdentity("LV", "Las Vegas Raiders", "Las Vegas Raiders", "Las Vegas", "AFC", "AFC West", ("LV", "LAS VEGAS RAIDERS", "LAS VEGAS", "RAIDERS", "OAKLAND RAIDERS")),
    TeamIdentity("LAC", "Los Angeles Chargers", "Los Angeles Chargers", "Los Angeles", "AFC", "AFC West", ("LAC", "LOS ANGELES CHARGERS", "LOS ANGELES", "CHARGERS", "SAN DIEGO CHARGERS")),
    TeamIdentity("LA", "Los Angeles Rams", "Los Angeles Rams", "Los Angeles", "NFC", "NFC West", ("LA", "LOS ANGELES RAMS", "LOS ANGELES", "RAMS", "ST LOUIS RAMS", "ST. LOUIS RAMS")),
    TeamIdentity("MIA", "Miami Dolphins", "Miami Dolphins", "Miami", "AFC", "AFC East", ("MIA", "MIAMI DOLPHINS", "MIAMI", "DOLPHINS")),
    TeamIdentity("MIN", "Minnesota Vikings", "Minnesota Vikings", "Minnesota", "NFC", "NFC North", ("MIN", "MINNESOTA VIKINGS", "MINNESOTA", "VIKINGS")),
    TeamIdentity("NE", "New England Patriots", "New England Patriots", "New England", "AFC", "AFC East", ("NE", "NEW ENGLAND PATRIOTS", "NEW ENGLAND", "PATRIOTS")),
    TeamIdentity("NO", "New Orleans Saints", "New Orleans Saints", "New Orleans", "NFC", "NFC South", ("NO", "NEW ORLEANS SAINTS", "NEW ORLEANS", "SAINTS")),
    TeamIdentity("NYG", "New York Giants", "New York Giants", "New York", "NFC", "NFC East", ("NYG", "NEW YORK GIANTS", "NEW YORK", "GIANTS")),
    TeamIdentity("NYJ", "New York Jets", "New York Jets", "New York", "AFC", "AFC East", ("NYJ", "NEW YORK JETS", "NEW YORK", "JETS")),
    TeamIdentity("PHI", "Philadelphia Eagles", "Philadelphia Eagles", "Philadelphia", "NFC", "NFC East", ("PHI", "PHILADELPHIA EAGLES", "PHILADELPHIA", "EAGLES")),
    TeamIdentity("PIT", "Pittsburgh Steelers", "Pittsburgh Steelers", "Pittsburgh", "AFC", "AFC North", ("PIT", "PITTSBURGH STEELERS", "PITTSBURGH", "STEELERS")),
    TeamIdentity("SEA", "Seattle Seahawks", "Seattle Seahawks", "Seattle", "NFC", "NFC West", ("SEA", "SEATTLE SEAHAWKS", "SEATTLE", "SEAHAWKS")),
    TeamIdentity("SF", "San Francisco 49ers", "San Francisco 49ers", "San Francisco", "NFC", "NFC West", ("SF", "SAN FRANCISCO 49ERS", "SAN FRANCISCO", "49ERS", "SANFRANCISCOERS")),
    TeamIdentity("TB", "Tampa Bay Buccaneers", "Tampa Bay Buccaneers", "Tampa Bay", "NFC", "NFC South", ("TB", "TAMPA BAY BUCCANEERS", "TAMPA BAY", "BUCCANEERS")),
    TeamIdentity("TEN", "Tennessee Titans", "Tennessee Titans", "Tennessee", "AFC", "AFC South", ("TEN", "TENNESSEE TITANS", "TENNESSEE", "TITANS")),
    TeamIdentity("WAS", "Washington Commanders", "Washington Commanders", "Washington", "NFC", "NFC East", ("WAS", "WASHINGTON COMMANDERS", "WASHINGTON", "COMMANDERS", "WASHINGTON FOOTBALL TEAM", "WASHINGTON REDSKINS")),
)


_TEAM_IDENTITY_BY_ABBR = {row.team_abbr: row for row in _TEAM_IDENTITY_ROWS}
_TEAM_IDENTITY_BY_ALIAS = {
    alias: row.team_abbr
    for row in _TEAM_IDENTITY_ROWS
    for alias in (*row.aliases, _normalize_team_text(row.team_name), _normalize_team_text(row.franchise_name), _normalize_team_text(row.city))
}


def canonical_team_abbr(value: Any) -> str:
    normalized = _normalize_team_text(value)
    if not normalized:
        return ""
    if normalized in _TEAM_IDENTITY_BY_ABBR:
        return normalized
    return _TEAM_IDENTITY_BY_ALIAS.get(normalized, normalized if len(normalized) <= 3 else normalized[:3])


def canonical_team_name(value: Any) -> str:
    team_abbr = canonical_team_abbr(value)
    identity = _TEAM_IDENTITY_BY_ABBR.get(team_abbr)
    if identity is None:
        return _normalize_team_text(value)
    return identity.team_name


def canonical_team_metadata(value: Any) -> dict[str, Any]:
    team_abbr = canonical_team_abbr(value)
    identity = _TEAM_IDENTITY_BY_ABBR.get(team_abbr)
    if identity is None:
        normalized = _normalize_team_text(value)
        return {
            "team_abbr": team_abbr or normalized,
            "team_name": normalized,
            "franchise_name": normalized,
            "city": normalized,
            "conference": None,
            "division": None,
            "aliases": [normalized] if normalized else [],
            "identity_source": "fallback_normalized",
        }
    return {
        "team_abbr": identity.team_abbr,
        "team_name": identity.team_name,
        "franchise_name": identity.franchise_name,
        "city": identity.city,
        "conference": identity.conference,
        "division": identity.division,
        "aliases": list(identity.aliases),
        "identity_source": "nfl_team_identity_table",
    }


def canonicalize_team_pair(home_team: Any, away_team: Any) -> tuple[str, str]:
    return canonical_team_abbr(home_team), canonical_team_abbr(away_team)