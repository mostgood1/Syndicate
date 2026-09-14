"""Live rows state the LIVE model's record, and first5 observations pair like with like.

Lane `accuracy-assessment-0914`, two defects on one join, both measured on the
production live game-line ledger 2026-08-31..09-13:

1. `_apply_verdict` copied the pregame projection, `model_skill` included, onto
   every live-joined row. MLB live rows therefore said "model never backtested"
   while the live model had its own 176-game measurement (it loses to the live
   market, Brier +0.010 [+0.001, +0.020]). A pregame note is wrong on a live
   row even when it is a real measurement: it describes a different model.
2. The first5 OBSERVATION computed a home-win probability for every first5 row
   and paired it with `market_fair_prob_over`, which on totals/spreads rows is
   P(over) / P(home covers). 43,269 such rows, ~85% of ledger volume since 09-08.

The mechanism tests inject their own table entries, so they do not move when
the measured numbers do.
"""

from __future__ import annotations

import pytest

import syndicate.features.shared.measured_market_skill as mms
from syndicate.features.shared.live_gameline_join import (
    REASON_NOT_PRICEABLE,
    REASON_SEGMENT_PRICING_DISABLED,
    REFUSAL_KEY,
    attach_live_gamelines,
    build_live_gameline_index,
)
from syndicate.features.shared.projection_skill import STATUS_MEASURED, STATUS_UNMEASURED

PREGAME_NOTE = {
    "status": STATUS_MEASURED,
    "correlation": None,
    "sample_games": 482,
    "seasons": "2026-06-17..08-30",
    "verdict": "pregame: loses to the de-vigged close",
}

LIVE_ENTRY = {
    "sample_games": 176,
    "seasons": "2026-08-31..09-13 live",
    "verdict": "live: loses to the market over 176 games",
    "verdict_class": mms.VERDICT_LOSES,
    "source": "test",
}


@pytest.fixture(autouse=True)
def _publishing_env(monkeypatch):
    # The publish switch is not what these tests are about; keep it out.
    monkeypatch.delenv("SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_FIRST5_PRICING", raising=False)


@pytest.fixture
def live_table(monkeypatch):
    monkeypatch.setattr(
        mms, "MEASURED_MARKET_SKILL", {("mlb", "h2h", "full", mms.PHASE_LIVE): dict(LIVE_ENTRY)}
    )


@pytest.fixture
def empty_table(monkeypatch):
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", {})


def _snapshot(prob=0.6842):
    return {"games": [{
        "gamePk": 823184,
        "status": {"abstract": "Live"},
        "matchup": {"away": {"name": "Colorado Rockies", "abbr": "COL"},
                    "home": {"name": "San Francisco Giants", "abbr": "SF"}},
        "gameLens": [{"key": "live", "source": "live_mc", "modelHomeWinProb": prob,
                      "simsRun": 120, "projection": {"total": 8.5, "homeMargin": 0.7}}],
    }]}


def _row(market_prob=0.50, sport="mlb", note=PREGAME_NOTE):
    row = {
        "kind": "game", "market": "h2h", "segment": "full",
        "away_team": "Colorado Rockies", "home_team": "San Francisco Giants",
        "age_seconds": 30.0,
        "game": {"state": "live"},
        "projection": {"market_fair_prob_over": market_prob, "edge_vs_market_pct": None},
    }
    if sport is not None:
        row["sport"] = sport
    if note is not None:
        row["projection"]["model_skill"] = dict(note)
    return row


# --------------------------------------------------------------------------
# 1. the skill note on a live-joined row
# --------------------------------------------------------------------------


def test_a_live_joined_row_carries_the_live_measurement_not_the_pregame_note(live_table):
    grid = [_row()]
    attach_live_gamelines(grid, build_live_gameline_index(_snapshot()))
    projection = grid[0]["projection"]
    assert projection["live_aware"] is True
    skill = projection["model_skill"]
    assert skill["verdict"] == LIVE_ENTRY["verdict"]
    assert skill["sample_games"] == 176
    assert skill["status"] == STATUS_MEASURED
    assert skill["basis"] == mms.NOTE_BASIS


def test_with_no_live_measurement_the_pregame_note_is_NOT_inherited(empty_table):
    """The defect itself: a real pregame measurement must still not survive
    onto the live row, because it describes a different model."""
    grid = [_row()]
    attach_live_gamelines(grid, build_live_gameline_index(_snapshot()))
    skill = grid[0]["projection"]["model_skill"]
    assert skill["status"] == STATUS_UNMEASURED
    assert skill["sample_games"] == 0
    assert "pregame" not in skill["verdict"]


def test_the_note_is_replaced_even_when_the_edge_is_withheld(live_table):
    grid = [_row(market_prob=0.67)]
    cov = attach_live_gamelines(grid, build_live_gameline_index(_snapshot()))
    assert cov["withheld_by_reason"] == {REASON_NOT_PRICEABLE: 1}
    assert grid[0]["projection"]["model_skill"]["verdict"] == LIVE_ENTRY["verdict"]


def test_the_sport_keyword_answers_when_the_row_carries_none(live_table):
    grid = [_row(sport=None)]
    attach_live_gamelines(grid, build_live_gameline_index(_snapshot()), sport="mlb")
    assert grid[0]["projection"]["model_skill"]["verdict"] == LIVE_ENTRY["verdict"]


def test_the_rows_own_sport_wins_over_the_keyword(live_table):
    grid = [_row(sport="soccer")]
    attach_live_gamelines(grid, build_live_gameline_index(_snapshot()), sport="mlb")
    assert grid[0]["projection"]["model_skill"]["status"] == STATUS_UNMEASURED


def test_an_unmatched_row_keeps_its_pregame_note(live_table):
    """No live model priced it, so the pregame note is still the true one."""
    grid = [_row()]
    grid[0]["home_team"] = "Some Other Team"
    attach_live_gamelines(grid, build_live_gameline_index(_snapshot()))
    assert "live_aware" not in grid[0]["projection"]
    assert grid[0]["projection"]["model_skill"] == PREGAME_NOTE


def test_the_real_table_records_the_mlb_live_moneyline_loss():
    """Pins the measurement the lane shipped, so a later edit that softens it
    has to change this line on purpose."""
    entry = mms.MEASURED_MARKET_SKILL[("mlb", "h2h", "full", mms.PHASE_LIVE)]
    assert entry["verdict_class"] == mms.VERDICT_LOSES
    assert entry["sample_games"] >= 150
    assert entry["ci95"][0] > 0


# --------------------------------------------------------------------------
# 2. first5 observations pair a home-win probability only with a home price
# --------------------------------------------------------------------------

MARGIN_DIST = {2: 30, 1: 14, 0: 20, -1: 20, -2: 16}
SEG_KEY = ("texas rangers", "athletics")


def _seg_hit():
    return {
        "game_pk": 824966, "home_win_prob": 0.44, "sims_run": 100,
        "total_mean": 4.3, "home_margin": -0.2,
        "total_runs_dist": {4: 100}, "margin_dist": dict(MARGIN_DIST),
        "as_of": None, "carried_forward": False, "analytic_markets": {},
        "progress": {"fraction": 0.3}, "pregame_home_win_prob": 0.5,
    }


def _seg_row(market="h2h", fair=0.55):
    return {
        "kind": "game", "market": market, "segment": "first5", "line": None,
        "event_id": "e1", "home_team": "Athletics", "away_team": "Texas Rangers",
        "books": ["pinnacle"], "age_seconds": 5.0, "sides": ["home", "away"],
        "game": {"state": "live"},
        "projection": {"market_fair_prob_over": fair},
    }


def test_a_first5_h2h_observation_is_still_recorded():
    grid = [_seg_row("h2h", fair=0.55)]
    attach_live_gamelines(grid, {}, segment_index={SEG_KEY: _seg_hit()})
    refusal = grid[0][REFUSAL_KEY]
    assert refusal["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED
    assert refusal["observed_model_prob"] == pytest.approx(0.55)
    assert refusal["observed_market_prob"] == pytest.approx(0.55)
    assert refusal["observed_edge_pp"] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("market", ["totals", "spreads"])
def test_a_first5_totals_or_spreads_observation_carries_no_home_win_probability(market):
    """43,269 production rows paired P(home wins) with P(over)/P(cover)."""
    grid = [_seg_row(market, fair=0.52)]
    attach_live_gamelines(grid, {}, segment_index={SEG_KEY: _seg_hit()})
    refusal = grid[0][REFUSAL_KEY]
    # still RECORDED, by name -- the denominator survives
    assert refusal["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED
    assert refusal["priceable"] is False
    # but no cross-market observation
    assert refusal["observed_model_prob"] is None
    assert refusal["observed_market_prob"] is None
    assert refusal["observed_edge_pp"] is None
