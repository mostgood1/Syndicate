from __future__ import annotations

from datetime import datetime
from typing import Any

from syndicate.features.ncaaf.cards import _engine_rows_for_season_week
from syndicate.features.ncaaf.cards import _ncaaf_default_active_week
from syndicate.features.ncaaf.cards import _prediction_source_path
from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
from syndicate.features.ncaaf.cards import _runtime_scoreboard_projection
from syndicate.features.ncaaf.cards import _smartsim2_standalone_rows
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import format_pct
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.timezone import CENTRAL_TIMEZONE


def _kickoff_date_and_label(kickoff: Any) -> tuple[str, str]:
    """Real per-game date (for day grouping) + a human weekday label, parsed
    from whatever ISO-ish kickoff string the row actually carries
    (start_date_api/start_date on engine rows, startDate on the real
    schedule rows behind the SmartSim2 standalone path -- both land in the
    same "kickoff" field by the time a card entry is built below). Falls
    back to an untethered "Date TBD" bucket rather than raising or silently
    dropping the game when a row has no usable kickoff yet.

    CENTRAL, not UTC. The kickoff strings are UTC (`...T00:00:00.000Z`), and
    this used to take `.date()` straight off the parsed value, so the day a
    game was filed under was its UTC day. Every evening kickoff is the NEXT
    UTC day: a 7pm Central Saturday game is 00:00Z Sunday, so the card filed
    Saturday's marquee slate under Sunday and labelled it "Sunday". This is
    the exact trap `features/shared/timezone.py:central_date_from_iso`
    documents for WNBA slate filtering, arrived at independently on a second
    surface -- which is why the conversion belongs at every point a timestamp
    becomes a calendar day, not at the ones somebody remembered.

    A naive timestamp is treated as already-Central, matching
    `central_date_from_iso`'s handling, rather than being assumed UTC."""
    text = str(kickoff or "").strip()
    if not text:
        return "", "Date TBD"
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        date_part = text[:10]
        return date_part, (date_part or "Date TBD")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL_TIMEZONE)
    local = parsed.astimezone(CENTRAL_TIMEZONE)
    date_part = local.date().isoformat()
    # Avoid strftime's %-d/%#d platform split (Windows vs. POSIX) -- build
    # the "Weekday, Month D" label from portable directives only.
    weekday_label = f"{local.strftime('%A')}, {local.strftime('%B')} {local.day}"
    return date_part, weekday_label


def _engine_game_entry(row: dict[str, Any], week: int) -> dict[str, Any]:
    scoreboard = _runtime_scoreboard_projection(row, week)
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    kickoff = str(scoreboard.get("kickoff") or "").strip()
    date_key, weekday_label = _kickoff_date_and_label(kickoff)
    source_label = scoreboard.get("source_label") or LEGACY_ENGINE_SOURCE_LABEL
    venue = str(scoreboard.get("venue") or "").strip()
    meta = f"{away_team} at {home_team}"
    if venue:
        meta = f"{meta} | {venue}"
    return {
        "date": date_key,
        "weekday_label": weekday_label,
        "kickoff": kickoff,
        "card": {
            "title": f"{away_team} at {home_team}",
            # Game-level dashboard entry, not a player prop -- see
            # picks.py's _collapse_results market-stamp note (keeps these
            # out of pregame props on shared surfaces that key off "market").
            "market": "game bet",
            "eyebrow": source_label,
            "badge": f"{scoreboard.get('win_probability') or '-'} win prob",
            "meta": meta,
            "metrics": [
                {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
                {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
                {"label": "Spread", "value": scoreboard.get("spread_label") or "-"},
                {"label": "Total", "value": scoreboard.get("total_points") or "-"},
            ],
            "summary": (
                f"{source_label} projects {home_team} {scoreboard.get('home_points') or '-'} - "
                f"{scoreboard.get('away_points') or '-'} {away_team} with a projected total of "
                f"{scoreboard.get('total_points') or '-'}."
            ),
            "list_items": [
                f"Kickoff: {kickoff or 'TBD'}",
                f"Projected spread: {scoreboard.get('spread_label') or '-'}",
                f"Win probability: {scoreboard.get('win_probability') or '-'}",
                f"Projection source: {source_label}",
            ],
        },
    }


def _standalone_game_entry(row: dict[str, Any]) -> dict[str, Any]:
    projection = row.get("projection")
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    kickoff = str(row.get("start_date") or "").strip()
    date_key, weekday_label = _kickoff_date_and_label(kickoff)
    venue = str(row.get("venue") or "").strip()

    if projection is None:
        home_points: Any = "-"
        away_points: Any = "-"
        total_points: Any = "-"
        spread_label = "-"
        win_probability = "-"
    else:
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

    meta = f"{away_team} at {home_team}"
    if venue:
        meta = f"{meta} | {venue}"
    return {
        "date": date_key,
        "weekday_label": weekday_label,
        "kickoff": kickoff,
        "card": {
            "title": f"{away_team} at {home_team}",
            "market": "game bet",
            "eyebrow": SMARTSIM2_PUBLIC_LABEL,
            "badge": f"{win_probability} win prob",
            "meta": meta,
            "metrics": [
                {"label": "Home mean", "value": home_points},
                {"label": "Away mean", "value": away_points},
                {"label": "Spread", "value": spread_label},
                {"label": "Total", "value": total_points},
            ],
            "summary": (
                f"{SMARTSIM2_PUBLIC_LABEL} projects {home_team} {home_points} - {away_points} {away_team} "
                f"with a projected total of {total_points}. {LEGACY_ENGINE_SOURCE_LABEL} has no prediction "
                "for this game yet."
            ),
            "list_items": [
                f"Kickoff: {kickoff or 'TBD'}",
                f"Projected spread: {spread_label}",
                f"Win probability: {win_probability}",
                f"Projection source: {SMARTSIM2_PUBLIC_LABEL}",
            ],
        },
    }


def _group_entries_by_day(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Real day concept nested inside the selected week -- NOT a season-long
    day rail. NCAAF's real schedule only ever has a handful of distinct
    calendar dates per week (Tue/Wed MACtion + the Thu/Fri/Sat majority,
    rarely more), so this groups whatever real dates the selected week's
    games actually carry rather than assuming a fixed weekly shape (a
    Saturday-only week must produce exactly one day entry, not seven)."""
    ordered_entries = sorted(
        entries,
        key=lambda entry: (entry.get("date") or "9999-99-99", entry.get("kickoff") or "", entry["card"]["title"]),
    )
    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for entry in ordered_entries:
        date_key = entry.get("date") or ""
        bucket_key = date_key or "__tbd__"
        if bucket_key not in buckets:
            buckets[bucket_key] = []
            order.append(bucket_key)
            labels[bucket_key] = entry.get("weekday_label") or "Date TBD"
        buckets[bucket_key].append(entry["card"])
    days: list[dict[str, Any]] = []
    for bucket_key in order:
        games = buckets[bucket_key]
        days.append(
            {
                "date": None if bucket_key == "__tbd__" else bucket_key,
                "weekday_label": labels[bucket_key],
                "games": games,
                "game_count": len(games),
            }
        )
    return days


def build_ncaaf_betting_card_page_context(season: int, selected_week: int) -> dict[str, Any]:
    """Real week-granularity NCAAF betting-card dashboard: every game for
    the selected (season, week) grouped by its real kickoff date into
    `days`, computed at request time from the same runtime data
    ncaaf/picks.py and ncaaf/cards.py already load (no offline
    manifest-generation pipeline exists for NCAAF, and none is added here).

    Reuses cards.py's season-aware engine lookup
    (_engine_rows_for_season_week) first, falling back to the real
    SmartSim 2.0 standalone schedule+projection join
    (_smartsim2_standalone_rows) for a season the legacy engine has no
    predicted-totals rows for yet -- the same two-source split
    build_smartsim_picks_page_context/build_smartsim_cards_page_context
    already use, just without truncating to a top-N picks list: a
    dashboard needs every real game for the week, not just the highest-
    scoring candidates.
    """
    requested_season = int(season) if season else default_season()
    active_season, active_weeks = _resolve_ncaaf_active_season_and_weeks()
    if active_weeks and requested_season == active_season:
        weeks = active_weeks
    else:
        weeks = available_weeks() or active_weeks or [1]

    resolved_season = requested_season
    default_active_week = _ncaaf_default_active_week(resolved_season, weeks) if weeks else 1
    requested_week = int(selected_week or default_active_week)
    resolved_week = resolve_selected_value(requested_week, weeks, default_active_week)

    engine_rows = _engine_rows_for_season_week(resolved_season, resolved_week)
    if engine_rows:
        entries = [_engine_game_entry(row, resolved_week) for row in engine_rows]
        source_label = LEGACY_ENGINE_SOURCE_LABEL
        source_path = _prediction_source_path()
    else:
        standalone_rows = _smartsim2_standalone_rows(resolved_season, resolved_week)
        entries = [_standalone_game_entry(row) for row in standalone_rows]
        source_label = SMARTSIM2_PUBLIC_LABEL
        source_path = None

    days = _group_entries_by_day(entries)
    game_count = len(entries)

    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    route_path = f"/ncaaf/season/{resolved_season}/betting-card"

    empty_state = None
    if not entries:
        empty_state = {
            "eyebrow": "NCAAF betting card",
            "title": "No games were available for this week",
            "body": (
                f"The betting card first reads {LEGACY_ENGINE_SOURCE_LABEL} predicted totals for this "
                f"season and week, then falls back to real {SMARTSIM2_PUBLIC_LABEL} standalone projections "
                "for a season the engine has no data for yet."
            ),
            "list_items": [
                f"Requested week: {selected_week}",
                f"Resolved week: {resolved_week}",
            ],
        }

    week_summary = {
        "season": resolved_season,
        "week": resolved_week,
        "game_count": game_count,
        "day_count": len(days),
        "source_label": source_label if entries else "No data",
    }

    return {
        "season": resolved_season,
        "week": resolved_week,
        "available_weeks": weeks,
        "route_path": route_path,
        "date": f"{resolved_season} Week {resolved_week}",
        "requested_date": f"{resolved_season} Week {selected_week}",
        "intro_title": f"NCAAF {resolved_season} Betting Card",
        "intro_body": (
            f"Week {resolved_week} games grouped by real kickoff date, sourced from "
            f"{source_label if entries else 'no available'} projections -- computed at request time from "
            "the same runtime data the picks board already loads, no offline manifest pipeline."
        ),
        "source_title": "NCAAF season betting-card",
        "source_path": str(source_path) if source_path else (f"NCAAF {source_label} predicted totals" if entries else None),
        "source_date_display": f"{resolved_season} Week {resolved_week}",
        "week_summary": week_summary,
        "days": days,
        "module_links": build_module_links(resolved_week, "Betting Card", season=resolved_season),
        "prev_week": prev_week,
        "next_week": next_week,
        "prev_href": f"{route_path}?week={prev_week}",
        "next_href": f"{route_path}?week={next_week}",
        "control_label": "Week",
        "control_type": "number",
        "control_name": "week",
        "control_value": str(resolved_week),
        "using_sample_data": False,
        "empty_state": empty_state,
        "header_stats": [
            {"label": "Games", "value": str(game_count)},
            {"label": "Days", "value": str(len(days))},
            {"label": "Weeks", "value": str(len(weeks) or "-")},
            {"label": "Source", "value": source_label if entries else "No data"},
        ],
    }
