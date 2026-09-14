"""The registry that replaces "model never backtested" where a measurement exists.

The load-bearing tests are the phase test (a pregame measurement must never
label a live re-sim's number) and the admission pin (relabelling a one-sided
market re-admits rows the Layer 2 gate withholds). The table's real entries
are checked for shape and provenance here; the mechanism is tested against
entries injected by the test, so it does not move when the numbers do.
"""

from __future__ import annotations

import pytest

import syndicate.features.shared.measured_market_skill as mms

ENTRY = {
    "sample_games": 220,
    "seasons": "2026-08-31..09-13, production",
    "correlation": None,
    "verdict": "loses to the de-vigged close: Brier +0.004 [+0.001,+0.007] over 220 games",
    "verdict_class": mms.VERDICT_LOSES,
    "source": "lane accuracy-assessment-0914",
}


@pytest.fixture
def table(monkeypatch):
    fake = {("mlb", "totals", "full", mms.PHASE_PREGAME): dict(ENTRY)}
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", fake)
    return fake


def test_unknown_market_returns_none(table):
    assert mms.skill_note(sport="mlb", market="h2h") is None
    assert mms.skill_note(sport="soccer", market="totals") is None


def test_lookup_normalises_case_whitespace_and_missing_segment(table):
    note = mms.skill_note(sport=" MLB ", market="Totals", segment=None)
    assert note is not None
    assert note["sample_games"] == 220


def test_a_pregame_measurement_never_labels_a_live_projection(table):
    assert mms.skill_note(sport="mlb", market="totals", phase=mms.PHASE_LIVE) is None


def test_a_segment_measurement_is_not_the_full_game_one(table):
    assert mms.skill_note(sport="mlb", market="totals", segment="first5") is None


def test_phase_comes_from_the_projection_not_the_game():
    assert mms.projection_phase({"live_aware": True}) == mms.PHASE_LIVE
    assert mms.projection_phase({"live_aware": False}) == mms.PHASE_PREGAME
    assert mms.projection_phase({}) == mms.PHASE_PREGAME


def test_note_is_compact_and_carries_no_status(table):
    note = mms.skill_note(sport="mlb", market="totals")
    assert set(note) == {"correlation", "sample_games", "seasons", "verdict", "verdict_class", "basis",
                         "established_loss_rel"}
    assert note["basis"] == mms.NOTE_BASIS


def test_note_is_a_copy(table):
    note = mms.skill_note(sport="mlb", market="totals")
    note["verdict"] = "rewritten"
    assert mms.skill_note(sport="mlb", market="totals")["verdict"] == ENTRY["verdict"]


# --------------------------------------------------------------------------
# the real table
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(mms.MEASURED_MARKET_SKILL))
def test_every_real_entry_cites_a_measurement(key):
    entry = mms.MEASURED_MARKET_SKILL[key]
    for field in mms.REQUIRED_ENTRY_KEYS:
        assert entry.get(field) not in (None, ""), f"{key} lacks {field}"
    assert entry["verdict_class"] in mms.VERDICT_CLASSES
    assert isinstance(entry["sample_games"], int) and entry["sample_games"] > 0
    assert len(entry["verdict"]) <= 140, "the verdict repeats on every row"
    sport, market, segment, phase = key
    assert key == (sport.lower(), market.lower(), segment.lower(), phase)
    assert phase in {mms.PHASE_PREGAME, mms.PHASE_LIVE}


@pytest.mark.parametrize("key", sorted(mms.MEASURED_MARKET_SKILL))
def test_relabelling_cannot_silently_readmit_one_sided_rows(key):
    """`layer2_board._row_rests_on_unmeasured_model` withholds one-sided rows
    whose model is not `measured`. A losing model on a one-sided market must
    not pass that gate just because it now has a number."""
    entry = mms.MEASURED_MARKET_SKILL[key]
    _, market, _, _ = key
    if entry["verdict_class"] == mms.VERDICT_BEATS or market in mms.TWO_SIDED_GAME_MARKETS:
        return
    assert entry.get("admission_checked"), (
        f"{key} is not a two-sided game market and does not beat the market; "
        "name the served-board reading that shows its rows are two-sided"
    )
