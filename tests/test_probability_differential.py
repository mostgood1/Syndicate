"""Locks in the Tier 3a differential findings.

These tests are deliberately asymmetric. They do NOT assert "all 31
implementations agree" -- they do not, that is the finding, and a test that
demanded it would just be red until someone did the consolidation.

What they assert instead:
  1. the recommended owner of each concept still meets every stated requirement,
     so a future edit cannot quietly demote the canonical implementation;
  2. the set of implementations that FAIL the requirements does not grow. Fixing
     one is welcome and makes the test pass more easily; adding a new broken
     converter, or breaking a currently-correct one, fails;
  3. every converter-shaped function in the tree is registered with the harness
     or explicitly excused, so implementation number 32 cannot land unnoticed.

Full working: `.syndicate/audit_2026-08-15_probability_differential.md`.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
for path in (ROOT, SCRIPTS):
    if path not in sys.path:
        sys.path.insert(0, path)

import probability_differential as pd_harness  # noqa: E402


# The owner of each concept, established by the requirement scorecard rather
# than asserted. `american_to_probability` has 15 behaviourally identical
# survivors, so the choice among them is a module-ownership call: the shared
# opportunity-signals module already exports the inverse (`american_price`),
# which makes it the only one where the pair can be kept consistent.
OWNERS = {
    "american_to_probability": "syndicate.features.shared.opportunity_signals:implied_probability",
    "american_to_decimal": "syndicate.features.shared.live_lens_local:_american_to_decimal",
    "probability_to_american": "syndicate.features.shared.opportunity_signals:american_price",
}

# Measured 2026-08-15. Shrinking this set is the point; growing it is a
# regression. Each entry is an implementation that fails at least one stated
# requirement -- see the report for which and why.
KNOWN_FAILING = {
    "american_to_probability": {
        "scripts.fetch_mlb_oddsapi_local:_american_implied_prob",
        "scripts.regrade_mlb_game_markets:_american_to_implied",
        "scripts.validate_soccer_vs_market:_american_to_prob",
        "syndicate.features.bankroll_manager:_implied_probability_from_odds",
        "syndicate.features.intelligence:_american_implied_probability",
        "syndicate.features.intelligence:odds_to_implied_probability",
        "syndicate.features.mlb.cards:_american_implied_prob",
        "syndicate.features.mlb.hr_targets:_american_odds_implied_prob",
        "syndicate.features.ncaab.mirror_export:_american_to_probability",
        "syndicate.features.nhl.sim_engine.hockeysim.adapters:american_to_implied",
        "syndicate.features.shared.odds_book_quotes:_implied_probability",
    },
    "american_to_decimal": {
        "scripts.regrade_mlb_game_markets:_american_to_decimal",
        "syndicate.features.bankroll_manager:_american_to_decimal",
        "syndicate.features.intelligence:_american_to_decimal",
        "syndicate.features.nhl.sim_engine.hockeysim.adapters:american_to_decimal",
    },
    "probability_to_american": {
        # `wnba.cards:_american_from_prob` was here until 2026-08-15. It now
        # delegates to `american_price` and passes 5/5, so it is deliberately
        # NOT listed: leaving a fixed implementation in this set would let it
        # silently regress back to a clamp. Two clamp sites remain, both held by
        # other OPEN lanes -- see the lane block for the handover.
        "pipeline.intelligence_state:_backfill_layer2_board_columns",
        "syndicate.features.nhl.sim_engine.hockeysim.features.market_lines:_prob_to_american",
        "syndicate.features.shared.layer2_board:_american_from_probability",
    },
}


@pytest.fixture(scope="module")
def results():
    payload = pd_harness.run()
    assert not payload["import_errors"], (
        "every registered implementation must import; an unimportable one is "
        f"untested, not passing: {payload['import_errors']}"
    )
    return payload["results"]


@pytest.mark.parametrize("concept", sorted(OWNERS))
def test_owner_meets_every_requirement(results, concept):
    owner = OWNERS[concept]
    card = {row["impl"]: row for row in pd_harness.scorecard(results, concept)}
    assert owner in card, f"the recorded owner of {concept} is no longer registered: {owner}"
    row = card[owner]
    assert row["met"] == row["total"], (
        f"{owner} no longer meets every requirement for {concept}: {row['failed']}"
    )


@pytest.mark.parametrize("concept", sorted(KNOWN_FAILING))
def test_failing_set_does_not_grow(results, concept):
    failing = {row["impl"] for row in pd_harness.scorecard(results, concept)
               if row["met"] != row["total"]}
    new = failing - KNOWN_FAILING[concept]
    assert not new, (
        f"new implementation(s) of {concept} fail the stated requirements: {sorted(new)}. "
        "Either fix them or, if the requirement is wrong, change the requirement and "
        "say so in .syndicate/audit_2026-08-15_probability_differential.md."
    )


def test_owner_round_trips():
    """The inverse pair must compose back to the input. This is what separates
    `american_price` from the clamped implementations without anyone having to
    prefer one -- a clamp cannot round-trip a probability outside its clamp."""
    trips = pd_harness.roundtrip()
    owner = OWNERS["probability_to_american"]
    assert owner in trips, f"owner missing from the round trip: {owner}"
    result = trips[owner]
    assert result["passed"] == result["probes"], (
        f"{owner} failed to round-trip: {result['failures']}"
    )


def test_percent_scale_is_refused_by_the_owner(results):
    """A probability of 50.0 is a unit error, not a 50-to-1 favourite.

    Called out separately because it is the one requirement that distinguishes
    a refusal from a plausible-looking wrong answer: the clamped implementations
    turn 50.0 into a confident -4900 rather than declining to price it, and
    `confidence` is stored 0-100 alongside probability 0-1 in the same rows.
    """
    owner = OWNERS["probability_to_american"]
    assert results[owner]["percent_50.0"] is None


def test_every_converter_is_registered_or_excused():
    """Implementation 32 cannot land unnoticed."""
    missing = pd_harness.discover_unregistered()
    assert not missing, (
        "converter-shaped functions are neither registered in "
        "scripts/probability_differential.py's REGISTRY nor listed in "
        f"NOT_A_SCALAR_CONVERTER with a reason: {missing}"
    )


def test_all_implementations_agree_on_valid_prices(results):
    """The reassuring half of the finding, and worth protecting.

    On genuinely valid American prices every implementation already agrees to
    the tenth decimal. The divergence is entirely at the boundary -- zero,
    null, empty, string and float inputs -- so nobody should read the
    disagreement table as "the odds maths is wrong in N places".
    """
    valid = ["plus_100", "minus_100", "plus_150", "minus_150", "plus_10000", "minus_10000"]
    for name in valid:
        answers = {}
        for label, row in results.items():
            if row.get("_concept") != "american_to_probability" or row.get("_error"):
                continue
            answers.setdefault(row[name], []).append(label)
        assert len(answers) == 1, (
            f"implementations disagree on the VALID price {name}: "
            f"{ {k: sorted(v) for k, v in answers.items()} }"
        )
