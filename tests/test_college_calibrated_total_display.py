"""I-17 (lane ncaab-total-overprojection; the rail monitor handed it over on the user's words "hand I-17 to the #816 lane
now", and the user chose the calibrated total over a "sim" label): a college total under the #816 calibration shows the
total its CALIBRATED probability implies, so the card's "ours" agrees with the flag beside it. On 11-17, 23 of 74 NCAAB
full-game under flags showed the sim's projected final ABOVE the line.

Reachability first (`off != on`): the same row through the join with a fit in force and with the switch off, then the
board's columns and the rail's row fields. Then the number itself: it sits on the calibrated lean's side of the line,
and the calibrated P(over) there is 0.5.
"""
from __future__ import annotations

import datetime as dt
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.college_basketball import total_prob_calibration as tpc
from syndicate.features.shared import layer2_board as l2
from syndicate.features.shared import live_rail_rows
from syndicate.features.shared.live_gameline_join import (
    LIVE_DISPLAY_KEY,
    agresti_coull_point,
    attach_live_gamelines,
    build_live_gameline_index,
    college_calibrated_total,
)
from syndicate.features.shared.prop_projections import _dist_prob_over

LANE_AT = datetime(2026, 11, 16, 20, 38, 0, tzinfo=timezone.utc)
HOME, AWAY = "UTEP Miners", "Florida A&M Rattlers"
DIST = {"130": 30, "134": 30, "138": 80, "144": 60}       # P(over 136.5) = 0.70 raw; mean 137.6
LINE = 136.5
MARKET = 0.497
CAL = tpc.TotalCalibration(league="ncaab", phase="live", as_of=dt.date(2026, 11, 15), a=-0.49, c=0.21,
                           var_a=0.01, var_c=0.004, cov_ac=0.0, games=130.0, source="fit.json")


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv(tpc.ENV_SWITCH, raising=False)
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE", raising=False)
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAB", raising=False)
    monkeypatch.setattr(tpc, "calibration_for", lambda league, phase, game_date, **kw: CAL if tpc.enabled() else None)


def _snapshot():
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(),
            "projection": {"total": 137.2, "homeMargin": 33.0, "totalRunsDist": dict(DIST), "marginDist": {"30": 100, "35": 100}}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(age=20.0, updated_at=None):
    return {"kind": "game", "market": "totals", "segment": "full", "line": LINE, "sides": ["over", "under"],
            "away_team": AWAY, "home_team": HOME, "age_seconds": age,
            "updated_at": (updated_at or LANE_AT).isoformat(),
            "game": {"state": "live", "home_score": 40, "away_score": 30},
            "projection": {"market_fair_prob_over": MARKET}}


def _attach(rows):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport="ncaab")
    return attach_live_gamelines(rows, index, sport="ncaab", now=LANE_AT + timedelta(seconds=10))


def _sig(x):
    return 1 / (1 + math.exp(-x))


# ------------------------------------------------------------------------------------------------ reachability

def test_off_is_not_on_through_the_join(monkeypatch):
    on, off = [_row()], [_row()]
    _attach(on)
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")
    _attach(off)
    lg_on, lg_off = on[0]["live_gameline"], off[0]["live_gameline"]
    assert lg_off["calibrated_total"] is None and lg_off["total_mean"] == pytest.approx(137.2)
    assert lg_on["calibrated_total"] is not None
    # The calibrated lean is UNDER here (served P(over) < 0.5): the shown total must be under the line too, while the
    # sim's own number stays above it -- the I-17 contradiction, removed.
    assert lg_on["model_prob"] < 0.5 and lg_on["calibrated_total"] < LINE < lg_on["total_mean"]


def test_the_board_shows_the_calibrated_total_and_keeps_the_sims(monkeypatch):
    on = [_row()]
    _attach(on)
    cols = l2._live_projection_columns(on[0])
    assert cols["live_total"] == pytest.approx(on[0]["live_gameline"]["calibrated_total"])
    assert cols["live_total_sim"] == pytest.approx(137.2) and cols["live_total_basis"] == "calibrated"
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")
    off = [_row()]
    _attach(off)
    cols_off = l2._live_projection_columns(off[0])
    assert cols_off["live_total"] == pytest.approx(137.2) and "live_total_basis" not in cols_off


def test_a_stale_quote_row_shows_the_calibrated_total_through_the_display_path():
    rows = [_row(age=20.0, updated_at=LANE_AT - timedelta(seconds=600))]       # refused: quote behind the score
    _attach(rows)
    block = rows[0].get(LIVE_DISPLAY_KEY)
    assert block is not None and block.get("calibrated_total") is not None and block["calibrated_total"] < LINE
    cols = l2._live_projection_columns(rows[0])
    assert cols["live_total"] == pytest.approx(block["calibrated_total"]) and cols["live_total_basis"] == "calibrated"


def test_the_rail_rows_carry_the_basis_and_the_sims_number():
    assert "live_total_basis" in live_rail_rows.ROW_FIELDS and "live_total_sim" in live_rail_rows.ROW_FIELDS


def test_the_rail_card_prefers_the_calibrated_total():
    html = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "intelligence.html").read_text(encoding="utf-8")
    assert 'row.live_total_basis === "calibrated"' in html


# ------------------------------------------------------------------------------------------------ the number

def _calibrated_over(total, p_mkt=MARKET, line=LINE, sims=200):
    """The helper's own curve, rebuilt independently for the check."""
    from statistics import NormalDist
    pts = [(float(k), float(v)) for k, v in DIST.items()]
    w = sum(c for _x, c in pts)
    mean = sum(x * c for x, c in pts) / w
    sd = math.sqrt(sum(c * (x - mean) ** 2 for x, c in pts) / w)
    nd = NormalDist()
    mu = line + sd * nd.inv_cdf(p_mkt)
    engine = agresti_coull_point(_dist_prob_over(DIST, total), sims)
    market = min(0.99, max(0.01, 1 - nd.cdf((total - mu) / sd)))
    return CAL.apply(engine, market)


def test_the_calibrated_total_is_where_the_calibrated_probability_is_even():
    total = college_calibrated_total(DIST, sims=200, prob_scale=1.0, calibration=CAL, line=LINE, market_prob_over=MARKET)
    assert total is not None
    # Within the histogram's steps the curve is flat, so check the crossing brackets 0.5 at +-0.2.
    assert _calibrated_over(total - 0.2) >= 0.5 >= _calibrated_over(total + 0.2)
    # At the row's own line the curve is exactly the served probability.
    served = CAL.apply(agresti_coull_point(_dist_prob_over(DIST, LINE), 200), MARKET)
    assert _calibrated_over(LINE) == pytest.approx(served, abs=1e-9)


@pytest.mark.parametrize("a", [-0.5, 0.0, 0.5])
def test_the_total_sits_on_the_calibrated_lean_side_of_the_line(a):
    cal = tpc.TotalCalibration(league="ncaab", phase="live", as_of=dt.date(2026, 11, 15), a=a, c=0.2)
    total = college_calibrated_total(DIST, sims=200, prob_scale=1.0, calibration=cal, line=LINE, market_prob_over=MARKET)
    served = cal.apply(agresti_coull_point(_dist_prob_over(DIST, LINE), 200), MARKET)
    assert total is not None and (total < LINE) == (served < 0.5)


@pytest.mark.parametrize("kw", [{"line": None}, {"market_prob_over": None}, {"market_prob_over": 1.0}, {"calibration": None}])
def test_missing_inputs_give_no_number(kw):
    args = {"sims": 200, "prob_scale": 1.0, "calibration": CAL, "line": LINE, "market_prob_over": MARKET} | kw
    assert college_calibrated_total(DIST, **args) is None
    assert college_calibrated_total({}, sims=200, prob_scale=1.0, calibration=CAL, line=LINE, market_prob_over=MARKET) is None
