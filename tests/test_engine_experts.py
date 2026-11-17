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


def test_the_join_check_reads_the_engines_number_on_a_tempered_spread(monkeypatch):
    """#780 fix 2b (`273a4a599`) tempers full-game SPREADS too (NBA k 2.02), and the ledger writes their k and
    unscaled number into the same v7 fields. The check keys on `prob_scale`, not on the market, so a tempered spread
    is compared on the engine's number exactly as a tempered total is."""
    from syndicate.features.shared import live_gameline_join as lgj

    for key in ("SYNDICATE_LIVE_SPREADS_PROB_SCALE", "SYNDICATE_LIVE_SPREADS_PROB_SCALE_NBA"):
        monkeypatch.delenv(key, raising=False)
    ev = _evidence()
    index = ee.EvidenceIndex([ev])
    k = lgj.full_game_prob_scale("spreads", "full", "nba")
    assert k == lgj.spreads_prob_scale("nba") and k != 1.0  # with k = 1 this test proves nothing
    assert lgj.full_game_prob_scale("spreads", "h2", "nba") == 1.0  # segments stay untempered (live_segment's k)
    line = -4.5  # home covers on 75 of 100 sims, so the temper moves the number
    join = lgj.price_distribution_market(dist=ev["marginDist"], line=line, side="home", market="spreads",
                                         market_prob=0.5, sims=100, prob_scale=k)
    assert abs(join["model_prob"] - join["model_prob_unscaled"]) > 0.05
    rec = {**_ledger("spreads", line, join_p=join["model_prob"]), "v": 7, "prob_scale": join["prob_scale"],
           "model_home_win_prob_unscaled": join["model_prob_unscaled"]}
    op = ee.live_resim_expert(rec, index, ee.Reader())
    assert op.refusal is None and op.inputs["join_prob_scale"] == pytest.approx(k)
    assert op.inputs["join_model_p"] == pytest.approx(join["model_prob_unscaled"], abs=1e-12)
    rep = ee.join_reproduction([op])
    assert rep["checked"] == 1 and rep["mismatched"] == 0
    # a spreads row written before 273a4a599 (prob_scale None) is read as the untempered number it was
    pre = ee.live_resim_expert({**rec, "prob_scale": None, "model_home_win_prob": join["model_prob_unscaled"],
                                "model_home_win_prob_unscaled": None}, index, ee.Reader())
    assert ee.join_reproduction([pre])["mismatched"] == 0
    # and reading the tempered number as the join's would be caught
    assert ee.join_reproduction([ee.live_resim_expert({**rec, "prob_scale": None}, index, ee.Reader())])[
        "mismatched"] == 1


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


def test_a_row_whose_state_is_newer_than_its_tick_is_filed_at_its_state():
    # NHL stamps its snapshot BEFORE it reads the scoreboard: this row's state is 20 s newer than its tick.
    row = _evidence(t="2026-11-09T18:20:00-06:00", as_of="2026-11-10T00:20:20+00:00", p_home=0.7)
    at = ee._parse("2026-11-10T00:20:10+00:00")
    on = ee.EvidenceIndex([row])
    assert on.state_after_tick == 1 and on.instant(row) == ee._parse("2026-11-10T00:20:20Z")
    assert on.lookup("Charlotte Hornets", "Cleveland Cavaliers", at, None) == (None, "no_evidence_before_instant")
    off = ee.EvidenceIndex([row], env={ee.OFF_ENV: ee.FEATURE_STATE_INSTANT})
    assert off.state_after_tick == 0 and off.instant(row) == ee._parse(row["t"])
    found, match = off.lookup("Charlotte Hornets", "Cleveland Cavaliers", at, None)
    assert match == "as_of_instant" and found["modelHomeWinProb"] == 0.7
    # A state at or before its tick is untouched (NBA / NCAAB stamp the snapshot after they read the state).
    plain = _evidence()
    assert ee.EvidenceIndex([plain]).instant(plain) == ee._parse(plain["t"])


def test_live_resim_never_scores_a_line_against_a_state_newer_than_the_line():
    row = _evidence(t="2026-11-09T18:20:00-06:00", as_of="2026-11-10T00:20:20+00:00")
    off_env = {ee.OFF_ENV: ee.FEATURE_STATE_INSTANT}
    early = [_ledger(recorded_at="2026-11-10T00:20:10+00:00", state_as_of=None, join_p=0.5)]
    on = ee.live_opinions(early, ee.EvidenceIndex([row]), ee.Reader())[0]
    off = ee.live_opinions(early, ee.EvidenceIndex([row], env=off_env), ee.Reader(), env=off_env)[0]
    assert on.refusal == "no_evidence_before_instant" and on.p_expert is None
    assert off.inputs["evidence_match"] == "as_of_instant" and off.inputs["evidence_age_s"] == 10.0
    late = [_ledger(recorded_at="2026-11-10T00:20:40+00:00", state_as_of=None, join_p=0.5)]
    on = ee.live_opinions(late, ee.EvidenceIndex([row]), ee.Reader())[0]
    off = ee.live_opinions(late, ee.EvidenceIndex([row], env=off_env), ee.Reader(), env=off_env)[0]
    # The evidence is as old as its STATE, not its stamp; the stamp still re-finds the row.
    assert on.inputs["evidence_age_s"] == 20.0 and on.inputs["evidence_instant"] == "2026-11-10T00:20:20+00:00"
    assert on.inputs["evidence_t"] == row["t"]
    assert off.inputs["evidence_age_s"] == 40.0 and "evidence_instant" not in off.inputs


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


def _sp(props, quotes, *, evidence=None, env=None, sport=None):
    index = ee.EvidenceIndex(evidence if evidence is not None else
                             [_evidence(t=T_TICK, home="Philadelphia 76ers", away="Toronto Raptors")])
    reader = ee.Reader()
    qi = ee.PropQuoteIndex(quotes, reader, sport=sport)
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


@pytest.mark.parametrize("engine, books", [
    ("Herbert Jones", "Herb Jones"),  # the engine's nickname alias
    ("Derrick Jones Jr.", "Derrick Jones"),  # a suffix the books leave off
    ("Paul Reed", "Paul Reed Jr"),  # and one they keep
    ("Robert Williams III", "Robert Williams"),
])
def test_nba_players_match_on_the_engines_name_key(engine, books):
    """Lane prop-expert-name-key: the re-sim publishes the engine's spelling, the books their own. On NBA the index
    keys both through the engine's key, so the line opines; with no sport (the old fold) it found no quotes at all."""
    quotes = _two_books(player=books)
    on, skipped_on, qi, _ = _sp([_prop(player=engine)], quotes, sport="nba")
    off, skipped_off, _, _ = _sp([_prop(player=engine)], quotes)
    assert on[0].refusal is None and on[0].delta_logit is not None and skipped_on == {}
    assert off == [] and skipped_off == {"no_quotes_for_player_market": 1}
    rep = ee.prior_reproduction(on, qi)
    assert rep["checked"] == 1 and rep["prior_mismatched"] == 0 and rep["p_mismatched"] == 0, rep


def test_the_index_names_spellings_it_merged_and_keeps_two_players_apart():
    quotes = (_two_books(player="Derrick Jones")[:2] + _two_books(player="Derrick Jones Jr.")[2:]
              + _two_books(player="Jalen Williams") + _two_books(player="Jaylin Williams"))
    qi = ee.PropQuoteIndex(quotes, ee.Reader(), sport="nba")
    spellings = sorted({ee._fold_player("Derrick Jones"), ee._fold_player("Derrick Jones Jr.")})
    assert list(qi.merged.values()) == [spellings]
    jalen, _ = qi.lookup("Philadelphia 76ers", "Toronto Raptors", "Jalen Williams", "player_points", 24.5)
    jaylin, _ = qi.lookup("Philadelphia 76ers", "Toronto Raptors", "Jaylin Williams", "player_points", 24.5)
    assert len(jalen) == 4 and len(jaylin) == 4 and jalen is not jaylin
    both, _ = qi.lookup("Philadelphia 76ers", "Toronto Raptors", "Derrick Jones Jr.", "player_points", 24.5)
    assert sorted(e[2] for e in both) == ["draftkings", "draftkings", "fanduel", "fanduel"]  # one player, both books
    assert ee.PropQuoteIndex(quotes, ee.Reader()).merged == {}  # the fold keeps the two spellings apart
    assert ee.prop_player_key("nhl", "Derrick Jones Jr.") == ee._fold_player("Derrick Jones Jr.")


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
    index = ee.EvidenceIndex(evidence, env=env)
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


def test_a_segment_opinion_on_a_tick_whose_state_is_newer_is_dated_and_priced_at_the_state():
    ev = _seg_evidence()
    ev["as_of"] = "2026-11-13T01:00:20+00:00"  # 20 s after its tick (T_TICK is 01:00:00Z)
    on, _, index, *_ = _seg([ev], _seg_quotes())
    off, *_ = _seg([dict(ev)], _seg_quotes(), env={ee.OFF_ENV: ee.FEATURE_STATE_INSTANT})
    t_on, t_off = _by(on, "totals")[0], _by(off, "totals")[0]
    assert t_on.t == "2026-11-13T01:00:20+00:00" and t_on.inputs["evidence_t"] == T_TICK
    assert t_off.t == T_TICK and "evidence_t" not in t_off.inputs
    # Same books, read 20 s later: the prior is the same number, 20 s older.
    assert t_on.p_prior == t_off.p_prior and t_on.prior_age_s == t_off.prior_age_s + 20.0
    # The reproduction still re-finds the tick through the stamp the opinion kept.
    rep = ee.segment_join_reproduction(on, index)
    assert (rep["checked"], rep["mismatched"]) == (2, 0)


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


def test_a_row_whose_abbreviations_reduce_to_its_names_is_one_tick_not_two():
    """NCAAB's evidence rows carry `home` / `away` with the same team key as the names. Filed under both, every
    tick sat twice in one series and every NCAAB segment opinion was written twice (fleet 11-09..11-12)."""
    row = {**_seg_evidence(), "home": SEG_HOME.upper(), "away": SEG_AWAY}
    index = ee.EvidenceIndex([row])
    assert [len(s) for s in index.by_game.values()] == [1]
    ops, stats, *_ = _seg([row], _seg_quotes())
    assert stats["ticks"] == 1 and sorted((o.market, o.line) for o in ops) == [("spreads", 2.5), ("totals", 35.5)]
    nba = {**_evidence(), "home": "CHA", "away": "CLE"}  # distinct abbreviations: one series per key, as before
    assert sorted(len(s) for s in ee.EvidenceIndex([nba]).by_game.values()) == [1, 1]


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


# ----------------------------------------------------------------------------- live refusals (2026-11-16)
#
# Lane engine-experts-live-refusals. Fleet 11-09..11-14: live NCAAF refused every line `no_game_match` (the ledger names
# the odds feed's teams, the evidence log ESPN's short names), and NHL puck lines / totals refused `no_prior` (their
# prior sits in `market_fair_prob_over`; the puck line's number only in the ledger's `display_prob`).

NCAAF_CANON = {"iowa state cyclones": "iowa state", "iowa state": "iowa state", "cincinnati bearcats": "cincinnati",
               "cincinnati": "cincinnati", "iowa state university": "iowa state"}


def _canon(sport, away, home):
    """A stand-in for the join's #791 registry: (away, home) canonical, None when either side does not resolve."""
    a, h = NCAAF_CANON.get(str(away).lower()), NCAAF_CANON.get(str(home).lower())
    return (a, h) if a and h else None


def _ncaaf_evidence(**kw):
    ev = _evidence(home="Iowa State", away="Cincinnati", **kw)
    return {**ev, "sport": "ncaaf", "event_id": None, "home": "Iowa State", "away": "Cincinnati"}


def _ncaaf_ledger(market="totals", line=215.5, *, home="Iowa State Cyclones", away="Cincinnati Bearcats", **kw):
    return {**_ledger(market, line, home=home, away=away, **kw), "sport": "ncaaf"}


def test_ncaaf_names_meet_through_the_joins_canonical_pair_and_off_restores_exact_only():
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    ev = _ncaaf_evidence()
    join = price_distribution_market(dist=ev["totalRunsDist"], line=215.5, side="over", market="totals",
                                     market_prob=0.5, sims=100)
    row = _ncaaf_ledger(join_p=join["model_prob"])
    on = ee.live_resim_expert(row, ee.EvidenceIndex([ev], sport="ncaaf", alias_key=_canon), ee.Reader())
    assert on.refusal is None and on.inputs["evidence_key"] == "team_alias"
    assert on.inputs["evidence_game"] == ["iowa state", "cincinnati"]  # the log's own key, to re-find the tick
    assert on.inputs["evidence_match"] == "same_state" and on.clock_bucket == "25-50"
    rep = ee.join_reproduction([on])
    assert (rep["checked"], rep["mismatched"]) == (1, 0)  # the lane the join priced, not merely a lane
    off_env = {ee.OFF_ENV: ee.FEATURE_TEAM_ALIAS}
    off = ee.live_resim_expert(row, ee.EvidenceIndex([ev], sport="ncaaf", alias_key=_canon, env=off_env),
                               ee.Reader())
    assert off.refusal == "no_game_match" and off.delta_logit is None  # off != on
    # no sport: the index is exact-only, as every caller was before
    assert ee.live_resim_expert(row, ee.EvidenceIndex([ev], alias_key=_canon), ee.Reader()).refusal == "no_game_match"
    # an exact name still wins, and says so
    exact = ee.live_resim_expert(_ncaaf_ledger(home="Iowa State", away="Cincinnati"),
                                 ee.EvidenceIndex([ev], sport="ncaaf", alias_key=_canon), ee.Reader())
    assert exact.inputs["evidence_key"] == "exact" and exact.refusal is None
    # a canonical pair with the sides swapped is not the same game (the join does not swap either)
    swapped = ee.live_resim_expert(_ncaaf_ledger(home="Cincinnati Bearcats", away="Iowa State Cyclones"),
                                   ee.EvidenceIndex([ev], sport="ncaaf", alias_key=_canon), ee.Reader())
    assert swapped.refusal == "no_game_match"


def test_two_evidence_games_under_one_canonical_pair_are_refused_not_guessed():
    a = _ncaaf_evidence()
    b = {**_ncaaf_evidence(p_home=0.3), "home_name": "Iowa State University", "home": "Iowa State University"}
    index = ee.EvidenceIndex([a, b], sport="ncaaf", alias_key=_canon)
    op = ee.live_resim_expert(_ncaaf_ledger(), index, ee.Reader())
    assert op.refusal == "team_alias_ambiguous" and op.delta_logit is None
    # one game filed under its names AND its codes is two keys over the SAME rows: one series, not ambiguity
    coded = {**_ncaaf_evidence(), "home": "ISU", "away": "CIN"}
    canon = {**NCAAF_CANON, "isu": "iowa state", "cin": "cincinnati"}
    index = ee.EvidenceIndex([coded], sport="ncaaf",
                             alias_key=lambda s, a, h: (canon.get(str(a).lower()), canon.get(str(h).lower())))
    assert len(index.by_game) == 2
    assert ee.live_resim_expert(_ncaaf_ledger(), index, ee.Reader()).inputs["evidence_key"] == "team_alias"


def test_the_default_canonical_pair_is_the_joins_own_function_and_switch(monkeypatch):
    from syndicate.features.shared import team_aliases

    monkeypatch.setattr(team_aliases, "chip_join_key", lambda sport, name: NCAAF_CANON.get(str(name).lower()))
    monkeypatch.delenv("SYNDICATE_LIVE_GAMELINE_TEAM_ALIASES", raising=False)
    ev = _ncaaf_evidence()
    on = ee.live_resim_expert(_ncaaf_ledger(), ee.EvidenceIndex([ev], sport="ncaaf"), ee.Reader())
    assert on.inputs["evidence_key"] == "team_alias" and on.refusal is None
    # NBA is outside the join's fallback (#791 is NCAAF only), so its names must still meet exactly
    nba = ee.EvidenceIndex([_evidence(home="Iowa State", away="Cincinnati")], sport="nba")
    assert nba.find("Iowa State Cyclones", "Cincinnati Bearcats") == (None, "no_game_match")
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_TEAM_ALIASES", "off")  # the join's own switch reaches the expert
    off = ee.live_resim_expert(_ncaaf_ledger(), ee.EvidenceIndex([ev], sport="ncaaf"), ee.Reader())
    assert off.refusal == "no_game_match"


def test_a_line_priced_before_the_log_starts_is_a_gap_not_a_failed_identity():
    index = ee.EvidenceIndex([_evidence()])  # first row 2026-11-10T00:20:00Z
    early = ee.live_resim_expert(_ledger(home="Nobody", recorded_at="2026-11-10T00:05:00+00:00"), index, ee.Reader())
    assert early.refusal == "evidence_log_starts_after_instant"
    late = ee.live_resim_expert(_ledger(home="Nobody"), index, ee.Reader())
    assert late.refusal == "no_game_match"
    assert ee.live_resim_expert(_ledger(), ee.EvidenceIndex([]), ee.Reader()).refusal == \
        "evidence_log_starts_after_instant"


def _unpriced(market="totals", line=215.5, *, over=0.5, segment="full", **kw):
    """A full-game row the join did not price (NHL puck line / total): no market fair, the v6 first side beside it."""
    return {**_ledger(market, line, segment=segment, prior=None, **kw), "v": 7, "market_fair_prob_over": over,
            "point_estimator": None}


def test_the_prior_is_read_under_its_v6_name_on_full_game_totals_and_spreads_only():
    index = ee.EvidenceIndex([_evidence()])
    on = ee.live_resim_expert(_unpriced(over=0.47), index, ee.Reader())
    assert on.refusal is None and on.p_prior == 0.47
    assert on.prior_basis == "live_gameline_ledger.market_fair_prob_over"
    sp = ee.live_resim_expert(_unpriced("spreads", 3.5, over=0.4), index, ee.Reader())
    assert sp.refusal is None and sp.p_prior == 0.4 and sp.side == "home"
    off = ee.live_resim_expert(_unpriced(over=0.47), index, ee.Reader(), frozenset({ee.FEATURE_FAIR_OVER}))
    assert off.refusal == "no_prior" and off.delta_logit is None  # off != on
    # the join's own price still wins where it exists
    both = ee.live_resim_expert({**_ledger(prior=0.52), "market_fair_prob_over": 0.47}, index, ee.Reader())
    assert both.p_prior == 0.52 and both.prior_basis == "live_gameline_ledger.market_fair_prob"
    # never on a segment (measured: never set there) or a moneyline (P(home) is `market_fair_prob` itself)
    seg = {**_unpriced(segment="h1", over=0.47), "market": "totals"}
    assert ee.live_resim_expert(seg, index, ee.Reader()).refusal == "no_prior"
    ml = {**_unpriced("h2h", None, over=0.47)}
    assert ee.live_resim_expert(ml, index, ee.Reader()).refusal == "no_prior"


def test_the_join_check_skips_a_row_the_join_did_not_price_and_the_frame_gate_reads_it():
    index = ee.EvidenceIndex([_evidence()])
    # the join keeps a raw k/n share on a row it did not price: not its estimator, so not the JOIN gate's row
    op = ee.live_resim_expert({**_unpriced(over=0.47), "model_home_win_prob": 0.5}, index, ee.Reader())
    assert op.refusal is None and op.inputs["join_model_p"] == 0.5
    assert ee.join_reproduction([op])["checked"] == 0
    assert ee.fallback_frame_check([op])["families"]["nba:totals"]["verdict"] == "UNJUDGED"  # 1 pair: not a pass


def _opined(p, prior, *, sport="nhl", market="spreads", display=True):
    op = ee.ExpertOpinion(expert="live_resim", sport=sport, market=market, p_expert=p, p_prior=prior,
                          delta_logit=0.0, prior_basis=ee.PRIOR_BASIS_FAIR_OVER)
    if display:
        op.inputs["p_source"] = ee.P_SOURCE_DISPLAY
    return op


def test_the_frame_gate_passes_the_right_frame_and_fails_a_flipped_one():
    right = [_opined(0.70 + 0.002 * i, 0.72) for i in range(30)] + [_opined(0.28, 0.30) for _ in range(10)]
    res = ee.fallback_frame_check(right)
    assert res["families"]["nhl:spreads"]["verdict"] == "PASS" and (res["judged"], res["failed"]) == (1, 0)
    flipped = [_opined(1.0 - o.p_expert, o.p_prior) for o in right]  # a side error: home read as away
    bad = ee.fallback_frame_check(flipped)
    assert bad["families"]["nhl:spreads"]["verdict"] == "FAIL" and bad["failed"] == 1
    near = [_opined(0.52, 0.49) for _ in range(50)]  # near even the flipped reading cannot be told apart: unjudged
    assert ee.fallback_frame_check(near)["families"]["nhl:spreads"]["verdict"] == "UNJUDGED"
    # opinions the JOIN gate checks are not this gate's population
    priced = _opined(0.3, 0.7, display=False)
    priced.prior_basis = "live_gameline_ledger.market_fair_prob"
    assert ee.fallback_frame_check([priced])["families"] == {}


def _nhl_evidence(**kw):
    ev = _evidence(home="Carolina Hurricanes", away="Seattle Kraken", sims=200, period=1, clock=600.0, **kw)
    return {k: v for k, v in {**ev, "sport": "nhl", "event_id": None}.items()
            if k not in ("marginDist", "totalRunsDist")}  # NHL lanes log neither (displayMarginDist is not kept)


def _nhl_puck_line(line=1.5, display=130 / 204, *, over=0.5811, reason="live_margin_published_for_display_only"):
    return {**_unpriced("spreads", line, over=over, home="Carolina Hurricanes", away="Seattle Kraken"), "sport": "nhl",
            "sims_run": 200, "display_prob": display, "display_basis": reason, "withheld_reason": reason,
            "model_home_win_prob": None}


def test_an_nhl_puck_line_opines_from_the_ledgers_display_number_and_each_switch_restores_its_refusal():
    index = ee.EvidenceIndex([_nhl_evidence()], sport="nhl")
    op = ee.live_resim_expert(_nhl_puck_line(), index, ee.Reader())
    assert op.refusal is None and op.inputs["p_source"] == ee.P_SOURCE_DISPLAY
    assert (op.inputs["k"], op.inputs["n"], op.inputs["push"]) == (128, 200, 0)
    assert op.p_expert == pytest.approx(130 / 204, abs=1e-6) and op.p_prior == 0.5811
    assert op.sigma_basis == "mc_agresti_coull" and op.sigma == pytest.approx(
        ee.sigma_logit_from_se(130 / 204, ee.agresti_coull(128, 200)[1]), abs=1e-6)
    assert op.clock_bucket == "0-25" and op.line == 1.5 and op.side == "home"
    off_display = ee.live_resim_expert(_nhl_puck_line(), index, ee.Reader(), frozenset({ee.FEATURE_DISPLAY_MARGIN}))
    assert off_display.refusal == "no_distribution"  # off != on
    off_prior = ee.live_resim_expert(_nhl_puck_line(), index, ee.Reader(), frozenset({ee.FEATURE_FAIR_OVER}))
    assert off_prior.refusal == "no_prior"  # the refusal fleet 11-09..11-14 showed on every puck line


def test_the_display_path_refuses_by_name_what_it_cannot_read():
    index = ee.EvidenceIndex([_nhl_evidence()], sport="nhl")
    r = ee.Reader()
    assert ee.live_resim_expert(_nhl_puck_line(display=0.6372), index, r).refusal == "display_prob_not_agresti_coull"
    assert ee.live_resim_expert(_nhl_puck_line(line=2.0, display=0.5), index, r).refusal == "display_prob_whole_line"
    assert ee.live_resim_expert(_nhl_puck_line(display=None), index, r).refusal == "no_display_probability"
    assert ee.live_resim_expert(_nhl_puck_line(display=202 / 204), index, r).refusal == "sample_certainty"
    # a spread with no histogram that is NOT a display-only row, and an NHL total (no histogram anywhere)
    assert ee.live_resim_expert(_nhl_puck_line(reason="quote_stale"), index, r).refusal == "no_distribution"
    total = {**_nhl_puck_line(), "market": "totals", "line": 6.5, "display_prob": None,
             "withheld_reason": "live_resim_published_no_distribution_for_this_market"}
    assert ee.live_resim_expert(total, index, r).refusal == "no_distribution"


def test_the_segment_expert_finds_an_ncaaf_game_through_the_canonical_pair():
    canon = {SEG_HOME.lower(): "sh", "sacred heart": "sh", SEG_AWAY.lower(): "aw", "away u": "aw"}

    def alias(sport, away, home):
        a, h = canon.get(str(away).lower()), canon.get(str(home).lower())
        return (a, h) if a and h else None

    ev = {**_seg_evidence(sport="ncaaf"), "home_name": "Sacred Heart", "away_name": "Away U"}
    reader = ee.Reader()
    qi = ee.GameLineQuoteIndex(_seg_quotes(), reader)
    index = ee.EvidenceIndex([ev], sport="ncaaf", alias_key=alias)
    ops, stats = ee.live_segment_opinions(index, qi, reader)
    assert (stats["games_matched"], stats["games_matched_by_team_alias"], stats["games_unmatched"]) == (1, 1, [])
    assert len(ops) == 2 and all(o.delta_logit is not None for o in ops)
    assert ops[0].inputs["evidence_game"] == ["sacred heart", "away u"]
    rep = ee.segment_join_reproduction(ops, index)
    assert (rep["checked"], rep["mismatched"]) == (2, 0)  # the tick is found under the evidence log's own key
    assert (rep := ee.segment_prior_reproduction(ops, qi))["mismatched"] == 0 and rep["checked"] == 2
    off = ee.EvidenceIndex([ev], sport="ncaaf", alias_key=alias, env={ee.OFF_ENV: ee.FEATURE_TEAM_ALIAS})
    ops_off, stats_off = ee.live_segment_opinions(off, qi, ee.Reader())
    assert ops_off == [] and stats_off["games_matched"] == 0  # off != on


def test_live_resim_refuses_a_sample_certainty_as_the_join_does():
    """The join records a certainty (`_dist_prob_over` -> None) as no distribution; once `fair_over` gave those rows a
    prior the expert met them (fleet 11-14: 313 NCAAF rows, a line the game had left behind)."""
    ev = _evidence(margin={"20": 60, "25": 60}, sims=120)
    op = ee.live_resim_expert(_unpriced("spreads", 8.5, over=0.5025), ee.EvidenceIndex([ev]), ee.Reader())
    assert op.refusal == "sample_certainty" and op.delta_logit is None
    assert (op.inputs["k"], op.inputs["n"]) == (120, 120)


def test_the_join_gate_reads_the_joins_own_rounding_at_n_120_and_still_catches_a_wrong_k():
    """`_dist_prob_over` rounds the share to 4 dp before smoothing: at NCAAF's 120 sims the join's number is up to
    4.8e-5 from the expert's unrounded one (fleet 11-14: 12,808 of 19,227 half-point lines); at 100 / 200 it is
    exact."""
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    dist = {"30": 52, "60": 68}  # 52 of 120 under 45.5, so 68 over: 68/120 = 0.56667 is not exact at 4 dp
    ev = _evidence(total=dist, sims=120)
    join = price_distribution_market(dist=dist, line=45.5, side="over", market="totals", market_prob=0.5, sims=120)
    op = ee.live_resim_expert(_ledger("totals", 45.5, join_p=join["model_prob"]), ee.EvidenceIndex([ev]), ee.Reader())
    assert op.p_expert == pytest.approx(70 / 124, abs=1e-6)  # the expert keeps the unrounded share
    assert abs(op.p_expert - join["model_prob"]) > 1e-6  # so the old gate would call this a mismatch
    assert ee.join_estimate(68, 120) == pytest.approx(join["model_prob"], abs=1e-12)
    rep = ee.join_reproduction([op])
    assert (rep["checked"], rep["mismatched"], rep["rounding_only"]) == (1, 0, 1)
    off_by_one = ee.live_resim_expert(_ledger("totals", 45.5, join_p=ee.join_estimate(67, 120)),
                                      ee.EvidenceIndex([ev]), ee.Reader())
    assert ee.join_reproduction([off_by_one])["mismatched"] == 1  # one sim is 8e-3: a wrong k still fails
    seg = {"h1": {"total_dist": dist, "margin_dist": {"-3": 60, "3": 60}, "sims": 120, "settled": False,
                  "marginAnchored": True}}
    quotes = [_gq("fanduel", "totals", "over", 45.5, -110, segment="h1"),
              _gq("fanduel", "totals", "under", 45.5, -110, segment="h1")]
    ops, _stats, index, *_ = _seg([_seg_evidence(h1=seg["h1"])], quotes)
    srep = ee.segment_join_reproduction(ops, index)
    assert (srep["checked"], srep["mismatched"], srep["rounding_only"]) == (1, 0, 1)


def test_an_ncaaf_segment_opinion_takes_the_odds_feeds_event_id_when_the_lane_has_none():
    ev = {**_seg_evidence(sport="ncaaf"), "event_id": None}
    ops, *_ = _seg([ev], _seg_quotes())
    assert ops and all(o.event_id == "fc5d" and o.inputs["event_id_source"] == "book_quotes" for o in ops)
    assert ops[0].line_key.startswith("ncaaf|fc5d|")
    with_id, *_ = _seg([_seg_evidence()], _seg_quotes())  # NCAAB lanes carry ESPN's id: kept, as before
    assert all(o.event_id == "401922250" and "event_id_source" not in o.inputs for o in with_id)


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
