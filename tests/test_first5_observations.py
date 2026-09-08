"""first5 is RECORDED, never published. The board must be byte-identical.

`[2026-09-08, user decision: "record first5 as observations"]`, taken instead of
turning `SYNDICATE_MLB_FIRST5_PRICING` on.

WHY NOT JUST TURN IT ON. A board row carrying `edge_vs_market_pct` reaches the
Layer 2 shortlist, and the shortlist is what `portfolio_commit` reads -- so it
becomes an ORDER CANDIDATE. Segments already reach that shortlist (30 of 102
rows on the served board, 2026-08-16), so this is not hypothetical. The LIVE
first-five probability has never been scored for skill, and the alternative
(gating the order path) needs `pipeline/portfolio_commit.py`, which another
session holds uncommitted work in.

So the price is computed and written to the LEDGER ONLY. The three tests that
matter are the negative ones: no `live_gameline` block, no `edge_vs_market_pct`,
`priceable` false. If any of those regress, first5 edges are reaching money.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_gameline_join import (  # noqa: E402
    REASON_SEGMENT_PRICING_DISABLED,
    REFUSAL_KEY,
    attach_live_gamelines,
)
from syndicate.features.shared.live_gameline_ledger import build_records  # noqa: E402

MARGIN_DIST = {2: 30, 1: 14, 0: 20, -1: 20, -2: 16}   # home 44 / tie 20 / away 36


def _hit(**over):
    base = {"game_pk": 824966, "home_win_prob": 0.44, "sims_run": 100,
            "total_mean": 4.3, "home_margin": -0.2, "total_runs_dist": {4: 100},
            "margin_dist": dict(MARGIN_DIST), "as_of": None,
            "carried_forward": False, "analytic_markets": {},
            "progress": {"fraction": 0.3}, "pregame_home_win_prob": 0.5}
    base.update(over)
    return base


def _row(segment="first5", fair=0.40):
    return {"kind": "game", "market": "h2h", "segment": segment, "line": None,
            "event_id": "e1", "home_team": "Athletics", "away_team": "Texas Rangers",
            "books": ["pinnacle"], "age_seconds": 5.0, "sides": ["home", "away"],
            "game": {"state": "live"},
            "projection": {"market_fair_prob_over": fair}}


KEY = ("texas rangers", "athletics")


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch):
    """Every test here runs with pricing OFF -- that is the shipped state."""
    monkeypatch.delenv("SYNDICATE_MLB_FIRST5_PRICING", raising=False)


class TestTheBoardIsUntouched:
    """The three negatives. A regression in any one puts money behind an
    unscored model, which is the whole reason this shape was chosen."""

    def test_no_live_gameline_block_is_attached(self):
        grid = [_row()]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        assert "live_gameline" not in grid[0], (
            "a live_gameline block reaches layer2_board's candidate, and from "
            "there the shortlist and portfolio_commit")

    def test_no_edge_reaches_the_projection(self):
        """`edge_vs_market_pct` is the field `portfolio_commit` refuses on when
        absent (`no_model_edge_pct`). It must stay absent."""
        grid = [_row()]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        assert grid[0]["projection"] == {"market_fair_prob_over": 0.40}
        assert "edge_vs_market_pct" not in grid[0]["projection"]
        assert "live_aware" not in grid[0]["projection"]

    def test_the_ledger_row_is_NOT_priceable(self):
        grid = [_row()]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        rec = build_records(grid, sport="mlb", date_str="2026-09-08")[0]
        assert rec["priceable"] is False
        assert rec["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED


class TestTheObservationIsRecorded:
    def test_the_ledger_carries_model_market_and_edge(self):
        grid = [_row(fair=0.40)]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        rec = build_records(grid, sport="mlb", date_str="2026-09-08")[0]
        # two-way row -> conditional 44/(44+36) = 0.55, market 0.40
        assert rec["model_home_win_prob"] == pytest.approx(0.55)
        assert rec["market_fair_prob"] == pytest.approx(0.40)
        assert rec["edge_pp"] == pytest.approx(15.0, abs=0.6)
        assert rec["segment"] == "first5"

    def test_it_is_rounded_to_2dp_which_is_the_VOLUME_bound(self):
        """`_moved` dedupes on exactly these fields. At full precision every
        build would rewrite every first5 row, and `append_records` stops writing
        for the REST OF THE DAY at `_MAX_RECORDS_PER_FILE` -- MLB was already at
        8,070 rows against a 20,000 cap. 2dp means a rewrite only on a real
        >= 0.01 move, finer than any question this series will be asked."""
        grid = [_row(fair=0.4067)]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        rec = build_records(grid, sport="mlb", date_str="2026-09-08")[0]
        for field in ("model_home_win_prob", "market_fair_prob"):
            assert rec[field] == round(rec[field], 2), (field, rec[field])

    def test_with_NO_segment_lane_there_is_no_observation(self):
        """Absent must stay absent -- an observation invented without a lens hit
        would be a number with no producer."""
        grid = [_row()]
        attach_live_gamelines(grid, {}, segment_index={})
        rec = build_records(grid, sport="mlb", date_str="2026-09-08")[0]
        assert rec["model_home_win_prob"] is None
        assert rec["market_fair_prob"] is None
        assert rec["edge_pp"] is None

    def test_a_first3_row_gets_no_observation_either(self):
        """Only first5 has a Monte-Carlo readout. first3/first1 remain
        interpolations and must not acquire a number that looks measured."""
        grid = [_row(segment="first3")]
        attach_live_gamelines(grid, {}, segment_index={KEY: _hit()})
        rec = build_records(grid, sport="mlb", date_str="2026-09-08")[0]
        assert rec["model_home_win_prob"] is None


class TestTheFullGamePathIsUnchanged:
    def test_a_full_game_row_still_prices_and_publishes(self):
        grid = [_row(segment="full", fair=0.20)]
        attach_live_gamelines(grid, {KEY: _hit()}, segment_index={KEY: _hit()})
        assert "live_gameline" in grid[0]
        assert REFUSAL_KEY not in grid[0]
        assert grid[0]["projection"].get("edge_vs_market_pct") is not None
