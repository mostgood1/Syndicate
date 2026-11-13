"""Live full-game totals P(over) is tempered per sport by its measured over-confidence (`#780` candidate fix 2).

User 2026-11-13 "Fit it now". `live_gameline_join.totals_prob_scale` holds k per sport (NBA 2.16, NCAAF 2.48; NCAAB and
WNCAAB stay at 1: their walk-forward fit showed no gain), and P_k(over) = Phi(Phi^-1(P) / k). The fit and its table are in
the comment above `_TOTALS_PROB_SCALE_BY_SPORT` and in `.syndicate/findings_2026-11-13_live_totals_width_fit.md`.

Reachability first (`off != on`): the same NBA totals row through the join, priced at the tempered probability with the
table and at the engine's own with `SYNDICATE_LIVE_TOTALS_PROB_SCALE=off`; then through the production caller. After
that: NCAAB / spreads / h2h untouched, the precision gate on the scaled error, the display number, the ledger fields.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import NormalDist

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared.live_gameline_join import (
    agresti_coull_point,
    attach_live_gamelines,
    build_live_gameline_index,
    live_display_block,
    price_distribution_market,
    prob_std_err,
    scale_prob,
    scale_prob_std_err,
    totals_prob_scale,
)
from syndicate.features.shared.live_gameline_ledger import LEDGER_VERSION, build_records

ENV = "SYNDICATE_LIVE_TOTALS_PROB_SCALE"
LANE_AT = datetime(2026, 11, 13, 2, 0, 0, tzinfo=timezone.utc)
HOME, AWAY = "Atlanta Hawks", "Washington Wizards"
# 200 sims: P(over 224.5) = 160 / 200 = 0.80 raw, so the scale has something to temper.
DIST = {"220": 40, "226": 60, "234": 60, "240": 40}
LINE = 224.5
MARKET = 0.30
NBA_K, NCAAF_K = 2.16, 2.48


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for sport in ("", "_NBA", "_NCAAF", "_NCAAB", "_WNCAAB"):
        monkeypatch.delenv(ENV + sport, raising=False)


def _snapshot(as_of: datetime = LANE_AT):
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "liveStateAsOf": as_of.isoformat(),
            "projection": {"total": 230.0, "homeMargin": 6.0, "totalRunsDist": dict(DIST),
                           "marginDist": {"2": 80, "10": 120}}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(market="totals", line=LINE, *, segment="full", quote_at: datetime = LANE_AT, market_prob=MARKET):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    return {"kind": "game", "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0, "updated_at": quote_at.isoformat(),
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(rows, sport):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=LANE_AT + timedelta(seconds=10))


def _ac_over():
    return agresti_coull_point(0.80, 200)


def _expected(k):
    return NormalDist().cdf(NormalDist().inv_cdf(_ac_over()) / k)


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_join(monkeypatch):
    """The same NBA totals row: tempered with the table, the engine's own number with the switch off."""
    on, off = [_row()], [_row()]
    cov_on = _attach(on, "nba")
    monkeypatch.setenv(ENV, "off")
    cov_off = _attach(off, "nba")

    lg_on, lg_off = on[0]["live_gameline"], off[0]["live_gameline"]
    assert cov_on["rows_live_gameline_priceable"] == 1 and cov_off["rows_live_gameline_priceable"] == 1
    assert lg_on["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert lg_off["model_prob"] == pytest.approx(_ac_over(), abs=1e-9)
    assert abs(lg_on["model_prob"] - lg_off["model_prob"]) > 0.10  # off != on, by a lot at P = 0.79
    assert lg_on["prob_scale"] == pytest.approx(NBA_K) and lg_off["prob_scale"] == 1.0
    assert lg_on["model_prob_unscaled"] == pytest.approx(_ac_over(), abs=1e-9)
    assert lg_off["model_prob_unscaled"] is None
    # The published edge moves with it: the board shows the tempered gap.
    assert on[0]["projection"]["edge_vs_market_pct"] == pytest.approx((_expected(NBA_K) - MARKET) * 100, abs=0.06)
    assert off[0]["projection"]["edge_vs_market_pct"] == pytest.approx((_ac_over() - MARKET) * 100, abs=0.06)


def test_the_board_caller_tempers_nba_totals(monkeypatch):
    """`board_enrichment.attach_live_gamelines_for_sport` is the path that prices on the fleet."""
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    wall = datetime.now(timezone.utc)
    snapshot = _snapshot(as_of=wall - timedelta(seconds=20))
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: snapshot)
    probs = {}
    for label, env in (("on", None), ("off", "off")):
        if env:
            monkeypatch.setenv(ENV, env)
        rows = [_row(quote_at=wall - timedelta(seconds=10))]
        board_enrichment.attach_live_gamelines_for_sport(rows, sport="nba", selected_date=wall.date().isoformat())
        probs[label] = rows[0]["live_gameline"]["model_prob"]
    assert probs["on"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert probs["off"] == pytest.approx(_ac_over(), abs=1e-9)


# --------------------------------------------------------------------------------------------- the table and the knob

@pytest.mark.parametrize("sport,k", [("nba", NBA_K), (" NBA ", NBA_K), ("ncaaf", NCAAF_K), ("ncaab", 1.0),
                                     ("wncaab", 1.0), ("mlb", 1.0), ("nhl", 1.0), ("nfl", 1.0), (None, 1.0), ("", 1.0)])
def test_the_table(sport, k):
    assert totals_prob_scale(sport) == pytest.approx(k)


@pytest.mark.parametrize("raw", ["off", "OFF", "0", "false", "no"])
def test_the_switch_turns_every_sport_off(monkeypatch, raw):
    monkeypatch.setenv(ENV, raw)
    assert totals_prob_scale("nba") == 1.0 and totals_prob_scale("ncaaf") == 1.0


def test_a_per_sport_value_sets_that_sport_only(monkeypatch):
    monkeypatch.setenv(ENV + "_NCAAB", "1.25")
    assert totals_prob_scale("ncaab") == pytest.approx(1.25)
    assert totals_prob_scale("nba") == pytest.approx(NBA_K)


@pytest.mark.parametrize("raw", ["abc", "0", "-2", "inf", "nan", ""])
def test_a_junk_per_sport_value_falls_back_to_the_table_not_off(monkeypatch, raw):
    monkeypatch.setenv(ENV + "_NBA", raw)
    assert totals_prob_scale("nba") == pytest.approx(NBA_K)


# --------------------------------------------------------------------------------------------- the math

@pytest.mark.parametrize("p", [0.03, 0.2, 0.5, 0.64, 0.97])
def test_scale_prob_is_symmetric_and_moves_toward_a_half(p):
    for k in (1.5, NBA_K, NCAAF_K):
        q = scale_prob(p, k)
        assert scale_prob(1 - p, k) == pytest.approx(1 - q, abs=1e-12)
        assert abs(q - 0.5) <= abs(p - 0.5) + 1e-12
    assert scale_prob(p, 1.0) == p
    assert scale_prob(0.5, NBA_K) == pytest.approx(0.5)


def test_the_precision_gate_judges_the_scaled_error():
    out = price_distribution_market(dist=DIST, line=LINE, side="over", market="totals", market_prob=MARKET,
                                    sims=200, prob_scale=NBA_K)
    se_raw = prob_std_err(0.80, 200)
    assert out["prob_std_err"] == pytest.approx(scale_prob_std_err(_ac_over(), se_raw, NBA_K), rel=1e-9)
    assert out["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert out["edge_pp"] == pytest.approx((_expected(NBA_K) - MARKET) * 100, abs=0.006)
    # A gap the untempered number would publish can fall under the gate once tempered: market just under the model.
    near = price_distribution_market(dist=DIST, line=LINE, side="over", market="totals", market_prob=0.62,
                                     sims=200, prob_scale=NBA_K)
    assert near["priceable"] is False and near["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)


def test_default_scale_leaves_the_pricer_unchanged():
    out = price_distribution_market(dist=DIST, line=LINE, side="over", market="totals", market_prob=MARKET, sims=200)
    assert out["model_prob"] == pytest.approx(_ac_over(), abs=1e-12)
    assert out["prob_scale"] == 1.0 and out["model_prob_unscaled"] is None


# --------------------------------------------------------------------------------------------- what is NOT tempered

def test_ncaab_totals_are_untouched():
    rows = [_row()]
    _attach(rows, "ncaab")
    lg = rows[0]["live_gameline"]
    assert lg["model_prob"] == pytest.approx(_ac_over(), abs=1e-9)
    assert lg["prob_scale"] == 1.0 and lg["model_prob_unscaled"] is None


@pytest.mark.parametrize("market,line", [("spreads", 5.5), ("h2h", None)])
def test_nba_spreads_and_moneylines_are_untouched(monkeypatch, market, line):
    on, off = [_row(market, line, market_prob=0.40)], [_row(market, line, market_prob=0.40)]
    _attach(on, "nba")
    monkeypatch.setenv(ENV, "off")
    _attach(off, "nba")
    assert on[0]["live_gameline"].get("model_prob") == off[0]["live_gameline"].get("model_prob")
    assert on[0]["live_gameline"].get("prob_scale") is None


# --------------------------------------------------------------------------------------------- display and ledger

def test_the_display_number_is_tempered_on_full_game_only(monkeypatch):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport="nba")
    hit = next(iter(index.values()))
    full = live_display_block(hit, _row(), sport="nba", basis="x")
    seg = live_display_block({**hit, "segment": "h1"}, _row(segment="h1"), sport="nba", basis="x")
    assert full["prob_over"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert seg["prob_over"] == pytest.approx(_ac_over(), abs=1e-9)
    monkeypatch.setenv(ENV, "off")
    assert live_display_block(hit, _row(), sport="nba", basis="x")["prob_over"] == pytest.approx(_ac_over(), abs=1e-9)


def test_the_ledger_records_the_scale_and_the_engine_number():
    rows = [_row()]
    _attach(rows, "nba")
    rec = next(r for r in build_records(rows, sport="nba", date_str="2026-11-12") if r.get("market") == "totals")
    assert rec["v"] == LEDGER_VERSION == 7
    assert rec["prob_scale"] == pytest.approx(NBA_K)
    assert rec["model_home_win_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert rec["model_home_win_prob_unscaled"] == pytest.approx(_ac_over(), abs=1e-9)
