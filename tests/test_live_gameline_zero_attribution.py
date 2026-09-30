"""A live-gameline zero must say WHICH zero it is.

WHY `[lane live-gameline-zero-attribution, 2026-09-29]`. The reasoned early returns
in `attach_live_gamelines_for_sport` cover "no live re-sim wired", "no soccer match
in play" and "no published live-lens snapshot". A sport whose snapshot EXISTS and
whose index comes back empty fell through all three and returned all-zero counters
with NO reason -- so `check_e2e_coverage` reported `ncaaf`/`nfl`/`nhl` `live_games`
as `unattributed_zero`, where a code gap and a Tuesday with nothing in play are the
same number.

The information was already in `index_diagnostics`; it was never turned into a
`reason`, and `reason` is what the coverage contract reads.

Three states, three owners:
  * nothing in the snapshot        -> nothing is in play, nobody is at fault
  * games present, none indexed    -> the producer or the accepted-source list
  * indexed but no row considered  -> the row/game join, not the producer
"""
from __future__ import annotations

from syndicate.features.shared import coverage_contract as cc
from syndicate.features.shared.board_enrichment import _attribute_live_gameline_zero


def _zero(**extra):
    base = {"rows_live_gameline_considered": 0, "rows_live_gameline_projected": 0}
    base.update(extra)
    return base


# --------------------------------------------------------------------------
# The three states
# --------------------------------------------------------------------------

def test_an_empty_snapshot_reads_as_nothing_in_play():
    cov = _zero()
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 0, "indexed": 0}, sport="nhl")
    assert "no nhl game in play" in cov["reason"]


def test_games_present_but_none_indexed_names_the_producer_gap_and_its_skips():
    cov = _zero()
    _attribute_live_gameline_zero(
        cov, {"games_in_snapshot": 16, "indexed": 0, "skipped_no_accepted_lane": 16},
        sport="nfl")
    assert "16 nfl game(s) in the live snapshot but none indexed" in cov["reason"]
    assert "skipped_no_accepted_lane=16" in cov["reason"]


def test_an_index_with_no_matching_board_row_names_the_join_not_the_producer():
    cov = _zero(index_size=3)
    _attribute_live_gameline_zero(
        cov, {"games_in_snapshot": 5, "indexed": 3}, sport="ncaaf")
    assert "3 ncaaf game(s) indexed from 5" in cov["reason"]
    assert "no board row matched" in cov["reason"]


def test_skip_buckets_with_zero_counts_are_left_out_of_the_reason():
    cov = _zero()
    _attribute_live_gameline_zero(
        cov, {"games_in_snapshot": 4, "indexed": 0,
              "skipped_no_accepted_lane": 4, "skipped_no_team_names": 0},
        sport="nhl")
    assert "skipped_no_accepted_lane=4" in cov["reason"]
    assert "skipped_no_team_names" not in cov["reason"]


# --------------------------------------------------------------------------
# What it must NOT touch
# --------------------------------------------------------------------------

def test_a_join_with_real_coverage_is_left_alone():
    """A non-zero `projected` is real coverage; a rate with a denominator explains
    itself and needs no reason."""
    cov = {"rows_live_gameline_considered": 58, "rows_live_gameline_projected": 3,
           "withheld_by_reason": {"quote_older_than_live_pricing_ceiling": 4}}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 4, "indexed": 1}, sport="mlb")
    assert cov.get("reason") is None


# --------------------------------------------------------------------------
# projected == 0 WITH rows considered -- the case that shipped broken
# --------------------------------------------------------------------------
#
# THE BLIND SPOT WAS IN THE TESTS AS WELL AS THE CODE. The first version returned
# early whenever `considered > 0`, and the two "left alone" tests above both used a
# NON-ZERO `projected`, so they passed on the early-return branch and nothing
# exercised `projected == 0, considered > 0`. 11 tests passed and NHL still measured
# as an unattributed_zero on production.


def test_rows_considered_but_none_priced_gets_a_reason_from_withheld_by_reason():
    """NHL's exact production shape, 2026-09-30 02:38:20Z."""
    cov = {"rows_live_gameline_considered": 9, "rows_live_gameline_projected": 0,
           "rows_live_gameline_withheld": 9,
           "withheld_by_reason": {"no_live_gameline_projection": 9}}
    _attribute_live_gameline_zero(
        cov, {"games_in_snapshot": 5, "indexed": 0, "skipped_no_accepted_lane": 5},
        sport="nhl")
    assert "9 nhl row(s) considered, none priced" in cov["reason"]
    assert "no_live_gameline_projection=9" in cov["reason"]


def test_the_withheld_breakdown_is_preserved_not_replaced():
    """The summary goes in `reason` ALONGSIDE the breakdown. Losing the detail was
    the stated worry that made the first version return early; it does not apply."""
    withheld = {"no_live_gameline_projection": 9}
    cov = {"rows_live_gameline_considered": 9, "rows_live_gameline_projected": 0,
           "withheld_by_reason": withheld}
    _attribute_live_gameline_zero(cov, {}, sport="nhl")
    assert cov["withheld_by_reason"] == withheld


def test_many_withheld_reasons_are_ranked_and_truncated_with_a_count():
    cov = {"rows_live_gameline_considered": 61, "rows_live_gameline_projected": 0,
           "withheld_by_reason": {"a": 30, "b": 20, "c": 7, "d": 3, "e": 1}}
    _attribute_live_gameline_zero(cov, {}, sport="mlb")
    reason = cov["reason"]
    assert "a=30, b=20, c=7" in reason      # ranked by count, biggest first
    assert "+2 more" in reason              # and the tail is counted, not dropped
    assert "d=3" not in reason


def test_rows_withheld_with_no_breakdown_is_itself_named():
    """Rows withheld and nothing recorded why is a gap in the join's own
    accounting, and must not read as a plain zero."""
    cov = {"rows_live_gameline_considered": 4, "rows_live_gameline_projected": 0}
    _attribute_live_gameline_zero(cov, {}, sport="nfl")
    assert "no withheld_by_reason was recorded" in cov["reason"]


def test_a_non_numeric_withheld_count_does_not_raise():
    cov = {"rows_live_gameline_considered": 3, "rows_live_gameline_projected": 0,
           "withheld_by_reason": {"weird": None, "real": 3}}
    _attribute_live_gameline_zero(cov, {}, sport="nhl")
    assert "real=3" in cov["reason"]


def test_the_gate_stops_flagging_nhls_considered_but_unpriced_zero():
    cov = {"rows_live_gameline_considered": 9, "rows_live_gameline_projected": 0,
           "withheld_by_reason": {"no_live_gameline_projection": 9}}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 5, "indexed": 0},
                                  sport="nhl")
    sport = cc.read_sport("nhl", {"enrichment": {"live_gamelines": cov}})
    cell = sport.cell(cc.LIVE_GAMES)
    assert cell.status == cc.ATTRIBUTED_ZERO
    assert cell.considered == 9
    assert not any("live_games" in d for d in sport.defects)


def test_a_zero_that_projected_without_considering_is_still_left_alone():
    cov = {"rows_live_gameline_considered": 0, "rows_live_gameline_projected": 2}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 4, "indexed": 1}, sport="mlb")
    assert cov.get("reason") is None


def test_an_existing_reason_is_never_overwritten():
    """The early returns set better, more specific reasons."""
    cov = _zero(reason="no soccer match in play in any league's live-state artifact")
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 0}, sport="soccer")
    assert cov["reason"] == "no soccer match in play in any league's live-state artifact"


def test_absent_or_malformed_diagnostics_do_not_raise():
    for diag in (None, {}, {"games_in_snapshot": "many"}, []):
        cov = _zero()
        _attribute_live_gameline_zero(cov, diag, sport="nhl")
        assert isinstance(cov.get("reason"), str) and cov["reason"]


def test_non_numeric_counters_do_not_raise_or_invent_a_reason():
    cov = {"rows_live_gameline_considered": "n/a", "rows_live_gameline_projected": None}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 3}, sport="nhl")
    # Unparseable counters mean the state is unknown -- say nothing rather than
    # guess, and do not crash the enrichment step.
    assert cov.get("reason") is None


# --------------------------------------------------------------------------
# The integration that is the point
# --------------------------------------------------------------------------

def test_the_coverage_gate_stops_reporting_an_unattributed_zero():
    cov = _zero()
    _attribute_live_gameline_zero(
        cov, {"games_in_snapshot": 10, "indexed": 0, "skipped_no_accepted_lane": 10},
        sport="nhl")
    sport = cc.read_sport("nhl", {"candidates": 836,
                                  "enrichment": {"live_gamelines": cov}})
    cell = sport.cell(cc.LIVE_GAMES)
    assert cell.status == cc.ATTRIBUTED_ZERO
    assert not any("live_games" in d for d in sport.defects)


def test_a_working_live_join_still_reads_as_real_coverage():
    cov = {"rows_live_gameline_considered": 58, "rows_live_gameline_projected": 3}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 4, "indexed": 1}, sport="mlb")
    sport = cc.read_sport("mlb", {"enrichment": {"live_gamelines": cov}})
    cell = sport.cell(cc.LIVE_GAMES)
    assert cell.status == cc.DEGRADED
    assert cell.rate == 3 / 58
