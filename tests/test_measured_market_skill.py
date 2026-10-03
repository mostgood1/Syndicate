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


# --------------------------------------------------------------------------
# soccer, re-measured 2026-10-03 (lane soccer-skill-registry-line-weighting)
# --------------------------------------------------------------------------


def test_soccer_pregame_totals_now_reads_its_larger_sample_loss():
    note = mms.skill_note(sport="soccer", market="totals")
    assert note["verdict_class"] == mms.VERDICT_LOSES
    assert note["sample_games"] >= 492
    assert note["established_loss_rel"] > 0


@pytest.mark.parametrize("alias,base", [("totals_alt", "totals"), ("spreads_alt", "spreads"), ("h2h_3_way", "h2h")])
def test_soccer_alias_keys_read_their_base_market_verdict(alias, base):
    a, b = mms.skill_note(sport="soccer", market=alias), mms.skill_note(sport="soccer", market=base)
    assert a is not None and b is not None
    assert (a["verdict_class"], a["established_loss_rel"], a["sample_games"]) == (b["verdict_class"], b["established_loss_rel"], b["sample_games"])
    assert mms.MEASURED_MARKET_SKILL[("soccer", alias, "full", mms.PHASE_PREGAME)].get("admission_checked")


def test_soccer_alias_never_labels_a_live_row():
    assert mms.skill_note(sport="soccer", market="totals_alt", phase=mms.PHASE_LIVE) is None

# ---- key SHAPE: the board's display case vs the table's snake_case -----------------
#
# REACHABILITY BEFORE CORRECTNESS. These assert `off != on`: that the board's own
# spelling resolves NOW and provably did not before. Measured 2026-10-03 on the fleet,
# 1,910 of 2,622 NFL Layer 2 rows matched nothing because `_norm` only lowercases, and
# six entries were unreachable while their tests passed -- the tests all used the
# snake_case spelling no board row ever carries.


@pytest.fixture
def spaced_table(monkeypatch):
    fake = {("nfl", "receiving_yards", "full", mms.PHASE_PREGAME): dict(ENTRY)}
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", fake)
    return fake


def test_the_boards_display_cased_market_reaches_the_snake_case_entry(spaced_table):
    note = mms.skill_note(sport="nfl", market="Receiving Yards", segment="full")
    assert note is not None, "the board names this market 'Receiving Yards'"
    assert note["sample_games"] == 220


def test_that_lookup_would_have_missed_under_a_lowercase_only_norm(spaced_table):
    """off != on: the old behaviour, reproduced, so the fix cannot be a no-op."""
    assert "receiving yards" not in {k[1] for k in spaced_table}
    assert mms.MEASURED_MARKET_SKILL.get(
        ("nfl", "receiving yards", "full", mms.PHASE_PREGAME)
    ) is None


def test_the_bridge_is_additive_and_never_reorders_an_exact_hit(monkeypatch):
    """An exact spelling wins over the bridged one, so no resolved lookup moves."""
    fake = {
        ("nfl", "passing tds", "full", mms.PHASE_PREGAME): dict(ENTRY, sample_games=1),
        ("nfl", "passing_tds", "full", mms.PHASE_PREGAME): dict(ENTRY, sample_games=2),
    }
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", fake)
    assert mms.skill_note(sport="nfl", market="Passing TDs")["sample_games"] == 1


def test_a_snake_case_market_tries_exactly_one_spelling():
    assert mms._market_key_candidates("receiving_yards") == ("receiving_yards",)
    assert mms._market_key_candidates("Receiving Yards") == (
        "receiving yards", "receiving_yards")
    assert mms._market_key_candidates(None) == ("",)


# ---- a SUPERSEDED entry is not a measurement --------------------------------------


def test_a_superseded_entry_yields_no_note_at_all(monkeypatch):
    """Returning its numbers would discount a row by a reading already called stale."""
    fake = {("nfl", "interceptions", "full", mms.PHASE_PREGAME): dict(
        ENTRY, superseded="2026-10-03: under-powered on re-measurement; treat as unmeasured")}
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", fake)
    assert mms.skill_note(sport="nfl", market="interceptions") is None
    assert mms.skill_note(sport="nfl", market="Interceptions") is None


def test_the_two_real_superseded_nfl_entries_reach_no_board_row():
    """Against the REAL table: both must be unmeasured, by either spelling."""
    for market, spelled in (("interceptions", "Interceptions"),
                            ("passing_tds", "Passing TDs")):
        entry = mms.MEASURED_MARKET_SKILL[("nfl", market, "full", mms.PHASE_PREGAME)]
        assert entry.get("superseded"), f"{market} should still be annotated superseded"
        assert mms.skill_note(sport="nfl", market=market) is None
        assert mms.skill_note(sport="nfl", market=spelled) is None


def test_the_six_refreshed_nfl_markets_reach_their_entries_by_board_spelling():
    """Against the REAL table, using the strings the board actually emits."""
    expected = {
        "Receiving Yards": 3116, "Receptions": 1179, "Rushing Yards": 1463,
        "Passing Yards": 834, "Rushing Attempts": 562, "Passing Attempts": 343,
    }
    for spelled, n in expected.items():
        note = mms.skill_note(sport="nfl", market=spelled, segment="full")
        assert note is not None, f"the board's {spelled!r} must reach its entry"
        assert note["sample_games"] == n, spelled
        assert note["verdict_class"] == mms.VERDICT_LOSES, spelled
