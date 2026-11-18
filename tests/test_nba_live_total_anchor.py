"""The NBA live re-sim's full-game TOTAL anchored to the market's close (`#834`, lane nba-live-resim-total-anchor).
`nba/live_resim.py` "total anchor" has the measurement and the rule; ABSENT IS OFF.

Reachability first (`off != on`): the same game through `build_live_lens_snapshot` with the switch absent and on, then
the anchored lane through the board join's totals pricer. After that: the math, the close (before the commence, per
book, either orientation), the named no-anchor paths (raw numbers kept, lane still published), WNBA untouched, the
cache, the history row and the tick's tally.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.college_basketball.prior_calibration import closing_totals
from syndicate.features.nba import live_resim as lr
from syndicate.features.shared.live_gameline_join import attach_live_gamelines, build_live_gameline_index
from tests.basketball_pbp_fixtures import Game

DATE = "2026-01-15"
ENV = "SYNDICATE_NBA_LIVE_TOTAL_ANCHOR"
MARGIN_ENV = "SYNDICATE_NBA_LIVE_MARGIN_ANCHOR"
HOME, AWAY = "GSW", "NYK"
HOME_NAME, AWAY_NAME = "Golden State Warriors", "New York Knicks"
COMMENCE = "2026-01-16 03:00:00+00:00"
# The raw sim: 200 draws, total 220 or 230 (mean 225.0).
RAW = {"sims_run": 200, "home_win_prob": 0.5, "overtime_prob": 0.03, "total_mean": 225.0, "home_margin_mean": 1.0,
       "total_dist": {"220": 100, "230": 100}, "margin_dist": {"-1": 100, "3": 100},
       "segments": {"h1": {"total_mean": 110.0, "total_dist": {"110": 200}}}, "player_remainders": {"home": {}, "away": {}}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setenv(MARGIN_ENV, "off")  # isolate the total anchor; the margin anchor has its own tests
    lr._TOTAL_ANCHOR_CACHE.clear()
    lr._TOTAL_SOURCES.clear()
    yield
    lr._TOTAL_ANCHOR_CACHE.clear()
    lr._TOTAL_SOURCES.clear()


def _quote(book, line, *, seen="2026-01-16T02:30:00+00:00", home=HOME_NAME, away=AWAY_NAME, selection="over"):
    return {"market": "totals", "selection": selection, "segment": "full", "line": line, "snapshot_ts": seen,
            "bookmaker": book, "home_team": home, "away_team": away, "commence_time": COMMENCE}


def _market(*rows):
    return closing_totals("nba", DATE, rows=list(rows))


def _artifact(root, total):
    path = lr.smart_sim_path(DATE, HOME, AWAY, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"score": {"total_mean": total, "margin_mean": 1.0}}), encoding="utf-8")


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
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: json.loads(json.dumps(RAW)))
    monkeypatch.setattr(lr, "build_live_props", lambda *a, **k: ([], {}))
    return lr.build_live_lens_snapshot(DATE, fetch_scoreboard=lambda *_a: sb, fetch_summary=lambda *_a: live,
                                       inputs_root=tmp_path)


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_snapshot(tmp_path, monkeypatch):
    """Close 219.5, pregame sim 225.0: offset -5.5, scaled by the share of regulation still to play."""
    _artifact(tmp_path, 225.0)
    monkeypatch.setattr(lr, "_total_anchor_market",
                        lambda *a, **k: _market(_quote("dk", 219.5), _quote("fd", 219.5)))
    off = _snapshot(tmp_path, monkeypatch)["games"][0]["gameLens"][0]  # switch ABSENT
    monkeypatch.setenv(ENV, "on")
    on = _snapshot(tmp_path, monkeypatch)["games"][0]["gameLens"][0]

    assert off["projection"]["total"] == 225.0 and "totalAnchor" not in off and "rawModelTotal" not in off
    assert "totalAnchorRefusal" not in off
    assert on["rawModelTotal"] == 225.0
    anchor = on["totalAnchor"]
    assert anchor["marketTotal"] == 219.5 and anchor["simTotal"] == 225.0 and anchor["offset"] == -5.5
    assert anchor["books"] == 2 and 0.5 < anchor["remainingFraction"] < 0.75  # Q2, 9:30 left
    assert on["projection"]["total"] == pytest.approx(225.0 + anchor["appliedOffset"], abs=0.01)
    assert on["projection"]["total"] < off["projection"]["total"] - 3.0
    assert on["projection"]["totalRunsDist"] != off["projection"]["totalRunsDist"]
    assert sum(on["projection"]["totalRunsDist"].values()) == 200
    # Untouched by the total anchor: margin, P(home), segments, the overtime chance.
    for key in ("marginDist", "homeMargin", "segments"):
        assert on["projection"][key] == off["projection"][key]
    assert on["modelHomeWinProb"] == off["modelHomeWinProb"] and on["modelOvertimeProb"] == off["modelOvertimeProb"]


def _totals_prob_through_the_join(result, line=224.5):
    """One full-game totals row priced through the board join off a lane built from `result`; P(over)."""
    now = datetime(2026, 1, 16, 3, 30, tzinfo=timezone.utc)
    facts = lr.ResumeFacts("401", HOME, AWAY, 50, 48, 2, 0.0, None, 99, (now - timedelta(seconds=20)).isoformat())
    snap = {"games": [{"home": HOME_NAME, "away": AWAY_NAME, "gameLens": lr.build_game_lens(facts, result)}]}
    index = build_live_gameline_index(snap, sources=("live_resim",), sport="nba")
    row = {"kind": "game", "market": "totals", "segment": "full", "line": line, "sides": ["over", "under"],
           "away_team": AWAY_NAME, "home_team": HOME_NAME, "age_seconds": 10.0,
           "updated_at": (now - timedelta(seconds=10)).isoformat(), "game": {"state": "live"},
           "projection": {"market_fair_prob_over": 0.5}}
    attach_live_gamelines([row], index, sport="nba", now=now)
    return row["live_gameline"].get("model_prob")


def test_the_board_join_prices_the_anchored_total():
    """The join prices totals off `totalRunsDist` (and refuses a line outside its support): 205..244 shifted by -10,
    so P(over 224.5) goes from one half to a quarter before the join's totals scale tempers it."""
    wide = {**RAW, "total_mean": 224.5, "total_dist": {str(t): 5 for t in range(205, 245)}}
    anchor = lr.NbaTotalAnchor(market_total=214.5, sim_total=224.5, books=3)
    raw_p = _totals_prob_through_the_join(wide)
    anc_p = _totals_prob_through_the_join(lr.anchor_total_result(wide, anchor, remaining_fraction=1.0))
    assert raw_p is not None and anc_p is not None
    assert raw_p == pytest.approx(0.5, abs=0.01)
    assert anc_p < raw_p - 0.05


# --------------------------------------------------------------------------------------------- the math

def test_anchor_total_result_moves_the_mean_by_the_scaled_offset_and_keeps_the_raw_mean():
    anchor = lr.NbaTotalAnchor(market_total=221.0, sim_total=225.0, books=5)
    out = lr.anchor_total_result(RAW, anchor, remaining_fraction=0.5)
    assert out["total_anchor"]["appliedOffset"] == -2.0
    assert out["total_mean"] == pytest.approx(223.0, abs=1 / 200)
    assert sum(out["total_dist"].values()) == 200
    assert out["raw_total_mean"] == 225.0
    assert out["margin_dist"] == RAW["margin_dist"] and out["segments"] == RAW["segments"]
    assert out["home_win_prob"] == RAW["home_win_prob"]


def test_a_fractional_offset_splits_the_mass():
    anchor = lr.NbaTotalAnchor(market_total=224.5, sim_total=225.0, books=1)  # -0.5 at the tip
    out = lr.anchor_total_result({**RAW, "total_dist": {"220": 200}}, anchor, remaining_fraction=1.0)
    assert out["total_dist"] == {"219": 100, "220": 100}
    assert out["total_mean"] == pytest.approx(219.5)


def test_at_the_tip_the_anchored_mean_is_the_close():
    anchor = lr.NbaTotalAnchor(market_total=219.5, sim_total=225.0, books=4)
    out = lr.anchor_total_result(RAW, anchor, remaining_fraction=1.0)
    assert out["total_mean"] == pytest.approx(219.5, abs=1 / 200)


def test_overtime_applies_no_shift():
    anchor = lr.NbaTotalAnchor(market_total=210.0, sim_total=225.0, books=4)
    facts = lr.ResumeFacts("401", HOME, AWAY, 100, 100, 5, 200.0, None, 9, "t")
    lr._TOTAL_ANCHOR_CACHE[("nba", DATE, "401")] = anchor
    out = lr.apply_total_anchor(RAW, facts, date=DATE, home=HOME, away=AWAY, env={ENV: "on"})
    assert out["total_dist"] == RAW["total_dist"] and out["total_anchor"]["appliedOffset"] == 0.0


# --------------------------------------------------------------------------------------------- the close

def test_the_close_is_each_books_last_over_line_before_the_commence_median_across_books():
    rows = [_quote("dk", 221.0, seen="2026-01-16T01:00:00+00:00"), _quote("dk", 219.0),  # dk's last: 219
            _quote("fd", 220.0), _quote("mgm", 225.0),
            _quote("dk", 240.0, seen="2026-01-16T03:10:00+00:00"),  # in-play: not the close
            _quote("fd", 230.0, selection="under")]  # an UNDER quote never votes
    close = lr.closing_market_total(_market(*rows), HOME_NAME, AWAY_NAME)
    assert close == (220.0, 3)


def test_a_flipped_feed_orientation_still_finds_the_total():
    flipped = _quote("dk", 218.5, home=AWAY_NAME, away=HOME_NAME)
    assert lr.closing_market_total(_market(flipped), HOME_NAME, AWAY_NAME) == (218.5, 1)


# --------------------------------------------------------------------------------------------- no anchor, WNBA, switch

def _facts():
    return lr.ResumeFacts("401", HOME, AWAY, 50, 48, 2, 300.0, None, 9, "t")


def test_no_pregame_sim_total_keeps_the_raw_numbers_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_total_anchor_market", lambda *a, **k: pytest.fail("the quote log must not be read"))
    out = lr.apply_total_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, root=tmp_path, env={ENV: "on"})
    assert out["total_anchor_refusal"] == "no_pregame_sim_total"
    assert out["total_mean"] == 225.0 and out["total_dist"] == RAW["total_dist"] and "total_anchor" not in out
    lane = lr.build_game_lens(_facts(), out)[0]
    assert lane["source"] == "live_resim" and lane["totalAnchorRefusal"] == "no_pregame_sim_total"
    assert lane["projection"]["total"] == 225.0  # published, not refused: its live props stay up


def test_no_closing_total_keeps_the_raw_numbers_by_name(tmp_path, monkeypatch):
    _artifact(tmp_path, 225.0)
    monkeypatch.setattr(lr, "_total_anchor_market", lambda *a, **k: _market(_quote("dk", 219.0, home="Boston Celtics")))
    out = lr.apply_total_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, root=tmp_path, env={ENV: "on"})
    assert out["total_anchor_refusal"] == "no_closing_total" and out["total_mean"] == 225.0


def test_wnba_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "total_anchor_for", lambda *a, **k: pytest.fail("WNBA must never look for an anchor"))
    out = lr.apply_total_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, league="wnba", root=tmp_path,
                                env={ENV: "on"})
    assert out == RAW


@pytest.mark.parametrize("raw", [None, "", "off", "0", "false", "no", "maybe"])
def test_absent_or_anything_but_on_serves_the_raw_sim(raw):
    env = {} if raw is None else {ENV: raw}
    assert lr.total_anchor_enabled(env) is False


@pytest.mark.parametrize("raw", ["on", "ON", "1", "true", "yes"])
def test_on_values(raw):
    assert lr.total_anchor_enabled({ENV: raw}) is True


def test_off_never_looks_for_an_anchor_and_the_lane_is_unchanged(monkeypatch):
    monkeypatch.setattr(lr, "total_anchor_for", lambda *a, **k: pytest.fail("off must not look for an anchor"))
    out = lr.apply_total_anchor(RAW, _facts(), date=DATE, home=HOME, away=AWAY, env={})
    assert out == RAW
    assert lr.build_game_lens(_facts(), out) == lr.build_game_lens(_facts(), dict(RAW))


def test_a_found_anchor_is_kept_for_the_game(tmp_path, monkeypatch):
    _artifact(tmp_path, 225.0)
    monkeypatch.setattr(lr, "_total_anchor_market", lambda *a, **k: _market(_quote("dk", 219.0)))
    first = lr.total_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path)
    lr.smart_sim_path(DATE, HOME, AWAY, root=tmp_path).unlink()
    monkeypatch.setattr(lr, "_total_anchor_market", lambda *a, **k: pytest.fail("a found anchor is cached"))
    assert lr.total_anchor_for(DATE, "401", HOME, AWAY, root=tmp_path) is first


# --------------------------------------------------------------------------------------------- history and tick line

def test_history_rows_carry_the_raw_total_only_when_anchored():
    facts = _facts()
    anchored = lr.anchor_total_result(RAW, lr.NbaTotalAnchor(219.5, 225.0, 3), remaining_fraction=0.5)
    games = [{"event_id": "1", "gameLens": lr.build_game_lens(facts, anchored)},
             {"event_id": "2", "gameLens": lr.build_game_lens(facts, {**RAW, "total_anchor_refusal": "no_closing_total"})},
             {"event_id": "3", "gameLens": lr.build_game_lens(facts, RAW)}]
    rows = lr.history_rows({"generatedAt": "t", "date": DATE, "games": games})
    assert rows[0]["total_raw"] == 225.0 and rows[0]["total_anchor"]["offset"] == -5.5
    assert rows[0]["total"] == pytest.approx(222.25, abs=0.01)
    assert rows[1]["total_anchor_refusal"] == "no_closing_total" and "total_raw" not in rows[1]
    assert "total_raw" not in rows[2] and "total_anchor" not in rows[2] and "total_anchor_refusal" not in rows[2]
    assert lr._anchor_counts(games) == {"total_anchored": 1, "total_anchor_missing": {"no_closing_total": 1}}
    assert lr._anchor_counts(games[2:]) == {}


def test_both_anchors_on_one_lane():
    facts = _facts()
    both = lr.anchor_total_result(lr.anchor_result(RAW, lr.NbaMarginAnchor(6.5, 1.0, 3), remaining_fraction=0.5),
                                  lr.NbaTotalAnchor(219.5, 225.0, 3), remaining_fraction=0.5)
    lane = lr.build_game_lens(facts, both)[0]
    assert lane["marginAnchor"]["offset"] == 5.5 and lane["totalAnchor"]["offset"] == -5.5
    assert lane["rawModelHomeWinProb"] == 0.5 and lane["rawModelTotal"] == 225.0
    assert lr._anchor_counts([{"gameLens": [lane]}]) == {"anchored": 1, "anchor_missing": "-", "total_anchored": 1,
                                                         "total_anchor_missing": "-"}
