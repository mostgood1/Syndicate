"""Live full-game SPREADS P(home covers) is tempered per sport by its measured over-confidence; moneylines are not
(`#780`, lane live-margin-prob-scale, user 2026-11-13 "Fit them now").

`live_gameline_join.spreads_prob_scale` holds k per sport (NBA 2.02, NCAAF 1.80, NCAAB 1.34; WNCAAB and every other sport
1), P_k = Phi(Phi^-1(P) / k), the same transform and knob rule as the totals scale but its own table and switch. The
fit and why h2h is left alone are in the comment above `_SPREADS_PROB_SCALE_BY_SPORT` and in
`.syndicate/findings_2026-11-13_live_margin_width_fit.md`.

Reachability first (`off != on`): the same NBA spreads row through the join, tempered with the table and the engine's
own number with `SYNDICATE_LIVE_SPREADS_PROB_SCALE=off`; then through the production caller. After that: the two
switches are independent, h2h / WNCAAB / segments untouched, the precision gate on the scaled error, the display
number, the ledger fields.
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
    full_game_prob_scale,
    live_display_block,
    price_distribution_market,
    prob_std_err,
    scale_prob_std_err,
    spreads_prob_scale,
    totals_prob_scale,
)
from syndicate.features.shared.live_gameline_ledger import build_records

SPREADS_ENV = "SYNDICATE_LIVE_SPREADS_PROB_SCALE"
TOTALS_ENV = "SYNDICATE_LIVE_TOTALS_PROB_SCALE"
LANE_AT = datetime(2026, 11, 13, 2, 0, 0, tzinfo=timezone.utc)
HOME, AWAY = "Atlanta Hawks", "Washington Wizards"
# 200 sims of the home margin: P(margin > 5.5) = 160 / 200 = 0.80 raw, so the scale has something to temper.
MARGIN = {"2": 40, "10": 160}
LINE = 5.5
MARKET = 0.40
NBA_K, NCAAF_K, NCAAB_K, NBA_TOTALS_K = 2.02, 1.80, 1.34, 2.16


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for env in (SPREADS_ENV, TOTALS_ENV):
        for sport in ("", "_NBA", "_NCAAF", "_NCAAB", "_WNCAAB"):
            monkeypatch.delenv(env + sport, raising=False)


def _snapshot(as_of: datetime = LANE_AT):
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "liveStateAsOf": as_of.isoformat(),
            "projection": {"total": 230.0, "homeMargin": 8.4,
                           "totalRunsDist": {"220": 40, "226": 60, "234": 60, "240": 40},
                           "marginDist": dict(MARGIN)}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(market="spreads", line=LINE, *, segment="full", quote_at: datetime = LANE_AT, market_prob=MARKET):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    return {"kind": "game", "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0, "updated_at": quote_at.isoformat(),
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(rows, sport):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=LANE_AT + timedelta(seconds=10))


def _ac_cover():
    return agresti_coull_point(0.80, 200)


def _expected(k):
    return NormalDist().cdf(NormalDist().inv_cdf(_ac_cover()) / k)


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_join(monkeypatch):
    """The same NBA spreads row: tempered with the table, the engine's own number with the switch off."""
    on, off = [_row()], [_row()]
    cov_on = _attach(on, "nba")
    monkeypatch.setenv(SPREADS_ENV, "off")
    cov_off = _attach(off, "nba")

    lg_on, lg_off = on[0]["live_gameline"], off[0]["live_gameline"]
    assert cov_on["rows_live_gameline_priceable"] == 1 and cov_off["rows_live_gameline_priceable"] == 1
    assert lg_off["model_prob"] == pytest.approx(_ac_cover(), abs=1e-9)  # the pricer read P(margin > 5.5)
    assert lg_on["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert abs(lg_on["model_prob"] - lg_off["model_prob"]) > 0.10  # off != on, by a lot at P = 0.79
    assert lg_on["prob_scale"] == pytest.approx(NBA_K) and lg_off["prob_scale"] == 1.0
    assert lg_on["model_prob_unscaled"] == pytest.approx(_ac_cover(), abs=1e-9)
    assert lg_off["model_prob_unscaled"] is None
    # The published edge moves with it.
    assert on[0]["projection"]["edge_vs_market_pct"] == pytest.approx((_expected(NBA_K) - MARKET) * 100, abs=0.06)
    assert off[0]["projection"]["edge_vs_market_pct"] == pytest.approx((_ac_cover() - MARKET) * 100, abs=0.06)


def test_the_board_caller_tempers_nba_spreads(monkeypatch):
    """`board_enrichment.attach_live_gamelines_for_sport` is the path that prices on the fleet."""
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    wall = datetime.now(timezone.utc)
    snapshot = _snapshot(as_of=wall - timedelta(seconds=20))
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: snapshot)
    probs = {}
    for label, env in (("on", None), ("off", "off")):
        if env:
            monkeypatch.setenv(SPREADS_ENV, env)
        rows = [_row(quote_at=wall - timedelta(seconds=10))]
        board_enrichment.attach_live_gamelines_for_sport(rows, sport="nba", selected_date=wall.date().isoformat())
        probs[label] = rows[0]["live_gameline"]["model_prob"]
    assert probs["on"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert probs["off"] == pytest.approx(_ac_cover(), abs=1e-9)


# --------------------------------------------------------------------------------------------- the table and the knob

@pytest.mark.parametrize("sport,k", [("nba", NBA_K), (" NBA ", NBA_K), ("ncaaf", NCAAF_K), ("ncaab", NCAAB_K),
                                     ("wncaab", 1.0), ("mlb", 1.0), ("nhl", 1.0), ("nfl", 1.0), (None, 1.0), ("", 1.0)])
def test_the_table(sport, k):
    assert spreads_prob_scale(sport) == pytest.approx(k)


@pytest.mark.parametrize("raw", ["off", "OFF", "0", "false", "no"])
def test_the_switch_turns_every_sport_off(monkeypatch, raw):
    monkeypatch.setenv(SPREADS_ENV, raw)
    assert spreads_prob_scale("nba") == 1.0 and spreads_prob_scale("ncaaf") == 1.0 and spreads_prob_scale("ncaab") == 1.0


def test_a_per_sport_value_sets_that_sport_only(monkeypatch):
    monkeypatch.setenv(SPREADS_ENV + "_NBA", "1")
    assert spreads_prob_scale("nba") == 1.0
    assert spreads_prob_scale("ncaaf") == pytest.approx(NCAAF_K)


@pytest.mark.parametrize("raw", ["abc", "0", "-2", "inf", "nan", ""])
def test_a_junk_per_sport_value_falls_back_to_the_table_not_off(monkeypatch, raw):
    monkeypatch.setenv(SPREADS_ENV + "_NBA", raw)
    assert spreads_prob_scale("nba") == pytest.approx(NBA_K)


def test_the_two_switches_are_independent(monkeypatch):
    monkeypatch.setenv(TOTALS_ENV, "off")
    assert spreads_prob_scale("nba") == pytest.approx(NBA_K) and totals_prob_scale("nba") == 1.0
    monkeypatch.delenv(TOTALS_ENV)
    monkeypatch.setenv(SPREADS_ENV, "off")
    assert spreads_prob_scale("nba") == 1.0 and totals_prob_scale("nba") == pytest.approx(NBA_TOTALS_K)


@pytest.mark.parametrize("market,segment,k", [
    ("spreads", "full", NBA_K), ("alternate_spreads", "full", NBA_K), ("spreads", "game", NBA_K),
    ("totals", "full", NBA_TOTALS_K),
    ("h2h", "full", 1.0),            # moneylines: measured no gain, never tempered
    ("spreads", "h1", 1.0), ("spreads", "q1", 1.0), ("totals", "h1", 1.0),  # segments were not fitted
    ("spreads", "", 1.0), ("spreads", None, 1.0),  # an absent segment is not "full": no permissive branch
])
def test_which_rows_are_tempered(market, segment, k):
    assert full_game_prob_scale(market, segment, "nba") == pytest.approx(k)


# --------------------------------------------------------------------------------------------- the math at the pricer

def test_the_precision_gate_judges_the_scaled_error():
    out = price_distribution_market(dist=MARGIN, line=LINE, side="home", market="spreads", market_prob=MARKET,
                                    sims=200, prob_scale=NBA_K)
    se_raw = prob_std_err(0.80, 200)
    assert out["prob_std_err"] == pytest.approx(scale_prob_std_err(_ac_cover(), se_raw, NBA_K), rel=1e-9)
    assert out["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    # A gap the untempered number would publish can fall under the gate once tempered.
    near = price_distribution_market(dist=MARGIN, line=LINE, side="home", market="spreads", market_prob=0.68,
                                     sims=200, prob_scale=NBA_K)
    assert near["priceable"] is False and near["model_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert price_distribution_market(dist=MARGIN, line=LINE, side="home", market="spreads", market_prob=0.68,
                                     sims=200)["priceable"] is True


def test_a_spreads_verdict_records_k_one_when_untempered():
    out = price_distribution_market(dist=MARGIN, line=LINE, side="home", market="spreads", market_prob=MARKET, sims=200)
    assert out["model_prob"] == pytest.approx(_ac_cover(), abs=1e-12)
    assert out["prob_scale"] == 1.0 and out["model_prob_unscaled"] is None


# --------------------------------------------------------------------------------------------- what is NOT tempered

def test_nba_moneylines_are_untouched(monkeypatch):
    on, off = [_row("h2h", None)], [_row("h2h", None)]
    _attach(on, "nba")
    monkeypatch.setenv(SPREADS_ENV, "off")
    _attach(off, "nba")
    assert on[0]["live_gameline"].get("model_prob") is not None
    assert on[0]["live_gameline"].get("model_prob") == off[0]["live_gameline"].get("model_prob")
    assert on[0]["live_gameline"].get("prob_scale") is None


def test_wncaab_spreads_are_untouched():
    rows = [_row()]
    _attach(rows, "wncaab")
    lg = rows[0]["live_gameline"]
    assert lg["model_prob"] == pytest.approx(_ac_cover(), abs=1e-9)
    assert lg["prob_scale"] == 1.0 and lg["model_prob_unscaled"] is None


def test_ncaab_spreads_take_their_own_k():
    rows = [_row()]
    _attach(rows, "ncaab")
    lg = rows[0]["live_gameline"]
    assert lg["prob_scale"] == pytest.approx(NCAAB_K)
    assert lg["model_prob"] == pytest.approx(_expected(NCAAB_K), abs=1e-9)


def test_nba_totals_keep_their_own_k():
    """The spreads table must not leak into totals: same NBA game, totals row, totals k."""
    rows = [_row("totals", 224.5, market_prob=0.30)]
    _attach(rows, "nba")
    assert rows[0]["live_gameline"]["prob_scale"] == pytest.approx(NBA_TOTALS_K)


# --------------------------------------------------------------------------------------------- display and ledger

def test_the_display_number_is_tempered_on_full_game_spreads_only(monkeypatch):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport="nba")
    hit = next(iter(index.values()))
    full = live_display_block(hit, _row(), sport="nba", basis="x")
    assert full["prob_over"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    ml = live_display_block(hit, _row("h2h", None), sport="nba", basis="x")
    assert ml["prob_over"] == pytest.approx(agresti_coull_point(0.7, 200), abs=1e-9)  # the moneyline is not tempered
    monkeypatch.setenv(SPREADS_ENV, "off")
    assert live_display_block(hit, _row(), sport="nba", basis="x")["prob_over"] == pytest.approx(_ac_cover(), abs=1e-9)


def test_the_ledger_records_the_spreads_scale_and_the_engine_number():
    rows = [_row()]
    _attach(rows, "nba")
    rec = next(r for r in build_records(rows, sport="nba", date_str="2026-11-12") if r.get("market") == "spreads")
    assert rec["prob_scale"] == pytest.approx(NBA_K)
    assert rec["model_home_win_prob"] == pytest.approx(_expected(NBA_K), abs=1e-9)
    assert rec["model_home_win_prob_unscaled"] == pytest.approx(_ac_cover(), abs=1e-9)
