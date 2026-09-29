"""Tests for the uniform cross-sport coverage contract.

The cases that carry weight are the ones about ABSENCE, because every one of them
corresponds to a real misreading this repo has already paid for:

  * an absent key must read `not_reported`, NEVER zero -- mapping absence onto the
    zero branch is how a reader turns "I cannot see this" into "there is no
    coverage", and it reports a healthy sport as broken;
  * a zero WITH a stated reason is a known gap and must PASS the gate, or the gate
    goes red for months over work already tracked in a lane;
  * a zero WITHOUT a reason must FAIL, because a code gap and an empty slate are
    the same number;
  * the resolved key must be recorded, so a sport changing its diagnostic shape
    shows up as drift rather than as a silently different number.
"""
from __future__ import annotations

from syndicate.features.shared import coverage_contract as cc


def _ingest(projections=None, live_gamelines=None, live_projections=None, candidates=None):
    enrichment = {}
    if projections is not None:
        enrichment["projections"] = projections
    if live_gamelines is not None:
        enrichment["live_gamelines"] = live_gamelines
    if live_projections is not None:
        enrichment["live_projections"] = live_projections
    block = {"enrichment": enrichment}
    if candidates is not None:
        block["candidates"] = candidates
    return block


# --------------------------------------------------------------------------
# The absence rule
# --------------------------------------------------------------------------

def test_an_absent_metric_reads_not_reported_and_never_zero():
    cov = cc.read_sport("nhl", _ingest(projections={"rows_with_projection": 9,
                                                    "rows_considered": 9}))
    props = cov.cell(cc.PREGAME_PROPS)
    assert props.projected is None          # NOT 0
    assert props.status == cc.NOT_REPORTED
    assert props.rate is None
    assert props.source_key is None


def test_a_missing_sport_block_is_all_not_reported_rather_than_all_zero():
    cov = cc.read_sport("ncaab", None)
    for name in cc.CELLS:
        assert cov.cell(name).projected is None
        assert cov.cell(name).status == cc.NOT_REPORTED


def test_an_active_sport_with_no_ingest_block_still_appears_in_the_matrix():
    """A sport that vanishes from the matrix entirely is the failure this avoids:
    it would read as 'nothing to report' instead of 'we cannot see this sport'."""
    matrix = cc.read_shortlist({"active_sports": ["mlb", "ncaab"],
                                "per_sport_ingest": {"mlb": _ingest(
                                    projections={"game_rows_with_projection": 5,
                                                 "game_rows_considered": 5})}})
    assert set(matrix) == {"mlb", "ncaab"}
    assert matrix["ncaab"].cell(cc.PREGAME_GAMES).status == cc.NOT_REPORTED


# --------------------------------------------------------------------------
# Attributed vs unattributed zero
# --------------------------------------------------------------------------

def test_zero_with_a_stated_reason_is_attributed_and_is_not_a_defect():
    cov = cc.read_sport("nhl", _ingest(live_projections={
        "rows_live_projected": 0, "reason": "no live re-sim wired for nhl"}))
    cell = cov.cell(cc.LIVE_PROPS)
    assert cell.status == cc.ATTRIBUTED_ZERO
    assert "no live re-sim wired" in cell.reason
    assert not any("live_props" in d for d in cov.defects)


def test_zero_with_no_reason_is_unattributed_and_IS_a_defect():
    cov = cc.read_sport("nfl", _ingest(live_gamelines={
        "rows_live_gameline_projected": 0, "rows_live_gameline_considered": 0}))
    cell = cov.cell(cc.LIVE_GAMES)
    assert cell.status == cc.UNATTRIBUTED_ZERO
    assert any("live_games" in d for d in cov.defects)


def test_a_blank_reason_does_not_count_as_attribution():
    cov = cc.read_sport("nfl", _ingest(live_projections={
        "rows_live_projected": 0, "reason": "   "}))
    assert cov.cell(cc.LIVE_PROPS).status == cc.UNATTRIBUTED_ZERO


# --------------------------------------------------------------------------
# Rates
# --------------------------------------------------------------------------

def test_rate_needs_a_denominator_and_is_never_invented():
    cov = cc.read_sport("x", _ingest(projections={"game_rows_with_projection": 7}))
    cell = cov.cell(cc.PREGAME_GAMES)
    assert cell.projected == 7
    assert cell.considered is None
    assert cell.rate is None              # a count alone is not a rate


def test_rate_is_computed_when_both_halves_are_present():
    cov = cc.read_sport("wnba", _ingest(projections={
        "prop_rows_with_projection": 376, "prop_rows_considered": 406}))
    assert cov.cell(cc.PREGAME_PROPS).rate == 376 / 406


def test_full_coverage_is_ok_and_partial_is_degraded():
    full = cc.read_sport("wnba", _ingest(projections={
        "game_rows_with_projection": 352, "game_rows_considered": 352}))
    part = cc.read_sport("nfl", _ingest(projections={
        "game_rows_with_projection": 94, "game_rows_considered": 1484}))
    assert full.cell(cc.PREGAME_GAMES).status == cc.OK
    assert part.cell(cc.PREGAME_GAMES).status == cc.DEGRADED
    # Neither is an instrument defect -- partial coverage is a real number.
    assert full.defects == [] or all("pregame_games" not in d for d in full.defects)
    assert all("pregame_games" not in d for d in part.defects)


# --------------------------------------------------------------------------
# Resolution order and provenance
# --------------------------------------------------------------------------

def test_split_keys_win_over_the_combined_count():
    cov = cc.read_sport("nfl", _ingest(projections={
        "game_rows_with_projection": 94, "game_rows_considered": 1484,
        "rows_with_projection": 563, "rows_considered": 2283}))
    cell = cov.cell(cc.PREGAME_GAMES)
    assert cell.projected == 94
    assert cell.source_key == "projections.game_rows_with_projection"


def test_the_mlb_shape_is_derived_rather_than_left_invisible():
    """MLB emits no `*_rows_with_projection` split, only considered-and-shortfall.
    Without the derivation the REFERENCE module is the least legible row: its games
    cell falls through to a combined games+props number and its props cell is
    invisible."""
    cov = cc.read_sport("mlb", _ingest(projections={
        "game_rows_considered": 245, "game_no_projection": 4,
        "player_rows_considered": 626, "player_no_projection": 39,
        "rows_with_projection": 763, "rows_considered": 871}))
    games, props = cov.cell(cc.PREGAME_GAMES), cov.cell(cc.PREGAME_PROPS)
    assert (games.projected, games.considered) == (241, 245)
    assert (props.projected, props.considered) == (587, 626)
    assert "game_no_projection" in games.source_key
    assert "player_no_projection" in props.source_key


def test_a_derivation_needs_both_halves():
    """A shortfall with no denominator derives nothing rather than guessing."""
    cov = cc.read_sport("mlb", _ingest(projections={"game_no_projection": 4}))
    assert cov.cell(cc.PREGAME_GAMES).status == cc.NOT_REPORTED


def test_the_combined_fallback_says_so_in_its_provenance():
    """A combined games+props number is the least informative resolution, so it
    must be identifiable as such and not mistaken for a games-only figure."""
    cov = cc.read_sport("soccer", _ingest(projections={
        "rows_with_projection": 366, "rows_considered": 752}))
    cell = cov.cell(cc.PREGAME_GAMES)
    assert cell.projected == 366
    assert "COMBINED" in cell.source_key


def test_derivation_is_preferred_over_the_combined_fallback():
    cov = cc.read_sport("mlb", _ingest(projections={
        "game_rows_considered": 245, "game_no_projection": 4,
        "rows_with_projection": 763, "rows_considered": 871}))
    assert cov.cell(cc.PREGAME_GAMES).projected == 241
    assert "COMBINED" not in (cov.cell(cc.PREGAME_GAMES).source_key or "")


# --------------------------------------------------------------------------
# Defect aggregation
# --------------------------------------------------------------------------

def test_defects_exclude_known_gaps_and_partial_coverage():
    matrix = cc.read_shortlist({"per_sport_ingest": {
        "nhl": _ingest(
            projections={"rows_with_projection": 10, "rows_considered": 10},
            live_projections={"rows_live_projected": 0,
                              "reason": "no live re-sim wired for nhl"},
            live_gamelines={"rows_live_gameline_projected": 0,
                            "rows_live_gameline_considered": 6}),
    }})
    defects = cc.all_defects(matrix)
    # The attributed live_props zero is NOT a defect; the unattributed live_games
    # zero and the unreported props cell ARE.
    assert "nhl.live_props: attributed_zero" not in " ".join(defects)
    assert any("nhl.live_games" in d for d in defects)
    assert any("nhl.pregame_props" in d for d in defects)


def test_bools_are_not_read_as_counts():
    """`supported: true` must never be coerced into a projected count of 1."""
    cov = cc.read_sport("x", _ingest(projections={
        "game_rows_with_projection": True, "game_rows_considered": 10}))
    assert cov.cell(cc.PREGAME_GAMES).projected is None
