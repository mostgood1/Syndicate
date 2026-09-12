"""#245: the single board-eligibility gate.

Every case here is a defect that actually reached production during #235-#244,
re-stated as a rule in one place. If a future symptom needs a new guard, it
belongs in `evaluate` and in this file -- not in a producer, a template, or a
second copy in JavaScript.
"""

from __future__ import annotations

from syndicate.features.shared.opportunity_gate import (
    LANE_DEAD,
    LANE_OPPORTUNITY,
    LANE_REJECTED,
    LANE_WATCHLIST,
    annotate,
    evaluate,
    game_state_of,
)


def _quote(**overrides):
    quote = {"price": -110, "book_age_seconds": 60.0, "fair_probability": 0.5}
    quote.update(overrides)
    return quote


def test_a_row_with_no_identity_is_rejected_not_left_looking_unpriced():
    verdict = evaluate({"market": "h2h"}, _quote())
    assert verdict.lane == LANE_REJECTED
    assert "no_identity" in verdict.reasons


def test_a_fixture_with_no_market_posted_is_watchlist_not_a_defect():
    # 146 of 230 board rows were Serie A steam for fixtures 16+ days out.
    verdict = evaluate({"player_name": "Carles Gil", "is_live": False}, None)
    assert verdict.lane == LANE_WATCHLIST
    assert "no_market_posted" in verdict.reasons


def test_a_stale_live_market_is_dead():
    # Luis Arraez / J.T. Realmuto: is_live=True, book_age 30,556s (8.5 hours).
    verdict = evaluate(
        {"player_name": "Luis Arraez", "is_live": True, "game_state": "live"},
        _quote(book_age_seconds=30556.0),
    )
    assert verdict.lane == LANE_DEAD
    assert "live_market_stale" in verdict.reasons


def test_a_fresh_live_market_is_an_opportunity():
    verdict = evaluate(
        {"player_name": "Luke Keaschall", "is_live": True, "game_state": "live"},
        _quote(book_age_seconds=134.0),
    )
    assert verdict.lane == LANE_OPPORTUNITY


def test_a_stale_pregame_price_is_not_dead():
    # Books post early and leave numbers alone for hours before first pitch.
    verdict = evaluate(
        {"player_name": "Someone", "is_live": True, "game_state": "scheduled"},
        _quote(book_age_seconds=30556.0),
    )
    assert verdict.lane == LANE_OPPORTUNITY
    assert verdict.market_state == "pregame"


def test_a_live_game_with_no_book_clock_is_dead():
    verdict = evaluate(
        {"player_name": "Someone", "is_live": True, "game_state": "In Progress"},
        _quote(book_age_seconds=None),
    )
    assert verdict.lane == LANE_DEAD
    assert "live_no_book_clock" in verdict.reasons


def test_a_final_game_is_dead_whatever_its_price_looks_like():
    verdict = evaluate(
        {"player_name": "Someone", "game_state": "Final", "is_live": False},
        _quote(book_age_seconds=10.0),
    )
    assert verdict.lane == LANE_DEAD
    assert "game_final" in verdict.reasons


def test_unnormalised_game_state_text_is_handled():
    # Production carries all of these for "in progress".
    for state in ("live", "In Progress", "3:39", "66-65 | 3:39 - 4th"):
        row = {"player_name": "X", "is_live": True, "game_state": state}
        assert game_state_of(row) == "live", state
        assert evaluate(row, _quote(book_age_seconds=99999.0)).lane == LANE_DEAD


def test_a_priced_but_undevigable_market_is_still_an_opportunity():
    # Anytime goal scorer is quoted one-sided, so no fair price exists. The row
    # is still bettable and must not be hidden -- but the reason is recorded so
    # the board can explain the empty Fair cell instead of showing a blank.
    verdict = evaluate(
        {"player_name": "Carles Gil", "is_live": False},
        {"price": 240, "book_age_seconds": 60.0},
    )
    assert verdict.lane == LANE_OPPORTUNITY
    assert "fair_unavailable" in verdict.reasons
    assert verdict.fair_method is None


def test_every_row_gets_a_lane_including_junk():
    # Totality is the point: a board that hides its rejects is harder to debug
    # than one that shows junk.
    for row in ({}, {"player_name": ""}, {"is_live": True}):
        assert evaluate(row, None).lane in {LANE_OPPORTUNITY, LANE_WATCHLIST, LANE_DEAD, LANE_REJECTED}


def test_annotate_stamps_the_row_and_never_raises():
    row = {"player_name": "X", "is_live": True, "game_state": "live", "quote": _quote()}
    annotate(row)
    assert row["board_lane"] == LANE_OPPORTUNITY
    assert row["gate"]["market_state"] == "live"
    assert isinstance(row["gate"]["reasons"], list)
    # Garbage in must not raise -- a gate that can break the board is worse
    # than no gate.
    broken = {"player_name": "X", "quote": "not-a-mapping"}
    annotate(broken)
    assert broken["board_lane"] in {LANE_OPPORTUNITY, LANE_WATCHLIST, LANE_DEAD, LANE_REJECTED}


_LIVE_ROW = {"event_id": "evt", "market": "spreads", "is_live": True, "game_state": "live"}


def test_a_live_quote_we_have_not_looked_at_recently_is_dead_on_a_fresh_book_clock():
    # 2026-09-12, WF @ PUR Q4 10:32: book_age 618s cleared the 900s book
    # ceiling while the price had not been observed for 1,013s, and it ranked
    # as a +4.8% EV opportunity on the live board.
    verdict = evaluate(dict(_LIVE_ROW), _quote(book_age_seconds=618.0, quote_seen_age_seconds=1013.0))
    assert verdict.lane == LANE_DEAD
    assert verdict.reasons == ("live_quote_unobserved",)


def test_a_live_quote_observed_recently_is_still_an_opportunity():
    # MLB's live rows on the same build: seen age p50 64s, 12 of 12 under 120s.
    verdict = evaluate(dict(_LIVE_ROW), _quote(book_age_seconds=64.0, quote_seen_age_seconds=64.0))
    assert verdict.lane == LANE_OPPORTUNITY


def test_a_live_row_with_no_observation_clock_is_judged_on_its_book_clock():
    # A recorded move is an observation, so the book clock bounds the capture
    # clock from above when the latter is absent: fresh passes, old does not.
    assert evaluate(dict(_LIVE_ROW), _quote(book_age_seconds=134.0)).lane == LANE_OPPORTUNITY
    stale = evaluate(dict(_LIVE_ROW), _quote(book_age_seconds=600.0))
    assert stale.lane == LANE_DEAD
    assert stale.reasons == ("live_quote_unobserved",)


def test_the_book_ceiling_still_names_itself_before_the_observation_ceiling():
    verdict = evaluate(dict(_LIVE_ROW), _quote(book_age_seconds=30556.0, quote_seen_age_seconds=30556.0))
    assert verdict.reasons == ("live_market_stale",)


def test_a_pregame_row_is_never_judged_on_the_observation_clock():
    verdict = evaluate(
        {"event_id": "evt", "market": "totals", "is_live": False, "game_state": "scheduled"},
        _quote(book_age_seconds=60.0, quote_seen_age_seconds=50_000.0),
    )
    assert verdict.lane == LANE_OPPORTUNITY


def test_the_observation_ceiling_moves_without_a_deploy_but_cannot_be_typoed_off(monkeypatch):
    quote = _quote(book_age_seconds=60.0, quote_seen_age_seconds=600.0)
    monkeypatch.setenv("SYNDICATE_GATE_LIVE_MAX_OBSERVED_AGE_SECONDS", "900")
    assert evaluate(dict(_LIVE_ROW), quote).lane == LANE_OPPORTUNITY
    for typo in ("0", "-5", "off", "abc", "nan"):
        monkeypatch.setenv("SYNDICATE_GATE_LIVE_MAX_OBSERVED_AGE_SECONDS", typo)
        assert evaluate(dict(_LIVE_ROW), quote).lane == LANE_DEAD, typo
