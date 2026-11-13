"""The NBA live re-sim's full-game margin is anchored to the market's close (`#780`, lane nba-live-margin-anchor, user
2026-11-13 "Build it now"). `nba/live_resim.py` "margin anchor" has the measurement and the rule.

Reachability first (`off != on`): the same game through `build_live_lens_snapshot` with the switch on and off, then the
anchored lane through the board join's moneyline. After that: the math, the named no-anchor paths (which keep the raw
numbers and the live props), WNBA untouched, the orientation flip, the cache, the history row and the tick's counts.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.ncaab.live_resim import home_spread_quotes
from syndicate.features.shared.live_gameline_join import (
    agresti_coull_point,
    attach_live_gamelines,
    build_live_gameline_index,
)
from tests.basketball_pbp_fixtures import Game

DATE = "2026-01-15"
ENV = "SYNDICATE_NBA_LIVE_MARGIN_ANCHOR"
HOME, AWAY = "GSW", "NYK"
HOME_NAME, AWAY_NAME = "Golden State Warriors", "New York Knicks"
COMMENCE = "2026-01-16 03:00:00+00:00"
# The raw sim: 200 draws, home margin -1 or +3 (mean +1.0), P(home) 0.5.
RAW = {"sims_run": 200, "home_win_prob": 0.5, "overtime_prob": 0.03, "total_mean": 220.0, "home_margin_mean": 1.0,
       "total_dist": {"220": 200}, "margin_dist": {"-1": 100, "3": 100}, "segments": {"h1": {"margin_dist": {"0": 200}}},
       "player_remainders": {"home": {}, "away": {}}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    lr._ANCHOR_CACHE.clear()
    lr._ANCHOR_SOURCES.clear()
    yield
    lr._ANCHOR_CACHE.clear()
    lr._ANCHOR_SOURCES.clear()


def _quote(book, line, *, seen="2026-01-16T02:30:00+00:00", home=HOME_NAME, away=AWAY_NAME):
    return {"market": "spreads", "selection": "home", "segment": "full", "line": line, "snapshot_ts": seen,
            "bookmaker": book, "home_team": home, "away_team": away, "commence_time": COMMENCE}


def _market(*rows):
    return home_spread_quotes("nba", DATE, rows=list(rows))


def _artifact(root, margin):
    path = lr.smart_sim_path(DATE, HOME, AWAY, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"score": {"margin_mean": margin}}), encoding="utf-8")


def _in_q2():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3).foul(1, "9:00", "home", "h2")
    g.end_period(1)
    g.shot(2, "11:40", "home", "h1").sub(2, "10:00", "away", "a6", "a5").shot(2, "9:30", "away", "a6")
    return g


def _snapshot(tmp_path, monkeypatch):
    """One live game, the engine and the inputs faked: only the anchor decides what the lane shows."""
    live = _in_q2().summary()
    sb = {"events": [{"id": "999", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]}]}
    monkeypatch.setattr(lr, "load_engine_inputs", lambda *a, **k: {"home_players": None, "away_players": None})
    monkeypatch.setattr(lr, "map_state_names", lambda gs, *_a: (gs, {}))
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: dict(RAW))
    monkeypatch.setattr(lr, "build_live_props", lambda *a, **k: ([], {}))
    return lr.build_live_lens_snapshot(DATE, fetch_scoreboard=lambda *_a: sb, fetch_summary=lambda *_a: live,
                                       inputs_root=tmp_path)


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_snapshot(tmp_path, monkeypatch):
    """Close -6.5 (home by 6.5), pregame sim +1.0: offset +5.5, scaled by the share still to play."""
    _artifact(tmp_path, 1.0)
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: _market(_quote("dk", -6.5), _quote("fd", -6.5)))
    on = _snapshot(tmp_path, monkeypatch)["games"][0]["gameLens"][0]
    lr._ANCHOR_CACHE.clear()
    monkeypatch.setenv(ENV, "off")
    off = _snapshot(tmp_path, monkeypatch)["games"][0]["gameLens"][0]

    assert off["modelHomeWinProb"] == 0.5 and "marginAnchor" not in off and "rawModelHomeWinProb" not in off
    assert on["rawModelHomeWinProb"] == 0.5
    anchor = on["marginAnchor"]
    assert anchor["marketHomeMargin"] == 6.5 and anchor["simHomeMargin"] == 1.0 and anchor["offset"] == 5.5
    assert anchor["books"] == 2 and 0.5 < anchor["remainingFraction"] < 0.75  # Q2, 9:30 left
    assert on["modelHomeWinProb"] > 0.9  # -1 / +3 shifted by ~+3.6: almost every draw is a home win
    assert on["projection"]["homeMargin"] == pytest.approx(1.0 + anchor["appliedOffset"], abs=0.01)
    assert on["projection"]["marginDist"] != off["projection"]["marginDist"]
    # Untouched by the anchor: totals, segments, the overtime chance.
    for key in ("totalRunsDist", "total", "segments"):
        assert on["projection"][key] == off["projection"][key]
    assert on["modelOvertimeProb"] == off["modelOvertimeProb"] == 0.03


def test_the_board_join_prices_the_anchored_moneyline(monkeypatch):
    """The lane's `modelHomeWinProb` is what the join's h2h pricer reads (`hit["home_win_prob"]`)."""
    now = datetime(2026, 1, 16, 3, 30, tzinfo=timezone.utc)
    facts = lr.ResumeFacts("401", HOME, AWAY, 50, 48, 2, 0.0, None, 99, (now - timedelta(seconds=20)).isoformat())
    anchor = lr.NbaMarginAnchor(market_home_margin=6.5, sim_home_margin=1.0, books=3)
    probs = {}
    for label, result in (("raw", dict(RAW)), ("anchored", lr.anchor_result(RAW, anchor, remaining_fraction=0.5))):
        snap = {"games": [{"home": HOME_NAME, "away": AWAY_NAME, "gameLens": lr.build_game_lens(facts, result)}]}
        index = build_live_gameline_index(snap, sources=("live_resim",), sport="nba")
        row = {"kind": "game", "market": "h2h", "segment": "full", "line": None, "sides": ["home", "away"],
               "away_team": AWAY_NAME, "home_team": HOME_NAME, "age_seconds": 10.0,
               "updated_at": (now - timedelta(seconds=10)).isoformat(), "game": {"state": "live"},
               "projection": {"market_fair_prob_over": 0.6}}
        attach_live_gamelines([row], index, sport="nba", now=now)
        probs[label] = row["live_gameline"]["model_prob"]
    assert probs["raw"] == pytest.approx(agresti_coull_point(0.5, 200), abs=1e-9)
    assert probs["anchored"] > probs["raw"] + 0.2


# --------------------------------------------------------------------------------------------- the math

@pytest.mark.parametrize("period,clock,share", [(1, 720.0, 1.0), (3, 720.0, 0.5), (2, 0.0, 0.5), (4, 0.0, 0.0),
                                                (4, 360.0, 0.125), (5, 300.0, 0.0), (None, None, 1.0)])
def test_remaining_regulation_fraction(period, clock, share):
    assert lr.remaining_regulation_fraction(period, clock) == pytest.approx(share)


def test_anchor_result_moves_the_mean_by_the_scaled_offset_and_keeps_the_raw_numbers():
    anchor = lr.NbaMarginAnchor(market_home_margin=4.0, sim_home_margin=1.0, books=5)
    out = lr.anchor_result(RAW, anchor, remaining_fraction=0.5)
    assert out["margin_anchor"]["appliedOffset"] == 1.5
    assert out["home_margin_mean"] == pytest.approx(1.0 + 1.5, abs=1 / 200)
    assert sum(out["margin_dist"].values()) == 200
    assert out["raw_home_win_prob"] == 0.5 and out["raw_home_margin_mean"] == 1.0
    assert out["total_dist"] == RAW["total_dist"] and out["segments"] == RAW["segments"]


def test_a_shifted_zero_counts_half_to_each_side():
    anchor = lr.NbaMarginAnchor(market_home_margin=0.0, sim_home_margin=1.0, books=1)  # offset -1 at the tip
    out = lr.anchor_result({**RAW, "margin_dist": {"1": 200}}, anchor, remaining_fraction=1.0)
    assert out["margin_dist"] == {"0": 200} and out["home_win_prob"] == 0.5


def test_at_the_tip_the_anchored_mean_is_the_market():
    anchor = lr.NbaMarginAnchor(market_home_margin=6.5, sim_home_margin=1.0, books=4)
    out = lr.anchor_result(RAW, anchor, remaining_fraction=1.0)
    assert out["home_margin_mean"] == pytest.approx(6.5, abs=1 / 200)


def test_overtime_applies_no_shift():
    anchor = lr.NbaMarginAnchor(market_home_margin=10.0, sim_home_margin=1.0, books=4)
    facts = lr.ResumeFacts("401", HOME, AWAY, 100, 100, 5, 200.0, None, 9, "t")
    lr._ANCHOR_CACHE[("nba", DATE, "401")] = anchor
    out = lr.apply_margin_anchor(RAW, facts, date=DATE, home=HOME, away=AWAY)
    assert out["margin_dist"] == RAW["margin_dist"] and out["margin_anchor"]["appliedOffset"] == 0.0


# --------------------------------------------------------------------------------------------- no anchor, WNBA, switch

def _facts():
    return lr.ResumeFacts("401", HOME, AWAY, 50, 48, 2, 300.0, None, 9, "t")


def test_no_pregame_sim_margin_keeps_the_raw_numbers_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: pytest.fail("the quote log must not be read"))
    out = lr.apply_margin_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, root=tmp_path)
    assert out["margin_anchor_refusal"] == "no_pregame_sim_margin"
    assert out["home_win_prob"] == 0.5 and out["margin_dist"] == RAW["margin_dist"] and "margin_anchor" not in out
    lane = lr.build_game_lens(_facts(), out)[0]
    assert lane["source"] == "live_resim" and lane["marginAnchorRefusal"] == "no_pregame_sim_margin"
    assert lane["modelHomeWinProb"] == 0.5  # the lane is published, not refused: its live props stay up


def test_no_closing_spread_keeps_the_raw_numbers_by_name(tmp_path, monkeypatch):
    _artifact(tmp_path, 1.0)
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: _market(_quote("dk", -3.0, home="Boston Celtics")))
    out = lr.apply_margin_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, root=tmp_path)
    assert out["margin_anchor_refusal"] == "no_closing_spread" and out["home_win_prob"] == 0.5


def test_a_quote_after_the_commence_is_not_the_close(tmp_path, monkeypatch):
    _artifact(tmp_path, 1.0)
    late = _quote("dk", -20.0, seen="2026-01-16T03:10:00+00:00")  # in-play
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: _market(_quote("dk", -4.0), late))
    anchor = lr.margin_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path)
    assert anchor.market_home_margin == 4.0


def test_a_flipped_feed_orientation_is_flipped_back(tmp_path, monkeypatch):
    _artifact(tmp_path, 1.0)
    flipped = _quote("dk", +4.0, home=AWAY_NAME, away=HOME_NAME)  # the feed's home is the live away side
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: _market(flipped))
    anchor = lr.margin_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path)
    assert anchor.market_home_margin == 4.0  # NYK +4 at home in the feed = GSW -4 there = GSW by 4 in the live frame


def test_wnba_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "margin_anchor_for", lambda *a, **k: pytest.fail("WNBA must never look for an anchor"))
    out = lr.apply_margin_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, league="wnba", root=tmp_path)
    assert out == RAW
    assert set(lr.build_game_lens(_facts(), out)[0]) == set(lr.build_game_lens(_facts(), RAW)[0])


@pytest.mark.parametrize("raw", ["off", "OFF", "0", "false", "no"])
def test_the_switch_serves_the_raw_sim(monkeypatch, raw):
    monkeypatch.setenv(ENV, raw)
    monkeypatch.setattr(lr, "margin_anchor_for", lambda *a, **k: pytest.fail("off must not look for an anchor"))
    out = lr.apply_margin_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY)
    assert out == RAW and "marginAnchorRefusal" not in lr.build_game_lens(_facts(), out)[0]


def test_a_found_anchor_is_kept_for_the_game(tmp_path, monkeypatch):
    _artifact(tmp_path, 1.0)
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: _market(_quote("dk", -5.0)))
    first = lr.margin_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path)
    lr.smart_sim_path(DATE, HOME, AWAY, root=tmp_path).unlink()
    monkeypatch.setattr(lr, "_anchor_market", lambda *a, **k: pytest.fail("a found anchor is cached"))
    assert lr.margin_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path) is first


# --------------------------------------------------------------------------------------------- history and tick line

def test_history_rows_carry_the_raw_number_only_when_anchored():
    facts = _facts()
    anchored = lr.anchor_result(RAW, lr.NbaMarginAnchor(6.5, 1.0, 3), remaining_fraction=0.5)
    games = [{"event_id": "1", "gameLens": lr.build_game_lens(facts, anchored)},
             {"event_id": "2", "gameLens": lr.build_game_lens(facts, {**RAW, "margin_anchor_refusal": "no_closing_spread"})},
             {"event_id": "3", "gameLens": lr.build_game_lens(facts, RAW)}]
    rows = lr.history_rows({"generatedAt": "t", "date": DATE, "games": games})
    assert rows[0]["p_home_raw"] == 0.5 and rows[0]["margin_anchor"]["offset"] == 5.5
    assert rows[1]["margin_anchor_refusal"] == "no_closing_spread" and "p_home_raw" not in rows[1]
    assert "p_home_raw" not in rows[2] and "margin_anchor" not in rows[2] and "margin_anchor_refusal" not in rows[2]
    assert lr._anchor_counts(games) == {"anchored": 1, "anchor_missing": {"no_closing_spread": 1}}
    assert lr._anchor_counts(games[2:]) == {}


# --------------------------------------------------------------------------------------------- the spreads scale follows the lane

SPREADS_ENV = "SYNDICATE_LIVE_SPREADS_PROB_SCALE"


def _spreads_scale_through_the_join(result, sport="nba"):
    """One full-game spreads row priced through the board join off a lane built from `result`; returns prob_scale."""
    from syndicate.features.shared.live_gameline_join import attach_live_gamelines, build_live_gameline_index

    now = datetime(2026, 1, 16, 3, 30, tzinfo=timezone.utc)
    facts = lr.ResumeFacts("401", HOME, AWAY, 50, 48, 2, 0.0, None, 99, (now - timedelta(seconds=20)).isoformat())
    snap = {"games": [{"home": HOME_NAME, "away": AWAY_NAME, "gameLens": lr.build_game_lens(facts, result)}]}
    index = build_live_gameline_index(snap, sources=("live_resim",), sport=sport)
    row = {"kind": "game", "market": "spreads", "segment": "full", "line": 2.5, "sides": ["home", "away"],
           "away_team": AWAY_NAME, "home_team": HOME_NAME, "age_seconds": 10.0,
           "updated_at": (now - timedelta(seconds=10)).isoformat(), "game": {"state": "live"},
           "projection": {"market_fair_prob_over": 0.2}}
    attach_live_gamelines([row], index, sport=sport, now=now)
    return row["live_gameline"].get("prob_scale")


@pytest.fixture
def _no_spreads_env(monkeypatch):
    for suffix in ("", "_NBA", "_NCAAB"):
        monkeypatch.delenv(SPREADS_ENV + suffix, raising=False)


def test_an_anchored_nba_lane_prices_spreads_at_the_anchored_k(_no_spreads_env):
    anchored = lr.anchor_result(RAW, lr.NbaMarginAnchor(6.5, 1.0, 3), remaining_fraction=0.5)
    assert _spreads_scale_through_the_join(anchored) == pytest.approx(1.57)
    assert _spreads_scale_through_the_join(dict(RAW)) == pytest.approx(2.02)  # a raw lane keeps the raw k
    no_anchor = {**RAW, "margin_anchor_refusal": "no_closing_spread"}
    assert _spreads_scale_through_the_join(no_anchor) == pytest.approx(2.02)


def test_the_switches_still_win_on_an_anchored_lane(_no_spreads_env, monkeypatch):
    from syndicate.features.shared.live_gameline_join import spreads_prob_scale

    assert spreads_prob_scale("nba", anchored=True) == pytest.approx(1.57)
    monkeypatch.setenv(SPREADS_ENV + "_NBA", "1.2")
    assert spreads_prob_scale("nba", anchored=True) == pytest.approx(1.2)  # an explicit per-sport value wins
    monkeypatch.delenv(SPREADS_ENV + "_NBA")
    monkeypatch.setenv(SPREADS_ENV, "off")
    assert spreads_prob_scale("nba", anchored=True) == 1.0


def test_an_anchored_college_lane_keeps_its_own_k(_no_spreads_env):
    """College lanes are always anchored and their table was fitted on anchored margins: no anchored entry."""
    from syndicate.features.shared.live_gameline_join import spreads_prob_scale

    assert spreads_prob_scale("ncaab", anchored=True) == spreads_prob_scale("ncaab") == pytest.approx(1.34)
    assert spreads_prob_scale("wncaab", anchored=True) == 1.0
