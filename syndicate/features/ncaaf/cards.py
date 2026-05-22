from __future__ import annotations

from typing import Any

from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import format_moneyline
from syndicate.features.ncaaf.sources import format_num
from syndicate.features.ncaaf.sources import format_pct
from syndicate.features.ncaaf.sources import load_json
from syndicate.features.ncaaf.sources import summary_path
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _abbr(team: str) -> str:
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _stake_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"${amount:.2f}" if amount is not None else "-"


def _kelly_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"{amount * 100:.1f}%" if amount is not None else "-"


def _week_label(week: int, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else default_season()
    return f"{resolved_season} Week {week}"


def _collapse_games(summary: dict[str, Any], week: int, *, limit: int = 16) -> list[dict[str, Any]]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        key = (away_team, home_team)
        current = best_rows.get(key)
        candidate_edge = _safe_float(row.get("edge")) or float("-inf")
        if current is None:
            best_rows[key] = row
            continue
        current_edge = _safe_float(current.get("edge")) or float("-inf")
        if candidate_edge > current_edge:
            best_rows[key] = row
            continue
        candidate_stake = _safe_float(row.get("stake")) or 0.0
        current_stake = _safe_float(current.get("stake")) or 0.0
        if candidate_edge == current_edge and candidate_stake > current_stake:
            best_rows[key] = row

    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: ((_safe_float(row.get("edge")) or 0.0), (_safe_float(row.get("stake")) or 0.0)),
        reverse=True,
    )
    games: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        home_abbr = _abbr(home_team)
        away_abbr = _abbr(away_team)
        market = str(row.get("market") or "ML").strip().upper() or "ML"
        side = str(row.get("side") or "Home").strip() or "Home"
        provider = str(row.get("provider") or "Book").strip() or "Book"
        price = format_moneyline(row.get("price_american"))
        model_prob = format_pct(row.get("model_prob"))
        implied_prob = format_pct(row.get("implied_prob"))
        edge = format_pct(row.get("edge"))
        stake = _stake_text(row.get("stake"))
        favored_team = home_team if side.lower() == "home" else away_team
        games.append(
            {
                "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
                "card_variant": "shared_default",
                "away": {"abbr": away_abbr, "name": away_team},
                "home": {"abbr": home_abbr, "name": home_team},
                "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
                "href_label": "Open NCAAF game detail",
                "status": f"Week {week}",
                "detail": "Historical summary",
                "summary": f"{favored_team} is the best {market} recommendation from {provider} at {price} with modeled edge {edge}.",
                "metrics": [
                    {"label": "Model", "value": model_prob},
                    {"label": "Implied", "value": implied_prob},
                    {"label": "Price", "value": price},
                    {"label": "Stake", "value": stake},
                    {"label": "Edge", "value": edge},
                ],
                "panels": [
                    {
                        "eyebrow": "Official card",
                        "title": provider,
                        "body": "The first NCAAF cards board groups the weekly recommendations summary into one best available recommendation per matchup.",
                        "items": [
                            f"Market: {market}",
                            f"Side: {side}",
                            f"Stake: {stake}",
                        ],
                    },
                    {
                        "eyebrow": "Model vs price",
                        "title": f"Model {model_prob} | Implied {implied_prob}",
                        "body": f"Best listed price is {price} from {provider}, producing modeled edge {edge}.",
                        "items": [
                            f"Kelly fraction: {_kelly_text(row.get('kelly_f'))}",
                            f"Raw edge multiple: {format_num(row.get('edge'))}",
                            f"Recommendation: {favored_team}",
                        ],
                    },
                    {
                        "eyebrow": "Game context",
                        "title": _week_label(week),
                        "body": f"{away_team} at {home_team} from the stored NCAAF recommendations summary.",
                        "items": [
                            f"Provider: {provider}",
                            "Current source artifacts are offseason weekly snapshots rather than live slate data.",
                        ],
                    },
                ],
            }
        )
    return games


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def build_cards_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    resolved_week = _clamp_week(selected_week or default_week())
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    path = summary_path(resolved_week)
    summary = load_json(path) or {}
    games = _collapse_games(summary, resolved_week)
    using_sample_data = False

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(path),
            "source_title": "NCAAF recommendations summary" if games else "NCAAF cards unavailable",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders saved NCAAF recommendation summary rows, and none were available for the requested week.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": "NCAAF enters the shared game-board contract with a first weekly cards surface built from stored recommendation summary artifacts in the source app.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Rows", "value": str(len(summary.get('results') or []))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": "Summary" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": "Use the picks board for the ranked weekly recommendation rows behind these matchup cards.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )