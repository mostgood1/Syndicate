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
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.smartsim2_trial_monitoring import record_trial_page_view

from syndicate.features.ncaaf.cards import _engine_rows_for_season_week
from syndicate.features.ncaaf.cards import _ncaaf_default_active_week
from syndicate.features.ncaaf.cards import _prediction_source_path
from syndicate.features.ncaaf.cards import _normalize_probability
from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
from syndicate.features.ncaaf.cards import _runtime_scoreboard_projection
from syndicate.features.ncaaf.cards import _runtime_prediction_rows
from syndicate.features.ncaaf.cards import _smartsim2_standalone_rows


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
    shown_rows = ordered_rows[:12]
    record_trial_page_view(
        route="/ncaaf/picks",
        season=season,
        week=week,
        scoreboards=[item["scoreboard"] for item in shown_rows],
    )
    cards: list[dict[str, Any]] = []
    for item in shown_rows:
        row = item["row"]
        scoreboard = item["scoreboard"]
        home_team = item["home_team"]
        away_team = item["away_team"]
        cards.append(
            {
                "title": f"{home_team} vs {away_team} {LEGACY_ENGINE_SOURCE_LABEL} candidate",
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "badge": f"{scoreboard.get('win_probability') or '-'} win prob",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
                    {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
                    {"label": "Spread", "value": scoreboard.get("spread_label") or "-"},
                    {"label": "Total", "value": scoreboard.get("total_points") or "-"},
                ],
                "summary": (
                    f"{LEGACY_ENGINE_SOURCE_LABEL} projects {home_team} {scoreboard.get('home_points') or '-'} - {scoreboard.get('away_points') or '-'} "
                    f"{away_team} with a projected total of {scoreboard.get('total_points') or '-'} and a home win probability of {scoreboard.get('win_probability') or '-'}."
                ),
                "list_items": [
                    f"Projected spread: {scoreboard.get('spread_label') or '-'}",
                    f"Home mean: {scoreboard.get('home_points') or '-'}",
                    f"Away mean: {scoreboard.get('away_points') or '-'}",
                    f"Projection source: {scoreboard.get('source_label') or LEGACY_ENGINE_SOURCE_LABEL}",
                    *_diagnostic_source_list_items(scoreboard),
                ],
            }
        )
    return cards


def _diagnostic_source_list_items(scoreboard: dict[str, Any]) -> list[str]:
    """Blend-trial source-comparison rows -- empty unless projection_sources
    was attached (internal diagnostics env var, or the Phase 3 public-trial
    gate; see cards._blend_trial_diagnostics_enabled /
    cards._public_trial_visible_for_request). Wording depends on
    projection_sources_mode so a public-trial tester never sees "internal
    diagnostic" language. Reuses the picks board's existing generic
    list_items rendering, so no template change was needed for this surface."""
    sources = scoreboard.get("projection_sources")
    if not isinstance(sources, dict):
        return []
    is_public_trial = scoreboard.get("projection_sources_mode") == "public_trial"
    header = (
        "You're seeing this because you're part of a limited SmartSim 2.0 trial:"
        if is_public_trial
        else "Internal diagnostic -- not publicly visible:"
    )
    lines = [header]
    for key in ("enhanced_totals_engine", "smartsim2", "consensus_projection"):
        source = sources.get(key)
        if not isinstance(source, dict):
            continue
        lines.append(f"{source.get('label')}: margin {source.get('margin')} | total {source.get('total')}")
    return lines


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def _standalone_smartsim2_pick_cards(season: int, week: int) -> list[dict[str, Any]]:
    """Same real-data fallback build_cards_page_context already has for
    itself (via _smartsim2_standalone_rows) -- picks never had this wired
    in, so a season the legacy engine has no predicted-totals rows for
    (e.g. 2026, confirmed: college_football_schedule_*_predicted_totals_enhanced*.csv
    is 2025-only) fell all the way through to the historical
    summary-artifact path below instead of showing the real SmartSim 2.0
    projections cards.py already renders for that same week."""
    standalone_rows = _smartsim2_standalone_rows(season, week)
    cards: list[dict[str, Any]] = []
    for row in standalone_rows:
        projection = row.get("projection")
        if projection is None:
            continue
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        home_points = round(projection.home_score_mean, 1)
        away_points = round(projection.away_score_mean, 1)
        total_points = round(projection.total_mean, 1)
        margin = projection.margin_mean
        if margin > 0:
            spread_label = f"{home_team} by {abs(margin):.1f}"
        elif margin < 0:
            spread_label = f"{away_team} by {abs(margin):.1f}"
        else:
            spread_label = "Pick'em"
        win_probability = format_pct(projection.home_win_rate)
        score = abs(projection.home_win_rate - 0.5) * 100.0 + abs(margin) + (total_points / 100.0)
        cards.append(
            {
                "score": score,
                "card": {
                    "title": f"{home_team} vs {away_team} {SMARTSIM2_PUBLIC_LABEL} candidate",
                    "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                    "badge": f"{win_probability} win prob",
                    "meta": f"{away_team} at {home_team}",
                    "metrics": [
                        {"label": "Home mean", "value": home_points},
                        {"label": "Away mean", "value": away_points},
                        {"label": "Spread", "value": spread_label},
                        {"label": "Total", "value": total_points},
                    ],
                    "summary": (
                        f"{SMARTSIM2_PUBLIC_LABEL} projects {home_team} {home_points} - {away_points} {away_team} "
                        f"with a projected total of {total_points} and a home win probability of {win_probability}. "
                        f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction for this game yet."
                    ),
                    "list_items": [
                        f"Projected spread: {spread_label}",
                        f"Home mean: {home_points}",
                        f"Away mean: {away_points}",
                        f"Projection source: {SMARTSIM2_PUBLIC_LABEL}",
                    ],
                },
            }
        )
    cards.sort(key=lambda item: item["score"], reverse=True)
    return [item["card"] for item in cards[:12]]


def _standalone_smartsim2_picks_context(*, season: int, resolved_week: int, weeks: list[int]) -> dict[str, Any] | None:
    standalone_cards = _standalone_smartsim2_pick_cards(season, resolved_week)
    if not standalone_cards:
        return None
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return {
        **build_rank_page_context(
            selected_date=_selected_date_token(resolved_week, season=season),
            route_path="/ncaaf/picks",
            intro_title="NCAAF Picks",
            intro_body=f"No {LEGACY_ENGINE_SOURCE_LABEL} data exists for this week yet, so this board shows {SMARTSIM2_PUBLIC_LABEL}'s own projections directly, unblended.",
            aria_label="NCAAF picks board",
            source_path=f"NCAAF {SMARTSIM2_PUBLIC_LABEL} standalone projections",
            source_title=f"NCAAF {SMARTSIM2_PUBLIC_LABEL} picks runtime",
            source_date_display=f"Week {resolved_week}",
            rank_cards=standalone_cards,
            using_sample_data=False,
            header_stats=[
                {"label": "Cards", "value": str(len(standalone_cards))},
                {"label": "Candidates", "value": str(len(standalone_cards))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks"),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            prev_href=f"/ncaaf/picks?week={prev_week}",
            next_href=f"/ncaaf/picks?week={next_week}",
            empty_state=None,
            warning_panel={
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": f"No {LEGACY_ENGINE_SOURCE_LABEL} data yet for this week",
                "body": f"This week has no {LEGACY_ENGINE_SOURCE_LABEL} predicted-totals row yet, so these candidates come directly from {SMARTSIM2_PUBLIC_LABEL}'s own projection, unblended.",
                "list_items": [
                    "Candidate rows are built from home_mean, away_mean, win_probability, and projected_spread/total.",
                    f"Will automatically switch to the blended {LEGACY_ENGINE_SOURCE_LABEL}+{SMARTSIM2_PUBLIC_LABEL} view once the engine has real data for this week.",
                ],
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
    }


def build_smartsim_picks_page_context(selected_week: int) -> dict[str, Any]:
    season, active_weeks = _resolve_ncaaf_active_season_and_weeks()
    if not active_weeks:
        return build_picks_page_context(selected_week)
    default_active_week = _ncaaf_default_active_week(season, active_weeks)
    requested_week = int(selected_week or default_active_week)
    resolved_week = resolve_selected_value(requested_week, active_weeks, default_active_week)

    # _prediction_weeks()/_runtime_prediction_rows() (used by the engine
    # path below) filter ONLY by week, never by season -- confirmed a real
    # bug: the (single, non-season-partitioned) predicted-totals CSV still
    # has old season's rows for week 1, which would otherwise get served
    # up as if they were this season's real picks. _engine_rows_for_season_week
    # (already used by cards.py's own engine/smartsim2 split) is the
    # season-aware check that avoids this.
    engine_rows = _engine_rows_for_season_week(season, resolved_week)
    if not engine_rows:
        standalone_context = _standalone_smartsim2_picks_context(season=season, resolved_week=resolved_week, weeks=active_weeks)
        if standalone_context is not None:
            return standalone_context
        return build_picks_page_context(selected_week)

    cards = _runtime_pick_cards(resolved_week, season=season)
    if not cards:
        return build_picks_page_context(selected_week)
    weeks = active_weeks
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    source_path = _prediction_source_path()
    empty_state = None
    if not cards:
        empty_state = {
            "eyebrow": f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} picks",
            "title": "No runtime picks were available.",
            "body": f"The {LEGACY_ENGINE_SOURCE_LABEL} picks board first reads the predicted-totals snapshot and falls back to saved weekly summaries only if the runtime source is unavailable.",
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
            intro_body=f"NCAAF picks now generate {LEGACY_ENGINE_SOURCE_LABEL} runtime candidates first, then fall back to summary artifacts if the runtime source is missing.",
            aria_label="NCAAF picks board",
            source_path=source_path or f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} predicted totals",
            source_title=f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} picks runtime",
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
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "title": "Picks are now generated from runtime projections first",
                "body": f"The picks board uses {LEGACY_ENGINE_SOURCE_LABEL} projection rows as its primary candidate source and only reverts to stored weekly summaries if the runtime source fails.",
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
    # Was unconditionally build_picks_page_context() (the pure-historical,
    # summary-artifact-only path), documented at the time as deliberate
    # ("without inventing new live data plumbing while the source feed
    # remains offseason-empty") -- that plumbing now exists
    # (build_smartsim_picks_page_context's real-engine/SmartSim2-standalone
    # split), so this reuses it instead of staying historical-only forever.
    context = dict(build_smartsim_picks_page_context(selected_week))
    resolved_week = int(context.get("week") or selected_week)
    context["route_path"] = f"/ncaaf/season/{int(season)}/betting-card"
    context["intro_title"] = f"NCAAF {int(season)} Betting Card"
    context["intro_body"] = "This NCAAF betting-card view reuses whatever real picks-board data is currently available (engine, SmartSim2 standalone, or the stored weekly summary lane) under an MLB-shaped season betting-card route family."
    context["source_title"] = "NCAAF season betting-card"
    context["source_date_display"] = f"{int(season)} Week {resolved_week}"
    context["module_links"] = build_module_links(resolved_week, "Betting Card", season=int(season))
    context["prev_href"] = f"/ncaaf/season/{int(season)}/betting-card?week={context.get('prev_href', '').split('=')[-1] or resolved_week}"
    context["next_href"] = f"/ncaaf/season/{int(season)}/betting-card?week={context.get('next_href', '').split('=')[-1] or resolved_week}"
    context["season"] = int(season)
    return context