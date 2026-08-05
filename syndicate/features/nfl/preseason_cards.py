"""Real NFL preseason game-cards board.

Separate module from cards.py -- keeps the regular-season card-building
path (_game_from_smartsim_projection, build_cards_page_context, the
whole upcoming_recs_*.csv/SmartSim2-standalone split) completely
untouched. Mirrors _game_from_smartsim_projection's exact output shape,
including the top-level away/home logo_url/primary_color/secondary_color
fields -- an equivalent NCAAF card-building function omitted those at the
top level earlier this session and silently broke every team logo in
production; do not repeat that omission here.
"""

from __future__ import annotations

import csv
from typing import Any

from syndicate.features.nfl.cards import _NFL_MARKET_BOARD_DISPLAY_LABELS
from syndicate.features.nfl.cards import _nfl_market_board_rows_for_game
from syndicate.features.nfl.cards import _resolve_branding
from syndicate.features.nfl.cards import _team_abbr
from syndicate.features.nfl.preseason_depth import NONSTARTER_PARTICIPATION_SHARE
from syndicate.features.nfl.preseason_depth import PRESEASON_WEEK_LABELS
from syndicate.features.nfl.preseason_depth import likely_snap_leaders
from syndicate.features.nfl.preseason_depth import likely_starters_sitting
from syndicate.features.nfl.preseason_projection import preseason_seasons_and_weeks
from syndicate.features.nfl.preseason_projection import preseason_projection_artifact_path
from syndicate.features.nfl.preseason_projection import read_preseason_projection_artifact
from syndicate.features.nfl.sources import build_preseason_module_links
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import format_odds
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import preseason_target_week
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.market_inventory import join_odds_to_sim


def _load_preseason_odds(season: int) -> dict[tuple[str, str], dict[str, Any]]:
    """Real market odds keyed by (away_team, home_team) abbreviation --
    written by scripts/fetch_nfl_preseason_odds.py from OddsAPI's real,
    active americanfootball_nfl_preseason sport key (confirmed live
    2026-08-05, a distinct key from the regular season's
    americanfootball_nfl). Empty dict, not an error, if the file hasn't
    been fetched yet for this season -- odds are always an optional
    overlay on the real model projection, never required for a card to
    render."""
    path = default_nfl_source_root() / f"preseason_odds_{season}.csv"
    odds: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                away = (row.get("away_team") or "").strip()
                home = (row.get("home_team") or "").strip()
                if not away or not home:
                    continue
                odds[(away, home)] = row
    except (OSError, FileNotFoundError):
        return {}
    return odds


def _depth_chart_panel(team_name: str, season: int, week: int) -> dict[str, Any]:
    leaders = likely_snap_leaders(season, team_name, week=week, top_n=6)
    sitting = likely_starters_sitting(season, team_name, week=week)
    leader_items = [f"{row['player_name']} ({row['position']}, depth {row['depth_rank']})" for row in leaders if row.get("player_name")]
    sitting_items = [f"{row['player_name']} ({row['position']}) -- {row['status_note']}" for row in sitting if row.get("player_name")]
    return {
        "eyebrow": "Real depth chart",
        "title": f"{team_name} likely snap leaders",
        "body": "Real depth-chart context, informational only -- not fed into the numeric projection above (see the module docstring for why real per-player quality data doesn't exist for most of this roster tier).",
        "items": (leader_items or ["No real depth-chart rows on file for this team yet."]) + sitting_items,
    }


def _market_panel(market: dict[str, Any] | None, *, away_name: str, home_name: str) -> dict[str, Any] | None:
    """Real, live sportsbook odds for this exact game (OddsAPI's real,
    active americanfootball_nfl_preseason sport key -- a distinct key
    from the regular season's americanfootball_nfl, confirmed live
    2026-08-05). None if no real market row was fetched for this game
    yet -- reference-only overlay, never required, never fabricated."""
    if not market:
        return None
    book = str(market.get("book") or "").strip().replace("_", " ").title() or "Sportsbook"
    home_ml = format_odds(market.get("home_moneyline"))
    away_ml = format_odds(market.get("away_moneyline"))
    total_raw = str(market.get("total_line") or "").strip()
    try:
        spread_val = float(market.get("spread_home"))
    except (TypeError, ValueError):
        spread_label = "-"
    else:
        if spread_val > 0:
            spread_label = f"{away_name} favored by {spread_val:.1f}"
        elif spread_val < 0:
            spread_label = f"{home_name} favored by {abs(spread_val):.1f}"
        else:
            spread_label = "Pick'em"
    return {
        "eyebrow": f"Real market ({book})",
        "title": "Posted preseason line",
        "body": "Real, live sportsbook odds for this game. Shown for reference only -- not blended into the model projection above.",
        "items": [
            f"Moneyline: {away_name} {away_ml} / {home_name} {home_ml}",
            f"Spread: {spread_label}",
            f"Total: {total_raw or '-'}",
        ],
    }


def _game_from_preseason_projection(projection: Any, season: int, week: int, *, market: dict[str, Any] | None = None) -> dict[str, Any]:
    away_team = str(projection.away_team or "Away").strip() or "Away"
    home_team = str(projection.home_team or "Home").strip() or "Home"
    away_branding = _resolve_branding(away_team)
    home_branding = _resolve_branding(home_team)
    away_abbr = away_branding.abbreviation if away_branding else _team_abbr(away_team)
    home_abbr = home_branding.abbreviation if home_branding else _team_abbr(home_team)
    away_name = away_branding.display_name if away_branding else away_team
    home_name = home_branding.display_name if home_branding else home_team
    margin = projection.margin_mean
    if margin > 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    elif margin < 0:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    else:
        spread_label = "Pick'em"
    win_probability = format_pct(projection.home_win_rate)
    game_pk = str(projection.game_id or f"{season}-preseason-{week}-{away_abbr}-{home_abbr}").replace(" ", "-")
    week_label = PRESEASON_WEEK_LABELS.get(week, f"Preseason Week {week}")
    share = projection.nonstarter_participation_share
    market_panel = _market_panel(market, away_name=away_name, home_name=home_name)
    summary = (
        f"SmartSim 2.0 projects {home_name} {round(projection.home_score_mean, 1)} - {round(projection.away_score_mean, 1)} {away_name} "
        f"with a projected total of {round(projection.total_mean, 1)}. Preseason projection -- shrunk toward league-neutral by "
        f"{share:.0%} to reflect expected backup/bubble-player snaps this week; treat with much lower confidence than a "
        f"regular-season projection."
    )
    metrics = [
        {"label": "Home mean", "value": round(projection.home_score_mean, 1)},
        {"label": "Away mean", "value": round(projection.away_score_mean, 1)},
        {"label": "Projected spread", "value": spread_label},
        {"label": "Win probability", "value": win_probability},
        {"label": "Shrinkage applied", "value": f"{share:.0%}"},
    ]
    if market:
        metrics.append({"label": "Market total", "value": str(market.get("total_line") or "-")})
    # Real data plumbing for the shared board contract's Box Score/Game tabs
    # (mirrors the same fix in nfl/cards.py's _game_from_smartsim_projection).
    # p_home_win is always the model's own win probability (never
    # fabricated); home_spread/total are only set when this exact matchup's
    # `market` argument (real preseason odds already loaded by the caller via
    # _load_preseason_odds -- no new fetch here) actually has a real quoted
    # value. No prop_recommendations here at all: preseason has no real prop
    # odds source (see build_nfl_preseason_market_board's own docstring), so
    # the generic template's "no props" empty state is correct, not a gap.
    betting: dict[str, Any] = {"p_home_win": projection.home_win_rate}
    if market:
        try:
            market_home_spread = float(market.get("spread_home")) if str(market.get("spread_home") or "").strip() else None
        except (TypeError, ValueError):
            market_home_spread = None
        try:
            market_total = float(market.get("total_line")) if str(market.get("total_line") or "").strip() else None
        except (TypeError, ValueError):
            market_total = None
        if market_home_spread is not None:
            betting["home_spread"] = market_home_spread
        if market_total is not None:
            betting["total"] = market_total
    panels = [
        {
            "eyebrow": "SmartSim 2.0 (preseason)",
            "title": "Projection contract",
            "body": projection.uncertainty_note,
            "items": [
                f"Home mean: {round(projection.home_score_mean, 1)}",
                f"Away mean: {round(projection.away_score_mean, 1)}",
                f"Projected spread: {spread_label}",
                f"Projected total: {round(projection.total_mean, 1)}",
                f"Win probability: {win_probability}",
            ],
        },
    ]
    if market_panel:
        panels.append(market_panel)
    panels.extend(
        [
            {
                "eyebrow": "Game context",
                "title": f"{season} {week_label}",
                "body": f"{away_name} at {home_name}.",
                "items": [
                    f"Teams: {away_name} at {home_name}",
                    f"Projection source: SmartSim 2.0 ({projection.rating_source})",
                    f"Real game id: {game_pk}",
                ],
            },
            _depth_chart_panel(away_name, season, week),
            _depth_chart_panel(home_name, season, week),
        ]
    )
    return {
        "gamePk": game_pk,
        "card_variant": "shared_default",
        "away": {
            "abbr": away_abbr,
            "name": away_name,
            "logo_url": away_branding.logo_url if away_branding else None,
            "primary_color": away_branding.primary_color if away_branding else None,
            "secondary_color": away_branding.secondary_color if away_branding else None,
        },
        "home": {
            "abbr": home_abbr,
            "name": home_name,
            "logo_url": home_branding.logo_url if home_branding else None,
            "primary_color": home_branding.primary_color if home_branding else None,
            "secondary_color": home_branding.secondary_color if home_branding else None,
        },
        "href": f"/nfl/game/{game_pk}?season={season}&week={week}",
        "href_label": "Open NFL game detail",
        "status": week_label,
        "detail": "SmartSim 2.0 (preseason)",
        "summary": summary,
        "metrics": metrics,
        "sim": {
            "periods": {
                "full": {
                    "away_mean": projection.away_score_mean,
                    "home_mean": projection.home_score_mean,
                    "total_mean": projection.total_mean,
                    "margin_mean": projection.margin_mean,
                    "p_home_win": projection.home_win_rate,
                }
            },
            "score": {"away_mean": projection.away_score_mean, "home_mean": projection.home_score_mean},
        },
        "betting": betting,
        "probability_rows": [
            {
                "label": "Full Game",
                "away_pct": (1.0 - projection.home_win_rate) * 100.0,
                "home_pct": projection.home_win_rate * 100.0,
                "summary": f"Home win probability {win_probability}",
            }
        ],
        "shared_top_play_rows": [],
        "panels": panels,
    }


def _available_preseason_weeks(season: int) -> list[int]:
    return sorted(preseason_seasons_and_weeks(default_nfl_source_root()).get(season, []))


def build_preseason_cards_page_context(selected_week: int, *, season: int | None = None) -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    weeks = _available_preseason_weeks(resolved_season)
    target_week = preseason_target_week(resolved_season)
    default_week = target_week if target_week is not None else (weeks[-1] if weeks else 1)
    requested_week = int(selected_week) if selected_week else default_week
    resolved_week = resolve_selected_value(requested_week, weeks, default_week) if weeks else requested_week
    season = resolved_season

    projections = read_preseason_projection_artifact(season=season, week=resolved_week, data_root=default_nfl_source_root())
    odds = _load_preseason_odds(season)
    games = [
        _game_from_preseason_projection(projection, season, resolved_week, market=odds.get((projection.away_team, projection.home_team)))
        for projection in projections
    ]

    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["status"],
        }
        for game in games
    ]
    week_label = PRESEASON_WEEK_LABELS.get(resolved_week, f"Preseason Week {resolved_week}")
    source_path = str(preseason_projection_artifact_path(season=season, week=resolved_week, data_root=default_nfl_source_root()))
    return apply_game_board_contract(
        {
            "date": f"{season} {week_label}",
            "requested_date": f"{season} Preseason Week {selected_week}",
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/nfl/preseason/cards",
            "controls_prev_href": f"/nfl/preseason/cards?season={season}&week={prev_week}",
            "controls_next_href": f"/nfl/preseason/cards?season={season}&week={next_week}",
            "control_label": "Preseason week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "hidden_fields": [{"name": "season", "value": str(season)}],
            "module_links": build_preseason_module_links(resolved_week, "Preseason Cards", season=season),
            "games": games,
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "source_title": "NFL SmartSim 2.0 preseason projections" if games else "NFL preseason projections unavailable",
            "empty_state": {
                "eyebrow": "NFL preseason",
                "title": "No preseason projections were available for this week",
                "body": "Run scripts/fetch_nfl_preseason_schedule.py then scripts/generate_smartsim2_nfl_preseason_projections.py for this season/week to populate this board.",
                "list_items": [
                    f"Season: {season}",
                    f"Week: {selected_week} ({week_label})",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": "/nfl/preseason/cards",
            "intro_title": "NFL Preseason Cards",
            "intro_body": (
                "Real preseason schedule from ESPN (nflverse has no preseason data of any kind) joined against a "
                "shrinkage-toward-league-neutral projection anchored on real prior-season team ratings -- carries "
                "much higher real uncertainty than the regular-season board, disclosed on every card."
            ),
            "cards_control_links": [
                {"label": "Market Board", "href": f"/nfl/preseason/market-board?season={season}&week={resolved_week}"},
                {"label": "Regular Season Cards", "href": f"/nfl/cards?season={season}"},
                {"label": "Hub", "href": "/nfl/hub"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Season", "value": str(season)},
                {"label": "Week", "value": week_label},
                {"label": "Shrinkage", "value": f"{NONSTARTER_PARTICIPATION_SHARE.get(resolved_week, 0):.0%}"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "NFL",
        },
        sport="nfl",
        module="preseason_cards",
        source_kind="local_artifact",
        live_lens_integrated=False,
    )


# ---------------------------------------------------------------------------
# Market board (Layer 1) -- real preseason market odds joined against real
# SmartSim 2.0 preseason projections. Mirrors
# syndicate.features.nfl.cards.build_nfl_market_board's shape and join
# logic exactly (reuses that module's own _nfl_market_board_rows_for_game/
# _NFL_MARKET_BOARD_DISPLAY_LABELS plus market_inventory.join_odds_to_sim
# directly rather than duplicating them), scoped to preseason_odds_{season}.csv
# / smartsim2_preseason_projections_{season}_wk{week}.csv instead of the
# regular-season artifacts. No player-prop rows -- there's no preseason prop
# odds source (see scripts/fetch_nfl_preseason_odds.py's docstring).
# ---------------------------------------------------------------------------


def _preseason_market_float(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


_DEFAULT_PRESEASON_UNCERTAINTY_NOTE = (
    "Preseason projections are shrunk toward league-neutral and their variance is widened to "
    "reflect expected backup/bubble-player participation -- treat with much lower confidence "
    "than a regular-season projection."
)


def build_nfl_preseason_market_board(season: int, week: int) -> dict[str, Any]:
    """Layer 1 market/odds inventory for NFL preseason game markets
    (moneyline, spread, total only)."""
    projections = read_preseason_projection_artifact(season=season, week=week, data_root=default_nfl_source_root())
    weeks = _available_preseason_weeks(season)
    odds = _load_preseason_odds(season)

    board_games: list[dict[str, Any]] = []
    uncertainty_note: str | None = None
    for projection in projections:
        if uncertainty_note is None and str(projection.uncertainty_note or "").strip():
            uncertainty_note = projection.uncertainty_note

        home_branding = _resolve_branding(projection.home_team)
        away_branding = _resolve_branding(projection.away_team)
        home_abbr = home_branding.abbreviation if home_branding else _team_abbr(projection.home_team)
        away_abbr = away_branding.abbreviation if away_branding else _team_abbr(projection.away_team)

        market = odds.get((projection.away_team, projection.home_team))

        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id=projection.game_id,
            home_moneyline=_preseason_market_float((market or {}).get("home_moneyline")),
            away_moneyline=_preseason_market_float((market or {}).get("away_moneyline")),
            spread_line=_preseason_market_float((market or {}).get("spread_home")),
            total_line=_preseason_market_float((market or {}).get("total_line")),
            model_margin=projection.margin_mean,
            model_total=projection.total_mean,
            model_margin_stdev=projection.margin_stdev,
            model_total_stdev=projection.total_stdev,
            home_win_probability=projection.home_win_rate,
        )

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            row["market"] = _NFL_MARKET_BOARD_DISPLAY_LABELS.get(row.get("market"), row.get("market"))

        board_games.append(
            {
                "gamePk": projection.game_id,
                "matchup": f"{away_abbr} @ {home_abbr}",
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_logo": away_branding.logo_url if away_branding else None,
                "home_logo": home_branding.logo_url if home_branding else None,
                "game_state": "pregame",
                "rows": inventory,
            }
        )

    return {
        "season": season,
        "week": week,
        "available_weeks": weeks,
        "games": board_games,
        "using_sample_data": False,
        "source_path": str(preseason_projection_artifact_path(season=season, week=week, data_root=default_nfl_source_root())),
        "route_path": "/nfl/preseason/market-board",
        "uncertainty_note": uncertainty_note or _DEFAULT_PRESEASON_UNCERTAINTY_NOTE,
    }
