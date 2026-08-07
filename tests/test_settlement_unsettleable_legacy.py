"""#260 -- separate records that CANNOT settle from records that FAILED to.

Measured on the real evaluation ledger 2026-08-07: 487 of 1,384 records (35%)
carry a market identity that cannot resolve.

    360  market = "betting card"   a SURFACE name that leaked into the market
                                   field on WNBA pregame props. Last written
                                   2026-07-22.
    127  market = ""               Last written 2026-08-01.

Both are PRE-FIX debris -- every record since carries a real market, so the
producer is already fixed. But left inside `unmatched` they depress the settled
rate permanently and make working settlement look broken, which is the
count-without-a-denominator error this codebase has paid for repeatedly.

They are classified, never deleted. Real history, just not settleable history.
"""

from __future__ import annotations

from syndicate.features.shared.evaluation_settlement import _is_unsettleable_legacy_record


def _record(market, *, nested=False):
    if nested:
        return {"recommendation": {"market": market}}
    return {"market": market}


def test_an_empty_market_is_unsettleable():
    for value in ("", "   ", None):
        assert _is_unsettleable_legacy_record(_record(value)) is True
        assert _is_unsettleable_legacy_record(_record(value, nested=True)) is True


def test_a_surface_name_in_the_market_field_is_unsettleable():
    # The exact shape found on 360 real records.
    assert _is_unsettleable_legacy_record(_record("betting card")) is True
    assert _is_unsettleable_legacy_record(_record("Betting Card")) is True
    assert _is_unsettleable_legacy_record(_record("betting card", nested=True)) is True


def test_a_real_market_is_settleable():
    for market in ("pitcher outs", "outs", "batter_total_bases", "h2h", "moneyline", "strikeouts"):
        assert _is_unsettleable_legacy_record(_record(market)) is False


def test_an_UNRECOGNISED_market_is_still_settleable():
    """Deliberately conservative, and this is the case that keeps it honest.

    An unknown market is not legacy debris -- it may simply be a market we have
    no mapping for yet, and #247's whole point is that an unknown market must
    not be treated as a failure. Only ABSENT, or a known non-market label,
    qualifies. Getting this wrong would silently shrink the denominator and
    flatter the settled rate, which is the exact failure mode #260 exists to
    prevent.
    """
    assert _is_unsettleable_legacy_record(_record("some_brand_new_market_2027")) is False
    assert _is_unsettleable_legacy_record(_record("player_quadruple_double")) is False


def test_the_nested_recommendation_market_is_read():
    # Real ledger records carry the market inside `recommendation`, not at the
    # top level -- the top-level field is absent on every one of the 1,384.
    assert _is_unsettleable_legacy_record({"recommendation": {"market": "pitcher outs"}}) is False
    assert _is_unsettleable_legacy_record({"recommendation": {"market": "betting card"}}) is True


def test_a_market_containing_a_non_market_word_is_not_matched_by_accident():
    # Matched exactly, not by substring: a real market that happens to contain
    # one of these words must not be classified as debris.
    assert _is_unsettleable_legacy_record(_record("player props over")) is False
    assert _is_unsettleable_legacy_record(_record("betting cards made")) is False
