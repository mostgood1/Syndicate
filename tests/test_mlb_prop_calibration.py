"""`#428`: the MLB hitter-prop skill measurement, and its wiring.

WHAT WAS MEASURED. 2,487 player-games over 2026-08-01..08-14, joined on
`batter_id` (an exact MLB StatsAPI person id) to real box scores. The verdict is
neither "skilled" nor "no skill": the model is **biased, not blind** — every
counting market carries real signal and loses to a constant baseline purely by
sitting too high, and de-biasing flips 5 of 7 to beating it.

THE TEST THAT MATTERS MOST is that an UNMEASURED market gets nothing. Handing a
market a neighbour's number would be `#377` all over again — an authoritative
figure that does not describe the thing it is attached to. `batter_hits_runs_rbis`
is the live example: it was the degenerate `0.0` throughout the backtest window
(`#429`), so it has no measurement and must stay `unmeasured`.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.mlb_prop_calibration import (
    OPPORTUNITY_BIAS,
    SAMPLE_PLAYER_GAMES,
    skill_note,
)

MEASURED = [
    "batter_hits", "batter_total_bases", "batter_rbis", "batter_runs_scored",
    "batter_doubles", "batter_triples", "batter_stolen_bases",
]


@pytest.mark.parametrize("market", MEASURED)
def test_measured_markets_carry_a_note_with_its_sample_size(market):
    note = skill_note(market)
    assert note is not None
    # n travels with the number, always. #377 and #429 were both authoritative
    # figures with no sample behind them.
    assert note["sample_games"] == SAMPLE_PLAYER_GAMES == 2487
    assert isinstance(note["correlation"], float)
    assert note["verdict"]


@pytest.mark.parametrize("market", ["batter_hits_runs_rbis", "batter_home_runs"])
def test_unmeasured_markets_get_NOTHING(market):
    """THE LOAD-BEARING ONE. hrr was the degenerate 0.0 for the whole backtest
    window, so it has no measurement. Returning None lets projection_skill stamp
    `unmeasured`; returning a neighbour's number would be a fabricated claim."""
    assert skill_note(market) is None


def test_unknown_market_is_not_given_a_number():
    assert skill_note("batter_moon_landings") is None
    assert skill_note("") is None
    assert skill_note(None) is None


def test_the_note_is_small_because_it_lands_on_every_row():
    """`#374`: extraHitterProps reached 68% of the MLB live-lens payload at 117
    keys per record. The full numbers live in the module, not on the row.

    Grew to five keys for `D4` (2026-08-15): every verdict says "until
    de-biased" and that de-biasing is in-sample, so the row has to carry its own
    validation state or a reader trusts it by default. The ceiling is still the
    point of this test -- adding a SIXTH key needs the same argument made again,
    not a quiet edit here.
    """
    note = skill_note("batter_hits")
    assert set(note) == {
        "sample_games", "seasons", "correlation", "verdict", "debias_validation",
    }


def test_the_row_declares_the_debias_is_in_sample():
    """`D4`. The published improvement is a fit, not a prediction, until the
    out-of-sample split in `scripts/backtest_mlb_props.py` is run against
    production. A row asserting the verdict without this is overstating."""
    for market in ("batter_hits", "batter_total_bases", "batter_stolen_bases"):
        assert skill_note(market)["debias_validation"] == "in_sample"


def test_verdicts_do_not_claim_skill_the_data_does_not_support():
    """Every counting market LOSES to a constant baseline as published. A
    verdict implying it is accurate would be the #377 failure."""
    for market in ("batter_hits", "batter_total_bases", "batter_rbis", "batter_runs_scored"):
        verdict = skill_note(market)["verdict"].lower()
        assert "biased high" in verdict
        assert "de-biased" in verdict


def test_the_no_signal_markets_say_so_plainly():
    assert "no measured skill" in skill_note("batter_triples")["verdict"].lower()
    assert "almost no signal" in skill_note("batter_doubles")["verdict"].lower()


def test_stolen_bases_is_recorded_as_the_exception_and_biased_LOW():
    """It is the only market that beats the mean as published, and its bias runs
    the other way. Flattening that into the others' wording would misdescribe it."""
    verdict = skill_note("batter_stolen_bases")["verdict"].lower()
    assert "beats the mean" in verdict
    assert "low" in verdict


def test_opportunity_bias_records_that_a_pa_fix_is_not_sufficient():
    """The measured split was 55% explained by opportunity, 12.2% residual. A
    reader must not come away thinking one upstream fix removes the inflation."""
    assert OPPORTUNITY_BIAS["pa_mean_inflation_pct"] == pytest.approx(18.4)
    assert OPPORTUNITY_BIAS["per_pa_rate_inflation_pct"] == pytest.approx(12.2)
    assert OPPORTUNITY_BIAS["share_of_count_bias_explained_by_opportunity_pct"] == 55
    assert "ALONE will not remove" in OPPORTUNITY_BIAS["note"]


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------


def _index_with_row(market_bucket="hits_2plus", mean_key="h_mean", value=1.2):
    from syndicate.features.shared.prop_projections import PropProjectionIndex

    index = PropProjectionIndex()
    index._hitters[("test player", market_bucket)] = {
        "name": "Test Player", "p_h_2plus": 0.4, mean_key: value,
    }
    index._hitter_means["test player"] = {mean_key: value}
    return index


def test_a_measured_market_row_carries_the_note_end_to_end():
    index = _index_with_row()
    out = index.project(player_name="Test Player", market="batter_hits", line=1.5)
    assert out["projected"] == 1.2
    assert out["model_skill"]["sample_games"] == 2487
    assert "biased high" in out["model_skill"]["verdict"]


def test_an_unmeasured_market_row_carries_NO_note_so_projection_skill_can_stamp_it():
    index = _index_with_row("hits_runs_rbis_2plus", "hrr_mean", 2.1)
    out = index.project(player_name="Test Player", market="batter_hits_runs_rbis", line=1.5)
    assert out["projected"] == 2.1
    assert "model_skill" not in out, "an unmeasured market must reach projection_skill bare"


def test_projection_skill_then_stamps_that_row_unmeasured():
    """The two halves compose: the producer says nothing, the shared pass says
    `unmeasured`. Neither invents a number."""
    from syndicate.features.shared.projection_skill import attach_projection_skill

    index = _index_with_row("hits_runs_rbis_2plus", "hrr_mean", 2.1)
    out = index.project(player_name="Test Player", market="batter_hits_runs_rbis", line=1.5)
    grid = [{"kind": "prop", "market": "batter_hits_runs_rbis", "segment": "full",
             "event_id": "g1", "projection": out}]
    attach_projection_skill(grid, sport="mlb")
    assert grid[0]["projection"]["model_skill"]["status"] == "unmeasured"


def test_projection_skill_leaves_a_measured_note_intact():
    from syndicate.features.shared.projection_skill import attach_projection_skill

    index = _index_with_row()
    out = index.project(player_name="Test Player", market="batter_hits", line=1.5)
    grid = [{"kind": "prop", "market": "batter_hits", "segment": "full",
             "event_id": "g1", "projection": out}]
    attach_projection_skill(grid, sport="mlb")
    skill = grid[0]["projection"]["model_skill"]
    assert skill["status"] == "measured"
    assert skill["correlation"] == 0.1607, "the measurement must not be reworded"


def test_a_broken_calibration_module_cannot_break_the_join(monkeypatch):
    """Breaks the thing the guard actually calls -- `skill_note` -- and asserts
    the JOIN still returns.

    An earlier version of this test patched `_attach_measured_skill` itself and
    then asserted it raised, which tested the monkeypatch rather than the guard
    and would have passed against a completely unprotected join. A test whose
    name does not match what it asserts is the same defect as a watcher label
    its exit condition does not entail.
    """
    import syndicate.features.shared.mlb_prop_calibration as calibration

    def _boom(*args, **kwargs):
        raise RuntimeError("calibration exploded")

    monkeypatch.setattr(calibration, "skill_note", _boom)

    index = _index_with_row()
    out = index.project(player_name="Test Player", market="batter_hits", line=1.5)
    assert out is not None, "a broken calibration must not take down the projection"
    assert out["projected"] == 1.2, "the projection itself must be unaffected"
    assert "model_skill" not in out, "and it must fall through bare, not half-written"
