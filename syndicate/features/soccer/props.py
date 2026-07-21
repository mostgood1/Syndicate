from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import league_select_control
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.soccer.sources import week_date_list
from syndicate.features.shared.rank_board import build_rank_page_context


def _fmt_pct(value: Any) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "-"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _prop_rank_card(row: dict[str, Any], *, league: str, week: int, season: int) -> dict[str, Any]:
    player_name = str(row.get("player_name") or "Player").strip() or "Player"
    team = str(row.get("team") or "").strip()
    side = str(row.get("side") or "").strip()
    return {
        "title": player_name,
        "eyebrow": f"{team} ({side})" if side else team,
        "badge": _fmt_pct(row.get("anytime_scorer_probability")),
        "meta": league_display_name(league),
        "metrics": [
            {"label": "Anytime scorer", "value": _fmt_pct(row.get("anytime_scorer_probability"))},
            {"label": "If playing", "value": _fmt_pct(row.get("anytime_scorer_probability_if_playing"))},
            {"label": "xShots", "value": _fmt_num(row.get("expected_shots"), 2)},
            {"label": "xSOT", "value": _fmt_num(row.get("expected_shots_on_target"), 2)},
            {"label": "Min share", "value": _fmt_pct(row.get("expected_minutes_share"))},
        ],
        "summary": (
            f"{player_name} ({team}) projects {_fmt_num(row.get('expected_shots'), 2)} shots and "
            f"{_fmt_num(row.get('expected_shots_on_target'), 2)} on target, with a {_fmt_pct(row.get('anytime_scorer_probability'))} "
            f"anytime-goalscorer probability."
        ),
        "list_items": [
            f"Expected minutes share: {_fmt_pct(row.get('expected_minutes_share'))}",
            f"Anytime scorer if playing: {_fmt_pct(row.get('anytime_scorer_probability_if_playing'))}",
            f"xShots if playing: {_fmt_num(row.get('expected_shots_if_playing'), 2)}",
        ],
        "href": f"/soccer/{league}/game/{row.get('match_id')}?week={week}&season={season}" if row.get("match_id") else None,
        "href_label": "Open match card",
    }


def build_props_page_context(league: str, week: int | None = None, season: int | None = None, *, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    weeks = available_weeks(league, resolved_season)
    resolved_week = int(week) if week else default_week(league, resolved_season)

    rows: list[dict[str, Any]] = []
    for date_str in week_date_list(league, resolved_season, resolved_week):
        payload = recommendations_payload(league, date_str) or {}
        rows.extend(row for row in (payload.get("player_props") or []) if isinstance(row, dict))

    team_filter = str((filters or {}).get("team") or "").strip().lower()
    player_filter = str((filters or {}).get("player") or "").strip().lower()
    sort_key = str((filters or {}).get("sort") or "").strip().lower() or "anytime_scorer_probability"

    filtered = [
        row
        for row in rows
        if (not team_filter or team_filter in str(row.get("team") or "").lower())
        and (not player_filter or player_filter in str(row.get("player_name") or "").lower())
    ]
    filtered.sort(key=lambda row: _safe_float(row.get(sort_key)), reverse=True)

    rank_cards = [_prop_rank_card(row, league=league, week=resolved_week, season=resolved_season) for row in filtered]

    query = f"?week={resolved_week}&season={resolved_season}"
    prev_week = max([w for w in weeks if w < resolved_week], default=resolved_week)
    next_week = min([w for w in weeks if w > resolved_week], default=resolved_week)

    return build_rank_page_context(
        selected_date=str(resolved_week),
        route_path=f"/soccer/{league}/props",
        intro_title=f"{league_label} Player Props",
        intro_body=f"{league_label} player props are ranked by SoccerSim's simulated anytime-goalscorer, shots, and shots-on-target projections for the selected week.",
        aria_label=f"{league_label} props board",
        source_path=f"data/soccer_source/{league}/api/recommendations/",
        source_title=f"{league_label} SoccerSim props" if rank_cards else f"{league_label} props unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Players", "value": str(len(rank_cards))},
            {"label": "League", "value": league_label},
            {"label": "Source", "value": "SoccerSim" if rank_cards else "No data"},
        ],
        module_links=build_module_links(league, resolved_week, resolved_season, "Props"),
        empty_state={
            "eyebrow": f"{league_label} props",
            "title": "No player-prop rows were available for this week",
            "body": "The props board reads the SoccerSim-generated player-prop artifact for this league and week, and none was available.",
            "list_items": [f"Run scripts/build_soccer_artifacts.py --league {league} for dates in week {resolved_week} to populate this week."],
        } if not rank_cards else None,
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/soccer/{league}/props?week={prev_week}&season={resolved_season}",
        next_href=f"/soccer/{league}/props?week={next_week}&season={resolved_season}",
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        # No query_suffix -- see cards.py's build_cards_page_context for why.
        extra_controls=[league_select_control(league, page_path="/props")],
    )
