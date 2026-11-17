"""#824 (lane ncaab-total-overprojection; user 2026-11-16 "Iona UMBC end game and PV/OSU end of half ... We need to find
a solve for this"): a live college full-game TOTAL whose projected final is below the points already scored is not
priced. Iona @ UMBC's lane projected 133.3 with 137 on the board and flagged the under 138.5 at -17 pp; it went over.

Reachability first (`off != on`): the same row through the join with the guard on, in shadow and off. Then its scope,
its order behind the quote and lane gates, an absent score, and the ledger fields that let it be graded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.college_basketball import total_prob_calibration as tpc
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared.live_gameline_join import (
    MODEL_BEHIND_SCORE_ENV,
    REASON_MODEL_BEHIND_SCORE,
    REASON_SCORE_OR_PROJECTION_ABSENT,
    attach_live_gamelines,
    build_live_gameline_index,
    model_behind_score_mode,
    model_behind_score_verdict,
)
from syndicate.features.shared.live_gameline_ledger import build_records

LANE_AT = datetime(2026, 11, 17, 0, 47, 57, tzinfo=timezone.utc)
HOME, AWAY = "UMBC Retrievers", "Iona Gaels"
LINE = 138.5
# The lane's projected final 133.3; its histogram straddles the line so the row would price.
DIST = {"130": 60, "134": 80, "140": 40, "146": 20}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv(MODEL_BEHIND_SCORE_ENV, raising=False)
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")       # the #816 calibration is not what these tests are about
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE", raising=False)
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAB", raising=False)


def _snapshot(total=133.3):
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(),
            "projection": {"total": total, "homeMargin": 6.0, "totalRunsDist": dict(DIST),
                           "marginDist": {"4": 100, "8": 100},
                           "homeScore": 70, "awayScore": 60, "period": 2, "clockSeconds": 95}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(market="totals", segment="full", home_score=72, away_score=65, line=LINE, market_prob=0.49):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    game = {"state": "live"}
    if home_score is not None:
        game["home_score"] = home_score
    if away_score is not None:
        game["away_score"] = away_score
    return {"kind": "game", "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0,
            "updated_at": (LANE_AT + timedelta(seconds=5)).isoformat(),
            "game": game, "projection": {"market_fair_prob_over": market_prob}}


def _attach(rows, sport="ncaab", total=133.3):
    index = build_live_gameline_index(_snapshot(total), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=LANE_AT + timedelta(seconds=10))


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_join(monkeypatch):
    """Iona @ UMBC, 00:50Z: 137 on the board (72-65), the lane's final 133.3, under 138.5 against a 0.49 market."""
    on = [_row()]
    cov_on = _attach(on)
    monkeypatch.setenv(MODEL_BEHIND_SCORE_ENV, "off")
    off = [_row()]
    cov_off = _attach(off)
    lg_on, lg_off = on[0]["live_gameline"], off[0]["live_gameline"]
    assert lg_on["priceable"] is False and lg_on["withheld_reason"] == REASON_MODEL_BEHIND_SCORE
    assert on[0]["projection"]["edge_vs_market_pct"] is None
    assert on[0]["projection"]["edge_unavailable_reason"] == REASON_MODEL_BEHIND_SCORE
    assert "live_model_prob_over" not in on[0]["projection"]                    # no Live number from a contradiction
    assert cov_on["withheld_by_reason"].get(REASON_MODEL_BEHIND_SCORE) == 1 and cov_on["model_behind_score_guard"] == "on"
    assert lg_off["model_prob"] is not None and lg_off.get("withheld_reason") != REASON_MODEL_BEHIND_SCORE
    assert lg_off["model_prob"] < 0.49                                          # the under it flagged
    assert REASON_MODEL_BEHIND_SCORE not in cov_off["withheld_by_reason"] and cov_off["model_behind_score_guard"] == "off"


def test_shadow_prices_as_before_and_counts_what_it_would_refuse(monkeypatch):
    monkeypatch.setenv(MODEL_BEHIND_SCORE_ENV, "shadow")
    rows = [_row()]
    cov = _attach(rows)
    assert rows[0]["live_gameline"]["model_prob"] is not None
    assert cov["model_behind_score_would_refuse"] == {"ncaab": 1}
    monkeypatch.setenv(MODEL_BEHIND_SCORE_ENV, "off")
    plain = [_row()]
    _attach(plain)
    assert rows[0]["live_gameline"]["model_prob"] == plain[0]["live_gameline"]["model_prob"]


def test_a_projection_at_or_above_the_score_still_prices():
    """Not every lane behind the board: a final 0-3 points above the score hit ABOVE its price (11-08..11-16)."""
    rows = [_row(home_score=70, away_score=62)]                                  # 132 scored, final 133.3
    cov = _attach(rows)
    assert rows[0]["live_gameline"]["model_prob"] is not None
    assert REASON_MODEL_BEHIND_SCORE not in cov["withheld_by_reason"]


def test_an_absent_score_refuses_by_name():
    rows = [_row(home_score=None)]
    cov = _attach(rows)
    assert rows[0]["live_gameline"]["withheld_reason"] == REASON_SCORE_OR_PROJECTION_ABSENT
    assert cov["withheld_by_reason"].get(REASON_SCORE_OR_PROJECTION_ABSENT) == 1


def test_the_quote_gates_still_judge_first():
    """A quote older than the lane's last score change keeps the quote reason; the new guard counts only new refusals."""
    row = _row()
    row["updated_at"] = (LANE_AT - timedelta(seconds=600)).isoformat()
    cov = _attach([row])
    assert REASON_MODEL_BEHIND_SCORE not in cov["withheld_by_reason"]
    assert sum(cov["withheld_by_reason"].values()) == 1


# --------------------------------------------------------------------------------------------- scope

@pytest.mark.parametrize("market,segment,sport", [
    ("spreads", "full", "ncaab"), ("h2h", "full", "ncaab"), ("totals", "h1", "ncaab"),
    ("totals", "full", "nba"), ("totals", "full", "ncaaf"), ("totals", "full", "mlb"),
])
def test_only_college_full_game_totals_are_judged(market, segment, sport):
    assert model_behind_score_verdict(market, segment, sport, 100.0, 70, 60) is None


@pytest.mark.parametrize("sport", ["ncaab", "wncaab", "NCAAB"])
def test_college_full_game_totals_below_the_score_refuse(sport):
    got = model_behind_score_verdict("totals", "full", sport, 133.3, 72, 65)
    assert got is not None and got["withheld_reason"] == REASON_MODEL_BEHIND_SCORE and got["priceable"] is False
    assert model_behind_score_verdict("totals", "full", sport, 137.0, 72, 65) is None   # equal is possible, not refused


@pytest.mark.parametrize("raw,mode", [(None, "on"), ("", "on"), ("on", "on"), ("shdow", "on"), ("shadow", "shadow"),
                                      ("SHADOW", "shadow"), ("off", "off"), ("0", "off"), ("false", "off")])
def test_the_switch_reads_a_typo_as_on(raw, mode):
    env = {} if raw is None else {MODEL_BEHIND_SCORE_ENV: raw}
    assert model_behind_score_mode(env) == mode


# --------------------------------------------------------------------------------------------- the ledger

def test_the_ledger_records_the_refusal_with_the_state_the_model_started_from():
    rows = [_row()]
    _attach(rows)
    rec = next(r for r in build_records(rows, sport="ncaab", date_str="2026-11-16") if r.get("market") == "totals")
    assert rec["withheld_reason"] == REASON_MODEL_BEHIND_SCORE and rec["priceable"] is False
    assert rec["model_total_mean"] == pytest.approx(133.3) and rec["home_score"] == 72 and rec["away_score"] == 65
    assert (rec["state_home_score"], rec["state_away_score"], rec["state_period"], rec["state_clock_seconds"]) == (70, 60, 2, 95)


def test_a_priced_row_carries_the_state_too(monkeypatch):
    monkeypatch.setenv(MODEL_BEHIND_SCORE_ENV, "off")
    rows = [_row()]
    _attach(rows)
    rec = next(r for r in build_records(rows, sport="ncaab", date_str="2026-11-16") if r.get("market") == "totals")
    assert rec["state_home_score"] == 70 and rec["state_period"] == 2


def test_lanes_without_a_state_carry_none():
    snap = _snapshot()
    for key in ("homeScore", "awayScore", "period", "clockSeconds"):
        del snap["games"][0]["gameLens"][0]["projection"][key]
    hit = lgj.live_gameline_from_lens(snap["games"][0]["gameLens"], sources=("live_resim",))
    assert hit is not None and hit["state_home_score"] is None and hit["state_clock_seconds"] is None
