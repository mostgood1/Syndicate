from __future__ import annotations

import csv
from functools import lru_cache
from typing import Any

from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import recommendation_path
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_num(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_signed(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}"


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _format_moneyline(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _format_ev_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _confidence_rank(value: Any) -> int:
    label = _safe_text(value).lower()
    if label == "high":
        return 3
    if label == "medium":
        return 2
    if label == "low":
        return 1
    return 0


def _team_abbr(team_name: str) -> str:
    tokens = [token for token in team_name.replace(".", " ").split() if token]
    initials = "".join(token[0] for token in tokens if token and token[0].isalpha()).upper()
    if len(initials) >= 2:
        return initials[:3]
    letters = "".join(char for char in team_name.upper() if char.isalpha())
    return (letters[:3] or "TEAM")


def _format_game_date(value: Any) -> str:
    raw = _safe_text(value, "TBD")
    return raw[:10] if len(raw) >= 10 else raw


@lru_cache(maxsize=64)
def _read_snapshot_rows(season: int, week: int) -> tuple[dict[str, Any], ...]:
    path = recommendation_path(week, season=season)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(row for row in csv.DictReader(handle) if isinstance(row, dict))
    except Exception:
        return ()


def _snapshot_source_path(season: int, week: int) -> str:
    return str(recommendation_path(week, season=season))


def _row_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    ev_pct = _safe_float(row.get("ev_pct"))
    return (
        _confidence_rank(row.get("confidence")),
        ev_pct if ev_pct is not None else float("-inf"),
        _safe_text(row.get("type")).upper(),
    )


def _group_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        away_team = _safe_text(row.get("away_team"), "Away")
        home_team = _safe_text(row.get("home_team"), "Home")
        game_date = _format_game_date(row.get("game_date"))
        grouped.setdefault((game_date, away_team, home_team), []).append(row)

    bundles: list[dict[str, Any]] = []
    for (game_date, away_team, home_team), matchup_rows in grouped.items():
        ordered_rows = sorted(matchup_rows, key=_row_sort_key, reverse=True)
        top_row = ordered_rows[0] if ordered_rows else {}
        confidence = _safe_text(top_row.get("confidence"), "Snapshot")
        top_ev = _safe_float(top_row.get("ev_pct"))
        type_scores: dict[str, float] = {}
        for row in ordered_rows:
            type_name = _safe_text(row.get("type"), "Recommendation").upper()
            ev_pct = _safe_float(row.get("ev_pct"))
            if type_name not in type_scores or ((ev_pct if ev_pct is not None else float("-inf")) > type_scores[type_name]):
                type_scores[type_name] = ev_pct if ev_pct is not None else float("-inf")
        bundles.append(
            {
                "game_date": game_date,
                "away_team": away_team,
                "home_team": home_team,
                "rows": ordered_rows,
                "top_row": top_row,
                "top_ev": top_ev,
                "confidence": confidence,
                "moneyline_ev": type_scores.get("MONEYLINE"),
                "spread_ev": type_scores.get("SPREAD"),
                "total_ev": type_scores.get("TOTAL"),
            }
        )
    return bundles


def _official_items(rows: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    for row in rows[:3]:
        rec_type = _safe_text(row.get("type"), "Recommendation").title()
        ev_pct = _format_ev_pct(row.get("ev_pct"))
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        items.append(f"{rec_type}: {ev_pct} EV | {confidence} | Odds {odds}")
    if not items:
        items.append("No stored recommendation rows were available for this matchup.")
    return items


def _top_play_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    top_rows: list[dict[str, str]] = []
    for row in rows[:4]:
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        top_rows.append(
            {
                "name": _safe_text(row.get("type"), "Recommendation").title(),
                "value": _format_ev_pct(row.get("ev_pct")),
                "detail": f"{confidence} | Odds {odds}",
            }
        )
    return top_rows


def _sort_bundles(bundles: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized_sort = _safe_text(sort, "date").lower()

    def _metric(bundle: dict[str, Any], key: str) -> float:
        value = _safe_float(bundle.get(key))
        return value if value is not None else float("-inf")

    if normalized_sort == "winner":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "moneyline_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "ats":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "spread_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "total":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "total_ev"), _metric(bundle, "top_ev")), reverse=True)
    return sorted(bundles, key=lambda bundle: (bundle.get("game_date") or "", -_metric(bundle, "top_ev")))


def _available_card_weeks(season: int | None = None) -> list[int]:
    resolved_season = int(season or latest_season())
    return sorted(week for week in available_weeks(resolved_season) if int(week) > 0)


def _resolved_week(selected_week: int, *, season: int | None = None) -> int:
    resolved_season = int(season or latest_season())
    try:
        requested_week = int(selected_week)
    except Exception:
        requested_week = int(default_week(resolved_season))
    return resolve_selected_value(requested_week, _available_card_weeks(resolved_season), default_week(resolved_season))


def _game_from_snapshot_bundle(bundle: dict[str, Any], season: int, week: int) -> dict[str, Any]:
    away_team = _safe_text(bundle.get("away_team"), "Away")
    home_team = _safe_text(bundle.get("home_team"), "Home")
    away_abbr = _team_abbr(away_team)
    home_abbr = _team_abbr(home_team)
    game_date = _safe_text(bundle.get("game_date"), "TBD")
    ordered_rows = bundle.get("rows") if isinstance(bundle.get("rows"), list) else []
    top_row = bundle.get("top_row") if isinstance(bundle.get("top_row"), dict) else {}
    top_ev = _safe_float(bundle.get("top_ev"))
    top_type = _safe_text(top_row.get("type"), "Recommendation").title()
    confidence = _safe_text(bundle.get("confidence"), "Snapshot").title()
    game_pk = f"{season}-{week}-{game_date}-{away_abbr}-{home_abbr}".replace(" ", "-")
    summary = (
        f"Stored weekly recommendation rows for {away_team} at {home_team}. "
        f"Top signal: {top_type} at {_format_ev_pct(top_ev)} EV."
    )
    return {
        "gamePk": game_pk,
        "card_variant": "shared_default",
        "away": {"abbr": away_abbr, "name": away_team},
        "home": {"abbr": home_abbr, "name": home_team},
        "href": f"/nfl/game/{game_pk}?season={season}&week={week}",
        "href_label": "Open NFL game detail",
        "status": f"Week {week}",
        "detail": game_date,
        "summary": summary,
        "metrics": [
            {"label": "Kickoff", "value": game_date},
            {"label": "Signals", "value": str(len(ordered_rows))},
            {"label": "Top EV", "value": _format_ev_pct(top_ev)},
            {"label": "Best signal", "value": top_type},
        ],
        "shared_top_play_rows": _top_play_rows(ordered_rows),
        "panels": [
            {
                "eyebrow": "Weekly snapshot",
                "title": confidence,
                "body": "NFL cards now summarize the stored weekly recommendation snapshot for this matchup instead of proxying the sibling source app.",
                "items": _official_items(ordered_rows),
            },
            {
                "eyebrow": "Signal mix",
                "title": f"Top EV {_format_ev_pct(top_ev)} | {len(ordered_rows)} stored rows",
                "body": "Snapshot rows are grouped by matchup so cards, game detail, and live lens can share the same local weekly artifact lane.",
                "items": [
                    f"Moneyline rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'MONEYLINE')}",
                    f"Spread rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'SPREAD')}",
                    f"Total rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'TOTAL')}",
                ],
            },
            {
                "eyebrow": "Game context",
                "title": f"{season} Week {week}",
                "body": f"{away_team} at {home_team} on {game_date}.",
                "items": [
                    f"Teams: {away_team} at {home_team}",
                    f"Snapshot-backed game key: {game_pk}",
                    "Pick-side fields are not preserved in the weekly snapshot, so this board summarizes stored signal types and EV instead of full source-card parity.",
                ],
            },
        ],
    }


def build_cards_page_context(selected_week: int, *, season: int | None = None, sort: str = "date") -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    resolved_week = _resolved_week(selected_week or default_week(resolved_season), season=resolved_season)
    season = resolved_season
    rows = list(_read_snapshot_rows(season, resolved_week))
    bundles = _sort_bundles(_group_snapshot_rows(rows), sort)
    games = [_game_from_snapshot_bundle(bundle, season, resolved_week) for bundle in bundles]
    using_sample_data = False

    weeks = _available_card_weeks(season)
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["status"],
        }
        for game in games
    ]
    source_path = _snapshot_source_path(season, resolved_week)
    return apply_game_board_contract(
        {
            "date": f"{season} Week {resolved_week}",
            "requested_date": f"{season} Week {selected_week}",
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/nfl/cards",
            "controls_prev_href": f"/nfl/cards?season={season}&week={prev_week}",
            "controls_next_href": f"/nfl/cards?season={season}&week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "hidden_fields": [{"name": "season", "value": str(season)}],
            "module_links": build_module_links(resolved_week, "Cards", season=season),
            "games": games,
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "source_title": "NFL weekly recommendation snapshot" if games else "NFL cards unavailable",
            "empty_state": {
                "eyebrow": "NFL cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders stored NFL weekly recommendation snapshots, and none were available for the requested season and week.",
                "list_items": [
                    f"Season: {season}",
                    f"Week: {selected_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/nfl/cards",
            "intro_title": "NFL Cards",
            "intro_body": "NFL cards now aggregate stored weekly recommendation snapshots into a shared matchup board, so cards, game detail, and live lens can run from the local mirror lane.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/nfl/season/{season}/betting-card?week={resolved_week}"},
                {"label": "Picks", "href": f"/nfl/picks?season={season}&week={resolved_week}"},
                {"label": "Live Lens", "href": f"/nfl/live-lens?season={season}&week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Season", "value": str(season)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "Snapshot" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "NFL",
        },
        sport="nfl",
        module="cards",
        source_kind="local_artifact",
        live_lens_integrated=False,
    )