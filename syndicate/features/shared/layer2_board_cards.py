"""L2-A row -> board card. The adapter that lets the board render L2-A rows.

**BUILT DARK ON PURPOSE (`#268`).** Nothing here changes what the board serves
until `SYNDICATE_BOARD_L2A_ENABLED` is turned on, and the release conditions in
`todo.md` gate that flag. This module exists so the wiring is reviewed, tested
and deployable *before* anyone decides to flip it.

WHY AN ADAPTER AT ALL, measured rather than assumed. The board template reads
**70 distinct fields** off a row. An L2-A row carries **18**. The overlap is
**9**. Pointing the template straight at L2-A rows would therefore blank most of
the card, which is why `#268` exists instead of a one-line data-source swap.

Of the 61 missing fields:

  * ~20 are pure mapping and are filled here (`matchup` <- `game.matchup`,
    `odds` <- `quote.price`, `pick` <- `side`, `game_id` <- `event_id`,
    `fair_price` <- `quote.fair_probability`, `board_score` <- `score`, ...)
  * **~40 have NO source on an L2-A row** -- headshots, `writeup`, `reasoning`,
    `summary`, live/sim projections, `movement`, every `settlement*` field,
    `quality`, `confidence`. Those are emitted as an EXPLICIT None.

**EXPLICIT None IS THE WHOLE DESIGN.** A missing key and a key that is
deliberately empty look identical on a rendered card and completely different in
review. `board_card_fields()` below enumerates the contract, the parity test
asserts every field appears, and so a field going missing fails a test instead
of turning up as a blank cell on the page -- which is precisely how "L2-A is the
board" came to be recorded in `todo.md` for a board that never read it.

PURE. No I/O, no artifact reads, no Flask. It runs worker-side inside the
shortlist build so the PERSISTED artifact is what the board displays -- a card
derived per request is recorded nowhere, and settlement needs a record of what
was recommended (`todo.md` mistake #3, already paid for once).
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared.opportunity_signals import american_price

# Every field the board template reads off a row, and how this adapter answers
# it. `None` means "no source on an L2-A row" -- a deliberate blank, not an
# oversight. Keep this list in sync with the template; the parity test derives
# the template's own list and fails if the two drift.
_UNSOURCED_FIELDS: tuple[str, ...] = (
    # player identity/imagery -- L2-A carries a name, nothing else
    "player_id",
    "player_team",
    "player_image",
    "headshot_url",
    "headshotUrl",
    # narrative -- produced by the cards/enrichment pipeline, not by ranking
    "writeup",
    "reasoning",
    "summary",
    "question",
    "detail",
    "context_label",
    "status_context",
    "status_display",
    "basketball_summary",
    # model/sim projections -- #263; present for MLB via model_edge_pct only
    "live_projection",
    "live_total",
    "sim_projection",
    "projected",
    "projected_sim",
    # line movement -- the quote log has it, the shortlist row does not
    "movement",
    "line_odds_movement",
    "price_improvement_pct",
    # settlement -- by definition absent on an unsettled recommendation
    "settlement",
    "settlement_result",
    "settlement_status",
    "result",
    "actual",
    # legacy-pool bookkeeping with no L2-A equivalent
    "quality",
    "confidence",
    "candidate_type",
    "adjusted_edge",
    "recommendation_id",
    "prediction_id",
    "market_data",
    "source_board_date",
    "type",
)


def _market_label(market: Any) -> str:
    text = str(market or "").strip().replace("_", " ")
    return text.title() if text else ""


def _side_team(row: Mapping[str, Any]) -> str:
    """The team the bet is ON, for a game-line row.

    Empty for props: a prop's `team` on the legacy card is the PLAYER's team,
    which an L2-A row does not carry, and guessing it from the side would be
    wrong half the time.
    """
    side = str(row.get("side") or "").strip().lower()
    if side == "home":
        return str(row.get("home_team") or "")
    if side == "away":
        return str(row.get("away_team") or "")
    return ""


def _matchup(row: Mapping[str, Any]) -> str:
    game = row.get("game") if isinstance(row.get("game"), Mapping) else None
    existing = str((game or {}).get("matchup") or "").strip()
    if existing:
        return existing
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    return f"{away} @ {home}" if away and home else ""


def board_card_fields() -> tuple[str, ...]:
    """Every field this adapter promises to emit.

    The parity test compares this against the fields the TEMPLATE reads, so a
    template that starts reading something new fails a test rather than
    rendering an empty cell.
    """
    return tuple(sorted({*_MAPPED_FIELDS, *_UNSOURCED_FIELDS}))


_MAPPED_FIELDS: tuple[str, ...] = (
    "sport",
    "sport_slug",
    "event_id",
    "game_id",
    "gamePk",
    "market",
    "market_label",
    "selection",
    "pick",
    "line",
    "odds",
    "odds_current",
    "fair_price",
    "ev_pct",
    "ev_current",
    "edge",
    "expected_value",
    "board_score",
    "board_score_components",
    "matchup",
    "event_matchup",
    "game_state",
    "is_live",
    "market_state",
    "board_lane",
    "player_name",
    "display_name",
    "name",
    "team",
    "team_name",
    "game_date",
    "last_updated",
    "updated_at",
    "quote",
)


def to_board_card(row: Mapping[str, Any], *, written_at: str | None = None) -> dict[str, Any]:
    """One L2-A row -> one board-card dict.

    Every field in `board_card_fields()` is present in the result. The ones with
    no L2-A source are present and None, deliberately -- see the module
    docstring.
    """
    game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    score = row.get("score") if isinstance(row.get("score"), Mapping) else {}

    event_id = row.get("event_id")
    price = quote.get("price")
    ev_pct = row.get("ev_pct")
    matchup = _matchup(row)
    player_name = str(row.get("player_name") or "").strip() or None
    state = str(game.get("state") or "").strip().lower() or None

    fair_probability = quote.get("fair_probability")
    fair_price = american_price(fair_probability) if fair_probability is not None else None

    card: dict[str, Any] = {field: None for field in _UNSOURCED_FIELDS}
    card.update(
        {
            "sport": row.get("sport"),
            "sport_slug": row.get("sport"),
            "event_id": event_id,
            # The legacy card keys off game_id/gamePk; L2-A's event_id is the
            # same identifier under a different name.
            "game_id": event_id,
            "gamePk": event_id,
            "market": row.get("market"),
            "market_label": _market_label(row.get("market")),
            "selection": row.get("side"),
            "pick": row.get("side"),
            "line": row.get("line"),
            "odds": price,
            "odds_current": price,
            "fair_price": fair_price,
            "ev_pct": ev_pct,
            "ev_current": ev_pct,
            "edge": ev_pct,
            "expected_value": ev_pct,
            "board_score": score.get("score"),
            "board_score_components": dict(score) if score else None,
            "matchup": matchup,
            "event_matchup": matchup,
            "game_state": state,
            # Absent state must not read as "not live" -- for nine of ten soccer
            # leagues state is permanently pregame, so a False here would be a
            # claim we cannot support. None means unknown.
            "is_live": (state == "live") if state else None,
            "market_state": row.get("market_state"),
            "board_lane": row.get("board_lane"),
            "player_name": player_name,
            # A prop card titles on the player; a game-line card on the matchup.
            "display_name": player_name or matchup or None,
            "name": player_name or matchup or None,
            "team": _side_team(row) or None,
            "team_name": _side_team(row) or None,
            "game_date": row.get("commence_time"),
            "last_updated": written_at,
            "updated_at": written_at,
            # Carried whole: the board shows price provenance (bookmaker, book
            # count, freshness) and re-deriving it here would let the card and
            # the row disagree.
            "quote": dict(quote) if quote else None,
        }
    )
    return card


def to_board_cards(rows: Any, *, written_at: str | None = None) -> list[dict[str, Any]]:
    return [
        to_board_card(row, written_at=written_at)
        for row in (rows or [])
        if isinstance(row, Mapping)
    ]


__all__ = ["board_card_fields", "to_board_card", "to_board_cards"]
