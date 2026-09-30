"""Every summed denominator must have a summed numerator across the board's window.

WHY `[lane layer2-window-merge-counters, 2026-09-29]`. `_attach_projections_over_window`
calls `attach_projections` once per date in a 7-day window and merges the coverage
dicts. Keys in `summable` are added up; everything else falls to "first non-falsy
date wins". `game_rows_considered` was in that tuple and `game_rows_with_projection`
was NOT, so NCAAF served **41 / 644**: a numerator frozen on 2026-10-02 (where it
was 41/41) over a denominator summed across seven dates whose 10-03 slice alone
holds 536 game rows. Two numbers from two populations, presented as a rate.

The same shape made "NCAAF props are healthy, 44/49" meaningless -- 44 and 49 froze
on DIFFERENT dates.

Two traps a naive fix hits, both covered below:
  * `isinstance(False, int)` is True in Python, so summing a nested coverage half
    turns `supported: False` into `0` and `supported: True` into a tally of dates;
  * a half's `reason` frozen at date one is served as the whole window's reason.
"""
from __future__ import annotations

import pipeline.layer2_shortlist as ls


def _run(per_date_coverage, sport="ncaaf"):
    """Drive the real merge with a stubbed per-date `attach_projections`."""
    dates = list(per_date_coverage)
    calls = {"n": 0}

    def fake_attach(grid, *, sport, selected_date):  # noqa: ARG001
        calls["n"] += 1
        return per_date_coverage[selected_date]

    import syndicate.features.shared.board_enrichment as be
    original = be.attach_projections
    be.attach_projections = fake_attach
    try:
        out = ls._attach_projections_over_window(
            [], sport=sport, selected_date=dates[0], window_dates=dates)
    finally:
        be.attach_projections = original
    assert calls["n"] == len(dates)
    return out


# --------------------------------------------------------------------------
# The core defect
# --------------------------------------------------------------------------

def test_game_numerator_sums_like_its_denominator():
    """The NCAAF case: a date with 41/41 followed by a date with 536 game rows.
    Before the fix the numerator froze at 41 while the denominator reached 577."""
    merged = _run({
        "2026-10-02": {"game_rows_considered": 41, "game_rows_with_projection": 41},
        "2026-10-03": {"game_rows_considered": 536, "game_rows_with_projection": 400},
    })
    assert merged["game_rows_considered"] == 577
    assert merged["game_rows_with_projection"] == 441      # not 41


def test_prop_halves_sum_on_both_sides():
    merged = _run({
        "2026-10-01": {"prop_rows_considered": 49, "prop_rows_with_projection": 0},
        "2026-10-02": {"prop_rows_considered": 200, "prop_rows_with_projection": 44},
    })
    assert merged["prop_rows_considered"] == 249
    assert merged["prop_rows_with_projection"] == 44


def test_nhl_unsupported_game_market_counter_sums():
    """NHL's new counters ride this list too, or its 0-of-N freezes at date one."""
    merged = _run({
        "2026-09-29": {"prop_rows_considered": 459, "prop_rows_with_projection": 0,
                       "rows_unsupported_game_market": 3},
        "2026-09-30": {"prop_rows_considered": 120, "prop_rows_with_projection": 0,
                       "rows_unsupported_game_market": 2},
    }, sport="nhl")
    assert merged["prop_rows_considered"] == 579
    assert merged["rows_unsupported_game_market"] == 5


def test_slate_shape_counters_sum_instead_of_describing_one_day():
    merged = _run({
        "2026-09-29": {"games_indexed": 4, "games_unratable_opponent": 3},
        "2026-10-03": {"games_indexed": 60, "games_unratable_opponent": 2},
    })
    assert merged["games_indexed"] == 64
    assert merged["games_unratable_opponent"] == 5


def test_a_rate_is_rederived_from_the_summed_counts():
    merged = _run({
        "2026-10-02": {"rows_considered": 100, "rows_with_projection": 50,
                       "pct_projected": 50.0},
        "2026-10-03": {"rows_considered": 100, "rows_with_projection": 90,
                       "pct_projected": 90.0},
    })
    assert merged["rows_considered"] == 200
    assert merged["rows_with_projection"] == 140
    assert merged["pct_projected"] == 70.0      # not 50.0, the first date's value


# --------------------------------------------------------------------------
# Trap 1: a bool is not a count
# --------------------------------------------------------------------------

def test_supported_false_survives_the_nested_merge_as_false_not_zero():
    """`isinstance(False, int)` is True, so a numeric sum would make this `0`."""
    merged = _run({
        "2026-09-29": {"prop_coverage": {"supported": False, "rows_considered": 10,
                                         "rows_with_projection": 0}},
        "2026-09-30": {"prop_coverage": {"supported": False, "rows_considered": 20,
                                         "rows_with_projection": 0}},
    }, sport="nhl")
    half = merged["prop_coverage"]
    assert half["supported"] is False
    assert half["rows_considered"] == 30


def test_supported_true_is_not_summed_into_a_tally_of_dates():
    merged = _run({
        "2026-10-02": {"game_coverage": {"supported": True, "rows_considered": 5,
                                         "rows_with_projection": 5}},
        "2026-10-03": {"game_coverage": {"supported": True, "rows_considered": 7,
                                         "rows_with_projection": 7}},
    })
    half = merged["game_coverage"]
    assert half["supported"] is True        # not 2
    assert half["rows_with_projection"] == 12


# --------------------------------------------------------------------------
# Trap 2: a half's reason must describe the window
# --------------------------------------------------------------------------

def test_a_halfs_reason_is_dropped_once_the_window_projected_something():
    """The NCAAF symptom: today has no game projections and says so, while the
    rest of the window projects hundreds of rows."""
    merged = _run({
        "2026-09-29": {"game_coverage": {
            "supported": True, "rows_considered": 0, "rows_with_projection": 0,
            "reason": "no NCAAF SmartSim2 projections for this date"}},
        "2026-10-03": {"game_coverage": {
            "supported": True, "rows_considered": 536, "rows_with_projection": 500}},
    })
    half = merged["game_coverage"]
    assert half["rows_with_projection"] == 500
    assert "reason" not in half
    assert "reasons" not in half        # the scratch bucket is never served


def test_a_halfs_reason_is_kept_when_the_whole_window_projected_nothing():
    merged = _run({
        "2026-09-29": {"prop_coverage": {
            "supported": False, "rows_considered": 459, "rows_with_projection": 0,
            "reason": "no NHL player-prop projection source"}},
        "2026-09-30": {"prop_coverage": {
            "supported": False, "rows_considered": 120, "rows_with_projection": 0,
            "reason": "no NHL player-prop projection source"}},
    }, sport="nhl")
    half = merged["prop_coverage"]
    assert half["rows_with_projection"] == 0
    assert half["reason"] == "no NHL player-prop projection source"   # deduped


def test_several_distinct_reasons_stay_several():
    """Collapsing different refusals into one would be a different lie than the
    one being fixed."""
    merged = _run({
        "2026-09-29": {"prop_coverage": {"rows_considered": 5, "rows_with_projection": 0,
                                         "reason": "no projection source"}},
        "2026-09-30": {"prop_coverage": {"rows_considered": 5, "rows_with_projection": 0,
                                         "reason": "artifact unreadable"}},
    })
    reason = merged["prop_coverage"]["reason"]
    assert "no projection source" in reason
    assert "artifact unreadable" in reason


def test_a_single_date_window_still_keeps_a_true_reason():
    merged = _run({
        "2026-09-29": {"prop_coverage": {"supported": False, "rows_considered": 459,
                                         "rows_with_projection": 0,
                                         "reason": "no NHL player-prop projection source"}},
    }, sport="nhl")
    assert merged["prop_coverage"]["reason"] == "no NHL player-prop projection source"


# --------------------------------------------------------------------------
# The contract reads the result
# --------------------------------------------------------------------------

def test_the_coverage_contract_reads_a_merged_window_at_the_right_grain():
    from syndicate.features.shared import coverage_contract as cc

    merged = _run({
        "2026-10-02": {"game_rows_considered": 41, "game_rows_with_projection": 41,
                       "prop_rows_considered": 20, "prop_rows_with_projection": 18},
        "2026-10-03": {"game_rows_considered": 536, "game_rows_with_projection": 500,
                       "prop_rows_considered": 80, "prop_rows_with_projection": 70},
    })
    cov = cc.read_sport("ncaaf", {"candidates": 1683, "enrichment": {"projections": merged}})
    games = cov.cell(cc.PREGAME_GAMES)
    props = cov.cell(cc.PREGAME_PROPS)
    assert (games.projected, games.considered) == (541, 577)
    assert (props.projected, props.considered) == (88, 100)
    # Both halves are real rates over one population now.
    assert games.rate == 541 / 577
    assert props.rate == 0.88
    # Only the PREGAME cells are in scope here: this fixture supplies no
    # `live_gamelines`/`live_projections`, so those read `not_reported` -- which
    # is the contract behaving correctly, not a defect in the merge.
    assert not any("pregame" in d for d in cov.defects)
