"""#298/#300 -- a row with no game state must FAIL the floor, not skip it.

`game_state_of` resolves the ambiguous rest to `pregame`, so a row nothing
matched was indistinguishable from a row confirmed not to have started. Since
`build_layer2_rows` sets `game_state`/`is_live` only inside `if game:`, an
unmatched team meant the row was exempted from the staleness rules rather than
failing them -- the guard cannot reject what it cannot see.

Measured on production 2026-08-09 15:29Z: 12 of 200 displayed rows (6.0%, all
soccer, all one match) carried no game state, and every one was for a match
already 48 minutes old -- four of them `player_first_goal_scorer`, a market a
single goal settles or reprices violently.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared.opportunity_gate import (
    LANE_OPPORTUNITY,
    LANE_WATCHLIST,
    evaluate,
    has_game_state,
)

NOW = datetime(2026, 8, 9, 15, 29, tzinfo=timezone.utc)
STARTED = (NOW - timedelta(minutes=48)).isoformat().replace("+00:00", "Z")
FAR_OUT = (NOW + timedelta(days=16)).isoformat().replace("+00:00", "Z")


def _row(**overrides):
    row = {
        "sport": "soccer",
        "event_id": "evt-1",
        "kind": "game",
        "market": "h2h",
        "home_team": "FC Twente Enschede",
        "away_team": "Heerenveen",
        "side": "home",
        "commence_time": STARTED,
    }
    row.update(overrides)
    return row


_QUOTE = {"price": -110, "fair_probability": 0.52, "fair_method": "two_sided", "book_age_seconds": 30.0}


def test_unmatched_row_past_its_kickoff_does_not_rank():
    """The measured case: 48 minutes after kickoff, nothing confirming state."""
    verdict = evaluate(_row(), _QUOTE, now=NOW)
    assert verdict.lane == LANE_WATCHLIST
    assert "no_game_state" in verdict.reasons, (
        "the reason is the point -- without it, 'the guard dropped it' and 'the "
        "guard never saw it' are the same zero (#306)"
    )
    assert verdict.market_state == "unknown", "must not claim pregame it cannot evidence"


def test_a_far_out_fixture_with_no_chip_is_STILL_an_opportunity():
    """The population this must not break. 146 of 230 board rows were Serie A
    steam for fixtures 16+ days out, which have no chip yet -- for those,
    resolving to `pregame` is correct rather than a default, because they
    genuinely have not started."""
    verdict = evaluate(_row(commence_time=FAR_OUT), _QUOTE, now=NOW)
    assert verdict.lane == LANE_OPPORTUNITY
    assert "no_game_state" not in verdict.reasons


def test_a_confirmed_pregame_row_is_unaffected():
    verdict = evaluate(_row(game_state="pregame", game={"state": "pregame"}), _QUOTE, now=NOW)
    assert "no_game_state" not in verdict.reasons
    assert verdict.market_state == "pregame"


def test_is_live_true_counts_as_affirmative():
    verdict = evaluate(_row(is_live=True, game={"state": "live"}), _QUOTE, now=NOW)
    assert "no_game_state" not in verdict.reasons


def test_is_live_false_alone_is_not_affirmative():
    """`False` is the same silence as absent: nothing distinguishes 'told us it
    is not live' from 'never set', so it must not satisfy the check."""
    assert has_game_state(_row(is_live=False)) is False
    assert "no_game_state" in evaluate(_row(is_live=False), _QUOTE, now=NOW).reasons


def test_a_game_block_alone_is_affirmative():
    """The board attaches `game` when a chip matched, even if the state string
    is one this sport does not spell in our vocabulary."""
    assert has_game_state(_row(game={"state": "1H"})) is True


def test_an_unreadable_kickoff_does_not_trigger_a_demotion():
    """The conservative default. This rule gates a demotion, so an unparseable
    or missing clock must not be treated as evidence a game is under way."""
    for bad in ("", "not-a-date", None):
        verdict = evaluate(_row(commence_time=bad), _QUOTE, now=NOW)
        assert "no_game_state" not in verdict.reasons, f"commence_time={bad!r}"


def test_the_rule_is_on_by_default():
    """An off-by-default guard is not a guard. The defect it prevents is live
    and measured, so absent must mean enabled."""
    import os

    assert "SYNDICATE_GATE_DEMOTE_UNKNOWN_GAME_STATE" not in os.environ
    assert "no_game_state" in evaluate(_row(), _QUOTE, now=NOW).reasons


def test_the_off_switch_disables_the_demotion(monkeypatch):
    """Needed because this is the one time-dependent rule, and because a rule
    that can drop production rows should be reversible without a deploy."""
    monkeypatch.setenv("SYNDICATE_GATE_DEMOTE_UNKNOWN_GAME_STATE", "0")
    verdict = evaluate(_row(), _QUOTE, now=NOW)
    assert "no_game_state" not in verdict.reasons
    assert verdict.lane == LANE_OPPORTUNITY


def test_final_still_wins_over_the_unknown_check():
    """Ordering guard: a settled market must stay dead, not become watchlist."""
    verdict = evaluate(_row(game_state="final"), _QUOTE, now=NOW)
    assert "no_game_state" not in verdict.reasons
    assert verdict.market_state == "final"
