from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any

from syndicate.features.shared.formatters import format_num
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.formatters import format_signed_price
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots


_SEASON_PATTERN = re.compile(r"college_football_betting_lines_(\d{4})\.csv", re.IGNORECASE)


def _source_roots() -> list[Path]:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_NCAAF_SOURCE_ROOT",
        local_dir_name="ncaaf_source",
    )


def default_ncaaf_source_root() -> Path:
    return _source_roots()[0]


def _artifact_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_NCAAF_SOURCE_ROOT",
        local_dir_name="ncaaf_source",
    )


def data_path(*parts: str) -> Path:
    roots = _source_roots()
    if roots:
        return roots[0] / "data" / Path(*parts)
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "data" / Path(*parts)


def ncaaf_source_artifacts_data_path(*parts: str) -> Path:
    return default_ncaaf_source_root() / "source_artifacts" / "data" / Path(*parts)


def player_identity_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "player_identity", "ncaaf_player_identity_snapshot.csv")


def roster_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "roster", "ncaaf_roster_snapshot.csv")


def transfer_portal_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "transfers", "ncaaf_transfer_portal_snapshot.csv")


def team_registry_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "team_registry", "ncaaf_team_registry_snapshot.csv")


def returning_production_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "returning_production", "ncaaf_returning_production_snapshot.csv")


def coach_continuity_snapshot_path() -> Path:
    return ncaaf_source_artifacts_data_path("processed", "coach_continuity", "ncaaf_coach_continuity_snapshot.csv")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_summary_index() -> dict[str, Any] | None:
    return load_json(data_path("recommendations_summary", "index.json"))


def default_season() -> int:
    payload = load_summary_index() or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    for week in weeks:
        if not isinstance(week, dict):
            continue
        fetch = week.get("fetch") if isinstance(week.get("fetch"), dict) else {}
        for key in ("stdout", "stderr"):
            text = fetch.get(key)
            if not isinstance(text, str):
                continue
            match = _SEASON_PATTERN.search(text)
            if match:
                return int(match.group(1))
    generated_utc = payload.get("generated_utc")
    if isinstance(generated_utc, str) and len(generated_utc) >= 4 and generated_utc[:4].isdigit():
        return int(generated_utc[:4])
    return 2025


def week_summaries() -> list[dict[str, Any]]:
    payload = load_summary_index() or {}
    weeks = payload.get("weeks") if isinstance(payload.get("weeks"), list) else []
    resolved_default_season = default_season()
    output: list[dict[str, Any]] = []
    for week in weeks:
        if not isinstance(week, dict):
            continue
        try:
            week_number = int(week.get("week"))
        except Exception:
            continue
        try:
            count = int(week.get("count") or 0)
        except Exception:
            count = 0
        fetch = week.get("fetch") if isinstance(week.get("fetch"), dict) else {}
        output.append(
            {
                "week": week_number,
                "season": int(week.get("season") or resolved_default_season),
                "count": count,
                "path": str(week.get("path") or summary_path(week_number)),
                "fetch_rc": fetch.get("rc"),
                "has_data": count > 0,
            }
        )
    return sorted(output, key=lambda item: item["week"])


def available_weeks() -> list[int]:
    return [item["week"] for item in week_summaries() if item["has_data"]]


def default_week() -> int:
    weeks = available_weeks()
    return weeks[-1] if weeks else 1


def summary_path(week: int) -> Path:
    return data_path("recommendations_summary", f"week_{week}.json")


def format_moneyline(value: Any) -> str:
    return format_signed_price(value)


def build_module_links(selected_week: int, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season) if season is not None else default_season()
    betting_href = f"/ncaaf/season/{resolved_season}/betting-card?week={selected_week}"
    links = [
        ("Cards", f"/ncaaf/cards?week={selected_week}"),
        ("Betting Card", betting_href),
        ("Picks", f"/ncaaf/picks?week={selected_week}"),
        ("Live Lens", f"/ncaaf/live-lens?week={selected_week}"),
        ("Daily Archive", f"/ncaaf/archive?week={selected_week}"),
        ("Hub", "/ncaaf/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def ncaaf_target_week(season: int) -> int | None:
    """Real calendar-driven "which week should we be preparing simulations
    for right now" -- mirrors syndicate.features.nfl.sources.nfl_target_week
    exactly: the lowest week number in the real schedule
    (historical_truth/games_{season}.json.gz, via load_games_season) with
    any game whose real `completed` field is False. None if the season
    isn't loaded yet, or every loaded game is already marked completed."""
    from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_games_season

    try:
        games = load_games_season(season)
    except Exception:
        return None
    weeks_with_unplayed_games: set[int] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        if game.get("completed"):
            continue
        week = game.get("week")
        try:
            weeks_with_unplayed_games.add(int(week))
        except (TypeError, ValueError):
            continue
    return min(weeks_with_unplayed_games) if weeks_with_unplayed_games else None