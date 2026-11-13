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


@pytest.mark.parametrize("commence,t,bucket", [
    ("2026-11-11T00:30:00Z", "2026-11-11T00:00:00Z", "pre<1h"),
    ("2026-11-11T00:30:00Z", "2026-11-10T20:30:00Z", "pre1-6h"),
    ("2026-11-11T00:30:00Z", "2026-11-10T06:30:00Z", "pre6-24h"),
    ("2026-11-11T00:30:00Z", "2026-11-09T00:30:00Z", "pre>24h"),
    (None, "2026-11-10T06:30:00Z", "pre"),
])
def test_pregame_buckets_are_hours_to_the_start(commence, t, bucket):
    assert ee.pregame_bucket(commence, t) == bucket


def test_kept_pregame_lines_reach_the_experts_with_their_own_instants(tmp_path):
    from datetime import datetime, timezone

    row = {"sport": "nba", "event_id": "e1", "kind": "game", "market": "totals", "segment": "full",
           "player_name": None, "side": "over", "line": 220.5, "commence_time": "2026-11-11T00:30:00Z",
           "home_team": "H", "away_team": "A", "game_state": "pregame", "model_probability_cal": 0.58,
           "projection": {"model_prob_over": 0.58, "basis": "sim_total_dist/full"},
           "quote": {"fair_probability": 0.50, "fair_method": "consensus", "books_quoting": 6}}
    ctx = dr.RecordContext(selected_date="2026-11-10")
    t0 = datetime(2026, 11, 10, 6, 30, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 11, 0, 5, tzinfo=timezone.utc)
    dr.keep_pregame_lines("2026-11-10", dr.build_records([row], ctx), build_id="b1", now=t0, root=tmp_path, env={})
    moved = {**row, "quote": {**row["quote"], "fair_probability": 0.55}}
    dr.keep_pregame_lines("2026-11-10", dr.build_records([moved], ctx), build_id="b2", now=t1, root=tmp_path, env={})
    items = []
    for kept in dr.read_pregame_lines("2026-11-10", tmp_path):
        items.append((dr.expand_record(kept["first"]), kept["ft"], "first"))
        items.append((dr.expand_record(kept["last"]), kept["lt"], "last"))
    ops = [o for o in ee.pregame_opinions_at(items) if o.expert == "sim"]
    by = {o.inputs["snapshot"]: o for o in ops}
    assert by["first"].clock_bucket == "pre6-24h" and by["last"].clock_bucket == "pre<1h"
    assert by["first"].p_prior == pytest.approx(0.50) and by["last"].p_prior == pytest.approx(0.55)
    assert by["last"].delta_logit < by["first"].delta_logit


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


def _v7(join, line):
    """A ledger v7 totals record as `live_gameline_ledger.build_records` writes one from the join's verdict (#780)."""
    return {**_ledger("totals", line, join_p=join["model_prob"]), "v": 7, "prob_scale": join["prob_scale"],
            "model_home_win_prob_unscaled": join["model_prob_unscaled"]}


def test_the_join_check_reads_the_engines_number_on_a_tempered_total(monkeypatch):
    """#780: a v7 full-game total's `model_home_win_prob` is the TEMPERED P(over); the engine's own is
    `model_home_win_prob_unscaled`. The expert reads the engine's histogram, so the check compares the engine's
    number. Read the tempered one and every tempered half-point total is a mismatch."""
    from syndicate.features.shared import live_gameline_join as lgj

    for key in ("SYNDICATE_LIVE_TOTALS_PROB_SCALE", "SYNDICATE_LIVE_TOTALS_PROB_SCALE_NBA"):
        monkeypatch.delenv(key, raising=False)
    ev = _evidence()
    index = ee.EvidenceIndex([ev])
    k = lgj.totals_prob_scale("nba")
    assert k != 1.0  # with k = 1 nothing is tempered and this test proves nothing
    line = 211.5  # 70 of 100 sims over, so the temper moves the number (at 0.5 it would not)
    join = lgj.price_distribution_market(dist=ev["totalRunsDist"], line=line, side="over", market="totals",
                                         market_prob=0.5, sims=100, prob_scale=k)
    assert abs(join["model_prob"] - join["model_prob_unscaled"]) > 0.05
    op = ee.live_resim_expert(_v7(join, line), index, ee.Reader())
    assert op.inputs["join_prob_scale"] == pytest.approx(k)
    assert op.inputs["join_model_p"] == pytest.approx(join["model_prob_unscaled"], abs=1e-12)
    rep = ee.join_reproduction([op])
    assert rep["checked"] == 1 and rep["mismatched"] == 0
    # the old reading -- the tempered number taken as the join's -- is caught as a mismatch
    old = ee.live_resim_expert({**_v7(join, line), "prob_scale": None}, index, ee.Reader())
    assert old.inputs["join_model_p"] == pytest.approx(join["model_prob"]) and \
        ee.join_reproduction([old])["mismatched"] == 1
    # k = 1 (NCAAB, segments): the join writes no unscaled number and the check reads model_home_win_prob as before
    flat = lgj.price_distribution_market(dist=ev["totalRunsDist"], line=line, side="over", market="totals",
                                         market_prob=0.5, sims=100, prob_scale=1.0)
    assert flat["prob_scale"] == 1.0 and flat["model_prob_unscaled"] is None
    same = ee.live_resim_expert(_v7(flat, line), index, ee.Reader())
    assert same.inputs["join_model_p"] == pytest.approx(flat["model_prob"]) and \
        ee.join_reproduction([same])["mismatched"] == 0
    # a tempered record missing the engine's number is not checked, rather than checked against the tempered one
    broken = ee.live_resim_expert({**_v7(join, line), "model_home_win_prob_unscaled": None}, index, ee.Reader())
    assert broken.inputs["join_model_p"] is None and ee.join_reproduction([broken])["checked"] == 0
    assert broken.p_expert == op.p_expert  # the opinion itself never read the join's number


def test_a_pre_v7_ledger_reads_as_before_and_its_new_inputs_are_documented_sparse():
    index = ee.EvidenceIndex([_evidence()])
    reader = ee.Reader()
    rows = [_ledger(join_p=0.5), _ledger(join_p=0.5)]
    ops = ee.live_opinions(rows, index, reader)
    assert all(o.inputs["join_model_p"] == 0.5 and o.inputs["join_prob_scale"] is None for o in ops)
    assert "live_gameline_ledger:prob_scale" in reader.consumed["live_resim"]
    res = ee.checklist(ops, reader, {"live_gameline_ledger": rows, "live_evidence": [_evidence()]}, sport="nba")
    assert not [a for a in res["alarms"] if "prob_scale" in str(a.get("input"))], res["alarms"]


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
        "nba:live_resim:live_gameline_ledger:quote_age_seconds": "fixture",
        "live_resim:live_gameline_ledger:prob_scale": "v5 fixture rows predate ledger v7"})
    assert quiet["ok"], quiet["alarms"]


def test_checklist_alarms_on_an_output_field_at_its_default_everywhere():
    reader = ee.Reader()
    ops = ee.pregame_opinions([_record(kind="game", market="h2h", side="home", line=None, player=None)], "t", reader)
    res = ee.checklist(ops, reader, {"decision_record": []}, sport="nba", expected_sparse={}, min_opined=1)
    fields = {(a["expert"], a.get("field")) for a in res["alarms"]}
    assert ("sim", "sigma") in fields and ("sim", "player") in fields
    # one opinion is not evidence that a field is never fed
    assert ee.checklist(ops, reader, {"decision_record": []}, sport="nba", expected_sparse={})["ok"]


# ----------------------------------------------------------------------------- stat progress (slice 3)
# Shapes from the fleet on 2026-11-12/13: a `live_prop_evidence` props row (ESPN event id, team full names, `t` in the
# producer's -06:00 offset, `simsRun` 100) and `book_quotes` prop rows (OddsAPI event id, over/under, Yes/No with a
# NaN line on the doubles markets, `captured_at` beside the book's own `book_updated_at`).

T_TICK = "2026-11-12T19:00:00-06:00"  # 01:00:00Z on 11-13


def _prop(line=24.5, p=0.82, *, player="Tyrese Maxey", prop="player_points", sims=100, actual=11.0, extra=None):
    row = {"playerName": player, "prop": prop, "line": line, "liveProjection": 26.4, "liveModelProbOver": p,
           "actualSoFar": actual, "simsRun": sims, "side": "home"}
    row.update(extra or {})
    return row


def _props_row(props, t=T_TICK):
    from syndicate.features.shared import live_prop_evidence as lpe

    return {"v": 1, "kind": "props", "sport": "nba", "date": "2026-11-12", "t": t,
            "observed_at": "2026-11-13T01:00:04+00:00", "event_id": "401909976", "home": "PHI", "away": "TOR",
            "home_name": "Philadelphia 76ers", "away_name": "Toronto Raptors", "n": len(props), "refusal": None,
            "props": lpe.compact_props(props)}


def _quote(book, selection, price, *, line=24.5, captured="2026-11-13T00:58:00Z", updated="2026-11-13T00:57:50Z",
           player="Tyrese Maxey", market="player_points"):
    return {"captured_at": captured, "snapshot_ts": updated or captured, "book_updated_at": updated, "sport": "nba",
            "date": "2026-11-12", "kind": "prop", "event_id": "ab12", "commence_time": "2026-11-13T00:10:00Z",
            "home_team": "Philadelphia 76ers", "away_team": "Toronto Raptors", "bookmaker": book, "market": market,
            "segment": "full", "selection": selection, "player_name": player, "line": line, "price": price}


def _two_books(**kw):
    return [_quote("fanduel", "over", -120, **kw), _quote("fanduel", "under", 100, **kw),
            _quote("draftkings", "over", -110, **kw), _quote("draftkings", "under", -110, **kw)]


def _sp(props, quotes, *, evidence=None, env=None):
    index = ee.EvidenceIndex(evidence if evidence is not None else
                             [_evidence(t=T_TICK, home="Philadelphia 76ers", away="Toronto Raptors")])
    reader = ee.Reader()
    qi = ee.PropQuoteIndex(quotes, reader)
    ops, skipped = ee.stat_progress_opinions([_props_row(props)], qi, index, reader, env=env)
    return ops, skipped, qi, reader


def test_stat_progress_on_then_off():
    on, _, _, _ = _sp([_prop()], _two_books())
    off, _, _, _ = _sp([_prop()], _two_books(), env={ee.OFF_ENV: "stat_progress"})
    assert on[0].refusal is None and on[0].delta_logit is not None
    assert off[0].refusal == "expert_off" and off[0].delta_logit is None and off[0].p_expert is None


def test_stat_progress_is_the_published_p_smoothed_at_sims_against_the_book_median():
    ops, _, _, _ = _sp([_prop(p=0.82)], _two_books())
    op = ops[0]
    p_adj, se = ee.agresti_coull(82.0, 100.0)
    assert op.p_expert == pytest.approx(round(p_adj, 6))
    assert op.sigma == pytest.approx(round(ee.sigma_logit_from_se(p_adj, se), 6))
    # fanduel -120/+100 de-vigs to 0.521739 over, draftkings -110/-110 to 0.5; median of two, renormalised
    fd = (120 / 220) / (120 / 220 + 0.5)
    assert op.p_prior == pytest.approx(round((fd + 0.5) / 2, 6))
    assert op.delta_logit == pytest.approx(round(ee.logit(p_adj) - ee.logit(op.p_prior), 6), abs=2e-6)
    assert op.inputs["book_p"] == {"draftkings": 0.5, "fanduel": round(fd, 6)}
    assert op.prior_age_s == 130.0  # 01:00:00Z - the newest book stamp 00:57:50Z
    assert (op.side, op.segment, op.player, op.market, op.line) == ("over", "full", "Tyrese Maxey", "player_points", 24.5)
    assert (op.clock_bucket, op.elapsed_share) == ("25-50", 0.375)


def test_a_quote_captured_after_the_instant_is_not_the_prior():
    late = [_quote("draftkings", "over", -300, captured="2026-11-13T01:00:30Z", updated="2026-11-13T01:00:20Z"),
            _quote("draftkings", "under", 220, captured="2026-11-13T01:00:30Z", updated="2026-11-13T01:00:20Z")]
    ops, _, _, _ = _sp([_prop()], _two_books() + late)
    assert ops[0].inputs["book_p"]["draftkings"] == 0.5


@pytest.mark.parametrize("quotes, refusal", [
    ([_quote("fanduel", "over", -120)], "prior_one_sided"),
    ([_quote("fanduel", "over", -120), _quote("fanduel", "under", 100, updated="2026-11-13T00:40:00Z",
                                              captured="2026-11-13T00:40:05Z")], "prior_unpaired"),
    (_two_books(captured="2026-11-13T00:40:05Z", updated="2026-11-13T00:40:00Z"), "prior_stale"),
    ([_quote("fanduel", "over", 150), _quote("fanduel", "under", 150)], "prior_implausible_hold"),
    (_two_books(captured="2026-11-13T01:05:00Z"), "no_quote_before_instant"),
])
def test_prior_refusals_are_named(quotes, refusal):
    ops, _, _, _ = _sp([_prop()], quotes)
    assert ops[0].refusal == refusal and ops[0].delta_logit is None and ops[0].p_prior is None


def test_producer_refusals_pass_through_by_their_own_name():
    pulled = _prop(p=None, extra={"unpricedReason": "quote_pulled", "quotePulled": True, "liveDisplayProbOver": 0.4})
    certain = _prop(line=24.5, p=None, player="Joel Embiid", extra={"unpricedReason": "certainty_refused"})
    quotes = _two_books() + _two_books(player="Joel Embiid")
    ops, _, _, _ = _sp([pulled, certain], quotes)
    assert sorted(o.refusal for o in ops) == ["certainty_refused", "quote_pulled"]
    assert all(o.delta_logit is None for o in ops)


def test_ladder_rows_are_counted_not_opined():
    rows = [_prop(line=24.5), _prop(line=22.5, p=0.9), _prop(player="Paul Reed", line=6.5, p=0.4)]
    ops, skipped, _, _ = _sp(rows, _two_books())
    assert [o.line for o in ops] == [24.5]
    assert skipped == {"line_not_quoted": 1, "no_quotes_for_player_market": 1}


def test_the_player_name_folds_and_the_team_order_does_not_matter():
    quotes = [dict(q, player_name="TYRESE  Maxey", home_team="Toronto Raptors", away_team="Philadelphia 76ers")
              for q in _two_books()]
    ops, skipped, _, _ = _sp([_prop()], quotes)
    assert skipped == {} and ops[0].refusal is None


def test_doubles_yes_is_over_the_fixed_line():
    nan = float("nan")
    dd = _prop(line=1.5, p=0.35, prop="player_double_double")
    quotes = [_quote("espnbet", "Yes", 180, line=nan, market="player_double_double"),
              _quote("espnbet", "No", -240, line=nan, market="player_double_double"),
              _quote("fanduel", "Yes", 170, line=nan, market="player_double_double")]
    ops, skipped, _, _ = _sp([dd], quotes)
    assert skipped == {}
    op = ops[0]
    assert op.refusal is None and op.inputs["prior_books"] == 1 and op.inputs["one_sided_books"] == ["fanduel"]
    over, under = 100 / 280, 240 / 340
    assert op.p_prior == pytest.approx(round(over / (over + under), 6))


def test_no_lane_row_leaves_the_bucket_unknown_not_the_opinion():
    ops, _, _, _ = _sp([_prop()], _two_books(), evidence=[])
    assert ops[0].refusal is None and ops[0].clock_bucket is None
    assert ops[0].inputs["evidence_match"] == "no_game_match"


def test_the_prior_reproduces_the_boards_own_fair_value_function():
    rows = [_prop(line=24.5, p=0.82), _prop(line=24.5, p=0.3, player="Joel Embiid")]
    quotes = _two_books() + [_quote("betmgm", "over", 105), _quote("betmgm", "under", -135)] + \
        _two_books(player="Joel Embiid") + [_quote("kalshi", "over", -105, player="Joel Embiid", updated=None),
                                            _quote("kalshi", "under", -102, player="Joel Embiid", updated=None)]
    ops, _, qi, _ = _sp(rows, quotes)
    rep = ee.prior_reproduction(ops, qi)
    assert rep["checked"] == 2 and rep["prior_mismatched"] == 0 and rep["p_mismatched"] == 0, rep


def test_stat_progress_checklist_reads_the_streamed_population():
    pulled = _prop(p=None, extra={"unpricedReason": "quote_pulled", "quotePulled": True})
    ops, _, qi, reader = _sp([_prop(), pulled], _two_books())
    props_row = _props_row([_prop(), pulled])
    # the fleet's nights: unpricedReason on 42-45% of the rows at quoted lines (11-11, 11-12)
    cl = ee.checklist(ops, reader, {"props_log": [props_row], "live_props": [_prop(), pulled],
                                    "live_evidence": [_evidence(t=T_TICK)]},
                      sport="nba", min_opined=1, populated={"book_quotes": qi.populated()})
    consumed = {row["input"] for row in cl["inputs"] if row["expert"] == "stat_progress"}
    assert {"book_quotes:price", "book_quotes:captured_at", "live_props:liveModelProbOver", "props_log:t",
            "live_evidence:state"} <= consumed
    assert cl["ok"], cl["alarms"]
    starved = ee.PropQuoteIndex([dict(q, captured_at=None) for q in _two_books()], ee.Reader())
    assert starved.populated() == (4, {k: 4 for k in starved.non_null}) and "captured_at" not in starved.non_null


# ----------------------------------------------------------------------------- live segment expert (college halves)
#
# Fixtures in the fleet's shapes (NCAAB 11-12): an evidence tick carrying `segments.<seg>` blocks (total_dist /
# margin_dist histograms, 200 sims, settled, marginAnchored, remainingFraction) and `book_quotes` game-line rows, where
# a spread's `selection` is "home" / "away" and each side carries its OWN handicap.

SEG_HOME, SEG_AWAY = "Sacred Heart Pioneers", "Central Connecticut St Blue Devils"
H2_TOTAL = {"30": 50, "34": 50, "38": 50, "42": 50}
H2_MARGIN = {"-6": 50, "-2": 50, "3": 50, "8": 50}


def _seg_block(*, settled=False, anchored=True, total=None, margin=None):
    return {"total_dist": dict(total or H2_TOTAL), "margin_dist": dict(margin or H2_MARGIN), "sims": 200,
            "settled": settled, "marginAnchored": anchored, "remainingFraction": 0.5, "total_mean": 36.0,
            "includesOvertime": True}


def _seg_evidence(t=T_TICK, *, h2=None, h1=None, sport="ncaab"):
    return {"t": t, "as_of": "2026-11-13T00:59:50+00:00", "sport": sport, "event_id": "401922250",
            "home_name": SEG_HOME, "away_name": SEG_AWAY, "refusal": None, "carried": False,
            "state": {"period": 2, "clockSeconds": 1200}, "segments": {
                "h1": h1 if h1 is not None else _seg_block(settled=True),
                "h2": h2 if h2 is not None else _seg_block()}}


def _gq(book, market, selection, line, price, *, segment="h2", captured="2026-11-13T00:58:00Z",
        updated="2026-11-13T00:57:50Z"):
    return {"captured_at": captured, "snapshot_ts": updated, "book_updated_at": updated, "sport": "ncaab",
            "date": "2026-11-12", "kind": "game", "event_id": "fc5d", "commence_time": "2026-11-13T00:00:00Z",
            "home_team": SEG_HOME, "away_team": SEG_AWAY, "bookmaker": book, "market": market, "segment": segment,
            "selection": selection, "player_name": None, "line": line, "price": price}


def _seg_quotes(**kw):
    """h2 total 35.5 and h2 spread home -2.5 / away +2.5, two books each."""
    return [_gq("fanduel", "totals", "over", 35.5, -120, **kw), _gq("fanduel", "totals", "under", 35.5, 100, **kw),
            _gq("draftkings", "totals", "over", 35.5, -110, **kw),
            _gq("draftkings", "totals", "under", 35.5, -110, **kw),
            _gq("fanduel", "spreads", "home", -2.5, -105, **kw), _gq("fanduel", "spreads", "away", 2.5, -115, **kw),
            _gq("draftkings", "spreads", "home", -2.5, -110, **kw),
            _gq("draftkings", "spreads", "away", 2.5, -110, **kw)]


def _seg(evidence, quotes, *, env=None):
    index = ee.EvidenceIndex(evidence)
    reader = ee.Reader()
    qi = ee.GameLineQuoteIndex(quotes, reader)
    rows, blocks = [], []
    ops, stats = ee.live_segment_opinions(index, qi, reader, env=env, keep_rows=rows, keep_blocks=blocks)
    return ops, stats, index, qi, reader, rows, blocks


def _by(ops, market):
    return [o for o in ops if o.market == market]


def test_canonical_quote_side_puts_spreads_in_the_joins_away_frame():
    assert ee.canonical_quote_side("totals", "over", 35.5) == ("over", 35.5)
    assert ee.canonical_quote_side("totals", "Under", 35.5) == ("under", 35.5)
    # home -2.5 and away +2.5 are ONE line: home covers when margin > 2.5 (`price_distribution_market`, no negation)
    assert ee.canonical_quote_side("spreads", "home", -2.5) == ("over", 2.5)
    assert ee.canonical_quote_side("spreads", "away", 2.5) == ("under", 2.5)
    side, line = ee.canonical_quote_side("spreads", "home", 0.0)
    assert (side, line, math.copysign(1.0, line)) == ("over", 0.0, 1.0)  # no -0.0 key
    assert ee.canonical_quote_side("spreads", "Sacred Heart Pioneers", -2.5) is None
    assert ee.canonical_quote_side("h2h", "home", None) is None


def test_live_segment_prices_the_tick_histogram_exactly_as_the_join_would():
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    ops, stats, index, qi, _, _, _ = _seg([_seg_evidence()], _seg_quotes())
    assert stats["games_matched"] == 1 and stats["games_unmatched"] == []
    total, spread = _by(ops, "totals")[0], _by(ops, "spreads")[0]
    # P(h2 total > 35.5) = 100 of 200; P(home covers -2.5) = P(margin > 2.5) = 100 of 200. Read in the WRONG frame
    # (margin > -2.5) the spread would be 150 of 200, which is what pins the sign.
    assert (total.inputs["k"], total.inputs["n"]) == (100, 200)
    assert (spread.inputs["k"], spread.inputs["n"], spread.line, spread.side) == (100, 200, 2.5, "home")
    for op, dist in ((total, H2_TOTAL), (spread, H2_MARGIN)):
        joined = price_distribution_market(dist=dist, line=op.line, side=op.side, market=op.market,
                                           market_prob=op.p_prior, sims=200, sport="ncaab", prob_scale=1.0)
        assert op.p_expert == pytest.approx(joined["model_prob"], abs=1e-6)
        assert (op.segment, op.phase, op.clock_bucket, op.elapsed_share) == ("h2", "live", "50-75", 0.5)
        assert op.line_key == f"ncaab|401922250|{op.market}|h2||{op.side}|{op.line:g}"
        assert op.sigma_basis == "mc_agresti_coull" and op.prior_basis == "book_quotes:median_devig_2way"
    fd = (120 / 220) / (120 / 220 + 0.5)  # fanduel -120 / +100 over; draftkings -110 / -110 is 0.5
    assert total.p_prior == pytest.approx(round((fd + 0.5) / 2, 6))
    rep = ee.segment_join_reproduction(ops, index)
    assert (rep["checked"], rep["mismatched"]) == (2, 0)


def test_live_segment_on_then_off():
    on, *_ = _seg([_seg_evidence()], _seg_quotes())
    off, *_ = _seg([_seg_evidence()], _seg_quotes(), env={ee.OFF_ENV: "live_segment"})
    assert len(on) == len(off) == 2
    assert all(o.delta_logit is not None for o in on)
    assert all(o.refusal == "expert_off" and o.delta_logit is None and o.p_expert is None for o in off)


def test_only_lines_standing_at_the_tick_are_opined_and_a_settled_half_is_skipped():
    stale = [_gq("fanduel", "totals", "over", 33.5, -110, captured="2026-11-13T00:40:00Z",
                 updated="2026-11-13T00:40:00Z"),
             _gq("fanduel", "totals", "under", 33.5, -110, captured="2026-11-13T00:40:00Z",
                 updated="2026-11-13T00:40:00Z")]
    later = [_gq("fanduel", "totals", "over", 37.5, -110, captured="2026-11-13T01:00:30Z",
                 updated="2026-11-13T01:00:20Z"),
             _gq("fanduel", "totals", "under", 37.5, -110, captured="2026-11-13T01:00:30Z",
                 updated="2026-11-13T01:00:20Z")]
    h1 = [_gq("fanduel", "totals", "over", 70.5, -110, segment="h1"),
          _gq("fanduel", "totals", "under", 70.5, -110, segment="h1")]
    ops, stats, *_ = _seg([_seg_evidence()], _seg_quotes() + stale + later + h1)
    # 33.5 was last quoted 20 min before the tick, 37.5 only after it, and h1 has settled: none is a line then
    assert sorted((o.market, o.line) for o in ops) == [("spreads", 2.5), ("totals", 35.5)]
    assert stats["segment_settled"] == 1 and stats["ticks"] == 1


def test_a_sample_certainty_is_refused_as_the_join_refuses_it():
    far = [_gq("fanduel", "totals", "over", 45.5, -110), _gq("fanduel", "totals", "under", 45.5, -110)]
    ops, *_ = _seg([_seg_evidence()], far)
    assert len(ops) == 1
    assert ops[0].refusal == "sample_certainty" and ops[0].delta_logit is None
    assert (ops[0].inputs["k"], ops[0].inputs["n"]) == (0, 200)


def test_an_unanchored_segment_margin_refuses_spreads_only():
    ops, *_ = _seg([_seg_evidence(h2=_seg_block(anchored=False))], _seg_quotes())
    assert _by(ops, "spreads")[0].refusal == "segment_margin_unanchored"
    assert _by(ops, "totals")[0].delta_logit is not None


def test_unmatched_games_are_counted_not_opined():
    ops, stats, *_ = _seg([_seg_evidence()], [dict(q, home_team="Other Home", away_team="Other Away")
                                             for q in _seg_quotes()])
    assert ops == [] and stats["games_matched"] == 0
    assert stats["games_unmatched"] == ["other home|other away"]


def test_the_segment_prior_reproduces_the_boards_own_fair_value_function():
    ops, _, _, qi, *_ = _seg([_seg_evidence()], _seg_quotes())
    rep = ee.segment_prior_reproduction(ops, qi)
    assert (rep["checked"], rep["mismatched"]) == (2, 0)
    ops[0].p_prior = round(ops[0].p_prior + 0.01, 6)
    assert ee.segment_prior_reproduction(ops, qi)["mismatched"] == 1


def test_the_frame_reading_scores_the_joins_own_prior_and_the_flipped_frame_worse():
    full = [_gq("fanduel", "spreads", "home", -2.5, -150, segment="full"),
            _gq("fanduel", "spreads", "away", 2.5, 130, segment="full"),
            _gq("fanduel", "spreads", "home", 2.5, 200, segment="full"),
            _gq("fanduel", "spreads", "away", -2.5, -240, segment="full")]
    qi = ee.GameLineQuoteIndex(full, ee.Reader())
    p_home = (150 / 250) / (150 / 250 + 100 / 230)  # home -2.5 at -150 against away +2.5 at +130, de-vigged
    row = _ledger("spreads", 2.5, recorded_at="2026-11-13T01:00:00+00:00", prior=round(p_home, 4), home=SEG_HOME,
                  away=SEG_AWAY)
    fr = ee.segment_frame_check([row], qi)
    assert fr["spreads"]["n"] == 1 and fr["spreads"]["median_pp"] < 0.01
    assert fr["spreads_sign_flipped"]["median_pp"] > 20.0


def test_segment_checklist_reads_the_block_population_and_names_nbas_missing_anchor():
    nba_block = {k: v for k, v in _seg_block().items() if k not in ("marginAnchored", "remainingFraction")}
    ev = [_seg_evidence(h2=nba_block, sport="nba")] + [_seg_evidence(t=f"2026-11-12T19:00:{s:02d}-06:00",
                                                                     h2=nba_block, sport="nba") for s in range(1, 25)]
    ops, _, _, qi, reader, rows, blocks = _seg(ev, _seg_quotes())
    assert len(blocks) == 25 and all(o.market == "totals" or o.refusal == "segment_margin_unanchored" for o in ops)
    cl = ee.checklist(ops, reader, {"live_evidence": rows, "segment_block": blocks}, sport="nba",
                      populated={"book_quotes": qi.populated()})
    assert cl["ok"], cl["alarms"]
    documented = {i["input"] for i in cl["inputs"] if i.get("documented_sparse")}
    assert {"segment_block:marginAnchored", "segment_block:remainingFraction"} <= documented
    # the same gap on a sport that has not documented it is an alarm
    alarmed = ee.checklist(ops, reader, {"live_evidence": rows, "segment_block": blocks}, sport="ncaab",
                           populated={"book_quotes": qi.populated()})
    assert {a["input"] for a in alarmed["alarms"]} == {"segment_block:marginAnchored",
                                                       "segment_block:remainingFraction"}


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
