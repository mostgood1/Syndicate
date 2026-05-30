from __future__ import annotations

import csv
import json
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.request import Request
from urllib.request import urlopen

from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import available_dates as source_available_dates
from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import format_num
from syndicate.features.nhl.sources import format_pct
from syndicate.features.nhl.sources import format_price
from syndicate.features.nhl.sources import market_label
from syndicate.features.nhl.sources import parse_iso_date
from syndicate.features.nhl.sources import processed_path
from syndicate.features.nhl.sources import recommendation_path
from syndicate.features.nhl.sources import props_lines_snapshot_path
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import team_abbreviation
from syndicate.features.nhl.sources import team_logo_url
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _public_schedule_fallback_enabled() -> bool:
    value = str(os.environ.get("NHL_PUBLIC_SCHEDULE_FALLBACK") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _pct_text(value: Any) -> str:
    number = _safe_float(value)
    return format_pct(number) if number is not None else "-"


def _coalesce_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _period_projection_text(home_value: Any, away_value: Any) -> str:
    home = format_num(home_value)
    away = format_num(away_value)
    return f"{away} - {home}"


def _best_edges(row: dict[str, Any]) -> list[str]:
    candidates: list[tuple[float, str]] = []
    mappings = [
        ("ev_home_ml", f"Home ML {format_pct(row.get('ev_home_ml'))} at {format_price(row.get('home_ml_odds'))}"),
        ("ev_away_ml", f"Away ML {format_pct(row.get('ev_away_ml'))} at {format_price(row.get('away_ml_odds'))}"),
        ("ev_over", f"Over {format_pct(row.get('ev_over'))} at {format_price(row.get('over_odds'))}"),
        ("ev_under", f"Under {format_pct(row.get('ev_under'))} at {format_price(row.get('under_odds'))}"),
        ("ev_home_pl_-1.5", f"Home -1.5 {format_pct(row.get('ev_home_pl_-1.5'))} at {format_price(row.get('home_pl_-1.5_odds'))}"),
        ("ev_away_pl_+1.5", f"Away +1.5 {format_pct(row.get('ev_away_pl_+1.5'))} at {format_price(row.get('away_pl_+1.5_odds'))}"),
        ("ev_f10_yes", f"First 10 Yes {format_pct(row.get('ev_f10_yes'))}"),
    ]
    for key, label in mappings:
        value = _safe_float(row.get(key))
        if value is None:
            continue
        candidates.append((value, label))
    ordered = [label for _, label in sorted(candidates, key=lambda item: item[0], reverse=True)[:3]]
    return ordered or ["No positive model edge was stored for this matchup."]


def _game_from_row(row: dict[str, str], *, idx: int, selected_date: str) -> dict[str, Any]:
    home_name = str(row.get("home") or "Home").strip() or "Home"
    away_name = str(row.get("away") or "Away").strip() or "Away"
    home_abbr = team_abbreviation(home_name)
    away_abbr = team_abbreviation(away_name)
    home_ml = _safe_float(row.get("home_ml_odds"))
    away_ml = _safe_float(row.get("away_ml_odds"))
    total_line = _coalesce_float(row, "total_line_used", "totals_line_used", "total_line")
    model_total_value = _safe_float(row.get("model_total"))
    model_spread_value = _safe_float(row.get("model_spread"))
    proj_home_goals = _safe_float(row.get("proj_home_goals"))
    proj_away_goals = _safe_float(row.get("proj_away_goals"))
    model_total = format_num(row.get("model_total"))
    model_spread = format_num(row.get("model_spread"))
    game_id = str(idx)
    best_edges = _best_edges(row)
    return {
        "gamePk": game_id,
        "away_tri": away_abbr,
        "away_name": away_name,
        "home_tri": home_abbr,
        "home_name": home_name,
        "away_logo": team_logo_url(away_abbr),
        "home_logo": team_logo_url(home_abbr),
        "away": {"abbr": away_abbr, "name": away_name, "logo": team_logo_url(away_abbr)},
        "home": {"abbr": home_abbr, "name": home_name, "logo": team_logo_url(home_abbr)},
        "status": "Processed artifact",
        "detail": str(row.get("date_et") or selected_date).strip() or selected_date,
        "summary": f"Projected total {model_total} | spread {model_spread}",
        "gameType": "NHL",
        "odds": {
            "commence_time": str(row.get("date") or "").strip() or None,
            "sportsbook": str(
                row.get("home_ml_book")
                or row.get("away_ml_book")
                or row.get("over_book")
                or row.get("under_book")
                or ""
            ).strip() or None,
        },
        "betting": {
            "home_ml": home_ml,
            "away_ml": away_ml,
            "total": total_line,
            "p_home_win": _safe_float(row.get("p_home_ml")),
            "p_away_win": _safe_float(row.get("p_away_ml")),
            "p_total_over": _safe_float(row.get("p_over")),
            "p_total_under": _safe_float(row.get("p_under")),
            "p_home_pl": _safe_float(row.get("p_home_pl_-1.5")),
            "p_away_pl": _safe_float(row.get("p_away_pl_+1.5")),
            "home_ml_ev": _safe_float(row.get("ev_home_ml")),
            "away_ml_ev": _safe_float(row.get("ev_away_ml")),
            "over_ev": _safe_float(row.get("ev_over")),
            "under_ev": _safe_float(row.get("ev_under")),
            "home_puck_line": -1.5,
            "away_puck_line": 1.5,
            "home_puck_line_ev": _safe_float(row.get("ev_home_pl_-1.5")),
            "away_puck_line_ev": _safe_float(row.get("ev_away_pl_+1.5")),
        },
        "sim": {
            "score": {
                "home_mean": proj_home_goals,
                "away_mean": proj_away_goals,
                "total_mean": model_total_value,
                "margin_mean": model_spread_value,
            },
            "periods": {
                "p1": {
                    "home_mean": _safe_float(row.get("period1_home_proj")),
                    "away_mean": _safe_float(row.get("period1_away_proj")),
                },
                "p2": {
                    "home_mean": _safe_float(row.get("period2_home_proj")),
                    "away_mean": _safe_float(row.get("period2_away_proj")),
                },
                "p3": {
                    "home_mean": _safe_float(row.get("period3_home_proj")),
                    "away_mean": _safe_float(row.get("period3_away_proj")),
                },
            },
            "first10": {
                "projection": _safe_float(row.get("first_10min_proj")),
                "prob_yes": _safe_float(row.get("p_f10_yes")),
                "prob_no": _safe_float(row.get("p_f10_no")),
                "ev_yes": _safe_float(row.get("ev_f10_yes")),
                "ev_no": _safe_float(row.get("ev_f10_no")),
            },
        },
        "metrics": [
            {"label": "Away ML", "value": format_price(row.get("away_ml_odds"))},
            {"label": "Home ML", "value": format_price(row.get("home_ml_odds"))},
            {"label": "Total", "value": format_num(row.get("total_line_used"))},
            {"label": "Model total", "value": model_total},
            {"label": "Home win", "value": _pct_text(row.get("p_home_ml"))},
            {"label": "First 10 yes", "value": _pct_text(row.get("p_f10_yes"))},
        ],
        "panels": [
            {
                "eyebrow": "Market snapshot",
                "title": "Moneyline and total board",
                "body": f"Home ML {format_price(row.get('home_ml_odds'))} | Away ML {format_price(row.get('away_ml_odds'))} | total {format_num(row.get('total_line_used'))}.",
                "summary_stats": [
                    {"label": "Home ML", "value": format_price(row.get("home_ml_odds"))},
                    {"label": "Away ML", "value": format_price(row.get("away_ml_odds"))},
                    {"label": "Over", "value": format_price(row.get("over_odds"))},
                    {"label": "Under", "value": format_price(row.get("under_odds"))},
                ],
            },
            {
                "eyebrow": "Model outlook",
                "title": "Projected scoring and period splits",
                "body": "The stored predictions file already carries full-game, period, and first-10 projections for the matchup.",
                "items": [
                    f"Projected score: {away_name} {format_num(row.get('proj_away_goals'))} | {home_name} {format_num(row.get('proj_home_goals'))}",
                    f"Period 1: {_period_projection_text(row.get('period1_home_proj'), row.get('period1_away_proj'))}",
                    f"Period 2: {_period_projection_text(row.get('period2_home_proj'), row.get('period2_away_proj'))}",
                    f"Period 3: {_period_projection_text(row.get('period3_home_proj'), row.get('period3_away_proj'))}",
                ],
            },
            {
                "eyebrow": "Top edges",
                "title": "Best playable angles",
                "body": "Positive-EV sides are lifted directly from the saved prediction row instead of recomputing anything inside Syndicate.",
                "items": best_edges,
            },
            {
                "eyebrow": "Probability checks",
                "title": "Win and total confidence",
                "body": "Model probabilities and first-10 scoring chances stay visible on the card so the main NHL pane remains a first-read workflow.",
                "summary_stats": [
                    {"label": "Home ML", "value": _pct_text(row.get("p_home_ml"))},
                    {"label": "Away ML", "value": _pct_text(row.get("p_away_ml"))},
                    {"label": "Over", "value": _pct_text(row.get("p_over"))},
                    {"label": "Under", "value": _pct_text(row.get("p_under"))},
                ],
                "items": [
                    f"Home -1.5: {_pct_text(row.get('p_home_pl_-1.5'))}",
                    f"Away +1.5: {_pct_text(row.get('p_away_pl_+1.5'))}",
                    f"First 10 yes: {_pct_text(row.get('p_f10_yes'))}",
                    f"First 10 no: {_pct_text(row.get('p_f10_no'))}",
                ],
            },
        ],
        "href": f"/nhl/picks?date={selected_date}",
        "href_label": "Open NHL picks",
    }


def _games_from_artifact(selected_date: str) -> tuple[list[dict[str, Any]], str]:
    primary_path = processed_path(f"predictions_{selected_date}.csv")
    sim_path = processed_path(f"predictions_sim_{selected_date}.csv")
    rows = _load_csv_rows(primary_path)
    source_path = primary_path
    if not rows:
        rows = _load_csv_rows(sim_path)
        if rows:
            source_path = sim_path
    games = [_game_from_row(row, idx=idx, selected_date=selected_date) for idx, row in enumerate(rows, start=1)]
    return games, str(source_path)


def _games_from_scoreboard_snapshot(selected_date: str) -> tuple[list[dict[str, Any]], str]:
    path = scoreboard_snapshot_path(selected_date)
    rows = _load_csv_rows(path) if path.exists() else []
    games: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        away_name = str(row.get("away") or "Away").strip() or "Away"
        home_name = str(row.get("home") or "Home").strip() or "Home"
        away_abbr = team_abbreviation(away_name)
        home_abbr = team_abbreviation(home_name)
        away_goals = _safe_float(row.get("away_goals"))
        home_goals = _safe_float(row.get("home_goals"))
        game_state = str(row.get("gameState") or "").strip().upper()
        detail = "Final" if game_state == "OFF" else (game_state or selected_date)
        summary = (
            f"Score {away_abbr} {format_num(away_goals)} - {format_num(home_goals)} {home_abbr}"
            if away_goals is not None and home_goals is not None
            else "Archived scoreboard snapshot"
        )
        games.append(
            {
                "gamePk": str(row.get("gamePk") or idx),
                "away_tri": away_abbr,
                "away_name": away_name,
                "home_tri": home_abbr,
                "home_name": home_name,
                "away_logo": team_logo_url(away_abbr),
                "home_logo": team_logo_url(home_abbr),
                "away": {"abbr": away_abbr, "name": away_name, "logo": team_logo_url(away_abbr)},
                "home": {"abbr": home_abbr, "name": home_name, "logo": team_logo_url(home_abbr)},
                "status": "Archived scoreboard",
                "detail": detail,
                "summary": summary,
                "gameType": "NHL",
                "metrics": [
                    {"label": "Away goals", "value": format_num(away_goals)},
                    {"label": "Home goals", "value": format_num(home_goals)},
                    {"label": "State", "value": game_state or "-"},
                ],
                "panels": [
                    {
                        "eyebrow": "Archived scoreboard",
                        "title": "Saved game state",
                        "body": "This NHL card is being reconstructed from the archived scoreboard snapshot because the processed predictions row was unavailable for this date.",
                        "summary_stats": [
                            {"label": away_abbr, "value": format_num(away_goals)},
                            {"label": home_abbr, "value": format_num(home_goals)},
                            {"label": "State", "value": game_state or "-"},
                        ],
                    }
                ],
                "href": "/nhl",
                "href_label": "Open NHL hub",
            }
        )
    return games, str(path)


def _recommendation_rows(selected_date: str) -> tuple[list[dict[str, str]], str]:
    path = recommendation_path(selected_date)
    rows = _load_csv_rows(path) if path.exists() else []
    return rows, str(path)


def _prediction_bundle_rows(selected_date: str) -> tuple[list[dict[str, Any]], str]:
    primary_path = processed_path(f"predictions_{selected_date}.csv")
    sim_path = processed_path(f"predictions_sim_{selected_date}.csv")
    rows = _load_csv_rows(primary_path)
    source_path = primary_path
    if not rows:
        rows = _load_csv_rows(sim_path)
        if rows:
            source_path = sim_path
    sim_rows_by_game = _prediction_sim_rows_by_game(selected_date)
    goalie_names_by_team = _sim_goalie_names_by_game_team(selected_date)
    schedule_rows_by_game = _schedule_rows_by_game(selected_date)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        enriched = dict(row)
        home_name = str(row.get("home") or "").strip()
        away_name = str(row.get("away") or "").strip()
        game_key = (away_name, home_name)
        home_abbr = team_abbreviation(home_name)
        away_abbr = team_abbreviation(away_name)
        sim_row = sim_rows_by_game.get(game_key, {})
        schedule_row = schedule_rows_by_game.get(game_key, {})
        away_goalie_name = goalie_names_by_team.get((away_name, home_name, away_name))
        home_goalie_name = goalie_names_by_team.get((away_name, home_name, home_name))

        numeric_sim_fields = (
            "proj_home_goals",
            "proj_away_goals",
            "model_total",
            "p_home_ml",
            "p_away_ml",
            "period1_home_proj",
            "period1_away_proj",
            "period2_home_proj",
            "period2_away_proj",
            "period3_home_proj",
            "period3_away_proj",
            "p_f10_yes",
            "p_f10_no",
            "home_ml_odds",
            "away_ml_odds",
            "over_odds",
            "under_odds",
            "home_pl_-1.5_odds",
            "away_pl_+1.5_odds",
            "p_over",
            "p_under",
            "p_home_pl_-1.5",
            "p_away_pl_+1.5",
            "ev_home_ml",
            "ev_away_ml",
            "ev_over",
            "ev_under",
            "ev_home_pl_-1.5",
            "ev_away_pl_+1.5",
        )
        for key in numeric_sim_fields:
            value = _safe_float(sim_row.get(key))
            if value is not None:
                enriched[key] = value

        total_line_value = _safe_float(sim_row.get("totals_line_used"))
        if total_line_value is not None:
            enriched["total_line_used"] = total_line_value
        enriched.setdefault("gamePk", str(idx))
        enriched.setdefault("game_pk", str(idx))
        enriched.setdefault("home_abbr", home_abbr)
        enriched.setdefault("away_abbr", away_abbr)
        enriched.setdefault("home_logo", team_logo_url(home_abbr))
        enriched.setdefault("away_logo", team_logo_url(away_abbr))
        enriched.setdefault("scheduled_start_utc", str(row.get("date") or "").strip() or None)
        enriched.setdefault("start_time_utc", str(row.get("date") or "").strip() or None)
        enriched.setdefault("game_state", "FUT")
        enriched.setdefault("pl_line_used", 1.5)
        enriched.setdefault("away_goalie_name", away_goalie_name)
        enriched.setdefault("home_goalie_name", home_goalie_name)
        enriched.setdefault("away_goalie", away_goalie_name)
        enriched.setdefault("home_goalie", home_goalie_name)
        if schedule_row.get("scheduled_start_utc"):
            enriched["scheduled_start_utc"] = schedule_row.get("scheduled_start_utc")
            enriched.setdefault("start_time_utc", schedule_row.get("scheduled_start_utc"))
        if schedule_row.get("venue"):
            enriched.setdefault("venue", schedule_row.get("venue"))
        if schedule_row.get("game_state"):
            enriched["game_state"] = schedule_row.get("game_state")
        if schedule_row.get("gamePk") is not None:
            enriched["gamePk"] = schedule_row.get("gamePk")
        out.append(enriched)
    return out, str(source_path)


def _prediction_sim_rows_by_game(selected_date: str) -> dict[tuple[str, str], dict[str, str]]:
    path = processed_path(f"predictions_sim_{selected_date}.csv")
    rows = _load_csv_rows(path) if path.exists() else []
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        away_name = str(row.get("away") or "").strip()
        home_name = str(row.get("home") or "").strip()
        if away_name and home_name:
            out[(away_name, home_name)] = row
    return out


def _sim_goalie_names_by_game_team(selected_date: str) -> dict[tuple[str, str, str], str]:
    rows, _ = _sim_boxscore_rows(selected_date)
    best: dict[tuple[str, str, str], tuple[float, float, str]] = {}
    for row in rows:
        away_name = str(row.get("game_away") or "").strip()
        home_name = str(row.get("game_home") or "").strip()
        team_name = str(row.get("team") or "").strip()
        player_name = str(row.get("player") or "").strip()
        saves_value = _safe_float(row.get("saves"))
        toi_value = _safe_float(row.get("toi_sec"))
        if not away_name or not home_name or not team_name or not player_name:
            continue
        if saves_value is None or saves_value <= 0:
            continue
        key = (away_name, home_name, team_name)
        current = best.get(key)
        candidate = (saves_value, toi_value or 0.0, player_name)
        if current is None or candidate[0] > current[0] or (candidate[0] == current[0] and candidate[1] > current[1]):
            best[key] = candidate
    return {key: value[2] for key, value in best.items()}


@lru_cache(maxsize=32)
def _schedule_payload(selected_date: str) -> dict[str, Any]:
    if not _public_schedule_fallback_enabled():
        return {}
    url = f"https://api-web.nhle.com/v1/schedule/{selected_date}"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _next_scheduled_game_date_after_empty_slate(selected_date: str) -> str | None:
    payload = _schedule_payload(selected_date)
    game_week = payload.get("gameWeek") or []
    selected_day_has_games = False
    for week in game_week:
        if str(week.get("date") or "") != selected_date:
            continue
        games = week.get("games") or []
        if isinstance(games, list) and games:
            selected_day_has_games = True
            break
        try:
            selected_day_has_games = int(week.get("numberOfGames") or 0) > 0
        except Exception:
            selected_day_has_games = False
        break

    if selected_day_has_games:
        return None

    for week in game_week:
        candidate_date = str(week.get("date") or "").strip()
        if not candidate_date or candidate_date <= selected_date:
            continue
        games = week.get("games") or []
        if isinstance(games, list) and games:
            return candidate_date
        try:
            if int(week.get("numberOfGames") or 0) > 0:
                return candidate_date
        except Exception:
            continue
    return None


@lru_cache(maxsize=32)
def _schedule_rows_by_game(selected_date: str) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _schedule_payload(selected_date)
    if not payload:
        return {}

    def _team_name(team: dict[str, Any]) -> str:
        try:
            place = team.get("placeName") or {}
            common = team.get("commonName") or {}
            place_name = place.get("default") if isinstance(place, dict) else str(place or "")
            common_name = common.get("default") if isinstance(common, dict) else str(common or "")
            return " ".join(f"{place_name} {common_name}".split())
        except Exception:
            return ""

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for week in payload.get("gameWeek") or []:
        if str(week.get("date") or "") != selected_date:
            continue
        for game in week.get("games") or []:
            away_name = _team_name(game.get("awayTeam") or {})
            home_name = _team_name(game.get("homeTeam") or {})
            if not away_name or not home_name:
                continue
            venue = None
            raw_venue = game.get("venue")
            if isinstance(raw_venue, dict):
                venue = raw_venue.get("default") or raw_venue.get("name")
            elif isinstance(raw_venue, str):
                venue = raw_venue
            out[(away_name, home_name)] = {
                "scheduled_start_utc": game.get("startTimeUTC") or None,
                "venue": venue,
                "game_state": game.get("gameState") or None,
                "gamePk": game.get("id"),
            }
    return out


def _sim_boxscore_rows(selected_date: str) -> tuple[list[dict[str, str]], str]:
    path = processed_path(f"props_boxscores_sim_{selected_date}.csv")
    rows = _load_csv_rows(path) if path.exists() else []
    if not rows:
        return rows, str(path)

    position_by_player_id, position_by_name = _position_maps_for_date(selected_date)
    for row in rows:
        existing = str(row.get("pos") or row.get("position") or row.get("player_position") or "").strip()
        if existing:
            continue
        player_id = str(row.get("player_id") or "").strip()
        player_name = str(row.get("player") or "").strip().lower()
        inferred_position = ""
        if player_id:
            inferred_position = position_by_player_id.get(player_id, "")
        if not inferred_position and player_name:
            inferred_position = position_by_name.get(player_name, "")
        if not inferred_position:
            saves_value = _safe_float(row.get("saves"))
            if saves_value is not None and saves_value > 0:
                inferred_position = "G"
        if inferred_position:
            row["pos"] = inferred_position
    return rows, str(path)


def _sim_hist_rows(selected_date: str) -> tuple[list[dict[str, str]], str]:
    path = processed_path(f"props_boxscores_sim_hist_{selected_date}.csv")
    rows = _load_csv_rows(path) if path.exists() else []
    return rows, str(path)


def build_sim_boxscores_payload(selected_date: str | None) -> dict[str, Any]:
    requested_date, resolved_date, lookahead_applied = _resolve_cards_date(selected_date)
    rows, source_path = _sim_boxscore_rows(resolved_date)
    return {
        "ok": True,
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": lookahead_applied,
        "rows": rows,
        "source_path": source_path,
    }


def build_sim_summary_payload(selected_date: str | None) -> dict[str, Any]:
    requested_date, resolved_date, lookahead_applied = _resolve_cards_date(selected_date)
    rows, source_path = _sim_hist_rows(resolved_date)
    n_sims = None
    for row in rows:
        value = _safe_float(row.get("n_sims"))
        if value is None:
            continue
        n_sims = int(value)
        break
    return {
        "ok": True,
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": lookahead_applied,
        "n_sims": n_sims,
        "source_path": source_path,
    }


def _props_recommendation_rows(selected_date: str) -> tuple[list[dict[str, str]], str]:
    path = processed_path(f"props_recommendations_{selected_date}.csv")
    rows = _load_csv_rows(path) if path.exists() else []
    if not rows:
        return rows, str(path)

    lines_path = props_lines_snapshot_path(selected_date)
    lines_rows = _load_csv_rows(lines_path) if lines_path.exists() else []

    def _norm_text(value: Any) -> str:
        return str(value or "").strip().lower()

    def _norm_market(value: Any) -> str:
        return str(value or "").strip().upper()

    def _line_key(value: Any) -> str:
        number = _safe_float(value)
        if number is None:
            return str(value or "").strip()
        return f"{number:.4f}"

    lines_by_key: dict[tuple[str, str, str, str], dict[str, str]] = {}
    lines_by_key_no_book: dict[tuple[str, str, str], dict[str, str]] = {}
    for line_row in lines_rows:
        player_name = _norm_text(line_row.get("player_name") or line_row.get("player"))
        market_key = _norm_market(line_row.get("market"))
        line_value_key = _line_key(line_row.get("line"))
        book_key = _norm_text(line_row.get("book"))
        if not player_name or not market_key or not line_value_key:
            continue
        full_key = (player_name, market_key, line_value_key, book_key)
        no_book_key = (player_name, market_key, line_value_key)
        lines_by_key[full_key] = line_row
        if no_book_key not in lines_by_key_no_book:
            lines_by_key_no_book[no_book_key] = line_row

    for row in rows:
        player_name = _norm_text(row.get("player"))
        market_key = _norm_market(row.get("market"))
        line_value_key = _line_key(row.get("line"))
        book_key = _norm_text(row.get("book"))
        full_key = (player_name, market_key, line_value_key, book_key)
        no_book_key = (player_name, market_key, line_value_key)
        line_row = lines_by_key.get(full_key) or lines_by_key_no_book.get(no_book_key)
        if not line_row:
            continue

        side = str(row.get("side") or "").strip().lower()
        over_price = line_row.get("over_price")
        under_price = line_row.get("under_price")

        if over_price not in (None, ""):
            row["over_price"] = over_price
        if under_price not in (None, ""):
            row["under_price"] = under_price
        if line_row.get("book"):
            row["book"] = line_row.get("book")

        if side == "over" and over_price not in (None, ""):
            row["price"] = over_price
        elif side == "under" and under_price not in (None, ""):
            row["price"] = under_price

    return rows, str(path)


@lru_cache(maxsize=32)
def _position_maps_for_date(selected_date: str) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    candidate_paths = (
        processed_path(f"roster_snapshot_{selected_date}.csv"),
        processed_path(f"lineups_{selected_date}.csv"),
    )

    for path in candidate_paths:
        rows = _load_csv_rows(path) if path.exists() else []
        for row in rows:
            raw_position = str(row.get("position") or row.get("pos") or row.get("player_position") or "").strip().upper()
            if not raw_position:
                continue
            player_id = str(row.get("player_id") or "").strip()
            player_name = str(row.get("full_name") or row.get("player") or "").strip().lower()
            if player_id and player_id not in by_id:
                by_id[player_id] = raw_position
            if player_name and player_name not in by_name:
                by_name[player_name] = raw_position
    return by_id, by_name


def _split_reason_tokens(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split("·") if part.strip()]


def _prop_reason_summary(row: dict[str, Any]) -> str:
    side = str(row.get("side") or "").strip().title() or "Recommended"
    line_value = _safe_float(row.get("line"))
    line_text = format_num(line_value) if line_value is not None else "-"
    market_text = market_label(row.get("market")).lower()
    price_text = format_price(row.get("price"))
    prob_value = _safe_float(row.get("chosen_prob") or row.get("prob"))
    ev_value = _safe_float(row.get("ev"))
    bits = [f"Sportsbook case: {side} {line_text} {market_text} at {price_text}."]
    if prob_value is not None:
        bits.append(f"Model win rate {prob_value * 100:.1f}%.")
    if ev_value is not None:
        bits.append(f"EV {ev_value * 100:.1f}%.")
    return " ".join(bits)


def build_props_cards_payload(selected_date: str | None, top: int = 12) -> dict[str, Any]:
    requested_date, resolved_date, lookahead_applied = _resolve_cards_date(selected_date)
    rows, source_path = _props_recommendation_rows(resolved_date)
    try:
        top_n = max(0, min(int(top), 100))
    except Exception:
        top_n = 12

    cards: list[dict[str, Any]] = []
    for row in rows:
        ev_value = _safe_float(row.get("ev"))
        price_value = _safe_float(row.get("price"))
        if ev_value is None or price_value is None:
            continue
        if ev_value < 0.02:
            continue

        team = team_abbreviation(row.get("team"))
        opp = team_abbreviation(row.get("opp"))
        cards.append(
            {
                "player": str(row.get("player") or "").strip() or None,
                "player_id": None,
                "headshot_url": None,
                "team_logo": team_logo_url(team),
                "team": team or None,
                "opp": opp or None,
                "opp_logo": team_logo_url(opp),
                "market": str(row.get("market") or "").strip().upper() or None,
                "side": str(row.get("side") or "").strip().title() or None,
                "book": str(row.get("book") or "").strip().lower() or None,
                "ev": ev_value,
                "prob": _safe_float(row.get("chosen_prob") or row.get("prob")),
                "line": _safe_float(row.get("line")),
                "price": price_value,
                "drivers": str(row.get("edge_reasons") or "").strip() or None,
                "reason_summary": _prop_reason_summary(row),
                "reasons": _split_reason_tokens(row.get("edge_reasons")),
                "movement": {
                    "line": {"open": None, "prev": None, "cur": None, "d_open": None, "d_prev": None},
                    "price": {"open": None, "prev": None, "cur": None, "d_open": None, "d_prev": None},
                },
                "has_snapshot": False,
                "has_current_snapshot": False,
                "has_movement": False,
                "movement_score": 0.0,
                "tracking_note": "Snapshot unavailable",
            }
        )

    cards.sort(key=lambda item: float(item.get("ev") or 0.0), reverse=True)
    if top_n > 0:
        cards = cards[:top_n]

    return {
        "ok": True,
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": lookahead_applied,
        "current_asof_utc": None,
        "snapshot_bookmaker": None,
        "tracked_cards": 0,
        "moving_cards": 0,
        "cards": cards,
        "source_path": source_path,
    }


def _prediction_dates() -> list[str]:
    return [date_str for date_str in source_available_dates() if len(date_str) == 10]


def _prediction_dates_with_rows() -> list[str]:
    return [
        date_str
        for date_str in _prediction_dates()
        if _load_csv_rows(processed_path(f"predictions_{date_str}.csv"))
        or _load_csv_rows(processed_path(f"predictions_sim_{date_str}.csv"))
        or _load_csv_rows(scoreboard_snapshot_path(date_str))
    ]


def _resolve_cards_date(selected_date: str | None) -> tuple[str, str, bool]:
    requested_date = str(selected_date or default_date()).strip() or default_date()
    available_dates = _prediction_dates_with_rows()
    if not available_dates:
        next_scheduled_date = _next_scheduled_game_date_after_empty_slate(requested_date)
        if next_scheduled_date:
            return requested_date, next_scheduled_date, True
        return requested_date, requested_date, False
    if requested_date in available_dates:
        return requested_date, requested_date, False
    next_scheduled_date = _next_scheduled_game_date_after_empty_slate(requested_date)
    if next_scheduled_date:
        return requested_date, next_scheduled_date, True
    return requested_date, requested_date, False


def build_source_bundle_payload(selected_date: str | None) -> dict[str, Any]:
    requested_date, resolved_date, lookahead_applied = _resolve_cards_date(selected_date)
    prediction_rows, prediction_path = _prediction_bundle_rows(resolved_date)
    recommendation_rows, recommendation_path_str = _recommendation_rows(resolved_date)
    props_rows, props_path = _props_recommendation_rows(resolved_date)
    empty_state = None
    if not prediction_rows:
        if lookahead_applied:
            empty_state = {
                "eyebrow": "NHL cards",
                "title": "Today has no NHL games; next game day is queued",
                "body": "The requested date is an empty NHL slate, so the cards source advanced to the next scheduled game day. Saved prediction rows are not available for that next slate yet.",
                "list_items": [
                    f"Requested date: {requested_date}",
                    f"Next scheduled game day: {resolved_date}",
                    "No local saved rows were found for the requested date.",
                ],
            }
        else:
            empty_state = {
                "eyebrow": "NHL cards",
                "title": "No game cards were available for this date",
                "body": "The source cards shell only renders saved NHL prediction rows for the selected slate, and none were available for this date.",
                "list_items": [
                    f"Requested date: {requested_date}",
                    "Choose another stored NHL date from the date control.",
                ],
            }
    return {
        "ok": True,
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": lookahead_applied,
        "source_title": "NHL processed predictions" if prediction_rows else "NHL cards unavailable",
        "empty_state": empty_state,
        "data": {
            "games": {
                "predictions": {
                    "rows": prediction_rows,
                    "path": prediction_path,
                },
                "recommendations": {
                    "rows": recommendation_rows,
                    "path": recommendation_path_str,
                },
            },
            "props": {
                "recommendations": {
                    "rows": props_rows,
                    "path": props_path,
                },
            },
        },
    }


def build_cards_page_context(selected_date: str | None) -> dict[str, Any]:
    requested_date, resolved_date, lookahead_applied = _resolve_cards_date(selected_date)
    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    games, source_path = _games_from_artifact(resolved_date)
    source_title = "NHL processed predictions"
    if not games:
        games, source_path = _games_from_scoreboard_snapshot(resolved_date)
        if games:
            source_title = "NHL archived scoreboard"
    using_sample_data = False

    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
        for game in games
    ]

    context = {
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": lookahead_applied,
        "prev_date": prev_date,
        "next_date": next_date,
        "games": games,
        "scoreboard_items": scoreboard_items,
        "using_sample_data": using_sample_data,
        "source_path": source_path,
        "source_title": source_title if games else "NHL cards unavailable",
        "empty_state": {
            "eyebrow": "NHL cards",
            "title": "Today has no NHL games; next game day is queued" if lookahead_applied else "No game cards were available for this date",
            "body": "The requested date is an empty NHL slate, so the board advanced to the next scheduled game day. Saved prediction or archived scoreboard rows are not available for that next slate yet." if lookahead_applied else "The cards board only renders saved NHL prediction or archived scoreboard rows, and none were available for the requested date.",
            "list_items": [
                f"Requested date: {requested_date}",
                *( [f"Next scheduled game day: {resolved_date}", "No local saved rows were found for the requested date."] if lookahead_applied else ["Choose another stored NHL date from the date control."] ),
            ],
        } if not games else None,
        "show_source_summary": True,
        "header_stats": [
            {"label": "Games", "value": str(len(games))},
            {"label": "Source", "value": Path(source_path).name if games else "No data"},
            *([
                {"label": "Requested", "value": requested_date},
                {"label": "Next game day", "value": resolved_date},
            ] if lookahead_applied else []),
        ],
        "route_path": "/nhl/cards",
        "intro_title": "NHL Cards",
        "intro_body": "NHL now has a real dense board in Syndicate backed by the stored predictions slate from the source app, keeping the main board workflow on active in-season data.",
        "cards_control_links": [
            {"label": "Betting Card", "href": f"/nhl/season/{parse_iso_date(resolved_date).year}/betting-card?date={resolved_date}"},
            {"label": "Picks", "href": f"/nhl/picks?date={resolved_date}"},
            {"label": "Live Lens", "href": f"/nhl/live-lens?date={resolved_date}"},
        ],
        "cards_grid_class": "wnba-cards-grid",
        "cards_stylesheet": "wnba/cards.css",
        "teaser": {
            "label": "NHL module rollout",
            "body": "This first NHL cards surface keeps game-level market, projection, and EV context on the main board before deeper parity work on detail pages and props.",
            "href": "/nhl",
            "cta": "Open NHL hub",
        },
        "module_links": build_module_links(resolved_date, "Cards"),
        "active_sport_name": "NHL",
    }
    return apply_game_board_contract(context, sport="nhl", module="cards", live_lens_integrated=False)