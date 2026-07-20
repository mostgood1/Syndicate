from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import recommendations_path
from syndicate.features.soccer.sources import recommendations_payload
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


def _prop_rank_card(row: dict[str, Any], *, league: str, selected_date: str) -> dict[str, Any]:
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
        "href": f"/soccer/{league}/game/{row.get('match_id')}?date={selected_date}" if row.get("match_id") else None,
        "href_label": "Open match card",
    }


def build_props_page_context(league: str, selected_date: str, *, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    payload = recommendations_payload(league, selected_date) or {}
    rows = payload.get("player_props") if isinstance(payload.get("player_props"), list) else []

    team_filter = str((filters or {}).get("team") or "").strip().lower()
    player_filter = str((filters or {}).get("player") or "").strip().lower()
    sort_key = str((filters or {}).get("sort") or "").strip().lower() or "anytime_scorer_probability"

    filtered = [
        row
        for row in rows
        if isinstance(row, dict)
        and (not team_filter or team_filter in str(row.get("team") or "").lower())
        and (not player_filter or player_filter in str(row.get("player_name") or "").lower())
    ]
    filtered.sort(key=lambda row: _safe_float(row.get(sort_key)), reverse=True)

    rank_cards = [_prop_rank_card(row, league=league, selected_date=selected_date) for row in filtered]

    context = build_rank_page_context(
        selected_date=selected_date,
        route_path=f"/soccer/{league}/props",
        intro_title=f"{league_label} Player Props",
        intro_body=f"{league_label} player props are ranked by SoccerSim's simulated anytime-goalscorer, shots, and shots-on-target projections.",
        aria_label=f"{league_label} props board",
        source_path=str(recommendations_path(league, selected_date)),
        source_title=f"{league_label} SoccerSim props" if rank_cards else f"{league_label} props unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Players", "value": str(len(rank_cards))},
            {"label": "League", "value": league_label},
            {"label": "Source", "value": "SoccerSim" if rank_cards else "No data"},
        ],
        module_links=build_module_links(league, selected_date, "Props"),
        empty_state={
            "eyebrow": f"{league_label} props",
            "title": "No player-prop rows were available for this date",
            "body": "The props board reads the SoccerSim-generated player-prop artifact for this league and date, and none was available.",
            "list_items": [f"Run scripts/build_soccer_artifacts.py --league {league} --date {selected_date} to populate this date."],
        } if not rank_cards else None,
    )
    return context
