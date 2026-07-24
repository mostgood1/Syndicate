from __future__ import annotations

import csv
from datetime import date as date_cls
from functools import lru_cache
import io
import json
from pathlib import Path
from typing import Any

from syndicate.features.soccer.features.schedule import default_season as _computed_default_season
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today_iso


LEAGUE_DISPLAY_NAMES: dict[str, str] = {
    "epl": "EPL",
    "la_liga": "La Liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie A",
    "ligue_1": "Ligue 1",
    "mls": "MLS",
    "eredivisie": "Eredivisie",
    "primeira_liga": "Primeira Liga",
    "championship": "Championship",
    "belgian_pro_league": "Belgian Pro League",
}

DEFAULT_LEAGUE = "epl"


def league_display_name(league: str) -> str:
    return LEAGUE_DISPLAY_NAMES.get(str(league or "").strip().lower(), str(league or "").upper())


def normalize_league(league: str | None) -> str:
    text = str(league or "").strip().lower()
    return text if text in LEAGUE_DISPLAY_NAMES else DEFAULT_LEAGUE


# Approximate calendar-month season windows, mirroring the month-level
# granularity ops_refresh.py's _active_sports_for_date() already uses for
# every other sport (e.g. NBA/NHL: "month >= 10 or month <= 6") rather than
# tracking exact real fixture-list start dates per league/season. Being a
# couple weeks early or late on either edge is low-cost: a league flagged
# "active" too early just means an ESPN schedule/fixture check comes back
# empty for a few ticks (build_soccer_artifacts.py already writes a cheap
# empty artifact and returns when there are no fixtures for the date), while
# being flagged inactive too late would silently stop refreshing a league
# that already has real games -- so windows below lean generous.
#
# MLS runs Feb/Mar - Dec (including playoffs/MLS Cup); every other league
# here follows the standard European Aug - May calendar (a couple, e.g.
# Belgian Pro League, sometimes start a few weeks earlier in practice, but
# are kept on the same Aug - May window rather than guessing an exact date).
_MLS_OFF_SEASON_MONTHS = (1,)
_EUROPEAN_OFF_SEASON_MONTHS = (6, 7)


def league_active_for_date(league: str, date_str: str) -> bool:
    normalized = normalize_league(league)
    try:
        month = date_cls.fromisoformat(str(date_str)[:10]).month
    except Exception:
        return True
    if normalized == "mls":
        return month not in _MLS_OFF_SEASON_MONTHS
    return month not in _EUROPEAN_OFF_SEASON_MONTHS


def active_leagues_for_date(date_str: str) -> list[str]:
    return [league for league in LEAGUE_DISPLAY_NAMES if league_active_for_date(league, date_str)]


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_SOCCER_SOURCE_ROOT",
        local_dir_name="soccer_source",
    )


def _api_root(league: str) -> Path:
    return _source_roots()[0] / normalize_league(league) / "api"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


# --- Per-date recommendations (cards/props source data) --------------------


def recommendations_path(league: str, selected_date: str) -> Path:
    return _api_root(league) / "recommendations" / f"recommendations_{selected_date}.json"


@lru_cache(maxsize=256)
def recommendations_payload(league: str, selected_date: str) -> dict[str, Any] | None:
    return load_json(recommendations_path(league, selected_date))


def live_state_path(league: str, selected_date: str) -> Path:
    return _api_root(league) / "live_state" / f"live_state_{selected_date}.json"


def live_state_payload(league: str, selected_date: str) -> dict[str, Any] | None:
    # Not cached: this file is overwritten by the live poller every cycle,
    # unlike the once-per-date recommendations artifact above.
    return load_json(live_state_path(league, selected_date))


def picks_path(league: str, selected_date: str) -> Path:
    return _api_root(league) / "picks" / f"picks_{selected_date}.csv"


@lru_cache(maxsize=256)
def picks_rows(league: str, selected_date: str) -> tuple[dict[str, str], ...]:
    # Same once-per-tick update cadence as recommendations_payload above
    # (both written by the pregame-phase dispatcher steps), so cached the
    # same way. Tuple (not list) so the cached value stays hashable/immutable.
    path = picks_path(league, selected_date)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except Exception:
        return ()


def game_odds_path(league: str) -> Path:
    return _api_root(league) / "odds" / "game_odds_current.csv"


def game_odds_rows(league: str) -> tuple[dict[str, str], ...]:
    # Not cached: unlike recommendations/picks (one file per date, written
    # once per pregame tick), this is a single rolling "current odds" file
    # per league that gets overwritten every refresh cycle -- same
    # reasoning as live_state_payload above.
    path = game_odds_path(league)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except Exception:
        return ()


def props_odds_path(league: str, selected_date: str) -> Path:
    return _api_root(league).parent / "props" / f"{selected_date}.csv"


def props_odds_rows(league: str, selected_date: str) -> tuple[dict[str, str], ...]:
    # Not cached, same reasoning as game_odds_rows -- a per-date file, but
    # only whatever the props-fetch step captured this tick, not a fixed
    # once-per-date artifact the rest of this module's @lru_cache pattern
    # assumes.
    path = props_odds_path(league, selected_date)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except Exception:
        return ()


def date_index_path(league: str) -> Path:
    return _api_root(league) / "display_prediction_dates.json"


def available_dates(league: str) -> list[str]:
    payload = load_json(date_index_path(league)) or {}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    return sorted({str(item).strip() for item in dates if str(item).strip()})


def default_date(league: str) -> str:
    dates = available_dates(league)
    today = central_today_iso()
    if today in dates:
        return today
    return dates[-1] if dates else today


# --- Team directory (id/abbr/crest/colors) ----------------------------------
#
# Sourced from the shared cross-sport `team_branding` module/snapshot
# (scripts/build_team_branding_snapshot.py --sport <league>), not a
# soccer-only artifact -- every other sport in this app gets its team
# crest/colors the same way, from the same ESPN teams endpoint, so soccer
# reuses that pipeline instead of maintaining its own parallel one.


def _normalize_team_key(value: str) -> str:
    return str(value or "").strip().lower()


def team_branding_path(league: str) -> Path:
    league = normalize_league(league)
    root = preferred_source_roots(
        __file__,
        env_var="SYNDICATE_SOCCER_SOURCE_ROOT",
        local_dir_name=f"soccer_source/{league}",
    )[0]
    return root / "source_artifacts" / "data" / "processed" / "team_branding" / f"{league}_team_branding.csv"


@lru_cache(maxsize=32)
def _team_branding_rows(league: str) -> tuple[Any, ...]:
    from syndicate.features.shared.team_branding import read_team_branding_snapshot

    return read_team_branding_snapshot(team_branding_path(league))


def _team_dict(row: Any) -> dict[str, Any]:
    return {
        "team_id": row.team_id,
        "name": row.display_name,
        "abbreviation": row.abbreviation,
        "short_name": row.location,
        "color": str(row.primary_color or "").lstrip("#"),
        "alternate_color": str(row.secondary_color or "").lstrip("#"),
        "logo_url": row.logo_url or "",
    }


@lru_cache(maxsize=32)
def _team_index(league: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _team_branding_rows(league):
        team = _team_dict(row)
        for key in (team.get("name"), team.get("abbreviation"), team.get("short_name")):
            normalized = _normalize_team_key(key)
            if normalized:
                index.setdefault(normalized, team)
    return index


def team_by_id(league: str, team_id: str) -> dict[str, Any] | None:
    for row in _team_branding_rows(league):
        if str(row.team_id) == str(team_id):
            return _team_dict(row)
    return None


def team_by_name(league: str, team_name: str) -> dict[str, Any] | None:
    return _team_index(league).get(_normalize_team_key(team_name))


def all_teams(league: str) -> list[dict[str, Any]]:
    return [_team_dict(row) for row in _team_branding_rows(league)]


# --- Full rosters ------------------------------------------------------------


def rosters_path(league: str, season: int) -> Path:
    return _api_root(league) / "rosters" / f"rosters_{season}.csv"


@lru_cache(maxsize=32)
def roster_rows(league: str, season: int) -> tuple[dict[str, Any], ...]:
    path = rosters_path(league, season)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ()
    return tuple(dict(row) for row in csv.DictReader(io.StringIO(text)))


def team_roster_rows(league: str, season: int, team_id: str) -> list[dict[str, Any]]:
    return [row for row in roster_rows(league, season) if str(row.get("team_id") or "") == str(team_id)]


# A bare matchday squad is 18 (11 starters + 7 subs); real registered
# squads run 20-30+. Below this, ESPN's own roster feed is almost certainly
# incomplete rather than the club genuinely having a tiny squad -- observed
# directly for several Bundesliga/La Liga/Ligue 1 clubs whose 2026-27
# squads were still being populated on ESPN's side (see
# soccersim_phase1_build_report.md Phase 14; confirmed non-transient by
# retrying the raw ESPN response, not assumed).
SPARSE_ROSTER_THRESHOLD = 15


def sparse_roster_teams(league: str, season: int, *, threshold: int = SPARSE_ROSTER_THRESHOLD) -> list[dict[str, Any]]:
    """Teams whose stored roster looks incomplete. Used both at build time
    (to warn the operator running build_soccer_rosters.py) and at serve
    time (team.py's roster page warns the reader) so this data gap is
    surfaced rather than silently presented as a complete squad."""
    counts: dict[str, int] = {}
    for row in roster_rows(league, season):
        team_id = str(row.get("team_id") or "").strip()
        if team_id:
            counts[team_id] = counts.get(team_id, 0) + 1
    sparse: list[dict[str, Any]] = []
    for team in all_teams(league):
        team_id = str(team.get("team_id") or "").strip()
        count = counts.get(team_id, 0)
        if count < threshold:
            sparse.append({"team_id": team_id, "name": team.get("name"), "player_count": count})
    return sparse


def roster_player_count(league: str, season: int, team_id: str) -> int:
    return len(team_roster_rows(league, season, team_id))


# --- Full-season schedule + computed matchweeks -----------------------------


def default_season(league: str) -> int:
    return _computed_default_season(league)


def schedule_path(league: str, season: int) -> Path:
    return _api_root(league) / "schedule" / f"schedule_{season}.json"


@lru_cache(maxsize=32)
def schedule_payload(league: str, season: int) -> dict[str, Any] | None:
    return load_json(schedule_path(league, season))


def available_weeks(league: str, season: int) -> list[int]:
    payload = schedule_payload(league, season) or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    return sorted({int(item["week"]) for item in weeks if isinstance(item, dict) and item.get("week") is not None})


def week_index_entry(league: str, season: int, week: int) -> dict[str, Any] | None:
    payload = schedule_payload(league, season) or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    for item in weeks:
        if isinstance(item, dict) and int(item.get("week") or -1) == int(week):
            return item
    return None


def week_matches(league: str, season: int, week: int) -> list[dict[str, Any]]:
    payload = schedule_payload(league, season) or {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    return [row for row in matches if isinstance(row, dict) and row.get("week") == int(week)]


def week_date_list(league: str, season: int, week: int) -> list[str]:
    dates = {str(row.get("date") or "")[:10] for row in week_matches(league, season, week)}
    return sorted(date_str for date_str in dates if date_str)


def default_week(league: str, season: int) -> int:
    weeks = available_weeks(league, season)
    if not weeks:
        return 1
    today = date_cls.today()
    for week in weeks:
        entry = week_index_entry(league, season, week) or {}
        start = str(entry.get("start_date") or "")
        end = str(entry.get("end_date") or "")
        try:
            if start and end and date_cls.fromisoformat(start) <= today <= date_cls.fromisoformat(end):
                return week
        except ValueError:
            continue
    for week in weeks:
        entry = week_index_entry(league, season, week) or {}
        start = str(entry.get("start_date") or "")
        try:
            if start and date_cls.fromisoformat(start) >= today:
                return week
        except ValueError:
            continue
    return weeks[-1]


def week_label(league: str, season: int, week: int) -> str:
    entry = week_index_entry(league, season, week) or {}
    start = str(entry.get("start_date") or "")
    end = str(entry.get("end_date") or "")
    if start and end:
        return f"Week {week} ({start} to {end})"
    return f"Week {week}"


def team_schedule_rows(league: str, season: int, team_id: str) -> list[dict[str, Any]]:
    team = team_by_id(league, team_id)
    if team is None:
        return []
    team_name = _normalize_team_key(team.get("name"))
    payload = schedule_payload(league, season) or {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    return [
        row
        for row in matches
        if isinstance(row, dict)
        and (_normalize_team_key(row.get("home_team")) == team_name or _normalize_team_key(row.get("away_team")) == team_name)
    ]


# --- Navigation --------------------------------------------------------------


def build_module_links(league: str, week: int, season: int, active_label: str) -> list[dict[str, Any]]:
    league = normalize_league(league)
    query = f"?week={week}&season={season}"
    links = [
        ("Cards", f"/soccer/{league}/cards{query}"),
        ("Props", f"/soccer/{league}/props{query}"),
        ("Live Lens", f"/soccer/{league}/live-lens{query}"),
        ("Weekly Archive", f"/soccer/{league}/archive{query}"),
        ("Hub", "/soccer/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def league_select_control(current_league: str, *, page_path: str, query_suffix: str = "") -> dict[str, Any]:
    """An `extra_controls` entry for `shared/_date_controls.html` that
    navigates to the same page under a different league on change (see the
    `onchange` support added there for this)."""
    options = [{"value": slug, "label": name} for slug, name in LEAGUE_DISPLAY_NAMES.items()]
    onchange = f"window.location.href = '/soccer/' + this.value + '{page_path}{query_suffix}'"
    return {
        "label": "League",
        "name": "league",
        "type": "select",
        "value": normalize_league(current_league),
        "options": options,
        "onchange": onchange,
    }
