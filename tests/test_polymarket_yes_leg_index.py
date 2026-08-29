"""The YES-leg derivation: `#595` step 3's evidence half.

`polymarket_us_orders` refuses every team side today because the venue's YES
leg is measurably NOT `outcomes[0]` (wrong on 3 of 8 settled moneylines, one
full-stake loss on a bet whose team WON). The venue does state the answer in
`marketSides[].long`; this module derives it and persists it so the order
module has a NAME rule available to consume.

The anchor cases below are the three real NFL moneylines read live on
2026-08-28 and recorded in `.syndicate/state.md`, whose `long_index` came back
**0, 0, 1**. The varying one is what makes this a rule rather than a
coincidence, so it is asserted explicitly.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.polymarket_us_markets import (
    YES_LEG_INDEX_FIELD,
    YES_LEG_REASON_FIELD,
    _slate_row_for_storage,
    yes_leg_index_from_market,
)


def _market(outcomes, sides, **extra):
    return {"outcomes": outcomes, "marketSides": sides, **extra}


def test_the_three_real_markets_reproduce_long_index_0_0_1():
    """The measurement this rule rests on, replayed.

    If a future edit made the derivation return the `marketSides` position
    instead of the `outcomes` position, `hou-car` is the row that catches it.
    """
    was_bal = _market(
        ["Commanders", "Ravens"],
        [{"description": "Commanders", "long": True}, {"description": "Ravens", "long": False}],
    )
    atl_mia = _market(
        ["Falcons", "Dolphins"],
        [{"description": "Falcons", "long": True}, {"description": "Dolphins", "long": False}],
    )
    hou_car = _market(
        ["Panthers", "Texans"],
        [{"description": "Panthers", "long": False}, {"description": "Texans", "long": True}],
    )
    assert yes_leg_index_from_market(was_bal) == (0, None)
    assert yes_leg_index_from_market(atl_mia) == (0, None)
    assert yes_leg_index_from_market(hou_car) == (1, None)


def test_index_comes_from_outcomes_not_from_the_market_sides_position():
    """The bug this function exists to avoid, one array over.

    `marketSides` lists the long side FIRST while `outcomes` lists it SECOND.
    Reading the `marketSides` position gives 0; the right answer is 1. That is
    the same positional assumption as `outcomes[0] == YES`, which cost $5.871
    on a bet we won.
    """
    row = _market(
        ["Panthers", "Texans"],
        [{"description": "Texans", "long": True}, {"description": "Panthers", "long": False}],
    )
    index, reason = yes_leg_index_from_market(row)
    assert reason is None
    assert index == 1, "index must be Texans' position in `outcomes`, not in `marketSides`"


def test_outcomes_arriving_as_a_json_string_still_resolve():
    """They DO arrive as strings on the wire -- a 2026-08-28 probe printed
    `long_index=None` on all three samples for exactly this reason."""
    row = _market(
        '["Panthers", "Texans"]',
        [{"team": {"name": "Texans"}, "long": True}, {"team": {"name": "Panthers"}, "long": False}],
    )
    assert yes_leg_index_from_market(row) == (1, None)


def test_team_name_is_used_when_description_is_absent():
    row = _market(["Commanders", "Ravens"], [{"team": {"name": "Ravens"}, "long": True}])
    assert yes_leg_index_from_market(row) == (1, None)


@pytest.mark.parametrize(
    "row, reason",
    [
        (_market(["A", "B"], None), "no_market_sides"),
        (_market(["A", "B"], "not json"), "market_sides_unreadable"),
        (_market(["A", "B"], []), "market_sides_unreadable"),
        (_market(["A", "B"], [{"description": "A", "long": False}]), "no_side_marked_long"),
        (
            _market(["A", "B"], [{"description": "A", "long": True}, {"description": "B", "long": True}]),
            "two_sides_marked_long",
        ),
        (_market(["A", "B"], [{"long": True}]), "long_side_has_no_name"),
        (_market(["A", "B"], [{"description": "Zebra", "long": True}]), "long_side_name_not_in_outcomes"),
        (_market(["A", "A"], [{"description": "A", "long": True}]), "long_side_name_matches_both_outcomes"),
        (_market(["A", "B", "C"], [{"description": "A", "long": True}]), "outcomes_unreadable"),
    ],
)
def test_every_ambiguity_refuses_by_its_own_name(row, reason):
    """No ambiguity resolves to an index, and each says which way it failed.

    The distinction matters operationally: `no_market_sides` means the venue
    never states a side for this family, while `long_side_name_not_in_outcomes`
    means our name matching is broken. Collapsing them to one reason -- or to a
    permissive default -- is how a failed join becomes a relaxed rule.
    """
    index, got = yes_leg_index_from_market(row)
    assert index is None
    assert got == reason


def test_two_long_sides_never_resolves_to_the_first():
    """`long` is not the yes/no axis on such a market, so the rule is void.

    Taking `matches[0]` here would be a coin flip wearing a rule's clothes --
    and it would look correct half the time, which is exactly how the
    `outcomes[0]` assumption survived as long as it did.
    """
    row = _market(
        ["Texans", "Panthers"],
        [{"description": "Texans", "long": True}, {"description": "Panthers", "long": True}],
    )
    assert yes_leg_index_from_market(row) == (None, "two_sides_marked_long")


def test_storage_row_carries_the_index_and_not_the_market_sides_blob():
    """The byte budget is the reason: the trimmed slate is already 4.9MB of an
    8MB keyvalue ceiling, and `marketSides` is two nested objects per row."""
    row = {
        "slug": "aec-nfl-hou-car-2026-08-29",
        "outcomes": ["Panthers", "Texans"],
        "outcomePrices": ["0.49", "0.51"],
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
        "marketSides": [
            {"description": "Panthers", "long": False, "price": 0.49, "team": {"name": "Panthers"}},
            {"description": "Texans", "long": True, "price": 0.51, "team": {"name": "Texans"}},
        ],
        "question": "Houston vs. Carolina",
    }
    stored = _slate_row_for_storage(row)
    assert stored[YES_LEG_INDEX_FIELD] == 1
    assert stored[YES_LEG_REASON_FIELD] is None
    assert "marketSides" not in stored, "the blob must not reach the artifact"
    assert "question" not in stored


def test_storage_row_records_the_refusal_reason_when_it_cannot_derive():
    """An absent index must be accompanied by WHY, or a census of the artifact
    cannot tell an unstated side from a broken join."""
    stored = _slate_row_for_storage({"slug": "s", "outcomes": ["A", "B"]})
    assert stored[YES_LEG_INDEX_FIELD] is None
    assert stored[YES_LEG_REASON_FIELD] == "no_market_sides"


def test_the_field_is_always_present_so_absence_is_never_ambiguous():
    """A row with no key at all is indistinguishable from one we never tried."""
    stored = _slate_row_for_storage({"slug": "s"})
    assert YES_LEG_INDEX_FIELD in stored
    assert YES_LEG_REASON_FIELD in stored
