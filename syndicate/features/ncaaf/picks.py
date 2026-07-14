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
from syndicate.features.shared.rank_board import build_rank_page_context

from syndicate.features.ncaaf.cards import _prediction_source_path
from syndicate.features.ncaaf.cards import _prediction_weeks
from syndicate.features.ncaaf.cards import _normalize_probability
from syndicate.features.ncaaf.cards import _runtime_scoreboard_projection
from syndicate.features.ncaaf.cards import _runtime_prediction_rows


def _stake_text(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except Exception:
        return "-"


def _kelly_text(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "-"


def _selected_date_token(week: int, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else default_season()
    return f"{resolved_season}-01-{week:02d}"


def _collapse_results(summary: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    best_rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        market = str(row.get("market") or "").strip().upper() or "BET"
        side = str(row.get("side") or "").strip() or "Side"
        provider = str(row.get("provider") or "").strip() or "Book"
        key = (away_team, home_team, market, side)
        current = best_rows.get(key)
        try:
            candidate_edge = float(row.get("edge"))
        except Exception:
            candidate_edge = float("-inf")
        if current is None:
            best_rows[key] = row
            continue
        try:
            current_edge = float(current.get("edge"))
        except Exception:
            current_edge = float("-inf")
        if candidate_edge > current_edge:
            best_rows[key] = row
            continue
        if candidate_edge == current_edge and provider < str(current.get("provider") or ""):
            best_rows[key] = row

    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: (
            float(row.get("edge") or 0.0),
            float(row.get("stake") or 0.0),
        ),
        reverse=True,
    )
    cards: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        home_team = str(row.get("home_team") or "Home").strip()
        away_team = str(row.get("away_team") or "Away").strip()
        market = str(row.get("market") or "BET").strip().upper() or "BET"
        side = str(row.get("side") or "Side").strip() or "Side"
        provider = str(row.get("provider") or "Book").strip() or "Book"
        cards.append(
            {
                "title": f"{home_team} vs {away_team} {market} {side}",
                "eyebrow": provider,
                "badge": f"{format_pct(row.get('edge'))} edge",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Model", "value": format_pct(row.get("model_prob"))},
                    {"label": "Implied", "value": format_pct(row.get("implied_prob"))},
                    {"label": "Price", "value": format_moneyline(row.get("price_american"))},
                    {"label": "Stake", "value": _stake_text(row.get("stake"))},
                ],
                "summary": (
                    f"Best {market} {side} number for {away_team} at {home_team} comes from {provider} "
                    f"with a modeled edge over the implied price."
                ),
                "list_items": [
                    f"Market: {market}",
                    f"Side: {side}",
                    f"Kelly fraction: {_kelly_text(row.get('kelly_f'))}",
                    f"Raw edge multiple: {format_num(row.get('edge'))}",
                ],
            }
        )
    return cards


def _runtime_pick_score(row: dict[str, Any], scoreboard: dict[str, Any]) -> float:
    win_probability = _normalize_probability(scoreboard.get("win_probability")) or 0.0
    spread_text = str(scoreboard.get("spread_label") or "").strip()
    spread_value = 0.0
    for token in spread_text.split():
        try:
            spread_value = abs(float(token))
            break
        except Exception:
            continue
    total_points = 0.0
    try:
        total_points = float(str(scoreboard.get("total_points") or "0").strip())
    except Exception:
        total_points = 0.0
    return abs(win_probability - 0.5) * 100.0 + spread_value + (total_points / 100.0)


def _runtime_pick_cards(week: int, *, season: int) -> list[dict[str, Any]]:
    runtime_rows = _runtime_prediction_rows(week)
    candidate_rows: list[dict[str, Any]] = []
    for row in runtime_rows:
        scoreboard = _runtime_scoreboard_projection(row, week)
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        candidate_rows.append(
            {
                "row": row,
                "scoreboard": scoreboard,
                "score": _runtime_pick_score(row, scoreboard),
                "home_team": home_team,
                "away_team": away_team,
            }
        )
    ordered_rows = sorted(candidate_rows, key=lambda item: (item["score"], str(item["home_team"]), str(item["away_team"])), reverse=True)
    cards: list[dict[str, Any]] = []
    for item in ordered_rows[:12]:
        row = item["row"]
        scoreboard = item["scoreboard"]
        home_team = item["home_team"]
        away_team = item["away_team"]
        cards.append(
            {
                "title": f"{home_team} vs {away_team} SmartSim candidate",
                "eyebrow": "SmartSim runtime",
                "badge": f"{scoreboard.get('win_probability') or '-'} win prob",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
                    {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
                    {"label": "Spread", "value": scoreboard.get("spread_label") or "-"},
                    {"label": "Total", "value": scoreboard.get("total_points") or "-"},
                ],
                "summary": (
                    f"SmartSim projects {home_team} {scoreboard.get('home_points') or '-'} - {scoreboard.get('away_points') or '-'} "
                    f"{away_team} with a projected total of {scoreboard.get('total_points') or '-'} and a home win probability of {scoreboard.get('win_probability') or '-'}."
                ),
                "list_items": [
                    f"Projected spread: {scoreboard.get('spread_label') or '-'}",
                    f"Home mean: {scoreboard.get('home_points') or '-'}",
                    f"Away mean: {scoreboard.get('away_points') or '-'}",
                    f"Projection source: {scoreboard.get('source_label') or 'SmartSim runtime'}",
                ],
            }
        )
    return cards


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def build_smartsim_picks_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    runtime_weeks = _prediction_weeks()
    if not runtime_weeks:
        return build_picks_page_context(selected_week)
    requested_week = int(selected_week or runtime_weeks[-1])
    resolved_week = resolve_selected_value(requested_week, runtime_weeks, runtime_weeks[-1])
    cards = _runtime_pick_cards(resolved_week, season=season)
    if not cards:
        return build_picks_page_context(selected_week)
    weeks = runtime_weeks
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    source_path = _prediction_source_path()
    empty_state = None
    if not cards:
        empty_state = {
            "eyebrow": "NCAAF SmartSim picks",
            "title": "No runtime picks were available.",
            "body": "The SmartSim picks board first reads the predicted-totals snapshot and falls back to saved weekly summaries only if the runtime source is unavailable.",
            "list_items": [
                f"Requested week: {selected_week}",
                f"Resolved week: {resolved_week}",
            ],
        }
    return {
        **build_rank_page_context(
            selected_date=_selected_date_token(resolved_week, season=season),
            route_path="/ncaaf/picks",
            intro_title="NCAAF Picks",
            intro_body="NCAAF picks now generate SmartSim runtime candidates first, then fall back to summary artifacts if the runtime source is missing.",
            aria_label="NCAAF picks board",
            source_path=source_path or "NCAAF SmartSim predicted totals",
            source_title="NCAAF SmartSim picks runtime",
            source_date_display=f"Week {resolved_week}",
            rank_cards=cards,
            using_sample_data=False,
            header_stats=[
                {"label": "Cards", "value": str(len(cards))},
                {"label": "Candidates", "value": str(len(cards))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks"),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            prev_href=f"/ncaaf/picks?week={prev_week}",
            next_href=f"/ncaaf/picks?week={next_week}",
            empty_state=empty_state,
            warning_panel={
                "eyebrow": "SmartSim runtime",
                "title": "Picks are now generated from runtime projections first",
                "body": "The picks board uses SmartSim projection rows as its primary candidate source and only reverts to stored weekly summaries if the runtime source fails.",
                "list_items": [
                    "Candidate rows are built from home_mean, away_mean, win_probability, projected_spread, and projected_total.",
                    "Summary artifacts remain as a fallback path only.",
                ],
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
    }


def build_picks_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    resolved_week = _clamp_week(selected_week or default_week())
    path = summary_path(resolved_week)
    summary = load_json(path) or {}
    cards = _collapse_results(summary)
    using_sample_data = False

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    total_results = len(summary.get("results") or []) if isinstance(summary.get("results"), list) else 0
    empty_state = None
    if not cards:
        empty_state = {
            "eyebrow": "Historical mode",
            "title": "No recommendations available.",
            "body": f"No stored NCAAF recommendation rows were available for Week {resolved_week}.",
            "list_items": [
                "Choose another stored week from the historical navigation lane.",
                "The live NCAAF source feed is currently offseason-empty, so Syndicate depends on saved weekly summaries.",
            ],
        }
    return {
        **build_rank_page_context(
            selected_date=_selected_date_token(resolved_week, season=season),
            route_path="/ncaaf/picks",
            intro_title="NCAAF Picks",
            intro_body="NCAAF starts in Syndicate as a historical weekly picks board backed by recommendation summary artifacts from the source app.",
            aria_label="NCAAF picks board",
            source_path=path,
            source_title="NCAAF recommendations summary",
            source_date_display=f"Week {resolved_week}",
            rank_cards=cards,
            using_sample_data=using_sample_data,
            header_stats=[
                {"label": "Cards", "value": str(len(cards))},
                {"label": "Rows", "value": str(total_results or "-")},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks"),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            prev_href=f"/ncaaf/picks?week={prev_week}",
            next_href=f"/ncaaf/picks?week={next_week}",
            empty_state=empty_state,
            warning_panel={
                "eyebrow": "Historical mode",
                "title": "Current source artifacts are offseason snapshots",
                "body": "The live recommendations file is empty right now, so the first NCAAF surface uses the populated historical weekly summaries already present in the source repo.",
                "list_items": [
                    "Week navigation follows the weeks that actually have stored summaries.",
                    "Each card keeps the best provider row for one game, market, and side.",
                ],
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
    }

def build_betting_card_page_context(season: int, selected_week: int) -> dict[str, Any]:
    context = dict(build_picks_page_context(selected_week))
    resolved_week = int(context.get("week") or selected_week)
    context["route_path"] = f"/ncaaf/season/{int(season)}/betting-card"
    context["intro_title"] = f"NCAAF {int(season)} Betting Card"
    context["intro_body"] = "This historical NCAAF betting-card view reuses the stored weekly recommendations summary lane under an MLB-shaped season betting-card route family."
    context["source_title"] = "NCAAF season betting-card summary"
    context["source_date_display"] = f"{int(season)} Week {resolved_week}"
    context["module_links"] = build_module_links(resolved_week, "Betting Card", season=int(season))
    context["prev_href"] = f"/ncaaf/season/{int(season)}/betting-card?week={context.get('prev_href', '').split('=')[-1] or resolved_week}"
    context["next_href"] = f"/ncaaf/season/{int(season)}/betting-card?week={context.get('next_href', '').split('=')[-1] or resolved_week}"
    context["warning_panel"] = {
        "eyebrow": "Historical mode",
        "title": "NCAAF betting card currently reuses weekly summary artifacts",
        "body": "This route gives NCAAF an MLB-shaped betting-card family without inventing new live data plumbing while the source feed remains offseason-empty.",
        "list_items": [
            "Week navigation follows the stored summary weeks already present in the source repo.",
            "The ranked cards on this page are the same recommendation artifacts surfaced on the picks board.",
        ],
    }
    context["season"] = int(season)
    return context