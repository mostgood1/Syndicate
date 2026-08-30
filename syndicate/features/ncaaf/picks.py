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
from syndicate.features.football.pick_gate import board_notice
from syndicate.features.football.pick_gate import filter_pick_rows
from syndicate.features.football.pick_gate import notice_for
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


def _collapse_results(
    summary: dict[str, Any],
    *,
    limit: int = 12,
    gate_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Collapse recommendation rows to the best card per (matchup, market, side).

    Rows are gated FIRST, before dedup and ranking. Gating after ranking would
    still withhold the card but would leave a suppressed row occupying a slot in
    the top-`limit`, so a served market could lose cards to a market that is not
    allowed to be served at all.

    `gate_counts` follows the `counts=` out-param idiom cards.py already uses for
    board truncation: a cap that bites must announce it.
    """
    raw_results = summary.get("results") if isinstance(summary.get("results"), list) else []
    results, suppressed = filter_pick_rows("ncaaf", raw_results)
    if gate_counts is not None:
        gate_counts.clear()
        gate_counts.update(suppressed)
    if suppressed:
        # Web's stdout IS collected by Render; logger.info is not.
        print(
            "NCAAF_PICKS_SUPPRESSED "
            + " ".join(f"{market}={count}" for market, count in sorted(suppressed.items())),
            flush=True,
        )
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
                # Team-level game bet, not a player prop. Without a "market"
                # key, home.py's _is_game_level_rank_card_market returns
                # False and these cards flow into pregame_props() mislabeled
                # as player props (the exact WNBA 2026-07-27 bug class).
                "market": market.lower() if market.lower() in ("moneyline", "spread", "total") else "game bet",
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
                # Game-level projection candidate -- see _collapse_results'
                # market-stamp note (keeps these out of pregame props).
                "market": "game bet",
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
                    # Game-level projection candidate -- see _collapse_results'
                    # market-stamp note (keeps these out of pregame props).
                    "market": "game bet",
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


#: Markets the NCAAF picks board can offer. Every candidate it builds is one of
#: these or a confidence ranking derived from them, so if none is servable the
#: board has nothing legitimate to show.
_PICKS_BOARD_MARKETS = ("spread", "moneyline", "total")


def _market_basis_pick_cards(
    season: int, week: int, *, limit: int = 12, counts: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Picks whose edge is the MARKET's, not the model's.

    The model gate denies a claim it measured and lost. This is the OTHER claim
    on the same rows -- *this book's price is better than the market's own
    consensus* -- which uses no model and which the gate never measured. Until
    2026-08-29 the two shared a key, so the second was suppressed by the first
    and this page rendered a blackout over 90 sides that each carried a computed
    number.

    READS ARTIFACTS, COMPUTES NOTHING. `read_book_grid_artifact` is the
    web-side reader by its own docstring ("Cheap: one file, already bounded"),
    and `market_basis_edge` is arithmetic over fields the worker already wrote.
    No shard is pivoted here -- that is worker work and would not belong on a
    request path.

    Week -> dates via `_ncaaf_week_kickoff_dates`, which exists for exactly this
    mismatch: the quote log shards by DATE, this board is scoped by WEEK, and
    2026 week 1 runs 08-29 to 09-07, so a window guessed from the week number
    would miss most of the slate.
    """
    from syndicate.features.ncaaf.cards import _ncaaf_week_kickoff_dates
    from syndicate.features.shared.book_grid_artifact import read_book_grid_artifact
    from syndicate.features.shared.market_basis_edge import market_basis_edge

    dates = _ncaaf_week_kickoff_dates(season, week)
    best_by_bet: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    dates_read = dates_absent = sides_seen = 0

    for date_str in dates:
        payload = read_book_grid_artifact("ncaaf", date_str)
        if not isinstance(payload, dict):
            # ABSENT, not empty. The reader's own contract says so, and counting
            # it separately is what keeps "no grid published for this date" from
            # reading as "no edges on this date".
            dates_absent += 1
            continue
        dates_read += 1
        for row in payload.get("rows") or ():
            if not isinstance(row, dict):
                continue
            for side in row.get("sides") or ():
                block = (row.get("best") or {}).get(side)
                if not isinstance(block, dict):
                    continue
                sides_seen += 1
                verdict = market_basis_edge(
                    block, commence_time=row.get("commence_time")
                )
                if not verdict.servable or verdict.edge_pct is None:
                    continue
                key = (
                    str(row.get("event_id") or ""),
                    str(row.get("market") or ""),
                    str(row.get("segment") or "full"),
                    str(side),
                )
                current = best_by_bet.get(key)
                if current is None or verdict.edge_pct > current["edge_pct"]:
                    best_by_bet[key] = {
                        "edge_pct": verdict.edge_pct,
                        "anchor_books": verdict.anchor_books,
                        "label": verdict.as_payload()["label"],
                        "row": row,
                        "side": side,
                        "block": block,
                    }

    ordered = sorted(best_by_bet.values(), key=lambda item: item["edge_pct"], reverse=True)
    if counts is not None:
        counts.clear()
        counts.update(
            {
                "dates_in_week": len(dates),
                "dates_read": dates_read,
                "dates_absent": dates_absent,
                "sides_considered": sides_seen,
                "servable": len(ordered),
                # A cap that bites must announce it -- the same out-param idiom
                # `_collapse_results` uses for the gate counts above.
                "shown": min(len(ordered), limit),
                "withheld_by_cap": max(0, len(ordered) - limit),
            }
        )

    cards: list[dict[str, Any]] = []
    for item in ordered[:limit]:
        row = item["row"]
        block = item["block"]
        home_team = str(row.get("home_team") or "Home").strip()
        away_team = str(row.get("away_team") or "Away").strip()
        market = str(row.get("market") or "BET").strip().lower()
        provider = str(block.get("bookmaker") or "Book").strip() or "Book"
        side = str(item["side"])
        side_label = _side_label(side, home_team=home_team, away_team=away_team)
        line_text = _line_for_side(row.get("line"), side, market)
        cards.append(
            {
                "title": (
                    f"{away_team} at {home_team} {market.upper()} {side_label}"
                    + ("" if line_text == "-" else f" {line_text}")
                ),
                # Same `market` vocabulary `_collapse_results` uses, and for the
                # same reason: without it `home.py._is_game_level_rank_card_market`
                # returns False and these game bets flow into pregame_props()
                # mislabelled as player props.
                "market": (
                    "moneyline" if market == "h2h"
                    else "spread" if market == "spreads"
                    else "total" if market == "totals"
                    else "game bet"
                ),
                "eyebrow": provider,
                "badge": f"{item['edge_pct']:+.2f} vs consensus",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Best price", "value": format_moneyline(block.get("price"))},
                    {"label": "Consensus", "value": format_moneyline(
                        (row.get("consensus") or {}).get(side)
                    )},
                    {"label": "Books", "value": str(item["anchor_books"])},
                    {"label": "Line", "value": line_text},
                ],
                # THE SENTENCE THAT KEEPS THIS FROM BEING READ AS THE MODEL'S.
                # It names the basis, the anchor and what the number is not, on
                # the card itself rather than in a page-level footnote a reader
                # scrolling a list of cards never reaches.
                "summary": (
                    f"{provider} is quoting {format_moneyline(block.get('price'))} on "
                    f"{side_label}"
                    + ("" if line_text == "-" else f" {line_text}")
                    + f" where {item['anchor_books']} books average "
                    f"{format_moneyline((row.get('consensus') or {}).get(side))}. This is a "
                    "PRICE-SHOPPING edge, not a model opinion and not expected value: the "
                    "NCAAF model is gated and had no part in this."
                ),
                "list_items": [
                    item["label"],
                    f"Market: {market} · side: {side_label}"
                    + ("" if line_text == "-" else f" at {line_text}"),
                    f"Anchor: {item['anchor_books']}-book vigged consensus (no sharp book in the NCAAF feed)",
                    "The model's own edge is withheld on this game; see the panel below for why.",
                ],
            }
        )
    return cards


def _side_label(side: str, *, home_team: str, away_team: str) -> str:
    """`home`/`away` -> the team's name; `over`/`under` unchanged.

    A card headed "Memphis Tigers at UNLV Rebels H2H away" makes the reader do
    the mapping, and on a spread they will do it while looking at a line stated
    from the OTHER side. Name the team.
    """
    token = str(side or "").strip().lower()
    if token == "home":
        return home_team or "home"
    if token == "away":
        return away_team or "away"
    return token or "side"


def _line_for_side(line: Any, side: str, market: str = "") -> str:
    """The line as THIS side holds it.

    `book_grid._canonical_line` normalises every row's `line` to the away/over
    perspective on purpose, so a SPREAD row's stored 4.5 is the AWAY team's
    +4.5 and the home side of that same row is -4.5. Printing the stored number
    against the home side states the opposite bet -- the exact sign ambiguity
    `ncaaf/game_projections.py` refuses to guess at when it declines to give
    spreads a probability. Here the side IS known, so the sign can be resolved
    rather than guessed.

    **THE SIGN CONVENTION IS THE SPREAD'S ALONE**, and applying it everywhere is
    a bug this function shipped for one draft: a TOTAL of 50.5 rendered as
    "+50.5", which reads as a handicap rather than a points total, and the same
    flip on the under side would have printed "-50.5" -- a number no total has.
    Totals are unsigned and identical on both sides; only which side you take
    changes.
    """
    if line is None:
        return "-"
    try:
        value = float(line)
    except (TypeError, ValueError):
        return str(line)
    if str(market or "").strip().lower() not in {"spread", "spreads", "handicap"}:
        return f"{value:g}"
    if str(side or "").strip().lower() == "home":
        value = -value
    return f"{value:+g}"


def _suppressed_picks_context(
    *,
    season: int,
    selected_week: int,
    active_weeks: list[int],
    gate: dict[str, Any],
) -> dict[str, Any]:
    """The picks board with no MODEL pick to serve, saying so and saying why.

    Deliberately NOT an error or an empty board. A blank surface with no reason
    reads as a data outage, and the repair somebody reaches for is deleting the
    gate. The board keeps its navigation so projections stay reachable -- the
    model's opinion is still published on /ncaaf/cards, it is only the BET that
    is withheld.

    **AND IT IS NO LONGER NECESSARILY EMPTY (2026-08-29).** The model gate now
    speaks only for the model's basis, so this page serves MARKET-basis picks
    beside the notice. When there are none the page is exactly what it was; when
    there are some, the notice becomes a caveat on a board rather than the whole
    board. The two are never blended: the cards say what they rest on and the
    panel says what is withheld.
    """
    weeks = active_weeks or [1]
    resolved_week = _clamp_week(selected_week or (weeks[-1] if weeks else 1))
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    market_counts: dict[str, Any] = {}
    try:
        market_cards = _market_basis_pick_cards(season, resolved_week, counts=market_counts)
    except Exception:
        # A market-basis failure must NOT take down the page that explains the
        # model suppression. The notice below is the thing this surface has
        # always owed the reader; the cards are the addition.
        market_cards, market_counts = [], {"error": "market-basis pick build failed"}
    if market_counts.get("withheld_by_cap"):
        print(
            "NCAAF_MARKET_BASIS_PICKS_CAPPED "
            f"shown={market_counts.get('shown')} withheld={market_counts.get('withheld_by_cap')}",
            flush=True,
        )
    return {
        **build_rank_page_context(
            selected_date=_selected_date_token(resolved_week, season=season),
            route_path="/ncaaf/picks",
            intro_title="NCAAF Picks",
            intro_body=(
                "NCAAF MODEL picks are suppressed -- the model is measured as losing "
                "to the closing line, and the panel below says by how much. The cards "
                "here are a different claim: books that are quoting a better price "
                "than the rest of the market on the same bet. That is price shopping, "
                "not a model opinion and not expected value."
                if market_cards
                else
                "NCAAF model picks are currently suppressed, and no market-basis pick "
                "clears its bar this week either. Projections remain available on the "
                "cards board; what is withheld is the recommendation to bet them."
            ),
            aria_label="NCAAF picks board",
            source_path="syndicate/features/football/pick_gate.py",
            source_title="NCAAF pick serving gate",
            source_date_display=f"Week {resolved_week}",
            rank_cards=market_cards,
            using_sample_data=False,
            header_stats=[
                {"label": "Cards", "value": str(len(market_cards))},
                {"label": "Basis", "value": "market" if market_cards else "-"},
                {"label": "Model picks withheld", "value": str(len(gate["markets"]))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
            ],
            module_links=build_module_links(resolved_week, "Picks"),
            control_label="Week",
            control_type="number",
            control_name="week",
            control_value=str(resolved_week),
            prev_href=f"/ncaaf/picks?week={prev_week}",
            next_href=f"/ncaaf/picks?week={next_week}",
            empty_state={
                "eyebrow": "Picks suppressed",
                "title": gate["headline"],
                "body": (
                    "A pick asserts the model prices a market better than the "
                    "book does. For NCAAF that assertion has been measured "
                    "against realised results and it is false, so the picks are "
                    "withheld rather than served."
                ),
                "list_items": [reason["reason"] for reason in gate["reasons"]]
                + [gate["lift_condition"]],
            },
            warning_panel={
                "eyebrow": "Model vs market",
                "title": "Measured: the NCAAF margin model loses to the close",
                "body": (
                    "Prior-season 2024 SP+ scoring realised 2025 margins, 220 "
                    "games, closing spread on the same games as the benchmark: "
                    "model MAE 13.763 against a market 11.586. Paired dMAE "
                    "+2.176, SE 0.518, t=+4.20. Every rating scale from 6 to 24 "
                    "loses, so this is a property of the model rather than of a "
                    "tuning constant."
                ),
                "list_items": [reason["detail"] for reason in gate["reasons"]]
                + (
                    [
                        "The cards above are NOT affected by this measurement. They "
                        "rest on cross-book price dispersion and the model plays no "
                        "part in them -- see each card's own summary for its anchor.",
                    ]
                    if market_cards
                    else []
                ),
            },
        ),
        "week": resolved_week,
        "available_weeks": weeks,
        "season": season,
        "picks_gate": gate,
        # The instrument for this surface. `servable` vs `sides_considered` is
        # the rate that says whether an empty board is a working filter or a
        # missing artifact, and `dates_absent` separates the two -- a count with
        # no denominator cannot.
        "market_basis": market_counts,
    }


def build_smartsim_picks_page_context(selected_week: int) -> dict[str, Any]:
    # GATE FIRST, before any candidate path runs. This function has three
    # sources (runtime engine rows, standalone SmartSim2 projections, and the
    # summary-artifact fallback) and BOTH routes -- /ncaaf/picks and
    # /ncaaf/api/picks -- enter here. Gating the fallback alone would have been
    # inert, the same way the board cap lived in build_cards_page_context while
    # the route served build_smartsim_cards_page_context.
    season, active_weeks = _resolve_ncaaf_active_season_and_weeks()
    gate = board_notice("ncaaf", _PICKS_BOARD_MARKETS)
    if gate is not None:
        return _suppressed_picks_context(
            season=season,
            selected_week=selected_week,
            active_weeks=active_weeks,
            gate=gate,
        )
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
    gate_counts: dict[str, int] = {}
    cards = _collapse_results(summary, gate_counts=gate_counts)
    gate_notice = notice_for("ncaaf", gate_counts)
    using_sample_data = False

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    total_results = len(summary.get("results") or []) if isinstance(summary.get("results"), list) else 0
    empty_state = None
    if not cards and gate_notice:
        # Rows EXIST and were withheld. Saying "none available" here would be
        # false, would read as an outage, and is how a suppression gets
        # "fixed" by deleting it. State the reason and the numbers.
        empty_state = {
            "eyebrow": "Picks suppressed",
            "title": gate_notice["headline"],
            "body": (
                f"{total_results} stored NCAAF recommendation row"
                f"{'' if total_results == 1 else 's'} for Week {resolved_week} "
                "were withheld rather than served. A pick asserts the model "
                "prices a market better than the book does; for these markets "
                "that assertion has been measured and it is false."
            ),
            "list_items": [reason["reason"] for reason in gate_notice["reasons"]]
            + [gate_notice["lift_condition"]],
        }
    elif not cards:
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