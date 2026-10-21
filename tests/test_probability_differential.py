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
        # ADDED 2026-10-16 (lane `ci-suite-red-1015`): the generated MLB live-lens
        # port (329edb1d) of the same vendored function -- the differential puts it
        # in hr_targets' cluster, identical on every input (truncates a fractional
        # price). A fix in the port is overwritten on regeneration; fix both at the
        # vendored source.
        "syndicate.features.mlb.live_lens_port.app_slice:_american_odds_implied_prob",
        # ADDED 2026-10-20 (lane `hygiene-guards-1020`), when the 17-name
        # backlog was classified. NOT NEW DEBT -- both have always failed this
        # requirement; they were invisible because they were never registered,
        # which is the whole point of the registration tripwire.
        #
        # Both fail `accepts_float_price` ONLY, 4/5, and in the same way as
        # `hr_targets` / `live_lens_port.app_slice` above: an int coercion
        # (`_safe_int`, `_parse_american_odds`) truncates -110.5 to -110, giving
        # 0.5238095238 against the reference 0.5249406175. A wrong number rather
        # than a refusal, but 0.11 of a percentage point of probability.
        #
        # RECORDED, NOT FIXED, deliberately: these are MLB SIM-ENGINE converters
        # and prop pricing is calibrated around what they currently return, so
        # changing them is a mechanism change owed a measurement (CLAUDE.md's
        # model-engine standard), not a hygiene edit. Integer prices -- what
        # books actually quote -- are unaffected; the exposure is averaged or
        # consensus prices, which arrive as floats.
        "syndicate.features.mlb.sim_engine.live_prop_ranking:american_odds_implied_prob",
        "syndicate.features.mlb.sim_engine.market_pitcher_props:american_implied_prob",
        "syndicate.features.ncaab.mirror_export:_american_to_probability",
        "syndicate.features.nhl.sim_engine.hockeysim.adapters:american_to_implied",
        "syndicate.features.shared.odds_book_quotes:_implied_probability",
        # ADDED 2026-10-02 (lane `local-prod-gap-fixes`), when the 26-name backlog
        # was registered. RAISES on 0/None/""/"+150" -- it never returns a wrong
        # number, and every row reaching it is pre-filtered by `usable()`
        # (`px not in (None, 0)`). 1/5.
        "scripts.score_ranking_analysis:implied",
        # 2026-10-03: four per-sport backtest copies (NFL, NHL props, WNBA,
        # consensus_movement) were ADDED here when registered -- each priced 0 as
        # 0.0 -- and all four were GUARDED and REMOVED the same day. Deliberately
        # not re-listed.
        # 2026-10-03: the NBA backtest's copy (795d420b) was ADDED here by lane
        # `nhl-props-converter-guard` and GUARDED + REMOVED the same day by lane
        # `nba-lines-props-backtest` (refuses 0/None/''/text/|price| < 100).
        # ADDED 2026-10-15 (lane `probability-differential-sweep-1015`), when the
        # 39-name backlog was registered. RAISES ValueError on '' only (bare
        # float()); refuses None and 0, and never returns a wrong number.
        "syndicate.features.shared.cheat_sheets:implied_from_price",
        # 2026-10-15: the two generated `source_cli/cli.py` copies of
        # `_merge_odds_df.implied_prob_american` were ADDED here by lane
        # `probability-differential-sweep-1015` (price 0 -> 1.0, the one row of
        # that sweep returning a WRONG NUMBER) and GUARDED + REMOVED the same day
        # by lane `source-cli-implied-prob-zero-guard`: a zero-guard EDIT in
        # `port_basketball_source_cli.py`, plus a harness adapter that reads their
        # pd.NA refusal as None. Deliberately not re-listed.
        # ADDED 2026-10-15 (lane `source-cli-implied-prob-zero-guard`), on
        # registration: landed in d139116c (lane `play-cards`) after the sweep.
        # Prices 0 as -0.0 (no zero guard); meets the other 4 requirements. Its
        # one caller draws the pick card's probability chart. The guard is
        # `play-cards`' to add.
        "syndicate.features.shared.play_cards:_implied",
    },
    "american_to_decimal": {
        # ADDED 2026-10-02, same registration. Four copies of the unguarded
        # one-liner `1 + (a/100 if a > 0 else 100/-a)`: all RAISE on bad input
        # (ZeroDivisionError at 0, TypeError on None/text) rather than mis-price.
        # `model_scorecard:_decimal_odds` is the production one; its ONLY call site
        # returns early on `price is None or price == 0` first
        # (`_accumulate_price`, model_scorecard.py:309).
        # Returning None instead would only move the TypeError into the caller's
        # arithmetic, so these are triaged here, not "fixed" into a new failure.
        "scripts.layer2_live_scorecard:decimal_odds",
        "scripts.score_ranking_analysis:decimal_odds",
        # ADDED 2026-10-20 (lane `hygiene-guards-1020`): a FIFTH copy of the
        # same unguarded one-liner, found by the 17-name classification. 2/5 --
        # ZeroDivisionError at 0, TypeError on None, ValueError on '' -- so it
        # fits this cluster's reasoning exactly, including the part about not
        # "fixing" a raise into a None that the caller's arithmetic then
        # inherits: `_devig_pair` in the same module divides by its result.
        # It is also the instrument of lane `sim-stake-unfitted-market-only`'s
        # pre-registered forward reading, so changing it mid-registration would
        # move the measurement as well as the code.
        "scripts.ev_overstatement_decomp:decimal_odds",
        "scripts.soccer_season_audit.common:dec_from_american",
        "syndicate.features.shared.model_scorecard:_decimal_odds",
        "scripts.regrade_mlb_game_markets:_american_to_decimal",
        "syndicate.features.bankroll_manager:_american_to_decimal",
        "syndicate.features.intelligence:_american_to_decimal",
        "syndicate.features.nhl.sim_engine.hockeysim.adapters:american_to_decimal",
        # 2026-10-03: the NFL and NHL-props backtest copies of the unguarded
        # one-liner were ADDED here and GUARDED + REMOVED the same day.
        # The NBA backtest's copy was ADDED and GUARDED + REMOVED the same day too.
        # `nba.betting_recap:_settlement_decimal_price` was ADDED here on
        # 2026-09-09 and REMOVED the same day, which is the whole point of the
        # set. It had returned 2.0 on a missing or zero price -- an unpriced
        # settled row booking EVEN MONEY, indistinguishable in the output from a
        # +100 winner -- and it was invisible until the sweep went AST-based and
        # found it nested inside `_settle_game_pick`. It refuses now, the
        # settlement path carries the None through to an `unpriced` count
        # instead of a fabricated payout, and it meets all five requirements.
        # Deliberately NOT listed: re-listing a fixed implementation would let
        # it silently regress to a fabricated default.
        #
        # ADDED 2026-10-15 (lane `probability-differential-sweep-1015`), same
        # triage as the 2026-10-02 four: every one RAISES on bad input and none
        # returns a wrong number. `daily_optimizer:_decimal_odds` is the production
        # one; its only call site skips `price in (None, 0)` first. The rest are
        # research/grading scripts: a bad price stops the run, it never mis-scores
        # it. `cheat_sheets:decimal_odds` refuses None and 0 and raises on '' only.
        "scripts.grade_h7_nba_unders:decimal",
        "scripts.grade_play_cards:decimal",
        "scripts.mlb_signal_tests:decimal",
        "scripts.nba_unders_test:decimal",
        "scripts.news_price_follow:_decimal",
        "scripts.nhl_saves_lift:decimal",
        "scripts.nhl_skater_history_lift:decimal",
        "scripts.signal_lift_football:decimal",
        "scripts.wnba_signal_tests:decimal",
        "syndicate.features.shared.cheat_sheets:decimal_odds",
        "syndicate.features.shared.daily_optimizer:_decimal_odds",
    },
    "probability_to_american": {
        # ALL THREE `max(0.02, min(0.98, p))` clamp sites are now fixed and are
        # deliberately NOT listed -- `wnba.cards:_american_from_prob`
        # (`de0c367f`), then `layer2_board:_american_from_probability` and the
        # inline copy in `pipeline.intelligence_state`. Leaving a fixed
        # implementation in this set would let it silently regress to a clamp,
        # which is the exact defect that published -4900 against a correct
        # -12488 on the live board.
        #
        # `market_lines:_prob_to_american` stays, and stays UNFIXED on purpose.
        # It fails all five requirements, but it has exactly ONE caller
        # (`_consensus_american`), which feeds it the median of
        # `_american_to_prob` outputs -- strictly inside (0, 1) by construction,
        # since every invalid price is filtered to None first. None of the five
        # failing inputs can reach it. Converting it to return Optional would
        # force None-handling onto six call sites for a case that cannot occur,
        # so this is triage, not an oversight: it is a sim-internal anchor, not
        # a published price.
        "syndicate.features.nhl.sim_engine.hockeysim.features.market_lines:_prob_to_american",
        # ADDED 2026-10-15 (lane `probability-differential-sweep-1015`). Fails ONE
        # requirement, by raising: '' reaches `0 < p < 1` and str-vs-int is a
        # TypeError. It refuses None, 0, 1 and the percent scale, does not clamp,
        # and round-trips; its callers pass `p_market`, a float or None.
        "syndicate.features.shared.play_cards:american_from_prob",
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
