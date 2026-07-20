from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import available_dates
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_date
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import recommendations_path
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_pct(value: Any) -> str:
    number = _safe_float(value)
    return f"{number * 100:.1f}%" if number is not None else "-"


def _fmt_num(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    return f"{number:.{digits}f}" if number is not None else "-"


def _abbr(team: str) -> str:
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _status_label(status_state: str, kickoff: str | None) -> str:
    state = str(status_state or "pre").strip().lower()
    if state == "post":
        return "Final"
    if state == "in":
        return "Live"
    return str(kickoff or "Scheduled").strip() or "Scheduled"


def _prop_line(row: dict[str, Any]) -> str:
    name = str(row.get("player_name") or "Player").strip()
    team = str(row.get("team") or "").strip()
    scorer_prob = _fmt_pct(row.get("anytime_scorer_probability"))
    shots = _fmt_num(row.get("expected_shots"), 1)
    return f"{name} ({team}) | Anytime scorer {scorer_prob} | xShots {shots}"


def _match_to_game(match: dict[str, Any], *, league: str, selected_date: str) -> dict[str, Any]:
    matchup = match.get("matchup") if isinstance(match.get("matchup"), dict) else {}
    home_team = str(matchup.get("home_team") or "Home").strip() or "Home"
    away_team = str(matchup.get("away_team") or "Away").strip() or "Away"
    win_prob = match.get("win_probability") if isinstance(match.get("win_probability"), dict) else {}
    team_projection = match.get("team_projection") if isinstance(match.get("team_projection"), dict) else {}
    total_distribution = match.get("total_distribution") if isinstance(match.get("total_distribution"), dict) else {}
    volume = match.get("volume_projection") if isinstance(match.get("volume_projection"), dict) else {}
    top_props = match.get("top_props") if isinstance(match.get("top_props"), list) else []
    event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
    status_state = str(match.get("status_state") or "pre")

    home_score = match.get("live_home_score")
    away_score = match.get("live_away_score")
    score_text = f"{away_score}-{home_score}" if status_state in {"in", "post"} and home_score is not None else "-"

    summary = (
        f"Projected {away_team} {_fmt_num(team_projection.get('away_mean'), 1)} @ {home_team} "
        f"{_fmt_num(team_projection.get('home_mean'), 1)} (total {_fmt_num(team_projection.get('total_mean'), 1)}). "
        f"Win prob: {home_team} {_fmt_pct(win_prob.get('home'))} / Draw {_fmt_pct(win_prob.get('draw'))} / "
        f"{away_team} {_fmt_pct(win_prob.get('away'))}."
    )

    return {
        "gamePk": event_id or f"{league}_{selected_date}_{home_team}_{away_team}".replace(" ", "_"),
        "event_id": event_id,
        "away": {"abbr": _abbr(away_team), "name": away_team, "score": away_score},
        "home": {"abbr": _abbr(home_team), "name": home_team, "score": home_score},
        "status": _status_label(status_state, match.get("kickoff")),
        "detail": score_text if score_text != "-" else league_display_name(league),
        "summary": summary,
        "href": f"/soccer/{league}/game/{event_id or 'unknown'}?date={selected_date}",
        "href_label": "Open match card",
        "metrics": [
            {"label": "Home win", "value": _fmt_pct(win_prob.get("home"))},
            {"label": "Draw", "value": _fmt_pct(win_prob.get("draw"))},
            {"label": "Away win", "value": _fmt_pct(win_prob.get("away"))},
            {"label": "Total goals", "value": _fmt_num(team_projection.get("total_mean"), 2)},
            {"label": "BTTS", "value": _fmt_pct(total_distribution.get("both_teams_scored_probability"))},
            {"label": "Over 2.5", "value": _fmt_pct(total_distribution.get("over_2_5_probability"))},
        ],
        "panels": [
            {
                "eyebrow": "Match projection",
                "title": f"{away_team} @ {home_team}",
                "body": summary,
                "items": [
                    f"Projected score: {away_team} {_fmt_num(team_projection.get('away_mean'), 1)} - {home_team} {_fmt_num(team_projection.get('home_mean'), 1)}",
                    f"Margin: {_fmt_num(team_projection.get('margin_mean'), 2)} (home perspective)",
                    f"Simulations: {match.get('simulations') or '-'}",
                ],
            },
            {
                "eyebrow": "Shot & set-piece volume",
                "title": "Shots / SOT / corners",
                "body": "Projected volume markets for live shot props and corner totals.",
                "items": [
                    f"Shots: {away_team} {_fmt_num(volume.get('away_shots'), 1)} | {home_team} {_fmt_num(volume.get('home_shots'), 1)}",
                    f"On target: {away_team} {_fmt_num(volume.get('away_shots_on_target'), 1)} | {home_team} {_fmt_num(volume.get('home_shots_on_target'), 1)}",
                    f"Corners: {away_team} {_fmt_num(volume.get('away_corners'), 1)} | {home_team} {_fmt_num(volume.get('home_corners'), 1)}",
                ],
            },
            {
                "eyebrow": "Top prop signals",
                "title": "Anytime scorer / shots leaders",
                "body": "Highest anytime-goalscorer probability players from the simulated player-props pass.",
                "items": [_prop_line(row) for row in top_props[:5]] or ["No player-prop rows were available for this match."],
            },
        ],
    }


def build_cards_page_context(league: str, selected_date: str) -> dict[str, Any]:
    league = normalize_league(league)
    dates = available_dates(league)
    resolved_date = str(selected_date or default_date(league)).strip() or default_date(league)
    payload = recommendations_payload(league, resolved_date) or {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    games = [_match_to_game(match, league=league, selected_date=resolved_date) for match in matches]

    prev_date, next_date = neighboring_values(dates, resolved_date, fallback=resolved_date)
    source_path = str(recommendations_path(league, resolved_date))
    league_label = league_display_name(league)

    return apply_game_board_contract(
        {
            "date": resolved_date,
            "requested_date": selected_date or resolved_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "control_action": f"/soccer/{league}/cards",
            "controls_prev_href": f"/soccer/{league}/cards?date={prev_date}",
            "controls_next_href": f"/soccer/{league}/cards?date={next_date}",
            "control_value": resolved_date,
            "module_links": build_module_links(league, resolved_date, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["detail"],
                }
                for game in games
            ],
            "source_path": source_path,
            "source_title": f"{league_label} SoccerSim artifact" if games else f"{league_label} cards unavailable",
            "empty_state": {
                "eyebrow": f"{league_label} cards",
                "title": "No simulated matches were available for this date",
                "body": "The cards board reads the SoccerSim-generated recommendations artifact for this league and date, and none was available.",
                "list_items": [
                    f"Requested date: {selected_date or resolved_date}",
                    f"Run scripts/build_soccer_artifacts.py --league {league} --date {resolved_date} to populate this date.",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": f"/soccer/{league}/cards",
            "intro_title": f"{league_label} Cards",
            "intro_body": f"{league_label} cards render directly from SoccerSim's simulated match and player-prop outputs for the selected date.",
            "cards_control_links": [
                {"label": "Props", "href": f"/soccer/{league}/props?date={resolved_date}"},
                {"label": "Live Lens", "href": f"/soccer/{league}/live-lens?date={resolved_date}"},
            ],
            "header_stats": [
                {"label": "Matches", "value": str(len(games))},
                {"label": "Dates stored", "value": str(len(dates) or "-")},
                {"label": "League", "value": league_label},
                {"label": "Source", "value": "SoccerSim" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "Soccer",
        },
        sport="soccer",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=True,
    )
