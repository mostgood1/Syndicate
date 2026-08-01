from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import league_select_control
from syndicate.features.soccer.sources import live_state_payload
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import week_date_list
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.shared.refresh_state_store import data_root


def live_lens_snapshot_path() -> Path:
    # Bookkeeping/validation snapshot only for live_lens_loop.py's own tick
    # status -- the real per-league live data lives at soccer/sources.py's
    # live_state_path(league, date) (soccer_source/{league}/api/live_state/
    # live_state_{date}.json), written directly by poll_league() inside
    # scripts/poll_soccer_live_state.py's poll_active_leagues_for_tick(),
    # unlike MLB/NBA/WNBA where this path IS the real snapshot the page
    # reads. Mirrors the {sport}_live_lens.json naming convention those
    # three already use, purely so live_lens_loop.py's generic tick/write/
    # validate flow needs no soccer-specific branching.
    return data_root() / "live" / "soccer_live_lens.json"


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if not str(snapshot.get("date") or "").strip():
        return False
    return isinstance(snapshot.get("games"), list)


def _fmt_pct(value: Any) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "-"


def _fmt_num(value: Any, digits: int = 1) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def _clock_label(half: Any, clock_remaining: Any) -> str:
    try:
        remaining_min = float(clock_remaining) / 60.0
    except Exception:
        return "Live"
    return f"H{half} | {remaining_min:.0f}' remaining"


def _prop_line(row: dict[str, Any]) -> str:
    name = str(row.get("player_name") or "Player").strip()
    side = str(row.get("side") or "").strip()
    final_shots = _fmt_num(row.get("projected_final_shots"), 1)
    so_far = row.get("shots_so_far")
    return f"{name} ({side}) | Shots so far {so_far} | Projected final {final_shots}"


def _rank_card(game: dict[str, Any], *, league: str, week: int, season: int) -> dict[str, Any]:
    away_team = str(game.get("away_team") or "Away").strip() or "Away"
    home_team = str(game.get("home_team") or "Home").strip() or "Home"
    projection = game.get("projection") if isinstance(game.get("projection"), dict) else {}
    goal_windows = game.get("goal_windows") if isinstance(game.get("goal_windows"), dict) else {}
    live_props = game.get("live_player_props") if isinstance(game.get("live_player_props"), list) else []
    event_id = str(game.get("event_id") or "").strip()

    summary = (
        f"{away_team} {game.get('score_away')} - {game.get('score_home')} {home_team}. "
        f"Projected final total {_fmt_num(projection.get('projected_final_total'), 2)}, "
        f"BTTS {_fmt_pct(projection.get('both_teams_scored_probability'))}, "
        f"goal in next 10 min {_fmt_pct(goal_windows.get('next_10_min'))}."
    )

    return {
        "title": f"{away_team} @ {home_team}",
        "eyebrow": _clock_label(game.get("half"), game.get("clock_remaining")),
        "badge": f"{game.get('score_away')}-{game.get('score_home')}",
        "meta": league_display_name(league),
        "metrics": [
            {"label": "Home win", "value": _fmt_pct(projection.get("home_win_probability"))},
            {"label": "Proj total", "value": _fmt_num(projection.get("projected_final_total"), 2)},
            {"label": "BTTS", "value": _fmt_pct(projection.get("both_teams_scored_probability"))},
            {"label": "Over 2.5", "value": _fmt_pct(projection.get("over_2_5_probability"))},
            {"label": "Goal in 10min", "value": _fmt_pct(goal_windows.get("next_10_min"))},
            {"label": "Goal in 5min", "value": _fmt_pct(goal_windows.get("next_5_min"))},
        ],
        "summary": summary,
        "list_items": [
            f"Shots so far: {away_team} {game.get('away_shots_so_far')} | {home_team} {game.get('home_shots_so_far')}",
            f"On target: {away_team} {game.get('away_shots_on_target_so_far')} | {home_team} {game.get('home_shots_on_target_so_far')}",
            f"Corners so far: {away_team} {game.get('away_corners_so_far')} | {home_team} {game.get('home_corners_so_far')}, "
            f"projected final {_fmt_num(projection.get('projected_total_corners'), 1)}",
            f"Red cards: {away_team} {game.get('away_red_cards')} | {home_team} {game.get('home_red_cards')}",
            *[_prop_line(row) for row in live_props[:3]],
        ],
        "href": f"/soccer/{league}/game/{event_id}?week={week}&season={season}" if event_id else None,
        "href_label": "Open match card",
    }


def build_live_lens_page_context(league: str, week: int | None = None, season: int | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    weeks = available_weeks(league, resolved_season)
    resolved_week = int(week) if week else default_week(league, resolved_season)

    live_games: dict[str, Any] = {}
    latest_generated_at = None
    for date_str in week_date_list(league, resolved_season, resolved_week):
        payload = live_state_payload(league, date_str) or {}
        games_map = payload.get("games") if isinstance(payload.get("games"), dict) else {}
        live_games.update({key: value for key, value in games_map.items() if isinstance(value, dict)})
        if payload.get("generated_at"):
            latest_generated_at = payload.get("generated_at")

    rank_cards = [_rank_card(dict(game), league=league, week=resolved_week, season=resolved_season) for game in live_games.values()]
    rank_cards.sort(key=lambda card: str(card.get("title") or ""))

    warning_panel = None
    if not rank_cards:
        warning_panel = {
            "eyebrow": f"{league_label} live lens",
            "title": "No live matches for this week",
            "body": "The live-lens board only reads the polled live-state snapshot, and no in-progress matches were captured for this week.",
            "list_items": [
                f"Requested week: {resolved_week} (season {resolved_season})",
                f"Run scripts/poll_soccer_live_state.py --league {league} while matches are in progress to populate this board.",
            ],
        }

    query = f"?week={resolved_week}&season={resolved_season}"
    prev_week = max([w for w in weeks if w < resolved_week], default=resolved_week)
    next_week = min([w for w in weeks if w > resolved_week], default=resolved_week)

    context = build_rank_page_context(
        selected_date=str(resolved_week),
        route_path=f"/soccer/{league}/live-lens",
        intro_title=f"{league_label} Live Lens",
        intro_body=f"{league_label} live lens resumes each in-progress match from its current state and projects live corners, shots/SOT, goals, and BTTS forward with SoccerSim's Monte Carlo engine.",
        aria_label=f"{league_label} live lens board",
        source_path=f"data/soccer_source/{league}/api/live_state/",
        source_title=f"{league_label} live-state snapshot" if rank_cards else f"{league_label} live-state unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Live matches", "value": str(len(rank_cards))},
            {"label": "League", "value": league_label},
            {"label": "Source", "value": "SoccerSim live lens" if rank_cards else "No data"},
        ],
        module_links=build_module_links(league, resolved_week, resolved_season, "Live Lens"),
        warning_panel=warning_panel,
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/soccer/{league}/live-lens?week={prev_week}&season={resolved_season}",
        next_href=f"/soccer/{league}/live-lens?week={next_week}&season={resolved_season}",
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        # No query_suffix -- see cards.py's build_cards_page_context for why.
        extra_controls=[league_select_control(league, page_path="/live-lens")],
    )
    if latest_generated_at:
        context["generatedAt"] = latest_generated_at
        context["odds_refreshed_at"] = latest_generated_at
        context["oddsRefreshedAt"] = latest_generated_at
    return attach_live_lens_contract(context, sport="soccer", module="live_lens")


def build_live_lens_api_payload(league: str, week: int | None = None, season: int | None = None) -> dict[str, Any]:
    context = build_live_lens_page_context(league, week, season)
    payload = build_rank_api_payload(context)
    payload["header_stats"] = context.get("header_stats", [])
    payload["warning_panel"] = context.get("warning_panel")
    return payload
