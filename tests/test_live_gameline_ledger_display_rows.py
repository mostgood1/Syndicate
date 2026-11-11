"""The live gameline ledger records the board's DISPLAY-ONLY number and its market (v6, lane nhl-live-puckline-grade).

`#773` made live NHL puck-line rows show P(home covers) off the re-sim's histogram, refused
`live_margin_published_for_display_only`. The v5 record of that row carried no model or market probability (nothing
was priced), and `_moved` -- which compares only those -- wrote it once per key per day. So production's own
number, and the market beside it, could never be graded. These pin:
  - REACHABILITY: through the REAL producer snapshot and the join's own attach, the record carries the display
    number the row shows and the market's de-vig for the same event; a row without the block records None;
  - MOVEMENT: a display-only puck-line row is re-recorded when its number or market moves at 2 dp, and not when
    it does not;
  - SCOPE: the movement trigger is that refusal only, so no other row's write rate changes.
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl import live_resim as LR
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared import live_gameline_ledger as L
from syndicate.features.shared.live_gameline_join import (
    LIVE_DISPLAY_KEY,
    REASON_MARGIN_DISPLAY_ONLY,
    attach_live_gamelines,
    build_live_gameline_index,
    lens_sources_for_sport,
)
from tests.test_nhl_live_resim import _StubFeatures

DATE = "2026-10-08"
GAME_PK = "2026020123"
HOME, AWAY = "Toronto Maple Leafs", "Ottawa Senators"


def _score_row():
    return {
        "id": int(GAME_PK), "gameState": "LIVE", "periodDescriptor": {"number": 2, "periodType": "REG"},
        "clock": {"timeRemaining": "10:00", "secondsRemaining": 600, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": 1},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": 1},
    }


@pytest.fixture(scope="module")
def snapshot():
    snap = LR.build_live_lens_snapshot(DATE, sims=60, score_rows=[_score_row()],
                                       slate_features=[_StubFeatures(GAME_PK, HOME, AWAY)])
    assert snap["games"][0]["gameLens"][0]["source"] == LR.LIVE_RESIM_LENS_SOURCE
    return snap


@pytest.fixture(autouse=True)
def _gate_defaults(monkeypatch):
    for key in (lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV, "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS",
                "MLB_LIVE_GAMELINE_LEDGER_ENABLED"):
        monkeypatch.delenv(key, raising=False)


def _row(market="spreads", line=-1.5, market_prob=0.62):
    sides = ["over", "under"] if market.startswith("totals") else ["home", "away"]
    return {"kind": "game", "sport": "nhl", "market": market, "segment": "full", "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0, "books": ["draftkings", "fanduel"],
            "game": {"state": "live", "home_score": 1, "away_score": 1},
            "projection": {"market_fair_prob_over": market_prob}}


def _joined(snap, rows):
    index = build_live_gameline_index(snap, sources=lens_sources_for_sport("nhl"), sport="nhl", slate_date=DATE)
    attach_live_gamelines(rows, index, sport="nhl")
    return rows


def test_reachability_the_record_carries_the_number_the_board_shows(snapshot):
    (row,) = _joined(snapshot, [_row()])
    assert row["live_gameline"]["withheld_reason"] == REASON_MARGIN_DISPLAY_ONLY      # the branch under test
    (rec,) = L.build_records([row], sport="nhl", date_str=DATE)
    assert rec["v"] == 6
    assert rec["display_prob"] == row[LIVE_DISPLAY_KEY]["prob_over"] is not None
    assert rec["display_basis"] == REASON_MARGIN_DISPLAY_ONLY
    assert rec["market_fair_prob_over"] == 0.62
    # Still nothing priced: the v5 fields a CLV or pricing reader uses are unchanged.
    assert rec["model_home_win_prob"] is None and rec["market_fair_prob"] is None and rec["edge_pp"] is None
    assert rec["priceable"] is False


def test_off_a_row_without_a_display_block_records_none(snapshot):
    (row,) = _joined(snapshot, [_row()])
    row.pop(LIVE_DISPLAY_KEY)
    (rec,) = L.build_records([row], sport="nhl", date_str=DATE)
    assert rec["display_prob"] is None and rec["display_basis"] is None


def test_h2h_does_not_store_its_market_twice(snapshot):
    (row,) = _joined(snapshot, [_row(market="h2h", line=None, market_prob=0.55)])
    (rec,) = L.build_records([row], sport="nhl", date_str=DATE)
    assert rec["market_fair_prob_over"] is None


def _rec(**kw):
    base = {"withheld_reason": REASON_MARGIN_DISPLAY_ONLY, "model_home_win_prob": None, "market_fair_prob": None,
            "edge_pp": None, "priceable": False, "display_prob": 0.7255, "market_fair_prob_over": 0.62}
    base.update(kw)
    return base


def test_a_display_only_row_moves_on_its_number_or_its_market_at_two_dp():
    prev = _rec()
    assert L._moved(prev, _rec(display_prob=0.7402)) is True          # 0.73 -> 0.74
    assert L._moved(prev, _rec(market_fair_prob_over=0.60)) is True
    assert L._moved(prev, _rec(display_prob=0.7284)) is False         # 0.73 -> 0.73: a re-sim, not a move
    assert L._moved(prev, _rec()) is False


def test_the_trigger_is_scoped_to_the_display_only_refusal():
    for reason in ("live_resim_published_no_distribution_for_this_market", "quote_older_than_live_pricing_ceiling",
                   None):
        prev = _rec(withheld_reason=reason)
        assert L._moved(prev, _rec(withheld_reason=reason, display_prob=0.31, market_fair_prob_over=0.4)) is False


def test_append_writes_each_moved_state_and_skips_a_repeat(snapshot, tmp_path):
    path = tmp_path / "ledger.jsonl"
    (row,) = _joined(snapshot, [_row()])
    first = L.build_records([row], sport="nhl", date_str=DATE)
    assert L.append_records(path, first)["written"] == 1
    assert L.append_records(path, first)["written"] == 0               # same build again: no write
    moved = [dict(first[0], market_fair_prob_over=0.50)]
    assert L.append_records(path, moved)["written"] == 1
    assert [r["market_fair_prob_over"] for r in L.read_records(path)] == [0.62, 0.50]


def test_refusal_records_carry_the_v6_keys_as_null():
    row = _row()
    row[lgj.REFUSAL_KEY] = {"withheld_reason": "segment_is_not_full_game"}
    (rec,) = L.build_records([row], sport="nhl", date_str=DATE)
    assert rec["v"] == 6
    assert rec["display_prob"] is None and rec["market_fair_prob_over"] is None and rec["display_basis"] is None
