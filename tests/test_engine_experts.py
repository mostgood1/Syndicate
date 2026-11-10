"""Phase 1B M1 slice 1: the engine experts (lane `engine-experts`, 2026-11-10).

Fixtures follow the shapes on the fleet on 2026-11-09: live gameline ledger v5 rows (event ids from the odds feed,
`live_state_as_of`, `market_fair_prob` on the over/home side), live evidence rows (ESPN ids or none, `as_of`,
`marginDist` / `totalRunsDist` / `segments`), and DecisionRecord dataclasses."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from syndicate.features.shared import decision_record as dr
from syndicate.features.shared import engine_experts as ee

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "syndicate" / "features" / "shared" / "engine_experts.py"


# ----------------------------------------------------------------------------- fixtures


def _record(*, sport="nba", kind="prop", market="player_points", side="under", line=24.5, player="A Player",
            p_market=0.52, p_model=0.58, game_state=None):
    rec = dr.DecisionRecord()
    rec.identity = dr.Identity(line_key=f"{sport}|e1|{market}|full|{player or ''}|{side}|{line}", sport=sport,
                               event_id="e1", kind=kind, market=market, segment="full", player=player, side=side,
                               line=line, game_state=game_state)
    rec.market = dr.MarketFair(p_market=p_market, fair_method="shin", book_age_seconds=40.0)
    rec.model = dr.ModelView(p_model=p_model, source_field="model_probability_cal", engine="smart_sim")
    return rec


def _evidence(t="2026-11-09T18:20:00-06:00", as_of="2026-11-10T00:19:50+00:00", *, period=2, clock=360.0,
              total=None, margin=None, segments=None, p_home=0.6, sims=100, home="Charlotte Hornets",
              away="Cleveland Cavaliers"):
    return {"t": t, "as_of": as_of, "event_id": "401909953", "home_name": home, "away_name": away, "home": "CHA",
            "away": "CLE", "refusal": None, "carried": False, "state": {"period": period, "clockSeconds": clock},
            "totalRunsDist": total if total is not None else {"210": 30, "214": 20, "218": 30, "222": 20},
            "marginDist": margin if margin is not None else {"-6": 25, "-2": 25, "3": 25, "8": 25},
            "segments": segments or {}, "modelHomeWinProb": p_home, "simsRun": sims}


def _ledger(market="totals", line=215.5, *, segment="full", recorded_at="2026-11-10T00:20:10+00:00",
            state_as_of="2026-11-10T00:19:50+00:00", prior=0.5, join_p=None, home="Charlotte Hornets",
            away="Cleveland Cavaliers"):
    return {"v": 5, "sport": "nba", "recorded_at": recorded_at, "event_id": "1df5ff8fe9c6d2dbff1d0ae176063b37",
            "home_team": home, "away_team": away, "segment": segment, "market": market, "line": line,
            "market_fair_prob": prior, "model_home_win_prob": join_p, "live_state_as_of": state_as_of,
            "quote_age_seconds": 50.0, "sims_run": 100, "point_estimator": "agresti_coull", "priceable": False}


# ----------------------------------------------------------------------------- the contract and the math


def test_a_refusal_never_carries_a_neutral_zero():
    rec = _record(p_model=None)
    op = ee.sim_expert(rec, "2026-11-10T15:00:00Z", ee.Reader())
    assert op.refusal == "no_model_probability" and op.delta_logit is None and op.p_expert is None


@pytest.mark.parametrize("sport,period,clock,share,bucket", [
    ("nba", 1, 720, 0.0, "0-25"),
    ("nba", 2, 360, 0.375, "25-50"),
    ("nba", 4, 0, 1.0, "95-100"),
    ("nba", 5, 200, None, "ot"),
    ("ncaab", 2, 600, 0.75, "75-95"),
    ("wncaab", 3, 300, 0.625, "50-75"),
    ("nhl", 4, 100, None, "ot"),
])
def test_clock_buckets_are_shares_of_regulation(sport, period, clock, share, bucket):
    assert ee.elapsed_share(sport, {"period": period, "clockSeconds": clock}) == (share, bucket)


def test_two_way_share_drops_push_sims_and_uses_the_joins_spread_frame():
    assert ee.two_way_share({"214": 3, "215": 2, "216": 5}, 215.0) == (5, 8, 2)
    assert ee.two_way_share({"214": 3, "216": 5}, 215.5) == (5, 8, 0)
    # away-frame spread L = 3.5 (home -3.5): home covers when margin > 3.5
    assert ee.two_way_share({"-6": 25, "3": 25, "4": 25, "8": 25}, 3.5) == (50, 100, 0)


def test_the_smoothing_is_the_live_joins_own():
    from syndicate.features.shared.live_gameline_join import agresti_coull_point

    for k, n in ((0, 100), (37, 100), (100, 100), (61, 200)):
        assert ee.agresti_coull(k, n)[0] == pytest.approx(agresti_coull_point(k / n, n), abs=1e-12)


# ----------------------------------------------------------------------------- pregame experts


def test_sim_expert_on_then_off():
    rec = _record(kind="game", market="h2h", side="home", line=None, player=None, p_market=0.55, p_model=0.60)
    on = ee.sim_expert(rec, "t", ee.Reader())
    assert on.delta_logit == pytest.approx(math.log(0.6 / 0.4) - math.log(0.55 / 0.45), abs=1e-6)
    assert on.sigma is None and on.sigma_basis == "unrecorded:no_sims_in_record" and on.clock_bucket == "pre"
    off = ee.pregame_opinions([rec], "t", env={ee.OFF_ENV: "sim"})
    sim_off = [o for o in off if o.expert == "sim"][0]
    assert sim_off.refusal == "expert_off" and sim_off.delta_logit is None


def test_a_model_anchored_to_the_prior_is_refused_not_read_as_agreement():
    """11-10 fleet record: every NBA spread's p_model sat within 1e-6 of p_market (margin dist anchored on the
    market spread). Read as an opinion it would be delta 0, indistinguishable from a sim that agrees."""
    rec = _record(kind="game", market="spreads", side="home", line=-4.5, player=None, p_market=0.5123456,
                  p_model=0.5123461)
    op = ee.sim_expert(rec, "t", ee.Reader())
    assert op.refusal == "model_anchored_to_prior" and op.delta_logit is None
    near = ee.sim_expert(_record(kind="game", market="spreads", side="home", line=-4.5, player=None,
                                 p_market=0.50, p_model=0.5002), "t", ee.Reader())
    assert near.refusal is None and near.delta_logit is not None


def test_a_started_game_is_not_a_pregame_opinion():
    op = ee.sim_expert(_record(game_state="live"), "t", ee.Reader())
    assert op.refusal == "game_not_pregame" and op.delta_logit is None


def test_under_tilt_shifts_the_under_up_and_the_over_down(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NBA_UNDER_BIAS_DELTA", raising=False)
    under = ee.under_tilt_expert(_record(side="under", p_market=0.5), "t", ee.Reader())
    over = ee.under_tilt_expert(_record(side="over", p_market=0.5), "t", ee.Reader())
    assert under.p_expert == pytest.approx(0.5123) and under.delta_logit > 0
    assert over.p_expert == pytest.approx(0.4877) and over.delta_logit < 0
    assert under.sigma == pytest.approx(0.0030 / 0.25, abs=1e-6)
    game = ee.under_tilt_expert(_record(kind="game", market="totals", side="under", player=None), "t", ee.Reader())
    assert game.refusal == "signal_not_applicable"
    off = ee.under_tilt_expert(_record(side="under"), "t", ee.Reader(), frozenset({"under_tilt"}))
    assert off.refusal == "expert_off" and off.delta_logit is None


# ----------------------------------------------------------------------------- the live re-sim expert


def test_live_resim_reproduces_the_joins_probability_on_a_half_point_line():
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    ev = _evidence()
    index = ee.EvidenceIndex([ev])
    for market, line, side, dist in (("totals", 215.5, "over", ev["totalRunsDist"]),
                                     ("spreads", 3.5, "home", ev["marginDist"]),
                                     ("totals_alt", 220.5, "over", ev["totalRunsDist"])):
        join = price_distribution_market(dist=dist, line=line, side=side, market=market.replace("_alt", ""),
                                         market_prob=0.5, sims=100)
        op = ee.live_resim_expert(_ledger(market, line, join_p=join["model_prob"]), index, ee.Reader())
        assert op.refusal is None and op.inputs["evidence_match"] == "same_state"
        assert op.p_expert == pytest.approx(join["model_prob"], abs=1e-6)
        assert op.clock_bucket == "25-50" and op.sigma_basis == "mc_agresti_coull"
    good = ee.live_resim_expert(_ledger("totals", 215.5, join_p=0.5), index, ee.Reader())  # 50 of 100 over
    bad = ee.live_resim_expert(_ledger("totals", 215.5, join_p=0.4), index, ee.Reader())
    rep = ee.join_reproduction([good, bad])
    assert rep["checked"] == 2 and rep["mismatched"] == 1  # the check can fail: a wrong join value is caught


def test_live_resim_is_two_way_on_a_whole_number_where_the_join_is_not():
    ev = _evidence(total={"214": 40, "215": 20, "216": 40})
    op = ee.live_resim_expert(_ledger("totals", 215.0), ee.EvidenceIndex([ev]), ee.Reader())
    assert op.inputs["push"] == 20 and op.inputs["n"] == 80
    assert op.p_expert == pytest.approx((40 + 2) / (80 + 4), abs=1e-6)


def test_live_resim_moneyline_and_segments():
    seg = {"h1": {"total_dist": {"100": 5, "110": 5}, "margin_dist": {"-3": 4, "0": 2, "5": 4}, "sims": 10,
                  "settled": False, "marginAnchored": True},
           "q1": {"total_dist": {"50": 10}, "margin_dist": {"2": 10}, "sims": 10, "settled": True},
           "q3": {"total_dist": {"50": 10}, "margin_dist": {"2": 10}, "sims": 10, "settled": False}}
    index = ee.EvidenceIndex([_evidence(segments=seg, p_home=0.6, sims=100)])
    ml = ee.live_resim_expert(_ledger("h2h", None, prior=0.55), index, ee.Reader())
    assert ml.p_expert == pytest.approx((60 + 2) / 104, abs=1e-6)
    h1 = ee.live_resim_expert(_ledger("h2h", None, segment="h1"), index, ee.Reader())
    assert h1.inputs["n"] == 8 and h1.p_expert == pytest.approx((4 + 2) / 12, abs=1e-6)  # ties out, two-way
    assert ee.live_resim_expert(_ledger("totals", 49.5, segment="q1"), index, ee.Reader()).refusal == "segment_settled"
    assert ee.live_resim_expert(_ledger("spreads", 1.5, segment="q3"), index, ee.Reader()).refusal == \
        "segment_margin_unanchored"
    assert ee.live_resim_expert(_ledger("totals", 49.5, segment="q2"), index, ee.Reader()).refusal == "segment_absent"


def test_live_resim_refusals_are_named():
    index = ee.EvidenceIndex([_evidence()])
    r = ee.Reader()
    assert ee.live_resim_expert(_ledger(home="Nobody"), index, r).refusal == "no_game_match"
    assert ee.live_resim_expert(_ledger(prior=None), index, r).refusal == "no_prior"
    assert ee.live_resim_expert(_ledger(recorded_at="2026-11-10T00:10:00+00:00", state_as_of=None), index, r).refusal \
        == "no_evidence_before_instant"
    stale = ee.live_resim_expert(_ledger(recorded_at="2026-11-10T00:40:00+00:00", state_as_of=None), index, r)
    assert stale.refusal == "evidence_stale" and stale.delta_logit is None
    off = ee.live_opinions([_ledger()], index, env={ee.OFF_ENV: "live_resim"})
    assert off[0].refusal == "expert_off" and off[0].delta_logit is None
    on = ee.live_opinions([_ledger()], index, env={})
    assert on[0].delta_logit is not None  # off != on


def test_a_ledger_refusal_row_is_named_and_never_read_as_a_price():
    refusal_row = {"v": 5, "sport": "ncaab", "recorded_at": "2026-11-10T00:20:10+00:00", "home_team": "A",
                   "away_team": "B", "segment": "h1", "market": "totals", "line": 70.5, "model_home_win_prob": None,
                   "market_fair_prob": None, "priceable": False, "withheld_reason": "segment_pricing_disabled",
                   "as_of": None, "sims_run": None}
    assert ee.is_ledger_refusal_row(refusal_row) and not ee.is_ledger_refusal_row(_ledger())
    op = ee.live_resim_expert(refusal_row, ee.EvidenceIndex([_evidence()]), ee.Reader())
    assert op.refusal == "ledger_refusal_row" and op.inputs["withheld_reason"] == "segment_pricing_disabled"


def test_the_evidence_lookup_prefers_the_state_the_join_priced():
    a = _evidence(t="2026-11-09T18:20:00-06:00", as_of="2026-11-10T00:19:50+00:00", p_home=0.6)
    b = _evidence(t="2026-11-09T18:21:00-06:00", as_of="2026-11-10T00:20:55+00:00", p_home=0.7)
    index = ee.EvidenceIndex([b, a])
    at = ee._parse("2026-11-10T00:21:30+00:00")
    row, match = index.lookup("Charlotte Hornets", "Cleveland Cavaliers", at, ee._parse("2026-11-10T00:19:50Z"))
    assert match == "same_state" and row["modelHomeWinProb"] == 0.6
    row, match = index.lookup("charlotte  hornets", "Cleveland Cavaliers.", at, None)
    assert match == "as_of_instant" and row["modelHomeWinProb"] == 0.7


# ----------------------------------------------------------------------------- the checklist


def test_checklist_alarms_on_a_consumed_input_nothing_populates_and_documentation_silences_it():
    index = ee.EvidenceIndex([_evidence()])
    reader = ee.Reader()
    rows = [_ledger(join_p=0.5), _ledger(join_p=0.5)]
    for row in rows:
        row["quote_age_seconds"] = None
    ops = ee.live_opinions(rows, index, reader)
    sources = {"live_gameline_ledger": rows, "live_evidence": [_evidence()]}
    res = ee.checklist(ops, reader, sources, sport="nba", expected_sparse={"live_resim:out:player": "x"})
    assert not res["ok"]
    assert any(a.get("input") == "live_gameline_ledger:quote_age_seconds" for a in res["alarms"])
    quiet = ee.checklist(ops, reader, sources, sport="nba", expected_sparse={
        "live_resim:out:player": "x", "live_resim:out:prior_age_s": "x",
        "nba:live_resim:live_gameline_ledger:quote_age_seconds": "fixture"})
    assert quiet["ok"], quiet["alarms"]


def test_checklist_alarms_on_an_output_field_at_its_default_everywhere():
    reader = ee.Reader()
    ops = ee.pregame_opinions([_record(kind="game", market="h2h", side="home", line=None, player=None)], "t", reader)
    res = ee.checklist(ops, reader, {"decision_record": []}, sport="nba", expected_sparse={}, min_opined=1)
    fields = {(a["expert"], a.get("field")) for a in res["alarms"]}
    assert ("sim", "sigma") in fields and ("sim", "player") in fields
    # one opinion is not evidence that a field is never fed
    assert ee.checklist(ops, reader, {"decision_record": []}, sport="nba", expected_sparse={})["ok"]


# ----------------------------------------------------------------------------- shadow: no reader, no order module


def test_the_module_imports_no_order_or_board_module():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    forbidden = ("portfolio_commit", "layer2_board", "inplay_entries", "execution_exits", "kalshi", "polymarket",
                 "order", "board_enrichment", "intelligence_state")
    assert not [m for m in imported if any(f in m for f in forbidden)], imported


def test_nothing_in_the_app_reads_the_experts_yet():
    readers = []
    for path in list((REPO / "pipeline").glob("*.py")) + list((REPO / "syndicate").rglob("*.py")):
        if path == MODULE:
            continue
        if "engine_experts" in path.read_text(encoding="utf-8", errors="ignore"):
            readers.append(str(path.relative_to(REPO)))
    assert readers == []
