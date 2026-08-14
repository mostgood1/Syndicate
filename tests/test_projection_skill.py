"""`#425` gap 1 — every projection declares whether its model was evaluated.

`skill_note` was called in exactly ONE of seven projection builders. A board row
from the other six carried a number with no statement of whether the model
behind it predicts anything, so "measured and good" and "never measured" were
indistinguishable — both were a bare number.

THIS DOES NOT MEASURE THE SIX MODELS and the tests are written so nobody can
later mistake it for that. It converts SILENT absence into DECLARED absence.
The data to measure them is not present (soccer results 0 files, MLB feed_live
1 date, WNBA game-cards 4 files as of 2026-08-14), and emitting a correlation
from n=4 would be `#377`'s own failure committed by the fix for it.

The load-bearing test is `test_a_measured_note_is_never_reworded`: code that
did not measure a model must not be able to change what the measurement says.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.projection_skill import (
    STATUS_MEASURED,
    STATUS_UNMEASURED,
    attach_projection_skill,
    normalize_existing_note,
    unmeasured_note,
)


# The real NFL note, as `nfl_preseason_calibration.skill_note` emits it.
NFL_NOTE = {
    "sample_games": 146,
    "seasons": "2023-2025",
    "correlation": -0.047,
    "verdict": "no measured skill -- moneyline probabilities are uninformative",
}


def _row(projection=None, kind="game"):
    row = {"kind": kind, "market": "totals", "segment": "full", "event_id": "g1"}
    if projection is not None:
        row["projection"] = projection
    return row


# --------------------------------------------------------------------------
# the declared-absence block
# --------------------------------------------------------------------------


def test_unmeasured_note_has_the_same_shape_as_a_measured_one():
    """A consumer must never branch on which producer wrote the block."""
    note = unmeasured_note()
    assert note["status"] == STATUS_UNMEASURED
    # Explicit nulls, not missing keys -- `model_skill["correlation"]` must not
    # raise for an unmeasured model.
    assert note["correlation"] is None
    assert note["sample_games"] == 0
    assert set(note) == {"status", "correlation", "sample_games", "verdict"}


def test_unmeasured_note_stays_small():
    """PAYLOAD DISCIPLINE. This lands on every projection row on every sport.
    `#374` records extraHitterProps reaching 68% of the MLB live-lens payload."""
    note = unmeasured_note()
    assert len(note) <= 4
    assert len(note["verdict"]) < 80, "prose belongs in the module docstring, not per row"


def test_unmeasured_verdict_does_not_claim_the_model_is_bad():
    """Unmeasured is not the same as measured-and-poor. NFL's margins model IS
    measured and IS poor; these six are simply unknown, and saying otherwise
    would invent a finding."""
    verdict = unmeasured_note()["verdict"].lower()
    assert "never backtested" in verdict or "unvalidated" in verdict
    for forbidden in ("no skill", "poor", "bad", "uninformative"):
        assert forbidden not in verdict


# --------------------------------------------------------------------------
# THE ONE THAT MATTERS: a measurement must survive contact with this code
# --------------------------------------------------------------------------


def test_a_measured_note_is_never_reworded():
    note = dict(NFL_NOTE)
    out = normalize_existing_note(note)
    assert out["status"] == STATUS_MEASURED
    for key, value in NFL_NOTE.items():
        assert out[key] == value, f"{key} was altered by code that did not measure it"


def test_a_note_that_already_declares_status_is_left_alone():
    note = {"status": "measured", "correlation": 0.9, "verdict": "custom"}
    assert normalize_existing_note(dict(note)) == note


def test_nfl_rows_keep_their_real_numbers_through_the_grid_pass():
    grid = [_row({"projected": 44.0, "model_skill": dict(NFL_NOTE)})]
    coverage = attach_projection_skill(grid, sport="nfl")
    skill = grid[0]["projection"]["model_skill"]
    assert skill["correlation"] == -0.047
    assert skill["sample_games"] == 146
    assert skill["status"] == STATUS_MEASURED
    assert coverage["rows_with_measured_skill"] == 1
    assert coverage["rows_with_unmeasured_skill"] == 0


# --------------------------------------------------------------------------
# filling the gap for the other six
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sport", ["soccer", "wnba", "mlb", "nhl", "nba", "ncaaf", "ncaab"])
def test_a_projection_without_a_note_gets_a_declared_absence(sport):
    grid = [_row({"projected": 7.5})]
    coverage = attach_projection_skill(grid, sport=sport)
    assert grid[0]["projection"]["model_skill"]["status"] == STATUS_UNMEASURED
    assert coverage["rows_with_unmeasured_skill"] == 1


def test_rows_without_a_projection_are_untouched():
    grid = [_row(), _row()]
    assert attach_projection_skill(grid, sport="mlb") == {}
    assert "projection" not in grid[0]


def test_an_empty_existing_note_is_treated_as_absent():
    """`model_skill: {}` is a producer that emitted nothing, not a measurement."""
    grid = [_row({"projected": 1.0, "model_skill": {}})]
    attach_projection_skill(grid, sport="soccer")
    assert grid[0]["projection"]["model_skill"]["status"] == STATUS_UNMEASURED


def test_counts_make_an_all_unmeasured_board_visible_as_a_number():
    """The point of `#425`: 'nothing would say so' becomes a number someone
    reads, rather than something they must notice."""
    grid = [_row({"projected": float(i)}) for i in range(12)]
    coverage = attach_projection_skill(grid, sport="soccer")
    assert coverage == {"rows_with_measured_skill": 0, "rows_with_unmeasured_skill": 12}


def test_mixed_board_reports_both_counts():
    grid = [
        _row({"projected": 1.0, "model_skill": dict(NFL_NOTE)}),
        _row({"projected": 2.0}),
        _row({"projected": 3.0}),
    ]
    coverage = attach_projection_skill(grid, sport="nfl")
    assert coverage["rows_with_measured_skill"] == 1
    assert coverage["rows_with_unmeasured_skill"] == 2


# --------------------------------------------------------------------------
# the wrapper wiring
# --------------------------------------------------------------------------


def test_wrapper_stamps_skill_for_every_sport(monkeypatch):
    import syndicate.features.shared.board_enrichment as mod

    grid = [_row({"projected": 5.0})]
    monkeypatch.setattr(
        mod, "_attach_projections_by_sport",
        lambda g, *, sport, selected_date: {"supported": True, "rows_with_projection": 1},
    )
    coverage = mod.attach_projections(grid, sport="soccer", selected_date="2026-08-14")
    assert coverage["rows_with_projection"] == 1, "the sport's own coverage must survive"
    assert coverage["rows_with_unmeasured_skill"] == 1
    assert grid[0]["projection"]["model_skill"]["status"] == STATUS_UNMEASURED


def test_a_skill_scan_failure_cannot_break_the_join(monkeypatch):
    """Same rule as the degeneracy scan: a reporting check must never take down
    the thing it reports on."""
    import syndicate.features.shared.board_enrichment as mod
    import syndicate.features.shared.projection_skill as skill_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("skill scan exploded")

    monkeypatch.setattr(
        mod, "_attach_projections_by_sport",
        lambda g, *, sport, selected_date: {"supported": True, "rows_with_projection": 3},
    )
    monkeypatch.setattr(skill_mod, "attach_projection_skill", _boom)
    coverage = mod.attach_projections([], sport="mlb", selected_date="2026-08-14")
    assert coverage["supported"] is True
    assert coverage["rows_with_projection"] == 3


def test_degeneracy_and_skill_are_independent_signals():
    """A varying-but-unmeasured board must report unmeasured skill and NO
    degeneracy; the two checks answer different questions and neither implies
    the other."""
    import syndicate.features.shared.board_enrichment as mod

    grid = [
        {"kind": "game", "market": "totals", "segment": "full", "event_id": f"g{i}",
         "projection": {"projected": 40.0 + i}}
        for i in range(8)
    ]
    degeneracy = mod.detect_degenerate_projections(grid, sport="soccer")
    skill = attach_projection_skill(grid, sport="soccer")
    assert degeneracy == {}, "values vary, so nothing is degenerate"
    assert skill["rows_with_unmeasured_skill"] == 8, "but nothing has been measured either"
