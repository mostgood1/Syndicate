from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from syndicate.features.nfl.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.nfl.smartsim2_projection import read_projection_artifact
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import format_odds
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import recommendation_path
from syndicate.features.nfl.sources import tracked_week
from syndicate.features.nfl.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.formatters import format_pct
from syndicate.features.shared.rank_board import build_rank_page_context


_SORT_OPTIONS = [
    {"value": "", "label": "Confidence"},
    {"value": "ev", "label": "EV"},
    {"value": "odds", "label": "Odds"},
    {"value": "type", "label": "Type"},
    {"value": "time", "label": "Kickoff"},
    {"value": "level", "label": "Confidence"},
]


def _read_rows(week: int, *, season: int | None = None) -> list[dict[str, Any]]:
    path = recommendation_path(week, season=season)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _resolved_week(selected_week: int, *, season: int | None = None) -> int:
    return resolve_selected_value(selected_week, available_weeks(season), default_week(season))


def _format_game_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return raw[:10]


def _sorted_rows(rows: list[dict[str, Any]], sort_value: str = "") -> list[dict[str, Any]]:
    def _float(row: dict[str, Any], key: str) -> float:
        try:
            return float(row.get(key) or 0.0)
        except Exception:
            return 0.0

    confidence_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    def _confidence(row: dict[str, Any]) -> int:
        return confidence_rank.get(str(row.get("confidence") or "").upper(), 0)

    def _kickoff(row: dict[str, Any]) -> tuple[int, str]:
        raw = str(row.get("game_date") or "").strip()
        if not raw:
            return (1, "")
        return (0, raw)

    normalized_sort = str(sort_value or "").strip().lower()
    if normalized_sort == "time":
        return sorted(rows, key=_kickoff)
    if normalized_sort == "type":
        type_order = {"MONEYLINE": 0, "SPREAD": 1, "TOTAL": 2}
        return sorted(rows, key=lambda row: (type_order.get(str(row.get("type") or "").upper(), 99), -_float(row, "ev_pct")))
    if normalized_sort == "odds":
        return sorted(rows, key=lambda row: _float(row, "odds"), reverse=True)
    if normalized_sort == "ev":
        return sorted(rows, key=lambda row: _float(row, "ev_pct"), reverse=True)
    if normalized_sort == "level":
        return sorted(rows, key=lambda row: (_confidence(row), _float(row, "ev_pct")), reverse=True)
    return sorted(rows, key=lambda row: (_confidence(row), _float(row, "ev_pct")), reverse=True)


def _nav_href(route_path: str, season: int, week: int, sort_value: str) -> str:
    query_items = [("season", str(season)), ("week", str(week))]
    if str(sort_value or "").strip():
        query_items.append(("sort", str(sort_value).strip()))
    return f"{route_path}?{urlencode(query_items)}"


def _build_cards(rows: list[dict[str, Any]], *, limit: int | None = 12, sort_value: str = "") -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    ordered_rows = _sorted_rows(rows, sort_value)
    if limit is not None:
        ordered_rows = ordered_rows[:limit]
    for row in ordered_rows:
        home_team = str(row.get("home_team") or "Home").strip()
        away_team = str(row.get("away_team") or "Away").strip()
        rec_type = str(row.get("type") or "Recommendation").strip().upper()
        confidence = str(row.get("confidence") or "Unranked").strip().title()
        season = str(row.get("season") or latest_season())
        week = str(row.get("week") or "-")
        cards.append(
            {
                "title": f"{rec_type} | {away_team} at {home_team}",
                "eyebrow": f"{confidence} confidence",
                "badge": f"{format_pct((float(row.get('ev_pct') or 0.0) / 100.0))} EV",
                "meta": f"Week {week} | {away_team} at {home_team}",
                "metrics": [
                    {"label": "Type", "value": rec_type},
                    {"label": "Odds", "value": format_odds(row.get("odds"))},
                    {"label": "Kickoff", "value": _format_game_date(row.get("game_date"))},
                    {"label": "Season", "value": season},
                ],
                "summary": (
                    f"The weekly NFL recommendation snapshot flags {rec_type.lower()} value for {away_team} at {home_team} "
                    f"with a {confidence.lower()} confidence tier."
                ),
                "list_items": [
                    f"EV: {format_pct((float(row.get('ev_pct') or 0.0) / 100.0))}",
                    f"Odds: {format_odds(row.get('odds'))}",
                    f"Season: {season}",
                    f"Week: {week}",
                ],
            }
        )
    return cards


def _summary_panel(rows: list[dict[str, Any]], season: int, week: int) -> dict[str, Any]:
    confidence_counts = Counter(str(row.get("confidence") or "").strip().title() or "Other" for row in rows)
    type_counts = Counter(str(row.get("type") or "").strip().upper() or "OTHER" for row in rows)
    top_row = _sorted_rows(rows, "ev")[0] if rows else None
    top_game = "-"
    if isinstance(top_row, dict):
        top_game = f"{str(top_row.get('away_team') or '').strip()} at {str(top_row.get('home_team') or '').strip()}".strip() or "-"
    return {
        "eyebrow": "Weekly snapshot summary",
        "title": f"{season} Week {week} recommendation mix",
        "body": "The source recommendations page groups plays by confidence tier; this Syndicate summary keeps that same weekly snapshot context visible above the ranked cards.",
        "summary_stats": [
            {"label": "Recommendations", "value": str(len(rows))},
            {"label": "Confidence tiers", "value": str(len([key for key, value in confidence_counts.items() if value > 0]))},
            {"label": "Top EV game", "value": top_game},
        ],
        "table_groups": [
            {
                "heading": "Confidence tiers",
                "rows": [
                    {"name": key, "value": str(value)}
                    for key, value in sorted(confidence_counts.items(), key=lambda item: (-item[1], item[0]))
                ],
            },
            {
                "heading": "Bet types",
                "rows": [
                    {"name": key, "value": str(value)}
                    for key, value in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
                ],
            },
        ],
        "list_items": [
            "Counts come directly from the stored weekly recommendation snapshot for this season and week.",
            "Use the sort control to change card ordering without changing the underlying weekly snapshot.",
        ],
    }


def _card_sections(rows: list[dict[str, Any]], sort_value: str) -> list[dict[str, Any]]:
    section_order = ["High", "Medium", "Low", "Other"]
    grouped_rows: dict[str, list[dict[str, Any]]] = {key: [] for key in section_order}
    for row in rows:
        confidence = str(row.get("confidence") or "").strip().title() or "Other"
        grouped_rows.setdefault(confidence, []).append(row)
    sections: list[dict[str, Any]] = []
    for key in section_order:
        section_rows = grouped_rows.get(key) or []
        if not section_rows:
            continue
        sections.append(
            {
                "title": "Other" if key == "Other" else f"{key} confidence",
                "meta": f"{len(section_rows)} recommendation{'s' if len(section_rows) != 1 else ''}",
                "cards": _build_cards(section_rows, limit=None, sort_value=sort_value),
            }
        )
    for key, section_rows in grouped_rows.items():
        if key in section_order or not section_rows:
            continue
        sections.append(
            {
                "title": key,
                "meta": f"{len(section_rows)} recommendation{'s' if len(section_rows) != 1 else ''}",
                "cards": _build_cards(section_rows, limit=None, sort_value=sort_value),
            }
        )
    return sections


def _group_rows(rows: list[dict[str, Any]], sort_value: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"High": [], "Medium": [], "Low": [], "": []}
    for row in _sorted_rows(rows, sort_value):
        confidence = str(row.get("confidence") or "").strip().title()
        if confidence not in groups:
            groups[confidence] = []
        groups[confidence].append(dict(row))
    return groups


def _standalone_smartsim2_pick_cards(season: int, week: int) -> list[dict[str, Any]]:
    """Real-data fallback for a (season, week) with no stored
    upcoming_recs_*.csv snapshot but a real generated SmartSimNflProjection
    artifact -- mirrors cards.py's own _game_from_smartsim_projection
    fallback and syndicate.features.ncaaf.picks._standalone_smartsim2_pick_cards,
    same real reason: a new season (2026) the older recs-snapshot pipeline
    has never been refreshed for still has real SmartSim 2.0 projections
    on disk."""
    projections = read_projection_artifact(season=season, week=week, data_root=default_nfl_source_root())
    scored_cards: list[tuple[float, dict[str, Any]]] = []
    for projection in projections:
        home_team = str(projection.home_team or "Home").strip() or "Home"
        away_team = str(projection.away_team or "Away").strip() or "Away"
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
        scored_cards.append(
            (
                score,
                {
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
                        f"No stored NFL weekly recommendation snapshot exists for this week yet."
                    ),
                    "list_items": [
                        f"Projected spread: {spread_label}",
                        f"Home mean: {home_points}",
                        f"Away mean: {away_points}",
                        f"Projection source: {SMARTSIM2_PUBLIC_LABEL}",
                    ],
                },
            )
        )
    scored_cards.sort(key=lambda item: item[0], reverse=True)
    return [card for _score, card in scored_cards[:12]]


def _standalone_smartsim2_picks_context(*, season: int, resolved_week: int, weeks: list[int]) -> dict[str, Any] | None:
    standalone_cards = _standalone_smartsim2_pick_cards(season, resolved_week)
    if not standalone_cards:
        return None
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return {
        **build_rank_page_context(
            selected_date=f"{season}-01-{resolved_week:02d}",
            route_path="/nfl/picks",
            intro_title="NFL Picks",
            intro_body=f"No stored NFL weekly recommendation snapshot exists for this week yet, so this board shows {SMARTSIM2_PUBLIC_LABEL}'s own projections directly, unblended.",
            aria_label="NFL picks board",
            source_path=str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk{resolved_week}.csv"),
            source_title=f"NFL {SMARTSIM2_PUBLIC_LABEL} standalone projections",
            source_date_display=f"{season} Week {resolved_week}",
            rank_cards=standalone_cards,
            using_sample_data=False,
            header_stats=[
                {"label": "Cards", "value": str(len(standalone_cards))},
                {"label": "Candidates", "value": str(len(standalone_cards))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks", season=season),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            submit_label="Apply",
            prev_href=_nav_href("/nfl/picks", season, prev_week, ""),
            next_href=_nav_href("/nfl/picks", season, next_week, ""),
            reset_href=f"/nfl/picks?season={season}",
            hidden_fields=[{"name": "season", "value": str(season)}],
            empty_state=None,
            warning_panel={
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": "No stored recommendation snapshot yet for this week",
                "body": f"This week has no upcoming_recs_*.csv snapshot yet, so these candidates come directly from {SMARTSIM2_PUBLIC_LABEL}'s own real projection, unblended.",
                "list_items": [
                    "Candidate rows are built from home_mean, away_mean, win_probability, and projected_spread/total.",
                    "Will automatically switch to the stored recommendation snapshot once it is generated for this week.",
                ],
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
        "rows": len(standalone_cards),
        "data": [],
        "groups": {},
        "have_data": bool(standalone_cards),
    }


def build_picks_page_context(selected_week: int, *, season: int | None = None, sort: str = "") -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    weeks = available_weeks(resolved_season)
    requested_week = int(selected_week or default_week(resolved_season))
    explicit_missing_week = bool(weeks) and requested_week not in weeks
    resolved_week = requested_week if explicit_missing_week else _resolved_week(requested_week, season=resolved_season)
    normalized_sort = str(sort or "").strip().lower()
    source_path = recommendation_path(resolved_week, season=resolved_season)
    rows = [] if explicit_missing_week else _read_rows(resolved_week, season=resolved_season)
    grouped_rows = _group_rows(rows, normalized_sort)
    ordered_rows = [row for group in grouped_rows.values() for row in group]
    cards = _build_cards(rows, limit=None, sort_value=normalized_sort)
    using_sample_data = False

    if not cards and not explicit_missing_week:
        # No stored upcoming_recs_*.csv snapshot for this (season, week) --
        # real, e.g. for a season the older recs-snapshot pipeline has never
        # been refreshed for (2026) -- fall back to the real generated
        # SmartSim 2.0 projection artifact before giving up to an empty
        # state, mirroring cards.py's own engine/SmartSim2-standalone split.
        standalone_context = _standalone_smartsim2_picks_context(season=resolved_season, resolved_week=resolved_week, weeks=weeks)
        if standalone_context is not None:
            return standalone_context

    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    tracked = tracked_week()
    season = resolved_season
    empty_state = None
    if not cards:
        if explicit_missing_week:
            empty_state = {
                "eyebrow": "Weekly snapshots",
                "title": "No recommendations available.",
                "body": f"No stored NFL recommendation snapshot is available for {season} Week {resolved_week}.",
                "list_items": [
                    "Choose one of the stored weekly snapshots from the available navigation lane.",
                    f"Tracked current source week: {tracked['season']} Week {tracked['week']}" if tracked else "Tracked current source week is unavailable.",
                ],
            }
        else:
            empty_state = {
                "eyebrow": "Weekly snapshots",
                "title": "No recommendations available.",
                "body": f"The stored NFL recommendation snapshot for {season} Week {resolved_week} did not contain any recommendation rows.",
                "list_items": [
                    "Try another stored week from the weekly navigation lane.",
                    f"Tracked current source week: {tracked['season']} Week {tracked['week']}" if tracked else "Tracked current source week is unavailable.",
                ],
            }
    return {
        **build_rank_page_context(
            selected_date=f"{season}-01-{resolved_week:02d}",
            route_path="/nfl/picks",
            intro_title="NFL Picks",
            intro_body="NFL starts in Syndicate as a weekly ranked picks board backed by stored recommendation snapshots from the source app.",
            aria_label="NFL picks board",
            source_path=source_path,
            source_title="NFL weekly recommendations snapshot",
            source_date_display=f"{season} Week {resolved_week}",
            rank_cards=cards,
            using_sample_data=using_sample_data,
            header_stats=[
                {"label": "Cards", "value": str(len(cards))},
                {"label": "Rows", "value": str(len(rows) or "-")},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks", season=season),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            submit_label="Apply",
            prev_href=_nav_href("/nfl/picks", season, prev_week, normalized_sort),
            next_href=_nav_href("/nfl/picks", season, next_week, normalized_sort),
            reset_href=f"/nfl/picks?season={season}",
            hidden_fields=[{"name": "season", "value": str(season)}],
            extra_controls=[
                {
                    "name": "sort",
                    "label": "Sort",
                    "type": "select",
                    "value": normalized_sort,
                    "options": _SORT_OPTIONS,
                }
            ],
            summary_panel=_summary_panel(rows, season, resolved_week) if rows else None,
            card_sections=_card_sections(rows, normalized_sort) if rows else None,
            empty_state=empty_state,
            warning_panel={
                "eyebrow": "Weekly snapshots",
                "title": "NFL starts from persisted weekly recommendation files",
                "body": "The source repo already stores weekly recommendation snapshot CSVs, so Syndicate can lift an NFL picks board directly from artifact-backed outputs before tackling full page parity.",
                "list_items": [
                    "Week navigation follows the stored weekly snapshots currently present in the source repo.",
                    f"Tracked current source week: {tracked['season']} Week {tracked['week']}" if tracked else "Tracked current source week is unavailable.",
                ],
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
        "rows": len(ordered_rows),
        "data": ordered_rows,
        "groups": grouped_rows,
        "have_data": bool(ordered_rows),
    }


def build_betting_card_page_context(season: int, selected_week: int, *, sort: str = "") -> dict[str, Any]:
    context = dict(build_picks_page_context(selected_week, season=season, sort=sort))
    resolved_week = int(context.get("week") or selected_week)
    normalized_sort = str(sort or "").strip().lower()
    context["route_path"] = f"/nfl/season/{int(season)}/betting-card"
    context["intro_title"] = f"NFL {int(season)} Betting Card"
    context["intro_body"] = "This historical NFL betting-card view reuses the stored weekly recommendation snapshot lane under an MLB-shaped season betting-card route family."
    context["source_title"] = "NFL season betting-card snapshot"
    context["source_date_display"] = f"{int(season)} Week {resolved_week}"
    context["module_links"] = build_module_links(resolved_week, "Betting Card", season=season)
    context["submit_label"] = "Apply"
    weeks = available_weeks(int(season))
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    query_suffix = f"week={prev_week}" if not normalized_sort else f"week={prev_week}&sort={normalized_sort}"
    context["prev_href"] = f"/nfl/season/{int(season)}/betting-card?{query_suffix}"
    query_suffix = f"week={next_week}" if not normalized_sort else f"week={next_week}&sort={normalized_sort}"
    context["next_href"] = f"/nfl/season/{int(season)}/betting-card?{query_suffix}"
    context["reset_href"] = f"/nfl/season/{int(season)}/betting-card"
    context["warning_panel"] = {
        "eyebrow": "Weekly snapshots",
        "title": "NFL betting card currently reuses persisted weekly recommendation files",
        "body": "This route gives NFL an MLB-shaped betting-card family without inventing new data plumbing before fuller season and live surfaces are ready.",
        "list_items": [
            "Week navigation follows the stored weekly recommendation snapshots already present in the source repo.",
            "The ranked cards on this page are the same recommendation artifacts surfaced on the picks board.",
        ],
    }
    return context