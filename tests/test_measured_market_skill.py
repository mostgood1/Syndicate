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


def test_no_nfl_pregame_prop_entry_is_superseded_any_more():
    """All eight were measured 2026-10-03, so none may still claim to be superseded.

    A `superseded` field on a measured entry makes `skill_note` return None (the gate
    below), which would silently un-measure a market that now HAS a reading.
    """
    for key, entry in mms.MEASURED_MARKET_SKILL.items():
        sport, market, segment, phase = key
        if sport != "nfl" or phase != mms.PHASE_PREGAME:
            continue
        assert not entry.get("superseded"), f"{market} still carries superseded"


def test_all_eight_nfl_prop_markets_reach_their_entries_by_board_spelling():
    """Against the REAL table, using the strings the board actually emits.

    `interceptions` is PARITY, not a loss: measured 2026-10-03 at Brier +0.0018 with a
    cluster-robust CI of [-0.0036, +0.0071] over 360 observations, which straddles zero
    while clearing the pre-registered 200-observation floor -- so parity is the reading,
    not a shortage of data. It is pinned here
    because a parity verdict and an unmeasured note are NOT interchangeable -- parity is
    a reading, and `skill_reliability` must leave its rows undiscounted for the right
    reason rather than by accident.
    """
    expected = {
        "Receiving Yards":  (6570, mms.VERDICT_LOSES),
        "Rushing Yards":    (3102, mms.VERDICT_LOSES),
        "Receptions":       (2542, mms.VERDICT_LOSES),
        "Passing Yards":    (1833, mms.VERDICT_LOSES),
        "Rushing Attempts": (1177, mms.VERDICT_LOSES),
        "Passing Attempts": ( 720, mms.VERDICT_LOSES),
        "Passing TDs":      ( 393, mms.VERDICT_LOSES),
        "Interceptions":    ( 360, mms.VERDICT_PARITY),
    }
    for spelled, (n, cls) in expected.items():
        note = mms.skill_note(sport="nfl", market=spelled, segment="full")
        assert note is not None, f"the board's {spelled!r} must reach its entry"
        assert note["sample_games"] == n, spelled
        assert note["verdict_class"] == cls, spelled


def test_the_parity_market_earns_no_discount_and_the_losing_one_does():
    """`established_loss_rel` clamps a negative lower bound to 0, so parity scores 1.0."""
    from syndicate.features.shared.projection_skill import normalize_existing_note

    parity = normalize_existing_note(
        mms.skill_note(sport="nfl", market="Interceptions", segment="full"))
    assert mms.skill_reliability(parity) == 1.0

    losing = normalize_existing_note(
        mms.skill_note(sport="nfl", market="Passing TDs", segment="full"))
    assert 0.5 <= mms.skill_reliability(losing) < 1.0


def test_every_nfl_prop_ci_lower_bound_agrees_with_its_verdict_class():
    """A LOSES entry must have a CI clear of zero; a PARITY one must straddle it.

    This is the check that would have caught the 2026-10-03 defect where the stored CIs
    were computed over book-rows rather than player-games: too-narrow CIs cannot flip a
    class, but a class asserted against a CI that contradicts it is unreadable.
    """
    for key, entry in mms.MEASURED_MARKET_SKILL.items():
        sport, market, segment, phase = key
        if sport != "nfl" or phase != mms.PHASE_PREGAME or "brier_market" not in entry:
            continue
        lo, hi = entry["ci95"]
        if entry["verdict_class"] == mms.VERDICT_LOSES:
            assert lo > 0, f"{market}: LOSES but CI lower bound {lo} is not above zero"
        elif entry["verdict_class"] == mms.VERDICT_PARITY:
            assert lo <= 0 <= hi, f"{market}: PARITY but CI [{lo}, {hi}] excludes zero"


def test_every_nfl_prop_entry_clears_the_pre_registered_observation_floor():
    """All eight were re-measured on the widened 2025 wk3-wk18 holdout.

    The 200-observation floor was set before the data was seen. The 7-week corpus put
    two markets under it; recovering 2025 wk10-18 from the already-purchased quote log
    doubled every sample, so no NFL pregame prop entry rests below the floor any more.
    If this fails, a reading was replaced by a narrower one and the verdict should be
    re-examined rather than the floor lowered.
    """
    for key, entry in mms.MEASURED_MARKET_SKILL.items():
        sport, market, segment, phase = key
        if sport != "nfl" or phase != mms.PHASE_PREGAME or "brier_market" not in entry:
            continue
        if market in ("h2h", "totals", "spreads"):
            continue
        assert entry["sample_games"] >= 200, f"{market}: {entry['sample_games']} < 200"


def test_nhl_saves_board_code_reaches_its_measured_loss():
    # the NHL grid writes the market CODE "SAVES" (lane nhl-saves-skill-registry, 2026-10-05)
    note = mms.skill_note(sport="nhl", market="SAVES", segment="full")
    assert note is not None and note["verdict_class"] == mms.VERDICT_LOSES and note["sample_games"] == 435
    assert note["established_loss_rel"] > 0                      # an established loss: it moves the row's score
    assert mms.skill_note(sport="nhl", market="SAVES", segment="full", phase=mms.PHASE_LIVE) is None
