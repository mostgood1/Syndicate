from __future__ import annotations

import csv
import json
import os
import re
import hashlib
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from syndicate.features.ncaaf.sources import coach_continuity_snapshot_path
from syndicate.features.ncaaf.sources import player_identity_snapshot_path
from syndicate.features.ncaaf.sources import team_registry_snapshot_path
from syndicate.features.ncaaf.sources import returning_production_snapshot_path
from syndicate.features.ncaaf.sources import roster_snapshot_path
from syndicate.features.ncaaf.sources import transfer_portal_snapshot_path


CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_ENV_VARS = (
    "CFBD_API_KEY",
    "COLLEGEFOOTBALLDATA_API_KEY",
    "COLLEGE_FOOTBALL_DATA_API_KEY",
)

PLAYER_IDENTITY_COLUMNS = (
    "player_id",
    "player_name",
    "team_id",
    "position",
    "season",
)

ROSTER_SNAPSHOT_COLUMNS = (
    "player_id",
    "player_name",
    "team_id",
    "position",
    "season",
    "roster_status",
    "source_system",
    "source_snapshot_date",
)

TRANSFER_PORTAL_COLUMNS = (
    "player_id",
    "player_name",
    "origin_team_id",
    "destination_team_id",
    "transfer_date",
    "season",
    "position",
    "eligibility",
    "source_system",
    "source_snapshot_date",
)

RETURNING_PRODUCTION_COLUMNS = (
    "team_id",
    "team_name",
    "conference",
    "season",
    "total_ppa",
    "total_passing_ppa",
    "total_receiving_ppa",
    "total_rushing_ppa",
    "percent_ppa",
    "percent_passing_ppa",
    "percent_receiving_ppa",
    "percent_rushing_ppa",
    "usage",
    "passing_usage",
    "receiving_usage",
    "rushing_usage",
    "transfer_adjusted_ppa",
    "transfer_adjusted_usage",
    "returning_starter_estimate",
    "source_system",
    "source_snapshot_date",
)

COACH_CONTINUITY_COLUMNS = (
    "team_id",
    "team_name",
    "season",
    "head_coach_name",
    "head_coach_hire_date",
    "prior_season_head_coach",
    "coach_changed",
    "coach_tenure_years",
    "continuity_score",
    "source_system",
    "source_snapshot_date",
)

TEAM_REGISTRY_COLUMNS = (
    "team_id",
    "canonical_team_name",
    "abbreviation",
    "conference",
    "subdivision",
    "aliases",
    "display_name",
    "conference_short_name",
    "school_name",
    "mascot_name",
    "source_system",
    "source_snapshot_date",
)

_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CfbdSnapshotResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    team_registry_rows: tuple[dict[str, str], ...]
    roster_rows: tuple[dict[str, Any], ...]
    connectivity: dict[str, Any]
    validation_issues: tuple[str, ...]
    source_system: str = "cfbd"
    source_snapshot_date: str = ""


@dataclass(frozen=True)
class NcaafRosterSnapshotResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    identity_path: Path
    validation_issues: tuple[str, ...]
    source_system: str
    source_snapshot_date: str


@dataclass(frozen=True)
class NcaafTransferPortalSnapshotResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    portal_rows: tuple[dict[str, Any], ...]
    identity_rows: tuple[dict[str, str], ...]
    roster_rows: tuple[dict[str, str], ...]
    team_registry_rows: tuple[dict[str, str], ...]
    validation_issues: tuple[str, ...]
    source_system: str
    source_snapshot_date: str


@dataclass(frozen=True)
class NcaafReturningProductionSnapshotResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    team_registry_rows: tuple[dict[str, str], ...]
    roster_rows: tuple[dict[str, str], ...]
    transfer_rows: tuple[dict[str, str], ...]
    validation_issues: tuple[str, ...]
    source_system: str
    source_snapshot_date: str


@dataclass(frozen=True)
class NcaafCoachContinuitySnapshotResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    team_registry_rows: tuple[dict[str, str], ...]
    coach_rows: tuple[dict[str, Any], ...]
    validation_issues: tuple[str, ...]
    source_system: str
    source_snapshot_date: str


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _normalize_text(value: Any) -> str:
    text = _safe_text(value).lower().replace("&", " and ")
    text = text.replace("’", "'").replace("ʻ", "'")
    text = re.sub(r"[^a-z0-9 '\-]", " ", text)
    text = text.replace("hawai'i", "hawaii")
    return _SPACE_RE.sub(" ", text).strip()


def _season_text(value: Any, fallback: int) -> str:
    try:
        season = int(str(value).strip())
    except Exception:
        season = fallback
    return str(season)


def _first_text(row: dict[str, Any], keys: tuple[str, ...], fallback: str = "") -> str:
    for key in keys:
        text = _safe_text(row.get(key))
        if text:
            return text
    return fallback


def _first_int(row: dict[str, Any], keys: tuple[str, ...], fallback: int) -> int:
    for key in keys:
        value = row.get(key)
        try:
            if value is None:
                continue
            return int(float(str(value).strip()))
        except Exception:
            continue
    return fallback


class CfbdClient:
    def __init__(self, api_key: str, *, base_url: str = CFBD_API_BASE, timeout: float = 30.0) -> None:
        self.api_key = _safe_text(api_key)
        if not self.api_key:
            raise RuntimeError("Set CFBD_API_KEY, COLLEGEFOOTBALLDATA_API_KEY, or COLLEGE_FOOTBALL_DATA_API_KEY.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "syndicate-cfbd/1.0",
            }
        )

    @classmethod
    def from_env(cls, *, base_url: str = CFBD_API_BASE, timeout: float = 30.0) -> "CfbdClient":
        for env_var in CFBD_ENV_VARS:
            api_key = _safe_text(os.environ.get(env_var))
            if api_key:
                return cls(api_key, base_url=base_url, timeout=timeout)
        raise RuntimeError("Missing CFBD API key. Set CFBD_API_KEY or COLLEGEFOOTBALLDATA_API_KEY.")

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params or {}, timeout=self.timeout, headers=dict(self.session.headers))
        response.raise_for_status()
        return response.json()

    def test_connection(self, *, season: int) -> dict[str, Any]:
        payload = self._get_json("/teams/fbs", params={"year": season})
        sample_count = len(payload) if isinstance(payload, list) else (len(payload.get("data") or []) if isinstance(payload, dict) else 0)
        first_team = None
        if isinstance(payload, list) and payload:
            first_team = payload[0]
        elif isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), list) else []
            if data:
                first_team = data[0]
        return {
            "connected": True,
            "endpoint": "/teams/fbs",
            "season": season,
            "sample_count": sample_count,
            "sample_team": _first_text(first_team or {}, ("school", "team", "name", "abbreviation")) if isinstance(first_team, dict) else "",
        }

    def fetch_team_catalog(self, *, season: int) -> list[dict[str, Any]]:
        for path, params in (
            ("/teams", {"year": season}),
            ("/teams", None),
            ("/teams/fbs", {"year": season}),
            ("/teams/fbs", None),
        ):
            payload = self._get_json(path, params=params)
            if isinstance(payload, list):
                return [dict(row) for row in payload if isinstance(row, dict)]
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, list):
                    return [dict(row) for row in data if isinstance(row, dict)]
        return []

    def fetch_roster(self, *, season: int) -> list[dict[str, Any]]:
        payload = self._get_json("/roster", params={"year": season})
        if isinstance(payload, list):
            return [dict(row) for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [dict(row) for row in data if isinstance(row, dict)]
        return []


def _registry_team_id(row: dict[str, Any]) -> str:
    return _safe_text(
        row.get("team_id")
        or row.get("teamId")
        or row.get("id")
        or row.get("abbreviation")
        or row.get("school")
        or row.get("name")
    )


def _registry_name(row: dict[str, Any]) -> str:
    return _safe_text(row.get("canonical_team_name") or row.get("school") or row.get("name") or row.get("team"))


def _registry_aliases(row: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    raw_aliases = row.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(_safe_text(alias) for alias in raw_aliases if _safe_text(alias))
    for key in ("school", "name", "mascot", "nickname", "abbreviation"):
        text = _safe_text(row.get(key))
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def build_team_registry_rows(*, season: int, team_catalog_rows: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    registry_rows_by_team_id: dict[str, dict[str, str]] = {}
    for row in team_catalog_rows:
        if not isinstance(row, dict):
            continue
        canonical_name = _registry_name(row)
        abbreviation = _safe_text(row.get("abbreviation") or row.get("abbr") or row.get("shortName") or row.get("school"))
        team_id = _safe_text(row.get("id") or row.get("team_id") or abbreviation or canonical_name)
        classification = _normalize_text(row.get("classification") or row.get("division") or row.get("subdivision") or row.get("conference"))
        if classification in {"fbs", "fcs", "ii", "iii"}:
            subdivision = classification.upper() if classification in {"ii", "iii"} else classification.upper()
        else:
            subdivision = _safe_text(row.get("division") or row.get("subdivision") or row.get("classification") or "FBS")
        aliases = sorted({ _normalize_text(alias) for alias in _registry_aliases(row) if _normalize_text(alias) })
        existing = registry_rows_by_team_id.get(team_id)
        row_payload = {
            "team_id": team_id,
            "canonical_team_name": canonical_name,
            "abbreviation": abbreviation,
            "conference": _safe_text(row.get("conference") or row.get("conf")),
            "subdivision": subdivision,
            "aliases": "|".join(aliases),
            "season": str(season),
            "display_name": canonical_name,
            "conference_short_name": _safe_text(row.get("conferenceShortName") or row.get("conference_abbreviation") or row.get("conf")),
            "school_name": _safe_text(row.get("school") or canonical_name),
            "mascot_name": _safe_text(row.get("mascot") or row.get("nickname")),
            "source_system": "cfbd",
            "source_snapshot_date": date_type.today().isoformat(),
        }
        if existing is None or len(_safe_text(row_payload.get("aliases"))) >= len(_safe_text(existing.get("aliases"))):
            registry_rows_by_team_id[team_id] = row_payload
    registry_rows = list(registry_rows_by_team_id.values())
    registry_rows.sort(key=lambda row: (row.get("canonical_team_name") or "", row.get("team_id") or ""))
    return tuple(registry_rows)


def _registry_index(team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in team_registry_rows:
        if not isinstance(row, dict):
            continue
        for candidate in (
            row.get("team_id"),
            row.get("canonical_team_name"),
            row.get("abbreviation"),
            *(row.get("aliases") or "").split("|"),
        ):
            normalized = _normalize_text(candidate)
            if normalized and normalized not in index:
                index[normalized] = row
    return index


def _normalize_team_reference(row: dict[str, Any], index: dict[str, dict[str, str]]) -> tuple[str, str]:
    candidates = (
        row.get("team_id"),
        row.get("teamId"),
        row.get("team"),
        row.get("school"),
        row.get("schoolName"),
        row.get("abbreviation"),
        row.get("abbr"),
        row.get("team_name"),
    )
    for candidate in candidates:
        normalized = _normalize_text(candidate)
        match = index.get(normalized)
        if match:
            return match.get("team_id", ""), match.get("canonical_team_name", "")
    return "", ""


def _normalize_player_name(row: dict[str, Any]) -> str:
    first_name = _safe_text(row.get("firstName") or row.get("first_name"))
    last_name = _safe_text(row.get("lastName") or row.get("last_name"))
    combined = _safe_text(row.get("fullName") or row.get("player_name") or row.get("name") or row.get("athleteName"))
    if combined:
        return combined
    if first_name or last_name:
        return " ".join(part for part in (first_name, last_name) if part)
    return _safe_text(row.get("player_display_name") or row.get("player"))


def _normalize_position(row: dict[str, Any]) -> str:
    return _safe_text(row.get("position") or row.get("pos") or row.get("positionGroup") or row.get("position_group"))


def _normalize_player_id(row: dict[str, Any]) -> str:
    return _safe_text(row.get("player_id") or row.get("playerId") or row.get("id") or row.get("cfbdId") or row.get("athleteId"))


def _build_snapshot_row(
    row: dict[str, Any],
    *,
    season: int,
    team_registry_index: dict[str, dict[str, str]],
) -> dict[str, str]:
    team_id, _team_name = _normalize_team_reference(row, team_registry_index)
    return {
        "player_id": _normalize_player_id(row),
        "player_name": _normalize_player_name(row),
        "team_id": team_id,
        "position": _normalize_position(row),
        "season": str(season),
    }


def build_player_identity_rows(
    *,
    season: int,
    roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    index = _registry_index(team_registry_rows)
    normalized_rows = [
        _build_snapshot_row(row, season=season, team_registry_index=index)
        for row in roster_rows
        if isinstance(row, dict)
    ]
    normalized_rows = [
        row
        for row in normalized_rows
        if _safe_text(row.get("player_id")) and _safe_text(row.get("player_name")) and _safe_text(row.get("team_id")) and _safe_text(row.get("position"))
    ]

    grouped: dict[str, dict[str, str]] = {}
    for row in normalized_rows:
        player_id = _safe_text(row.get("player_id"))
        player_name = _safe_text(row.get("player_name"))
        team_id = _safe_text(row.get("team_id"))
        position = _safe_text(row.get("position"))
        season_text = _safe_text(row.get("season")) or str(season)
        group_key = player_id or "|".join((player_name, team_id, position, season_text))
        current = grouped.get(group_key)
        current_score = _row_score(current) if current is not None else -1
        new_score = _row_score(row)
        if current is None or new_score >= current_score:
            grouped[group_key] = {
                "player_id": player_id,
                "player_name": player_name,
                "team_id": team_id,
                "position": position,
                "season": season_text,
            }

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("team_id") or "", row.get("player_name") or "", row.get("player_id") or ""))
    return tuple(deduped)


def _row_score(row: dict[str, str] | None) -> int:
    if row is None:
        return -1
    score = 0
    for field in PLAYER_IDENTITY_COLUMNS:
        if _safe_text(row.get(field)):
            score += 1
    return score


def validate_player_identity_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    season: int,
) -> list[str]:
    issues: list[str] = []
    seen_player_ids: set[str] = set()
    team_ids = {_safe_text(row.get("team_id")) for row in team_registry_rows if _safe_text(row.get("team_id"))}

    for index, row in enumerate(rows):
        for field in PLAYER_IDENTITY_COLUMNS:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        player_id = _safe_text(row.get("player_id"))
        if player_id in seen_player_ids:
            issues.append(f"duplicate player_id {player_id}")
        seen_player_ids.add(player_id)
        if _safe_text(row.get("team_id")) not in team_ids:
            issues.append(f"row {index} unresolved team_id {row.get('team_id')}")
        if _safe_text(row.get("season")) != str(season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")

    return issues


def write_player_identity_snapshot_csv(
    *,
    season: int,
    roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    output_path: Path | None = None,
) -> CfbdSnapshotResult:
    rows = build_player_identity_rows(season=season, roster_rows=roster_rows, team_registry_rows=team_registry_rows)
    validation_issues = tuple(validate_player_identity_rows(rows, team_registry_rows=team_registry_rows, season=season))
    path = output_path or player_identity_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAYER_IDENTITY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PLAYER_IDENTITY_COLUMNS})
    connectivity = {"connected": False, "endpoint": "", "season": season, "sample_count": 0, "sample_team": ""}
    return CfbdSnapshotResult(
        rows=rows,
        output_path=path,
        team_registry_rows=tuple(team_registry_rows),
        roster_rows=tuple(roster_rows),
        connectivity=connectivity,
        validation_issues=validation_issues,
        source_system="cfbd",
        source_snapshot_date=date_type.today().isoformat(),
    )


def _safe_date_text(value: Any, fallback: str) -> str:
    text = _safe_text(value)
    if not text:
        return fallback
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return fallback


def _parse_transfer_date(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        return ""


def _load_player_identity_snapshot_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _roster_row_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        _safe_text(row.get("player_id")),
        _safe_text(row.get("player_name")),
        _safe_text(row.get("team_id")),
        _safe_text(row.get("position")),
        _safe_text(row.get("season")),
    )


def build_ncaaf_roster_snapshot_rows(
    *,
    identity_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    source_system: str = "cfbd",
    source_snapshot_date: str | None = None,
) -> tuple[dict[str, str], ...]:
    snapshot_date = source_snapshot_date or date_type.today().isoformat()
    normalized: list[dict[str, str]] = []
    for row in identity_rows:
        if not isinstance(row, dict):
            continue
        player_id = _safe_text(row.get("player_id"))
        player_name = _safe_text(row.get("player_name"))
        team_id = _safe_text(row.get("team_id"))
        position = _safe_text(row.get("position"))
        season = _safe_text(row.get("season"))
        if not (player_id and player_name and team_id and position and season):
            continue
        normalized.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "team_id": team_id,
                "position": position,
                "season": season,
                "roster_status": "active",
                "source_system": source_system,
                "source_snapshot_date": snapshot_date,
            }
        )

    grouped: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in normalized:
        grouped[_roster_row_key(row)] = row

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("team_id") or "", row.get("player_name") or "", row.get("player_id") or ""))
    return tuple(deduped)


def validate_ncaaf_roster_snapshot_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    expected_season: int,
) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for index, row in enumerate(rows):
        for field in ROSTER_SNAPSHOT_COLUMNS:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        key = _roster_row_key(row)
        if key in seen:
            issues.append(f"duplicate roster row {key[0]}")
        seen.add(key)
        if _safe_text(row.get("season")) != str(expected_season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")
        if _safe_text(row.get("roster_status")) not in {"active", "inactive", "unknown"}:
            issues.append(f"row {index} has invalid roster_status {row.get('roster_status')}")
        if _safe_text(row.get("source_system")) != "cfbd":
            issues.append(f"row {index} has unexpected source_system {row.get('source_system')}")
        if not _safe_date_text(row.get("source_snapshot_date"), ""):
            issues.append(f"row {index} has invalid source_snapshot_date {row.get('source_snapshot_date')}")
    return issues


def write_ncaaf_roster_snapshot_csv(
    *,
    season: int,
    identity_snapshot_path: Path | None = None,
    identity_rows: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    output_path: Path | None = None,
    source_system: str = "cfbd",
    source_snapshot_date: str | None = None,
) -> NcaafRosterSnapshotResult:
    identity_path = identity_snapshot_path or player_identity_snapshot_path()
    loaded_identity_rows = list(identity_rows) if identity_rows is not None else _load_player_identity_snapshot_rows(identity_path)
    rows = build_ncaaf_roster_snapshot_rows(
        identity_rows=loaded_identity_rows,
        source_system=source_system,
        source_snapshot_date=source_snapshot_date,
    )
    validation_issues = tuple(validate_ncaaf_roster_snapshot_rows(rows, expected_season=season))
    path = output_path or roster_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROSTER_SNAPSHOT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in ROSTER_SNAPSHOT_COLUMNS})
    return NcaafRosterSnapshotResult(
        rows=rows,
        output_path=path,
        identity_path=identity_path,
        validation_issues=validation_issues,
        source_system=source_system,
        source_snapshot_date=source_snapshot_date or date_type.today().isoformat(),
    )


def build_ncaaf_roster_generation_report(
    *,
    season: int,
    output_path: Path,
    identity_path: Path,
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    source_system: str,
    source_snapshot_date: str,
) -> str:
    lines = [
        "# NCAAF Roster Snapshot Generation Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Generated: {'yes' if not validation_issues else 'partial'}",
        f"Snapshot output: {output_path}",
        f"Identity snapshot input: {identity_path}",
        f"Source system: {source_system}",
        f"Source snapshot date: {source_snapshot_date}",
        "",
        "## Counts",
        "",
        f"Publishable rows: {len(list(rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Was the roster snapshot generated successfully? {'Yes' if not validation_issues else 'Partially'}.",
        f"How many publishable rows were produced? {len(list(rows))}.",
        f"What validation issues remain? {'None' if not validation_issues else '; '.join(validation_issues)}.",
        f"Is M3 roster onboarding now complete? {'No, because the roster artifact still needs to be wired into the broader M3 publication path.' if not validation_issues else 'No.'}",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the roster snapshot build.")
    lines.append("")
    return "\n".join(lines)


def _load_snapshot_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _portal_row_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        _safe_text(row.get("player_id")),
        _safe_text(row.get("origin_team_id")),
        _safe_text(row.get("destination_team_id")),
        _safe_text(row.get("transfer_date")),
        _safe_text(row.get("season")),
    )


def _player_search_crosswalk(client: CfbdClient, *, search_term: str, expected_season: int) -> dict[str, str]:
    payload = client._get_json("/player/search", params={"searchTerm": search_term})
    if not isinstance(payload, list):
        return {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        player_id = _safe_text(row.get("id") or row.get("player_id"))
        player_name = _safe_text(row.get("name") or row.get("player_name") or row.get("firstName") or row.get("lastName"))
        position = _safe_text(row.get("position"))
        team = _safe_text(row.get("team"))
        if player_id and player_name:
            return {
                "player_id": player_id,
                "player_name": player_name,
                "position": position,
                "team": team,
                "season": str(expected_season),
            }
    return {}


def _load_identity_index(identity_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in identity_rows:
        if not isinstance(row, dict):
            continue
        player_id = _safe_text(row.get("player_id"))
        player_name = _normalize_text(row.get("player_name"))
        if player_id and player_id not in index:
            index[player_id] = row
        if player_name and player_name not in index:
            index[player_name] = row
    return index


def _player_name_position_key(player_name: str, position: str) -> str:
    return "|".join((_normalize_text(player_name), _normalize_text(position)))


def _deterministic_transfer_player_id(
    *,
    player_name: str,
    origin_team_id: str,
    destination_team_id: str,
    transfer_date: str,
    season: int,
) -> str:
    token = "|".join(
        (
            _normalize_text(player_name),
            _normalize_text(origin_team_id),
            _normalize_text(destination_team_id),
            _safe_text(transfer_date),
            str(season),
        )
    )
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]
    return f"cfbd-transfer-{digest}"


def _load_team_registry_index(team_registry_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return _registry_index(team_registry_rows)


def _find_team_row(team_label: str, index: dict[str, dict[str, str]]) -> tuple[str, str]:
    normalized = _normalize_text(team_label)
    match = index.get(normalized)
    if match:
        return match.get("team_id", ""), match.get("canonical_team_name", "")
    return "", ""


def build_ncaaf_transfer_portal_rows(
    *,
    client: CfbdClient,
    season: int,
    portal_rows: list[dict[str, Any]],
    identity_rows: list[dict[str, str]],
    roster_rows: list[dict[str, str]],
    team_registry_rows: list[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    identity_index = _load_identity_index(identity_rows)
    roster_index = _load_identity_index(roster_rows)
    team_index = _load_team_registry_index(team_registry_rows)
    normalized_rows: list[dict[str, str]] = []

    for row in portal_rows:
        if not isinstance(row, dict):
            continue
        player_name = _normalize_player_name(row)
        normalized_position = _safe_text(row.get("position"))
        identity_match = {}
        if player_name:
            identity_match = identity_index.get(_normalize_text(player_name), {})
            if not identity_match:
                identity_match = roster_index.get(_normalize_text(player_name), {})
            if not identity_match:
                identity_match = identity_index.get(_player_name_position_key(player_name, normalized_position), {})
        player_id = _safe_text(
            _safe_text(row.get("player_id"))
            or (identity_match.get("player_id") if identity_match else "")
        )
        resolved_player_name = _safe_text(
            player_name
            or (identity_match.get("player_name") if identity_match else "")
        )
        origin_team_id, _ = _find_team_row(_safe_text(row.get("origin")), team_index)
        destination_team_id, _ = _find_team_row(_safe_text(row.get("destination")), team_index)
        transfer_date = _parse_transfer_date(row.get("transferDate") or row.get("transfer_date"))
        roster_match = roster_index.get(_normalize_text(resolved_player_name)) if resolved_player_name else {}
        if not player_id and roster_match:
            player_id = _safe_text(roster_match.get("player_id"))
        if not resolved_player_name and player_id:
            resolved_player_name = _safe_text(identity_index.get(player_id, {}).get("player_name") or roster_match.get("player_name"))
        if not player_id and resolved_player_name and origin_team_id and destination_team_id and transfer_date:
            player_id = _deterministic_transfer_player_id(
                player_name=resolved_player_name,
                origin_team_id=origin_team_id,
                destination_team_id=destination_team_id,
                transfer_date=transfer_date,
                season=season,
            )
        normalized_row = {
            "player_id": player_id,
            "player_name": resolved_player_name,
            "origin_team_id": origin_team_id,
            "destination_team_id": destination_team_id,
            "transfer_date": transfer_date,
            "season": str(_safe_text(row.get("season")) or season),
            "position": _safe_text(row.get("position") or identity_match.get("position") if identity_match else ""),
            "eligibility": _safe_text(row.get("eligibility")),
            "source_system": "cfbd",
            "source_snapshot_date": date_type.today().isoformat(),
        }
        if normalized_row["player_id"] and normalized_row["player_name"] and normalized_row["origin_team_id"] and normalized_row["destination_team_id"] and normalized_row["transfer_date"] and normalized_row["position"] and normalized_row["eligibility"]:
            normalized_rows.append(normalized_row)

    grouped: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in normalized_rows:
        grouped[_portal_row_key(row)] = row

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("origin_team_id") or "", row.get("destination_team_id") or "", row.get("player_name") or "", row.get("transfer_date") or ""))
    return tuple(deduped)


def validate_ncaaf_transfer_portal_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    expected_season: int,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    team_ids = {_safe_text(row.get("team_id")) for row in team_registry_rows if _safe_text(row.get("team_id"))}

    for index, row in enumerate(rows):
        for field in TRANSFER_PORTAL_COLUMNS:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        key = _portal_row_key(row)
        if key in seen:
            issues.append(f"duplicate transfer row {key[0]}:{key[1]}:{key[2]}:{key[3]}")
        seen.add(key)
        if _safe_text(row.get("season")) != str(expected_season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")
        if _safe_text(row.get("origin_team_id")) not in team_ids:
            issues.append(f"row {index} unresolved origin_team_id {row.get('origin_team_id')}")
        if _safe_text(row.get("destination_team_id")) not in team_ids:
            issues.append(f"row {index} unresolved destination_team_id {row.get('destination_team_id')}")
        if not _parse_transfer_date(row.get("transfer_date")):
            issues.append(f"row {index} invalid transfer_date {row.get('transfer_date')}")
        if _safe_text(row.get("source_system")) != "cfbd":
            issues.append(f"row {index} has unexpected source_system {row.get('source_system')}")
        if not _safe_date_text(row.get("source_snapshot_date"), ""):
            issues.append(f"row {index} has invalid source_snapshot_date {row.get('source_snapshot_date')}")
    return issues


def write_ncaaf_transfer_portal_snapshot_csv(
    *,
    client: CfbdClient,
    season: int,
    identity_snapshot_path: Path | None = None,
    identity_rows: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    roster_snapshot_path_input: Path | None = None,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    output_path: Path | None = None,
) -> NcaafTransferPortalSnapshotResult:
    identity_path = identity_snapshot_path or player_identity_snapshot_path()
    roster_path = roster_snapshot_path_input or roster_snapshot_path()
    loaded_identity_rows = list(identity_rows) if identity_rows is not None else _load_snapshot_rows(identity_path)
    roster_rows = _load_snapshot_rows(roster_path)
    registry_rows = tuple(team_registry_rows) if team_registry_rows is not None else load_team_registry_rows(registry_path=None, season=season, team_catalog_rows=client.fetch_team_catalog(season=season))
    portal_rows = client._get_json("/player/portal", params={"year": season})
    if not isinstance(portal_rows, list):
        portal_rows = []
    rows = build_ncaaf_transfer_portal_rows(
        client=client,
        season=season,
        portal_rows=portal_rows,
        identity_rows=loaded_identity_rows,
        roster_rows=roster_rows,
        team_registry_rows=list(registry_rows),
    )
    validation_issues = tuple(validate_ncaaf_transfer_portal_rows(rows, expected_season=season, team_registry_rows=list(registry_rows)))
    path = output_path or transfer_portal_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRANSFER_PORTAL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in TRANSFER_PORTAL_COLUMNS})
    return NcaafTransferPortalSnapshotResult(
        rows=rows,
        output_path=path,
        portal_rows=tuple(portal_rows),
        identity_rows=tuple(loaded_identity_rows),
        roster_rows=tuple(roster_rows),
        team_registry_rows=registry_rows,
        validation_issues=validation_issues,
        source_system="cfbd",
        source_snapshot_date=date_type.today().isoformat(),
    )


def build_ncaaf_transfer_generation_report(
    *,
    season: int,
    output_path: Path,
    identity_path: Path,
    roster_path: Path,
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    source_system: str,
    source_snapshot_date: str,
) -> str:
    lines = [
        "# NCAAF Transfer Portal Generation Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Generated: {'yes' if not validation_issues else 'partial'}",
        f"Snapshot output: {output_path}",
        f"Identity snapshot input: {identity_path}",
        f"Roster snapshot input: {roster_path}",
        f"Source system: {source_system}",
        f"Source snapshot date: {source_snapshot_date}",
        "",
        "## Counts",
        "",
        f"Publishable rows: {len(list(rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Was the transfer snapshot generated successfully? {'Yes' if not validation_issues else 'Partially' }.",
        f"How many publishable transfer rows were produced? {len(list(rows))}.",
        f"What validation issues remain? {'None' if not validation_issues else '; '.join(validation_issues)}.",
        f"Is M4 transfer onboarding now complete? {'No, because the transfer artifact still needs publication wiring and any unresolved joins must be reviewed.' if not validation_issues else 'No.'}",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the transfer snapshot build.")
    lines.append("")
    return "\n".join(lines)


def build_integration_report(
    *,
    season: int,
    connectivity: dict[str, Any],
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    snapshot_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    output_path: Path,
    registry_mode: str,
) -> str:
    connected = bool(connectivity.get("connected"))
    lines = [
        "# NCAAF CFBD Integration Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Connected: {'yes' if connected else 'no'}",
        f"Connectivity endpoint: {connectivity.get('endpoint') or 'n/a'}",
        f"Snapshot output: {output_path}",
        f"Registry mode: {registry_mode}",
        "",
        "## Counts",
        "",
        f"Team registry rows: {len(list(team_registry_rows))}",
        f"Roster rows fetched: {len(list(roster_rows))}",
        f"Snapshot rows written: {len(list(snapshot_rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Did CFBD successfully connect? {'Yes' if connected else 'No'}.",
        f"Can CFBD populate the player identity snapshot? {'Yes' if connected and not validation_issues else 'Not yet' if connected else 'No'}.",
        f"What fields required normalization? team references, player names, positions, and season values.",
        "What blockers remain? canonical team registry publication, any unresolved team joins, and live-key availability if the environment cannot reach CFBD.",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the prototype snapshot build.")
    lines.append("")
    return "\n".join(lines)


def load_team_registry_rows(
    *,
    registry_path: Path | None,
    season: int,
    team_catalog_rows: list[dict[str, Any]],
) -> tuple[dict[str, str], ...]:
    if registry_path is not None and registry_path.exists():
        if registry_path.suffix.lower() == ".json":
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("rows") if isinstance(payload, dict) else []
            if isinstance(rows, list):
                return tuple(dict(row) for row in rows if isinstance(row, dict))
        with registry_path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    return build_team_registry_rows(season=season, team_catalog_rows=team_catalog_rows)


def validate_team_registry_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    expected_season: int,
) -> list[str]:
    issues: list[str] = []
    seen_team_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, row in enumerate(rows):
        for field in ("team_id", "canonical_team_name", "abbreviation", "conference", "subdivision", "aliases"):
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        team_id = _safe_text(row.get("team_id"))
        canonical_name = _safe_text(row.get("canonical_team_name"))
        if team_id in seen_team_ids:
            issues.append(f"duplicate team_id {team_id}")
        seen_team_ids.add(team_id)
        if canonical_name in seen_names:
            issues.append(f"duplicate canonical_team_name {canonical_name}")
        seen_names.add(canonical_name)
        aliases = [alias for alias in (_safe_text(value) for value in (_safe_text(row.get("aliases")).split("|") if _safe_text(row.get("aliases")) else [])) if alias]
        if not aliases:
            issues.append(f"row {index} missing alias coverage")
        if not _safe_text(row.get("conference")):
            issues.append(f"row {index} missing conference coverage")
        if _safe_text(row.get("subdivision")).lower() not in {"fbs", "fcs", "ii", "iii"}:
            issues.append(f"row {index} has unexpected subdivision {row.get('subdivision')}")
        if _safe_text(row.get("source_system")) and _safe_text(row.get("source_system")) != "cfbd":
            issues.append(f"row {index} has unexpected source_system {row.get('source_system')}")
        if _safe_text(row.get("season")) and _safe_text(row.get("season")) != str(expected_season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")
    return issues


def write_team_registry_snapshot_csv(
    *,
    client: CfbdClient,
    season: int,
    team_catalog_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    output_path: Path | None = None,
) -> CfbdSnapshotResult:
    catalog_rows = list(team_catalog_rows) if team_catalog_rows is not None else client.fetch_team_catalog(season=season)
    rows = build_team_registry_rows(season=season, team_catalog_rows=catalog_rows)
    validation_issues = tuple(validate_team_registry_rows(rows, expected_season=season))
    path = output_path or team_registry_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEAM_REGISTRY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in TEAM_REGISTRY_COLUMNS})
    connectivity = {
        "connected": True,
        "endpoint": "/teams/fbs",
        "season": season,
        "sample_count": len(catalog_rows),
        "sample_team": _safe_text(catalog_rows[0].get("school") if catalog_rows and isinstance(catalog_rows[0], dict) else ""),
    }
    return CfbdSnapshotResult(
        rows=rows,
        output_path=path,
        team_registry_rows=tuple(rows),
        roster_rows=tuple(),
        connectivity=connectivity,
        validation_issues=validation_issues,
    )


def build_team_registry_generation_report(
    *,
    season: int,
    output_path: Path,
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    source_system: str,
    source_snapshot_date: str,
) -> str:
    lines = [
        "# NCAAF Team Registry Generation Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Generated: {'yes' if not validation_issues else 'partial'}",
        f"Snapshot output: {output_path}",
        f"Source system: {source_system}",
        f"Source snapshot date: {source_snapshot_date}",
        "",
        "## Counts",
        "",
        f"Publishable rows: {len(list(rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Was the registry snapshot generated successfully? {'Yes' if not validation_issues else 'Partially' }.",
        f"How many publishable rows were produced? {len(list(rows))}.",
        f"What validation issues remain? {'None' if not validation_issues else '; '.join(validation_issues)}.",
        f"Is the canonical team registry published? {'Yes' if not validation_issues else 'Not yet' }.",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the team registry snapshot build.")
    lines.append("")
    return "\n".join(lines)


def run_cfbd_player_identity_build(
    *,
    client: CfbdClient,
    season: int,
    registry_path: Path | None = None,
    output_path: Path | None = None,
) -> CfbdSnapshotResult:
    connectivity = client.test_connection(season=season)
    team_catalog_rows = client.fetch_team_catalog(season=season)
    roster_rows = client.fetch_roster(season=season)
    team_registry_rows = load_team_registry_rows(registry_path=registry_path, season=season, team_catalog_rows=team_catalog_rows)
    rows = build_player_identity_rows(season=season, roster_rows=roster_rows, team_registry_rows=team_registry_rows)
    validation_issues = tuple(validate_player_identity_rows(rows, team_registry_rows=team_registry_rows, season=season))
    path = output_path or player_identity_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAYER_IDENTITY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PLAYER_IDENTITY_COLUMNS})
    connectivity = {
        **connectivity,
        "roster_sample_count": len(roster_rows),
        "team_catalog_count": len(team_catalog_rows),
    }
    return CfbdSnapshotResult(
        rows=rows,
        output_path=path,
        team_registry_rows=team_registry_rows,
        roster_rows=tuple(roster_rows),
        connectivity=connectivity,
        validation_issues=validation_issues,
        source_system="cfbd",
        source_snapshot_date=date_type.today().isoformat(),
    )


def _returning_row_key(row: dict[str, str]) -> tuple[str, str]:
    return (_safe_text(row.get("team_id")), _safe_text(row.get("season")))


def _coach_row_key(row: dict[str, str]) -> tuple[str, str]:
    return (_safe_text(row.get("team_id")), _safe_text(row.get("season")))


def _safe_float_text(value: Any, fallback: str = "") -> str:
    text = _safe_text(value)
    if not text:
        return fallback
    try:
        return str(float(text))
    except Exception:
        return fallback


def _parse_hire_date(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
        return ""


def _coach_seasons_years(row: dict[str, Any]) -> list[int]:
    seasons = row.get("seasons")
    if not isinstance(seasons, list):
        return []
    years: list[int] = []
    for season_row in seasons:
        if not isinstance(season_row, dict):
            continue
        try:
            years.append(int(season_row.get("year")))
        except Exception:
            continue
    return sorted(set(years))


def _derive_hire_date(row: dict[str, Any], *, season: int) -> str:
    hire_date = _parse_hire_date(row.get("hireDate"))
    if hire_date:
        return hire_date
    years = _coach_seasons_years(row)
    if years:
        return f"{years[0]:04d}-01-01"
    return f"{season:04d}-01-01"


def _coach_tenure_years(row: dict[str, Any], *, season: int) -> str:
    hire_date = _parse_hire_date(row.get("hireDate"))
    if hire_date and len(hire_date) >= 4 and hire_date[:4].isdigit():
        hire_year = int(hire_date[:4])
        return str(max(1, season - hire_year + 1))
    years = _coach_seasons_years(row)
    if years:
        return str(max(1, season - years[0] + 1))
    return "1"


def _normalized_returning_row(
    row: dict[str, Any],
    *,
    season: int,
    team_index: dict[str, dict[str, str]],
) -> dict[str, str]:
    team_id, team_name = _normalize_team_reference(row, team_index)
    conference = _safe_text(row.get("conference") or row.get("conf") or (team_index.get(_normalize_text(team_name), {}) if team_name else {}).get("conference"))
    total_ppa = _safe_float_text(row.get("totalPPA"))
    total_passing_ppa = _safe_float_text(row.get("totalPassingPPA"))
    total_receiving_ppa = _safe_float_text(row.get("totalReceivingPPA"))
    total_rushing_ppa = _safe_float_text(row.get("totalRushingPPA"))
    percent_ppa = _safe_float_text(row.get("percentPPA"))
    percent_passing_ppa = _safe_float_text(row.get("percentPassingPPA"))
    percent_receiving_ppa = _safe_float_text(row.get("percentReceivingPPA"))
    percent_rushing_ppa = _safe_float_text(row.get("percentRushingPPA"))
    usage = _safe_float_text(row.get("usage"))
    passing_usage = _safe_float_text(row.get("passingUsage"))
    receiving_usage = _safe_float_text(row.get("receivingUsage"))
    rushing_usage = _safe_float_text(row.get("rushingUsage"))
    roster_total = _safe_float_text(row.get("roster_total"), "")
    return {
        "team_id": team_id,
        "team_name": team_name,
        "conference": conference,
        "season": str(_first_int(row, ("season", "year"), season)),
        "total_ppa": total_ppa,
        "total_passing_ppa": total_passing_ppa,
        "total_receiving_ppa": total_receiving_ppa,
        "total_rushing_ppa": total_rushing_ppa,
        "percent_ppa": percent_ppa,
        "percent_passing_ppa": percent_passing_ppa,
        "percent_receiving_ppa": percent_receiving_ppa,
        "percent_rushing_ppa": percent_rushing_ppa,
        "usage": usage,
        "passing_usage": passing_usage,
        "receiving_usage": receiving_usage,
        "rushing_usage": rushing_usage,
        "transfer_adjusted_ppa": _safe_float_text(row.get("transfer_adjusted_ppa"), total_ppa),
        "transfer_adjusted_usage": _safe_float_text(row.get("transfer_adjusted_usage"), usage),
        "returning_starter_estimate": _safe_float_text(row.get("returning_starter_estimate"), roster_total),
        "source_system": "cfbd",
        "source_snapshot_date": date_type.today().isoformat(),
    }


def _team_transfer_counts(
    *,
    roster_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    transfer_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    team_id: str,
) -> tuple[int, int, int]:
    roster_count = sum(1 for row in roster_rows if _safe_text(row.get("team_id")) == team_id)
    outgoing = sum(1 for row in transfer_rows if _safe_text(row.get("origin_team_id")) == team_id)
    incoming = sum(1 for row in transfer_rows if _safe_text(row.get("destination_team_id")) == team_id)
    return roster_count, outgoing, incoming


def build_ncaaf_returning_production_rows(
    *,
    season: int,
    returning_rows: list[dict[str, Any]],
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    roster_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    transfer_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    team_index = _load_team_registry_index(list(team_registry_rows))
    normalized_rows: list[dict[str, str]] = []
    for row in returning_rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalized_returning_row(row, season=season, team_index=team_index)
        if not normalized["team_id"] or not normalized["team_name"] or not normalized["conference"] or not normalized["season"]:
            continue
        roster_count, outgoing, incoming = _team_transfer_counts(roster_rows=roster_rows, transfer_rows=transfer_rows, team_id=normalized["team_id"])
        adjusted_ppa = float(normalized["total_ppa"] or 0.0) + (incoming * 0.1) - (outgoing * 0.1)
        adjusted_usage = float(normalized["usage"] or 0.0) + (incoming * 0.005) - (outgoing * 0.005)
        starter_estimate = max(0.0, min(11.0, float(normalized["percent_ppa"] or 0.0) * 11.0))
        normalized["transfer_adjusted_ppa"] = f"{adjusted_ppa:.3f}".rstrip("0").rstrip(".")
        normalized["transfer_adjusted_usage"] = f"{adjusted_usage:.3f}".rstrip("0").rstrip(".")
        normalized["returning_starter_estimate"] = f"{starter_estimate:.3f}".rstrip("0").rstrip(".")
        normalized["roster_total"] = str(roster_count)
        normalized_rows.append(normalized)

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for row in normalized_rows:
        grouped[_returning_row_key(row)] = row

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("conference") or "", row.get("team_name") or ""))
    return tuple(deduped)


def _normalize_coach_name(row: dict[str, Any]) -> str:
    return _safe_text(" ".join(part for part in (_safe_text(row.get("firstName")), _safe_text(row.get("lastName"))) if part))


def _extract_season_row(row: dict[str, Any], *, expected_season: int) -> dict[str, Any] | None:
    seasons = row.get("seasons")
    if not isinstance(seasons, list):
        return None
    for season_row in seasons:
        if not isinstance(season_row, dict):
            continue
        try:
            season_year = int(season_row.get("year"))
        except Exception:
            continue
        if season_year == expected_season:
            return season_row
    return None


def build_ncaaf_coach_continuity_rows(
    *,
    season: int,
    coach_rows: list[dict[str, Any]],
    prior_coach_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    team_index = _load_team_registry_index(list(team_registry_rows))
    current_rows: list[dict[str, str]] = []
    prior_lookup: dict[str, str] = {}

    current_payload = list(coach_rows)
    for row in current_payload:
        if not isinstance(row, dict):
            continue
        season_row = _extract_season_row(row, expected_season=season)
        if not season_row:
            continue
        team_id, team_name = _find_team_row(_safe_text(season_row.get("school")), team_index)
        if not team_id or not team_name:
            continue
        head_coach_name = _normalize_coach_name(row)
        hire_date = _parse_hire_date(row.get("hireDate"))
        current_rows.append(
            {
                "team_id": team_id,
                "team_name": team_name,
                "season": str(season),
                "head_coach_name": head_coach_name,
                "head_coach_hire_date": _derive_hire_date(row, season=season),
                "source_system": "cfbd",
                "source_snapshot_date": date_type.today().isoformat(),
            }
        )

    if prior_coach_rows:
        for row in prior_coach_rows:
            if not isinstance(row, dict):
                continue
            season_row = _extract_season_row(row, expected_season=season - 1)
            if not season_row:
                continue
            team_id, _ = _find_team_row(_safe_text(season_row.get("school")), team_index)
            if not team_id:
                continue
            prior_lookup[team_id] = _normalize_coach_name(row)
    elif season > 0:
        # If the caller does not provide prior-season rows, keep the field blank
        # rather than inventing a continuity history.
        prior_lookup = {}

    normalized_rows: list[dict[str, str]] = []
    for row in current_rows:
        team_id = _safe_text(row.get("team_id"))
        current_coach = _safe_text(row.get("head_coach_name"))
        prior_coach = prior_lookup.get(team_id, "") or current_coach
        coach_changed = "1" if prior_coach and prior_coach != _safe_text(row.get("head_coach_name")) else "0"
        tenure_years = float(_coach_tenure_years({"hireDate": row.get("head_coach_hire_date")}, season=season)) if _safe_text(row.get("head_coach_hire_date")) else 1.0
        continuity_score = max(0.0, min(1.0, 1.0 - (0.5 if coach_changed == "1" else 0.0)))
        normalized_rows.append(
            {
                "team_id": team_id,
                "team_name": _safe_text(row.get("team_name")),
                "season": _safe_text(row.get("season")),
                "head_coach_name": _safe_text(row.get("head_coach_name")),
                "head_coach_hire_date": _safe_text(row.get("head_coach_hire_date")),
                "prior_season_head_coach": prior_coach,
                "coach_changed": coach_changed,
                "coach_tenure_years": f"{tenure_years:.3f}".rstrip("0").rstrip("."),
                "continuity_score": f"{continuity_score:.3f}".rstrip("0").rstrip("."),
                "source_system": "cfbd",
                "source_snapshot_date": _safe_text(row.get("source_snapshot_date"), date_type.today().isoformat()),
            }
        )

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for row in normalized_rows:
        grouped[_coach_row_key(row)] = row
    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("team_name") or "", row.get("season") or ""))
    return tuple(deduped)


def validate_ncaaf_coach_continuity_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    expected_season: int,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    team_ids = {_safe_text(row.get("team_id")) for row in team_registry_rows if _safe_text(row.get("team_id"))}

    for index, row in enumerate(rows):
        for field in COACH_CONTINUITY_COLUMNS:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        key = _coach_row_key(row)
        if key in seen:
            issues.append(f"duplicate coach continuity row {key[0]}:{key[1]}")
        seen.add(key)
        if _safe_text(row.get("season")) != str(expected_season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")
        if _safe_text(row.get("team_id")) not in team_ids:
            issues.append(f"row {index} unresolved team_id {row.get('team_id')}")
        if _safe_text(row.get("source_system")) != "cfbd":
            issues.append(f"row {index} has unexpected source_system {row.get('source_system')}")
        if not _safe_date_text(row.get("head_coach_hire_date"), ""):
            issues.append(f"row {index} has invalid head_coach_hire_date {row.get('head_coach_hire_date')}")
        if not _safe_date_text(row.get("source_snapshot_date"), ""):
            issues.append(f"row {index} has invalid source_snapshot_date {row.get('source_snapshot_date')}")
    return issues


def write_ncaaf_coach_continuity_snapshot_csv(
    *,
    client: CfbdClient,
    season: int,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    output_path: Path | None = None,
) -> NcaafCoachContinuitySnapshotResult:
    registry_rows = tuple(team_registry_rows) if team_registry_rows is not None else load_team_registry_rows(registry_path=None, season=season, team_catalog_rows=client.fetch_team_catalog(season=season))
    coach_rows = client._get_json("/coaches", params={"year": season})
    if not isinstance(coach_rows, list):
        coach_rows = []
    prior_coach_rows = client._get_json("/coaches", params={"year": season - 1}) if season > 0 else []
    if not isinstance(prior_coach_rows, list):
        prior_coach_rows = []
    rows = build_ncaaf_coach_continuity_rows(season=season, coach_rows=coach_rows, prior_coach_rows=prior_coach_rows, team_registry_rows=registry_rows)
    validation_issues = tuple(validate_ncaaf_coach_continuity_rows(rows, expected_season=season, team_registry_rows=registry_rows))
    path = output_path or coach_continuity_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COACH_CONTINUITY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COACH_CONTINUITY_COLUMNS})
    return NcaafCoachContinuitySnapshotResult(
        rows=rows,
        output_path=path,
        team_registry_rows=registry_rows,
        coach_rows=tuple(coach_rows),
        validation_issues=validation_issues,
        source_system="cfbd",
        source_snapshot_date=date_type.today().isoformat(),
    )


def build_ncaaf_coach_continuity_generation_report(
    *,
    season: int,
    output_path: Path,
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    source_system: str,
    source_snapshot_date: str,
) -> str:
    lines = [
        "# NCAAF Coach Continuity Generation Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Generated: {'yes' if not validation_issues else 'partial'}",
        f"Snapshot output: {output_path}",
        f"Source system: {source_system}",
        f"Source snapshot date: {source_snapshot_date}",
        "",
        "## Counts",
        "",
        f"Publishable rows: {len(list(rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Was the snapshot generated successfully? {'Yes' if not validation_issues else 'Partially' }.",
        f"How many publishable rows were produced? {len(list(rows))}.",
        f"What validation issues remain? {'None' if not validation_issues else '; '.join(validation_issues)}.",
        f"Is M6 complete? {'Yes, if this artifact is accepted as the canonical head-coach continuity layer.' if not validation_issues else 'No.'}",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the coach continuity snapshot build.")
    lines.append("")
    return "\n".join(lines)


def validate_ncaaf_returning_production_rows(
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    *,
    expected_season: int,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    team_ids = {_safe_text(row.get("team_id")) for row in team_registry_rows if _safe_text(row.get("team_id"))}

    for index, row in enumerate(rows):
        for field in RETURNING_PRODUCTION_COLUMNS:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        key = _returning_row_key(row)
        if key in seen:
            issues.append(f"duplicate returning production row {key[0]}:{key[1]}")
        seen.add(key)
        if _safe_text(row.get("season")) != str(expected_season):
            issues.append(f"row {index} has unexpected season {row.get('season')}")
        if _safe_text(row.get("team_id")) not in team_ids:
            issues.append(f"row {index} unresolved team_id {row.get('team_id')}")
        if _safe_text(row.get("source_system")) != "cfbd":
            issues.append(f"row {index} has unexpected source_system {row.get('source_system')}")
        if not _safe_date_text(row.get("source_snapshot_date"), ""):
            issues.append(f"row {index} has invalid source_snapshot_date {row.get('source_snapshot_date')}")
    return issues


def write_ncaaf_returning_production_snapshot_csv(
    *,
    client: CfbdClient,
    season: int,
    identity_snapshot_path: Path | None = None,
    roster_snapshot_path_input: Path | None = None,
    transfer_snapshot_path_input: Path | None = None,
    registry_path: Path | None = None,
    team_registry_rows: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    output_path: Path | None = None,
) -> NcaafReturningProductionSnapshotResult:
    roster_path = roster_snapshot_path_input or roster_snapshot_path()
    transfer_path = transfer_snapshot_path_input or transfer_portal_snapshot_path()
    registry_rows = tuple(team_registry_rows) if team_registry_rows is not None else load_team_registry_rows(registry_path=registry_path, season=season, team_catalog_rows=client.fetch_team_catalog(season=season))
    roster_rows = _load_snapshot_rows(roster_path)
    transfer_rows = _load_snapshot_rows(transfer_path)
    payload = client._get_json("/player/returning", params={"year": season})
    if not isinstance(payload, list):
        payload = []
    rows = build_ncaaf_returning_production_rows(
        season=season,
        returning_rows=payload,
        team_registry_rows=registry_rows,
        roster_rows=roster_rows,
        transfer_rows=transfer_rows,
    )
    validation_issues = tuple(validate_ncaaf_returning_production_rows(rows, expected_season=season, team_registry_rows=registry_rows))
    path = output_path or returning_production_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RETURNING_PRODUCTION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in RETURNING_PRODUCTION_COLUMNS})
    return NcaafReturningProductionSnapshotResult(
        rows=rows,
        output_path=path,
        team_registry_rows=registry_rows,
        roster_rows=tuple(roster_rows),
        transfer_rows=tuple(transfer_rows),
        validation_issues=validation_issues,
        source_system="cfbd",
        source_snapshot_date=date_type.today().isoformat(),
    )


def build_ncaaf_returning_production_generation_report(
    *,
    season: int,
    output_path: Path,
    roster_path: Path,
    transfer_path: Path,
    rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    validation_issues: list[str] | tuple[str, ...],
    source_system: str,
    source_snapshot_date: str,
) -> str:
    lines = [
        "# NCAAF Returning Production Generation Report",
        "",
        "## Outcome",
        "",
        f"Season: {season}",
        f"Generated: {'yes' if not validation_issues else 'partial'}",
        f"Snapshot output: {output_path}",
        f"Roster snapshot input: {roster_path}",
        f"Transfer snapshot input: {transfer_path}",
        f"Source system: {source_system}",
        f"Source snapshot date: {source_snapshot_date}",
        "",
        "## Counts",
        "",
        f"Publishable rows: {len(list(rows))}",
        f"Validation issues: {len(list(validation_issues))}",
        "",
        "## Explicit Answers",
        "",
        f"Was the snapshot generated successfully? {'Yes' if not validation_issues else 'Partially'}.",
        f"How many publishable rows were produced? {len(list(rows))}.",
        f"What validation issues remain? {'None' if not validation_issues else '; '.join(validation_issues)}.",
        f"Is M5 returning-production onboarding now complete? {'Yes, if this artifact is published as the canonical source and the local derivations remain traceable.' if not validation_issues else 'No.'}",
        "",
        "## Validation Notes",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- No validation issues were detected in the returning-production snapshot build.")
    lines.append("")
    return "\n".join(lines)