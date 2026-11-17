"""The games rail's live lines, between whole-board polls (todo #803, lane live-rail-fast-poll).

WHY. The rail reads its live game-line rows off the board, and the page re-fetches the whole board every 60 s
(~5-6 MB compressed). A live price reaches the board every ~90 s now (the live-first book-grid round,
`8553a38cc`), so the 60 s poll added ~30 s on average, up to 60 s, before the rail showed it -- and the user's
complaint was "by the time I see the edge its already gone".

WHAT. Today's live GAME-LINE rows from the book-grid in-play overlay, built exactly as the board builds them
(`pipeline.intelligence_state._merge_inplay_overlay` + `_layer2_fallback_recommendations` + the board contract),
trimmed to the fields the rail reads. Small enough to poll every ~15 s. The page swaps these rows in by the
server merge's own identity (game, market, segment, player -- `inplay_overlay_identity`), and only for identities
the board already shows; anything new waits for the next whole-board poll.

WEB-SAFE: reads the worker's overlay artifacts and the scoreboard the board path already reads. No simulation,
no grid build. Never raises: a failure returns no rows and the reason, and the rail keeps the board's rows.

Off switch: SYNDICATE_LIVE_RAIL_FAST_POLL=off -> `enabled: false`, and the page stops polling.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping

FLAG = "SYNDICATE_LIVE_RAIL_FAST_POLL"

# What the rail reads off a row (`intelligence.html`, LIVE RAIL LINES + gameKey / displayMatchup), and nothing else.
ROW_FIELDS = (
    "kind", "candidate_type", "market_state", "is_live", "lane", "market", "market_type", "segment",
    "segment_label", "line", "side", "odds", "live_model_probability", "live_total", "live_total_basis",
    "live_total_sim", "model_edge_pct", "live_aware",
    "book_age_seconds", "price_grid_generated_at", "team", "display_name", "home_key", "away_key", "home_team",
    "away_team", "matchup", "sport", "sport_slug", "event_id", "game_id", "gamePk", "player_name",
    "game_date", "commence_time", "source", "source_board_date",
)
QUOTE_FIELDS = ("fair_probability", "fair_consensus_prob", "books_quoting", "book_age_seconds", "bookmaker",
                "quote_seen_age_seconds")


def live_rail_fast_poll_enabled(env: Mapping[str, str] | None = None) -> bool:
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_live_game_row(card: Mapping[str, Any]) -> bool:
    if str(card.get("kind") or card.get("candidate_type") or "").strip().lower() != "game":
        return False
    return str(card.get("market_state") or "").strip().lower() == "live" or card.get("is_live") is True


def trim_row(card: Mapping[str, Any]) -> dict[str, Any]:
    row = {key: card[key] for key in ROW_FIELDS if key in card}
    quote = card.get("quote")
    if isinstance(quote, Mapping):
        row["quote"] = {key: quote[key] for key in QUOTE_FIELDS if key in quote}
    return row


def board_cards_from_overlay(date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """This date's in-play overlay GAME cards, through the same per-card steps the board path runs
    (`_merge_inplay_overlay`) and the same board contract.

    NOT the board path's scoreboard restate + decided-market prune (`_refresh_layer2_live_state`,
    `_prune_decided_layer2_cards`), deliberately. Measured on the fleet 2026-11-14: the restate is 4.5 s when its
    30 s scoreboard cache is cold (a gunicorn worker blocked that long, every other 15 s poll), against 30-50 ms
    for the whole endpoint warm. It is not needed here: every overlay game card already carries
    `market_state: live` (163 of 163, 22:5xZ), the rail decides a game's liveness and a settled interval from the
    scoreboard chip, and the page only swaps in rows for identities the board already shows.
    """
    from pipeline.intelligence_state import (
        _backfill_layer2_board_columns,
        _normalize_card_edge_units,
        _promote_board_contract_cards,
    )
    from syndicate.features.intelligence_board import build_intelligence_board_contract
    from syndicate.features.shared.book_grid_artifact import inplay_overlay_cards
    from syndicate.features.shared.intelligence_contracts import resolve_candidate_game_date

    overlay, report = inplay_overlay_cards(date_str)
    cards: list[dict[str, Any]] = []
    for card in overlay:
        if str(card.get("kind") or card.get("candidate_type") or "").strip().lower() != "game":
            continue
        tagged = dict(card)
        tagged["game_date"] = resolve_candidate_game_date(tagged, fallback=date_str)
        tagged["source_board_date"] = date_str
        tagged.setdefault("sport", tagged.get("sport_slug"))
        _normalize_card_edge_units(tagged)
        _backfill_layer2_board_columns(tagged)
        cards.append(tagged)
    if not cards:
        return [], report
    contract = build_intelligence_board_contract({"recommendations": cards})
    promoted = _promote_board_contract_cards({"board_contract": contract})
    return [dict(item) for item in promoted.get("top_opportunities") or [] if isinstance(item, Mapping)], report


def live_rail_payload(date_str: str, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The endpoint's body. Never raises."""
    started = time.perf_counter()
    body: dict[str, Any] = {
        "ok": True,
        "enabled": live_rail_fast_poll_enabled(env),
        "date": date_str,
        "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": [],
    }
    if not body["enabled"]:
        return body
    try:
        cards, report = board_cards_from_overlay(date_str)
        body["rows"] = [trim_row(card) for card in cards if _is_live_game_row(card)]
        body["newest_written_at"] = report.get("newest_written_at")
        body["sports"] = report.get("sports")
    except Exception as exc:  # noqa: BLE001 -- the rail keeps the board's rows
        body["ok"] = False
        body["error"] = type(exc).__name__
    body["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return body
