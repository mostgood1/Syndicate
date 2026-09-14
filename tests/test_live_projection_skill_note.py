"""A live PROP row states the live re-sim's record, not the pregame model's.

Lane `accuracy-assessment-0914`. `live_projection_join.attach_live_projections`
switches a prop projection to the live re-sim (`basis: live_resim`, live
`model_prob_over`, `live_aware`) and used to leave the pregame `model_skill`
beside it -- e.g. `mlb_prop_calibration`'s hitter note, which measures the
PREGAME model. The same defect as the live game-line join, on the second of the
two paths that set `live_aware`.
"""

from __future__ import annotations

import pytest

import syndicate.features.shared.measured_market_skill as mms
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
)
from syndicate.features.shared.projection_skill import STATUS_MEASURED, STATUS_UNMEASURED

PREGAME_PROP_NOTE = {
    "status": STATUS_MEASURED,
    "sample_games": 14,
    "seasons": "2026-07-29..08-11",
    "correlation": 0.15,
    "verdict": "biased high ~29%; real ranking signal",
}


def _snapshot():
    return {"games": [{
        "status": {"abstract": "Live", "detailed": "In Progress"},
        "liveProps": [
            {"playerName": "J.D. Martinez", "market": "hits", "line": 0.5,
             "liveProjection": 1.24, "modelProbOver": 0.61, "livePropOver": 0.58,
             "actualSoFar": 1, "selection": "Over"},
        ],
    }]}


def _row(state="live", sport="mlb"):
    row = {"kind": "prop", "player_name": "JD Martinez", "market": "batter_hits",
           "line": 0.5, "game": {"state": state},
           "projection": {"projected": 0.9, "basis": "pregame",
                          "model_skill": dict(PREGAME_PROP_NOTE)}}
    if sport is not None:
        row["sport"] = sport
    return row


@pytest.fixture
def empty_table(monkeypatch):
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL", {})


def test_a_live_prop_row_does_not_keep_the_pregame_note(empty_table):
    grid = [_row()]
    coverage = attach_live_projections(grid, build_live_prop_index(_snapshot()))
    assert coverage["rows_live_projected"] == 1
    projection = grid[0]["projection"]
    assert projection["live_aware"] is True
    assert projection["model_skill"]["status"] == STATUS_UNMEASURED
    assert projection["model_skill"]["sample_games"] == 0


def test_a_live_prop_measurement_is_used_when_one_exists(monkeypatch):
    entry = {"sample_games": 60, "seasons": "test", "verdict": "live props: test verdict",
             "verdict_class": mms.VERDICT_PARITY, "source": "test"}
    monkeypatch.setattr(mms, "MEASURED_MARKET_SKILL",
                        {("mlb", "batter_hits", "full", mms.PHASE_LIVE): entry})
    grid = [_row()]
    attach_live_projections(grid, build_live_prop_index(_snapshot()))
    skill = grid[0]["projection"]["model_skill"]
    assert skill["status"] == STATUS_MEASURED
    assert skill["verdict"] == "live props: test verdict"


def test_a_pregame_prop_row_keeps_its_note(empty_table):
    grid = [_row(state="pregame")]
    attach_live_projections(grid, build_live_prop_index(_snapshot()))
    assert "live_aware" not in grid[0]["projection"]
    assert grid[0]["projection"]["model_skill"] == PREGAME_PROP_NOTE


def test_an_unmatched_live_prop_row_keeps_its_note(empty_table):
    grid = [_row()]
    grid[0]["player_name"] = "Nobody Here"
    attach_live_projections(grid, build_live_prop_index(_snapshot()))
    assert "live_aware" not in grid[0]["projection"]
    assert grid[0]["projection"]["model_skill"] == PREGAME_PROP_NOTE
