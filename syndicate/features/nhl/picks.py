from __future__ import annotations

import csv
from typing import Any

import re

from syndicate.features.nhl.sources import available_dates
from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import format_pct
from syndicate.features.nhl.sources import format_price
from syndicate.features.nhl.sources import market_label
from syndicate.features.nhl.sources import recommendation_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.shared import board_game_picks
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.rank_board import build_rank_page_context


def _read_rows(date_str: str) -> list[dict[str, Any]]:
    path = recommendation_path(date_str)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _resolved_date(selected_date: str | None) -> str:
    return resolve_selected_value(str(selected_date or default_date()), available_dates(), default_date())


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _float(row: dict[str, Any], key: str) -> float:
        try:
            return float(row.get(key) or 0.0)
        except Exception:
            return 0.0

    return sorted(rows, key=lambda row: (_float(row, "ev"), _float(row, "prob")), reverse=True)


_PL_SIDE = re.compile(r"^(?P<team>.*?)\s*(?P<line>[+-]\d+(?:\.\d+)?)\s*$")


def _team_side(team: str, away_team: str, home_team: str) -> str | None:
    key = board_game_picks.team_key(team)
    if key and key == board_game_picks.team_key(home_team):
        return "home"
    if key and key == board_game_picks.team_key(away_team):
        return "away"
    return None


def board_line_for_sim_row(
    board: board_game_picks.SportBoardView, row: dict[str, Any]
) -> board_game_picks.BoardLine | None:
    """The board's row for the same line as one sim recommendation (`recommendations_sim_<date>.csv`: market ML /
    TOTAL / PL; side a team, "Over"/"Under", or "Team +1.5")."""
    home_team = str(row.get("home") or "").strip()
    away_team = str(row.get("away") or "").strip()
    market = str(row.get("market") or "").strip().upper()
    side = str(row.get("side") or "").strip()
    if market in ("TOTAL", "TOTALS"):
        return board.find_game_line(away_team, home_team, "totals", side.lower(), row.get("totals_line"))
    if market == "ML":
        team_side = _team_side(side, away_team, home_team)
        return board.find_game_line(away_team, home_team, "h2h", team_side) if team_side else None
    if market == "PL":
        match = _PL_SIDE.match(side)
        if not match:
            return None
        team_side = _team_side(match.group("team"), away_team, home_team)
        if not team_side:
            return None
        return board.find_game_line(away_team, home_team, "spreads", team_side, match.group("line"))
    return None


def _build_cards(
    rows: list[dict[str, Any]],
    source_path: str,
    *,
    limit: int = 12,
    board: board_game_picks.SportBoardView | None = None,
) -> list[dict[str, Any]]:
    """The raw sim's snapshot, LABELLED as the sim's (#861 step 1d): its EV is at its own price, and each card says
    what the board makes of the same line. It used to be the page's headline, under "EV" alone, while the board
    suggested none of it (fleet 2026-11-25: 0 of 12)."""
    cards: list[dict[str, Any]] = []
    source_kind = "Sim snapshot" if "recommendations_sim_" in source_path else "Direct snapshot"
    for row in _sorted_rows(rows)[:limit]:
        home_team = str(row.get("home") or "Home").strip()
        away_team = str(row.get("away") or "Away").strip()
        market = market_label(row.get("market"))
        side = str(row.get("side") or "Recommended side").strip()
        totals_line = str(row.get("totals_line") or "-").strip() or "-"
        list_items: list[str] = []
        if board is not None and board.ok:
            line = board_line_for_sim_row(board, row)
            list_items.append(board.verdict(line, away_team, home_team))
        list_items.extend([
            f"Market: {market}",
            f"Home: {home_team}",
            f"Away: {away_team}",
            f"Source type: {source_kind}",
        ])
        cards.append(
            {
                "title": side,
                "eyebrow": f"Sim view · {market}",
                "badge": f"Sim EV {format_pct(row.get('ev'))}",
                "source": "sim",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Sim win prob", "value": format_pct(row.get("prob"))},
                    {"label": "Sim price", "value": format_price(row.get("price"))},
                    {"label": "Confidence", "value": format_pct(row.get("conf"))},
                    {"label": "Total", "value": totals_line},
                ],
                "summary": (
                    f"The raw sim's {market.lower()} snapshot prefers {side} for {away_team} at {home_team}, at its own "
                    f"price. This is the sim's view, not the board's pick."
                ),
                "list_items": list_items,
            }
        )
    return cards


def _pct_text(value: float | None) -> str:
    return "-" if value is None else f"{100.0 * value:.1f}%"


def board_built_text(board: board_game_picks.SportBoardView) -> str:
    return str(board.written_at or "").replace("T", " ").replace("Z", " UTC").strip()


def build_board_cards(board: board_game_picks.SportBoardView, *, limit: int = 12) -> list[dict[str, Any]]:
    """The Layer 2 board's NHL picks for the slate (`suggested`, the board's own order) as the page's headline cards."""
    built = board_built_text(board)
    cards: list[dict[str, Any]] = []
    for pick in board.picks[: max(0, int(limit))]:
        cards.append(
            {
                "title": pick.side_label,
                "eyebrow": f"Board pick · {pick.market_label}",
                "badge": pick.ev_label,
                "source": "board",
                "meta": f"{pick.away} at {pick.home}",
                "metrics": [
                    {"label": "Price", "value": pick.price_text},
                    {"label": "Fair", "value": _pct_text(pick.fair)},
                    {"label": "Board win%", "value": _pct_text(pick.model_prob)},
                    {"label": "Books", "value": "-" if pick.books_quoting is None else str(pick.books_quoting)},
                ],
                "summary": f"The board suggests this bet: {pick.ev_label} at {pick.price_text}, against its fair price.",
                "list_items": [
                    board_game_picks.verdict_text(pick),
                    f"Market: {pick.market_label}",
                    "Source type: Layer 2 board" + (f" (built {built})" if built else ""),
                ],
            }
        )
    return cards


def build_picks_page_context(selected_date: str | None) -> dict[str, Any]:
    requested_date = str(selected_date or default_date()).strip() or default_date()
    resolved_date = _resolved_date(selected_date)
    source_path = recommendation_path(resolved_date)
    rows = _read_rows(resolved_date)
    board = board_game_picks.sport_view("nhl", resolved_date)
    board_cards = build_board_cards(board)
    sim_cards = _build_cards(rows, source_path.name, board=board)
    # The HEADLINE is the board's picks (#861 step 1d): `rank_cards` is what the API and the page lead with.
    cards = board_cards
    using_sample_data = False

    dates = available_dates()
    prev_date, next_date = neighboring_values(dates, requested_date, fallback=resolved_date)
    latest_date = dates[-1] if dates else resolved_date
    latest_kind = next((item["kind"] for item in reversed(slate_summaries()) if item["date"] == resolved_date), "Sim snapshot")
    warning_items = [f"Latest detected slate: {latest_date}"]
    if requested_date != resolved_date:
        warning_items.insert(0, f"Requested date: {requested_date}")
        warning_items.insert(1, f"Showing stored slate: {resolved_date}")
    summary_stats = [
        {"label": "Board picks", "value": str(len(board.picks)) if board.ok else "-"},
        {"label": "Sim rows", "value": str(len(rows) or 0)},
        {"label": "Slates", "value": str(len(dates) or 0)},
    ]
    built = board_built_text(board)
    if board.ok:
        board_note = (
            f"The Layer 2 board's pregame picks for {resolved_date}, in its own order"
            + (f" (built {built})" if built else "")
            + ". Price, fair and EV are the board's."
        )
        if not board.picks:
            board_note += f" The board suggests no NHL bet on this slate ({len(board.lines)} pregame lines judged)."
        elif len(board.picks) > len(board_cards):
            board_note += f" Showing {len(board_cards)} of {len(board.picks)}."
    else:
        board_note = f"The board has no saved shortlist for {resolved_date}, so it has no picks to show for this date."
    card_sections = [
        {"key": "board", "title": "The board's NHL picks", "note": board_note, "cards": board_cards},
        {
            "key": "sim",
            "title": "Raw sim view: not the board's picks",
            "note": (
                "The NHL sim's own recommendation snapshot, each at the sim's own price. "
                "Each card says what the board makes of the same line."
            ),
            "cards": sim_cards,
        },
    ]

    return {
        **build_rank_page_context(
            selected_date=requested_date,
            route_path="/nhl/picks",
            intro_title="NHL Picks",
            intro_body="The board's NHL picks lead this page. The raw sim's recommendation snapshot follows, labelled as the sim's, with the board's verdict on each line.",
            aria_label="NHL picks board",
            source_path=source_path,
            source_title="NHL picks: the board first, then the raw sim" if (cards or sim_cards) else "NHL picks unavailable",
            rank_cards=cards,
            using_sample_data=using_sample_data,
            header_stats=[
                {"label": "Board picks", "value": str(len(board.picks)) if board.ok else "-"},
                {"label": "Sim rows", "value": str(len(rows) or "-")},
                {"label": "Slates", "value": str(len(dates) or "-")},
            ],
            module_links=build_module_links(requested_date, "Picks"),
            source_date_display=resolved_date,
            prev_href=f"/nhl/picks?date={prev_date}",
            next_href=f"/nhl/picks?date={next_date}",
            warning_panel={
                "eyebrow": latest_kind,
                "title": "The board's picks lead; the sim's snapshot is labelled",
                "body": "A pick on this page is the Layer 2 board's (its price, fair and EV). The raw sim's recommendation snapshot is kept below as the sim's view, with its own EV at its own price.",
                "list_items": ["Date navigation follows the slates that actually have stored recommendation files.", *warning_items],
            },
            summary_panel={"summary_stats": summary_stats},
            card_sections=card_sections,
            reset_href="/nhl/picks",
            empty_state={
                "eyebrow": "NHL picks",
                "title": "No stored NHL picks were available for this date",
                "body": "The picks board only renders saved NHL recommendation snapshots, and none were available for the requested date.",
                "list_items": ["Choose another stored NHL date from the calendar control."],
            } if not (cards or sim_cards) else None,
        ),
        "available_dates": dates,
    }


def build_betting_card_page_context(season: int, selected_date: str | None) -> dict[str, Any]:
    context = dict(build_picks_page_context(selected_date))
    requested_date = str(context.get("date") or selected_date or default_date())
    resolved_date = str(context.get("source_date_display") or requested_date)
    resolved_season = int(season)
    dates = available_dates()
    prev_date, next_date = neighboring_values(dates, requested_date, fallback=resolved_date)
    context["route_path"] = f"/nhl/season/{resolved_season}/betting-card"
    context["intro_title"] = f"NHL {resolved_season} Betting Card"
    context["intro_body"] = "This historical NHL betting-card view reuses the stored recommendation snapshot lane under an MLB-shaped season betting-card route family."
    context["source_title"] = "NHL season betting-card snapshot" if context.get("rank_cards") else "NHL betting card unavailable"
    context["source_date_display"] = resolved_date
    context["module_links"] = build_module_links(requested_date, "Betting Card", season=resolved_season)
    context["prev_href"] = f"/nhl/season/{resolved_season}/betting-card?date={prev_date}"
    context["next_href"] = f"/nhl/season/{resolved_season}/betting-card?date={next_date}"
    context["reset_href"] = f"/nhl/season/{resolved_season}/betting-card"
    context["warning_panel"] = {
        "eyebrow": "Stored snapshots",
        "title": "NHL betting card currently reuses persisted recommendation files",
        "body": "This route gives NHL an MLB-shaped betting-card family without inventing new season-specific data plumbing before fuller season surfaces are ready.",
        "list_items": [
            "Date navigation follows the stored recommendation snapshots already present in the source repo.",
            *( [f"Showing stored slate: {resolved_date}"] if requested_date != resolved_date else [] ),
            "The ranked cards on this page are the same recommendation artifacts surfaced on the picks board.",
        ],
    }
    return context