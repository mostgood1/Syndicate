from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from syndicate.features.football.ingestion.source_fetchers import ensure_directory
from syndicate.features.football.ingestion.source_fetchers import load_tabular_rows
from syndicate.features.football.ingestion.source_fetchers import save_json
from syndicate.features.football.ingestion.source_fetchers import tracking_root
from syndicate.features.shared.source_roots import preferred_artifact_roots


RBSDM_STATS_URL = "https://rbsdm.com/stats"


class _SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            self._current_row.append("".join(self._current_cell).strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if any(cell.strip() for cell in self._current_row):
                self._current_table.append(self._current_row)
        elif tag == "table" and self._in_table:
            self._in_table = False
            if self._current_table:
                self.tables.append(self._current_table)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def rbsdm_tracking_root() -> Path:
    return tracking_root("nfl_source") / "rbsdm"


def rbsdm_tracking_roots() -> tuple[Path, ...]:
    roots = []
    for base_root in preferred_artifact_roots(__file__, env_var="SYNDICATE_NFL_SOURCE_ROOT", local_dir_name="nfl_source"):
        candidate = base_root / "tracking" / "rbsdm"
        if candidate not in roots:
            roots.append(candidate)
    return tuple(roots)


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _load_rows_from_path(path: Path) -> list[dict[str, Any]]:
    return load_tabular_rows(path)


def _fetch_stats_page() -> str | None:
    try:
        with urlopen(RBSDM_STATS_URL, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return None


def _parse_tables(html: str) -> list[dict[str, Any]]:
    parser = _SimpleTableParser()
    parser.feed(html)
    rows: list[dict[str, Any]] = []
    for table in parser.tables:
        if len(table) < 2:
            continue
        header = [cell.strip() for cell in table[0]]
        for data_row in table[1:]:
            if len(data_row) != len(header):
                continue
            row = {header[idx]: data_row[idx] for idx in range(len(header))}
            rows.append(row)
    return rows


@lru_cache(maxsize=16)
def load_rbsdm_rows(source_root: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    if source_root is not None:
        rows = _load_rows_from_path(Path(source_root))
        return tuple(row for row in rows if isinstance(row, dict))

    rows: list[dict[str, Any]] = []
    for root in rbsdm_tracking_roots():
        rows.extend(_load_rows_from_path(root))
        if rows:
            break
    if rows:
        return tuple(row for row in rows if isinstance(row, dict))

    html = _fetch_stats_page()
    if not html:
        return ()
    rows = _parse_tables(html)
    if rows:
        cache_dir = ensure_directory(rbsdm_tracking_root())
        save_json(cache_dir / "stats_page.json", {"source": RBSDM_STATS_URL, "rows": rows})
    return tuple(row for row in rows if isinstance(row, dict))


def _match_team_row(rows: list[dict[str, Any]], *, team: str, season: int | None = None, week: int | None = None) -> dict[str, Any] | None:
    target = _safe_text(team, "").upper()
    if not target:
        return None
    for row in rows:
        row_team = _safe_text(
            row.get("team")
            or row.get("team_abbr")
            or row.get("team_id")
            or row.get("posteam")
            or row.get("Team")
            or row.get("TEAM")
            or ""
        ).upper()
        if row_team != target:
            continue
        if season is not None:
            row_season = _safe_float(row.get("season") or row.get("Season"))
            if row_season is not None and int(row_season) != int(season):
                continue
        if week is not None:
            row_week = _safe_float(row.get("week") or row.get("Week"))
            if row_week is not None and int(row_week) != int(week):
                continue
        return row
    return None


def _first_float(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _game_side_metrics(row: dict[str, Any], *, side: str) -> dict[str, Any]:
    prefix = f"{side}_"
    offensive_epa = _first_float(row, [f"{prefix}offensive_epa", f"{prefix}off_epa", f"{prefix}epa_play", f"{side}_off_epa"])
    defensive_epa = _first_float(row, [f"{prefix}defensive_epa", f"{prefix}def_epa", f"{prefix}epa_allowed", f"{side}_def_epa"])
    success_rate = _first_float(row, [f"{prefix}success_rate", f"{side}_success_rate", "Success Rate", "SR"])
    success_rate_allowed = _first_float(row, [f"{prefix}success_rate_allowed", f"{side}_success_rate_allowed"])
    pass_rate = _first_float(row, [f"{prefix}pass_rate", f"{side}_pass_rate", "Neutral Pass Freq"])
    proe = _first_float(row, [f"{prefix}proe", "proe", f"{side}_proe", "Pass Over Expected", "pass_rate_over_expected", "pass_rate_over_expectation"])
    red_zone_efficiency = _first_float(row, [f"{prefix}red_zone_efficiency", f"{side}_rzd_off_eff", f"{side}_red_zone_efficiency"])
    explosive_play_rate = _first_float(row, [f"{prefix}explosive_play_rate", f"{side}_explosive_play_rate", f"{side}_explosive_pass_rate"])
    pace = _first_float(row, [f"{prefix}pace_secs_play", f"{side}_pace_secs_play", "pace_secs_play"])
    return {
        "offensive_epa": offensive_epa,
        "defensive_epa": defensive_epa,
        "success_rate": success_rate,
        "success_rate_allowed": success_rate_allowed,
        "pass_rate": pass_rate,
        "proe": proe,
        "red_zone_efficiency": red_zone_efficiency,
        "explosive_play_rate": explosive_play_rate,
        "pace_secs_play": pace,
    }


def build_rbsdm_game_metrics(
    game: dict[str, Any],
    *,
    season: int | None = None,
    week: int | None = None,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    rows = list(load_rbsdm_rows(source_root))
    if not rows:
        return {}
    home_team = _safe_text((game.get("home") or {}).get("abbr") or game.get("home_team") or "")
    away_team = _safe_text((game.get("away") or {}).get("abbr") or game.get("away_team") or "")
    home_row = _match_team_row(rows, team=home_team, season=season, week=week)
    away_row = _match_team_row(rows, team=away_team, season=season, week=week)
    if home_row is None and away_row is None:
        return {}

    home_metrics = _game_side_metrics(home_row or {}, side="home")
    away_metrics = _game_side_metrics(away_row or {}, side="away")
    home_offensive = home_metrics.get("offensive_epa") or away_metrics.get("defensive_epa")
    away_offensive = away_metrics.get("offensive_epa") or home_metrics.get("defensive_epa")
    home_defensive = home_metrics.get("defensive_epa") or away_metrics.get("offensive_epa")
    away_defensive = away_metrics.get("defensive_epa") or home_metrics.get("offensive_epa")

    proe_values = [value for value in (home_metrics.get("proe"), away_metrics.get("proe")) if value is not None]
    success_values = [value for value in (home_metrics.get("success_rate"), away_metrics.get("success_rate")) if value is not None]

    return {
        "source": "rbsdm_team_efficiency",
        "source_root": str(Path(source_root) if source_root is not None else rbsdm_tracking_root()),
        "home_team": home_team,
        "away_team": away_team,
        "season": season,
        "week": week,
        "row_count": int(bool(home_row)) + int(bool(away_row)),
        "epa_per_play": home_offensive,
        "success_rate": home_metrics.get("success_rate"),
        "proe": _rate(proe_values),
        "home_offensive_epa": home_offensive,
        "away_offensive_epa": away_offensive,
        "home_defensive_epa": home_defensive,
        "away_defensive_epa": away_defensive,
        "home_success_rate": home_metrics.get("success_rate"),
        "away_success_rate": away_metrics.get("success_rate"),
        "home_success_rate_allowed": home_metrics.get("success_rate_allowed"),
        "away_success_rate_allowed": away_metrics.get("success_rate_allowed"),
        "home_pass_rate": home_metrics.get("pass_rate"),
        "away_pass_rate": away_metrics.get("pass_rate"),
        "home_red_zone_efficiency": home_metrics.get("red_zone_efficiency"),
        "away_red_zone_efficiency": away_metrics.get("red_zone_efficiency"),
        "home_explosive_play_rate": home_metrics.get("explosive_play_rate"),
        "away_explosive_play_rate": away_metrics.get("explosive_play_rate"),
        "home_pace_secs_play": home_metrics.get("pace_secs_play"),
        "away_pace_secs_play": away_metrics.get("pace_secs_play"),
        "game_success_rate": _rate(success_values),
    }
