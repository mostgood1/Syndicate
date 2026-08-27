"""Kalshi quotes must carry a price, and a threshold market must offer both legs.

Two defects, both live, both invisible for the same reason: `quotes` was
non-empty so `status` read `ok`.

1. The adapter read `row.get("yes_bid") or row.get("last_price")`. NEITHER is
   persisted -- `kalshi_odds_refresh._LEAN_MARKET_FIELDS` is the whole schema
   that survives `_lean_market`, and it carries `yes_probability` /
   `yes_ask_dollars` instead. So every Kalshi quote was published with
   `probability=None` and `american=None`.

2. Kalshi titles every total as an OVER, so only that leg was emitted, while
   the board asked for `under` rows the venue does list -- as the NO leg of the
   same contract.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_quote_adapters import _kalshi_leg_probability


# Exactly the fields `_lean_market` persists, and nothing else -- a fixture
# carrying `yes_bid` would test a shape production never sees.
LEAN_ROW = {
    "ticker": "KXNCAAFTOTAL-26AUG29-T52.5",
    "event_ticker": "KXNCAAFTOTAL-26AUG29",
    "series": "KXNCAAFTOTAL",
    "title": "Full Game: over 52.5 points scored?",
    "yes_sub_title": "Over 52.5",
    "no_sub_title": "Under 52.5",
    "status": "active",
    "yes_ask_dollars": 0.58,
    "no_ask_dollars": 0.45,
    "yes_american": -138,
    "no_american": 122,
    "yes_probability": 0.58,
    "no_probability": 0.45,
    "close_time": "2026-08-29T23:00:00Z",
}


def test_the_yes_leg_is_priced_from_a_field_that_actually_exists():
    """THE OFF/ON TEST. `yes_bid` is absent from every persisted row, so the
    old read returned None here."""
    assert "yes_bid" not in LEAN_ROW
    assert "last_price" not in LEAN_ROW

    assert _kalshi_leg_probability(LEAN_ROW, "yes") == 0.58


def test_the_no_leg_is_priced_from_its_own_quote():
    assert _kalshi_leg_probability(LEAN_ROW, "no") == 0.45


def test_the_two_legs_do_not_sum_to_one_and_must_not_be_derived():
    """`kalshi_board_join`: "they do not sum to 1 (the gap is the spread) ...
    deriving the Under from the Over's price would erase the spread and invent
    an edge that is not there." This pins that the fixture is realistic and that
    we read both independently."""
    yes = _kalshi_leg_probability(LEAN_ROW, "yes")
    no = _kalshi_leg_probability(LEAN_ROW, "no")

    assert yes + no != pytest.approx(1.0)
    assert no != pytest.approx(1.0 - yes)


def test_ask_dollars_is_the_fallback_when_probability_is_absent():
    row = dict(LEAN_ROW)
    row["yes_probability"] = None

    assert _kalshi_leg_probability(row, "yes") == 0.58


def test_cents_are_still_guarded():
    """Kalshi has quoted CENTS on some routes; 54 read as a probability is the
    100x error its first live run found."""
    row = dict(LEAN_ROW)
    row["yes_probability"] = 54

    assert _kalshi_leg_probability(row, "yes") == pytest.approx(0.54)


@pytest.mark.parametrize("degenerate", [0, 0.0, 1, 1.0, -0.2])
def test_a_degenerate_price_is_refused_not_published_as_certainty(degenerate):
    row = dict(LEAN_ROW)
    row["yes_probability"] = degenerate
    row["yes_ask_dollars"] = degenerate

    assert _kalshi_leg_probability(row, "yes") is None


def test_a_missing_leg_returns_none_rather_than_zero():
    row = dict(LEAN_ROW)
    row["no_probability"] = None
    row["no_ask_dollars"] = None

    assert _kalshi_leg_probability(row, "no") is None


def test_mirror_side_map_covers_both_directions_and_nothing_else():
    """h2h's NO leg is "the other team wins" -- it needs the opponent's name to
    key and is refused rather than guessed. spreads are refused outright."""
    from syndicate.features.shared.venue_quote_adapters import _MIRROR_SIDE

    assert _MIRROR_SIDE == {"over": "under", "under": "over"}
    assert _MIRROR_SIDE.get("yes") is None
    assert _MIRROR_SIDE.get("home") is None


# ---------------------------------------------------------------------------
# End to end through the real adapter and the real classifier, because the unit
# tests above prove the pieces and not the behaviour that was actually missing.
# ---------------------------------------------------------------------------


def _totals_payload():
    return {
        "fetched_at": 1787804283.0,
        "series": {
            "KXNCAAFTOTAL": {
                "markets": [
                    dict(LEAN_ROW, title="Full Game: over 52.5 points scored?"),
                ]
            }
        },
    }


def test_a_totals_market_publishes_BOTH_legs_each_at_its_own_price(monkeypatch):
    """THE BEHAVIOUR THAT WAS MISSING. Kalshi titles every total as an OVER, so
    only that leg reached the board while every `under` row it carried went
    unmatched against a venue that does list the bet."""
    from syndicate.features.shared import venue_quote_adapters as mod

    monkeypatch.setattr(mod, "_artifact", lambda parts: (_totals_payload(), 1787804283.0))

    outcome = mod.kalshi_outcome("ncaaf", "2026-08-29")

    by_key = {q.key: q for q in outcome.quotes}
    assert "ncaaf|totals|over|52.5" in by_key, sorted(by_key)
    assert "ncaaf|totals|under|52.5" in by_key, sorted(by_key)

    over, under = by_key["ncaaf|totals|over|52.5"], by_key["ncaaf|totals|under|52.5"]

    # Each from its OWN quoted leg -- not 1 - p, which would erase the spread.
    assert over.probability == 0.58
    assert under.probability == 0.45
    assert over.american is not None and under.american is not None


def test_every_quote_carries_a_price(monkeypatch):
    """The silent defect: `yes_bid`/`last_price` are not persisted, so every
    Kalshi quote was published with probability None and american None while
    `status` read `ok` because `quotes` was non-empty."""
    from syndicate.features.shared import venue_quote_adapters as mod

    monkeypatch.setattr(mod, "_artifact", lambda parts: (_totals_payload(), 1787804283.0))

    outcome = mod.kalshi_outcome("ncaaf", "2026-08-29")

    assert outcome.quotes, "fixture produced no quotes at all"
    assert all(q.probability is not None for q in outcome.quotes)
    assert all(q.american is not None for q in outcome.quotes)
