"""todo #859: the NCAAF live margin anchor (the in-play team-strength re-fit's passing candidate), lane
ncaaf-margin-aware-endgame.

REACHABILITY FIRST (`model_engine_standard.md`): through `run_refresh_worker._run_ncaaf_live_resim_tick` -- the function
the worker runs -- the switch must change the PUBLISHED win probability and margin when on, reach the board join, and
leave the snapshot and the tick's status byte-identical when absent. Only then is what the transform computes tested.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import scripts.run_refresh_worker as rw
from syndicate.features.ncaaf import live_margin_anchor as lma
from syndicate.features.ncaaf import live_resim as lr
from tests.test_ncaaf_live_resim_wiring import _espn_event, _FakeProjection, _wire_tick

RATINGS = {"oregon": (1.2, 0.6), "boise state": (0.1, 0.1), "penn state": (1.5, 0.8), "marshall": (-0.4, -0.2)}
_SEEN = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
_KICK = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)


def _quotes(home_spreads):
    """The NCAAF quote log in `home_spread_quotes`' shape: (home_key, away_key) -> [(seen, book, home line, commence)]."""
    return {key: [(_SEEN, f"book{i}", line, _KICK) for i, line in enumerate(lines)]
            for key, lines in home_spreads.items()}


# Oregon -10.5 (books -10, -10.5, -11), Penn State -21, Auburn +20 (3 books: the market makes the live game's home side
# a big underdog, so the anchor moves its win probability a long way even at the tick test's 12 sims).
QUOTES = _quotes({("oregon", "boise state"): [-10.0, -10.5, -11.0], ("penn state", "marshall"): [-21.0],
                  ("auburn", "baylor"): [20.0, 20.0, 19.5]})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(lma.SWITCH_ENV, raising=False)
    for key in list(__import__("os").environ):
        if key.startswith("SYNDICATE_NCAAF_LIVE_"):
            monkeypatch.delenv(key, raising=False)
    lma._QUOTE_SOURCES.clear()
    lma._E0_CACHE.clear()
    rw._NCAAF_SP_RATINGS_MEMO.clear()
    monkeypatch.setattr(lma, "_spread_quotes", lambda date: QUOTES)
    yield
    lma._QUOTE_SOURCES.clear()
    lma._E0_CACHE.clear()
    rw._NCAAF_SP_RATINGS_MEMO.clear()


# --------------------------------------------------------------------------
# REACHABILITY, through the worker's tick
# --------------------------------------------------------------------------

def _run_tick(monkeypatch, tmp_path):
    _wire_tick(
        monkeypatch, tmp_path,
        events=[_espn_event(away_loc="Baylor", home_loc="Auburn", away_id="239", home_id="2", period=2,
                            clock="9:41", away_score="7", home_score="10",
                            situation={"possession": "2", "down": 2, "distance": 6, "yardLine": 41})],
        projections=[_FakeProjection("Baylor", "Auburn")],
        ratings_teams={"baylor": (25.0, 20.0), "auburn": (28.0, 18.0)},
    )
    meta = rw._run_ncaaf_live_resim_tick()
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(lr.live_lens_snapshot_path(data_root()))
    status = read_json_file(rw._ncaaf_live_resim_status_path())
    return meta, snapshot, status


def _stable(doc):
    """The snapshot minus its wall clocks (two runs read the clock at different instants), and nothing else."""
    out = json.loads(json.dumps(doc))
    for key in ("generatedAt", "elapsedSeconds"):
        out.pop(key, None)
    ((out.get("coverage") or {}).get("player_exits") or {}).pop("elapsed_seconds", None)
    for game in out.get("games") or ():
        for lane in game.get("gameLens") or ():
            lane.pop("liveStateAsOf", None)
    return out


def _lane(snapshot):
    return snapshot["games"][0]["gameLens"][0]


def test_REACHABILITY_absent_switch_never_runs_the_anchor(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("the anchor ran with the switch absent")

    monkeypatch.setattr(lma, "anchor_lane", boom)
    monkeypatch.setattr(lma, "closing_home_margin_for", boom)
    meta, snapshot, status = _run_tick(monkeypatch, tmp_path)
    assert meta["written"] is True and meta["coverage"]["live_resimmed"] == 1
    assert "marginAnchor" not in snapshot
    lane = _lane(snapshot)
    assert "marginAnchor" not in lane["projection"] and "marginAnchorRefusal" not in lane["projection"]
    assert "rawModelHomeWinProb" not in lane
    assert "margin_anchor" not in meta and "margin_anchor" not in status["last"]


def test_REACHABILITY_off_is_byte_identical_to_absent(monkeypatch, tmp_path):
    _meta, absent, status_absent = _run_tick(monkeypatch, tmp_path / "absent")
    monkeypatch.setenv(lma.SWITCH_ENV, "off")
    _meta, off, status_off = _run_tick(monkeypatch, tmp_path / "off")
    assert _stable(off) == _stable(absent)
    assert set(status_off["last"]) == set(status_absent["last"])


def test_REACHABILITY_on_changes_the_win_probability_and_margin_and_nothing_else(monkeypatch, tmp_path):
    _meta, off, _status = _run_tick(monkeypatch, tmp_path / "off")
    monkeypatch.setenv(lma.SWITCH_ENV, "on")
    meta, on, status = _run_tick(monkeypatch, tmp_path / "on")
    lane_off, lane_on = _lane(off), _lane(on)
    block = lane_on["projection"]["marginAnchor"]
    assert block["source"] == lma.SOURCE
    assert block["marketHomeMargin"] == -20.0 and block["books"] == 3
    assert block["appliedOffset"] != 0
    assert lane_on["modelHomeWinProb"] != lane_off["modelHomeWinProb"]
    assert lane_on["projection"]["marginDist"] != lane_off["projection"]["marginDist"]
    # the engine's own numbers ride beside the anchored ones
    assert lane_on["rawModelHomeWinProb"] == lane_off["modelHomeWinProb"]
    assert lane_on["projection"]["rawHomeMargin"] == lane_off["projection"]["homeMargin"]
    assert lane_on["projection"]["homeMargin"] == pytest.approx(
        lane_off["projection"]["homeMargin"] + block["appliedOffset"], abs=2e-3)
    # the total and the state are the re-sim's own
    for key in ("total", "totalRunsDist", "homeScore", "awayScore", "period", "clockSeconds"):
        assert lane_on["projection"][key] == lane_off["projection"][key]
    assert lane_on["simsRun"] == lane_off["simsRun"]
    # counted where the fleet can read it: the snapshot and the tick's status
    assert on["marginAnchor"]["anchored"] == 1 and on["marginAnchor"]["kickoff_sims"] == 1
    assert meta["margin_anchor"]["anchored"] == 1
    assert status["last"]["margin_anchor"]["anchored"] == 1


def test_REACHABILITY_the_anchored_lane_is_what_the_real_join_prices(monkeypatch, tmp_path):
    """The join prices the moneyline off `modelHomeWinProb` and spreads off `marginDist`: both must be the anchored
    ones, and the hit must say it is anchored (`spreads_prob_scale` reads that)."""
    from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport

    monkeypatch.setenv(lma.SWITCH_ENV, "on")
    _meta, snapshot, _status = _run_tick(monkeypatch, tmp_path)
    index = build_live_gameline_index(snapshot, sources=lens_sources_for_sport("ncaaf"), diagnostics={},
                                      sport="ncaaf")
    (hit,) = index.values()
    lane = _lane(snapshot)
    assert hit["home_win_prob"] == lane["modelHomeWinProb"]
    assert {str(k): v for k, v in hit["margin_dist"].items()} == lane["projection"]["marginDist"]
    assert hit["margin_anchored"] is True


# --------------------------------------------------------------------------
# THE SNAPSHOT PASS: its inputs
# --------------------------------------------------------------------------

def _games():
    return [{"away_team": "Boise State", "home_team": "Oregon", "live_key": "a"},
            {"away_team": "Marshall", "home_team": "Penn State", "live_key": "b"}]


def _index(**overrides):
    row = {"in_progress": True, "final": False}
    out = {"a": {**row, "period": 2, "clock": "11:17", "home_score": 7, "away_score": 7,
                 "situation": {"down": 4, "distance": 5, "yardLine": 97}},
           "b": {**row, "period": 3, "clock": "13:28", "home_score": 17, "away_score": 0,
                 "situation": {"down": 2, "distance": 5, "yardLine": 24}}}
    for key, value in overrides.items():
        out[key] = {**row, **value}
    return out


def _snapshot(sims=40, **overrides):
    return lr.build_live_lens_snapshot("2026-11-14", games=_games(), live_index=_index(**overrides), ratings=RATINGS,
                                       sims=sims)


def _by_home(snap, home):
    (game,) = [g for g in snap["games"] if g["home_name"] == home]  # the snapshot runs cheapest-first
    return game["gameLens"][0]


def _no_clock(lane):
    """A lane minus its wall clock: two snapshots built a moment apart stamp different instants."""
    return {k: v for k, v in lane.items() if k != "liveStateAsOf"}


def _kickoff(home, away, ho, hd, ao, ad, sims=40):
    return lr.resim_live_game(lr.NcaafLiveGameState(away_team=away, home_team=home, period=1, clock_seconds=900,
                                                    home_score=0, away_score=0),
                              home_offense=ho, home_defense=hd, away_offense=ao, away_defense=ad, sims=sims)


ON = {lma.SWITCH_ENV: "on"}


def test_E0_is_the_resim_itself_at_kickoff_and_is_computed_once_per_game():
    snap = _snapshot()
    lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
    kick = _kickoff("Oregon", "Boise State", 1.2, 0.6, 0.1, 0.1)
    block = _by_home(snap, "Oregon")["projection"]["marginAnchor"]
    e0 = sum(int(k) * v for k, v in kick["margin_dist"].items()) / kick["sims_run"]
    assert block["kickoffHomeMargin"] == pytest.approx(e0, abs=1e-3)
    assert block["offset"] == pytest.approx(10.5 - e0, abs=1e-3)
    assert snap["marginAnchor"]["kickoff_sims"] == 2
    again = _snapshot()
    summary = lma.anchor_snapshot_margins(again, ratings=RATINGS, date_str="2026-11-14", env=ON)
    assert summary["kickoff_sims"] == 0 and summary["anchored"] == 2


def test_at_kickoff_the_anchored_margin_IS_the_market_margin():
    """The identity the anchor is built on: a lane resumed at Q1 15:00, 0-0, possession unknown is E0's own draws,
    the whole regulation is left, so its anchored mean is the close."""
    snap = _snapshot(a={"period": 1, "clock": "15:00", "home_score": 0, "away_score": 0})
    lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
    lane = _by_home(snap, "Oregon")
    assert lane["projection"]["marginAnchor"]["remainingShare"] == 1.0
    assert lane["projection"]["homeMargin"] == pytest.approx(10.5, abs=2e-3)
    dist = {int(k): v for k, v in lane["projection"]["marginDist"].items()}
    assert sum(dist.values()) == lane["simsRun"]
    assert sum(k * v for k, v in dist.items()) / sum(dist.values()) == pytest.approx(10.5, abs=1.0 / lane["simsRun"])


def test_with_852s_damping_on_E0_is_the_DAMPED_kickoff_and_a_cached_plain_E0_is_not_reused(monkeypatch):
    from syndicate.features.ncaaf import live_blowout_damping as lbd

    def oregon_e0():
        snap = _snapshot()
        lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
        return _by_home(snap, "Oregon")["projection"]["marginAnchor"]["kickoffHomeMargin"]

    plain = oregon_e0()
    monkeypatch.setenv(lbd.SWITCH_ENV, "on")
    damped = oregon_e0()  # same process, same cache: the key must tell the two engines apart
    kick = _kickoff("Oregon", "Boise State", 1.2, 0.6, 0.1, 0.1)
    assert "blowout_damping" in kick
    assert damped == pytest.approx(sum(int(k) * v for k, v in kick["margin_dist"].items()) / kick["sims_run"],
                                   abs=1e-3)
    assert damped != pytest.approx(plain, abs=1e-3)


def test_kickoff_sims_are_capped_per_tick_and_the_rest_are_served_raw_by_name():
    raw = _snapshot()
    snap = _snapshot()
    summary = lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON, max_kickoff_sims=1)
    assert summary == {"kickoff_sims": 1, "anchored": 1, "refused:kickoff_margin_pending": 1}
    (home,) = [g["home_name"] for g in snap["games"]
               if g["gameLens"][0]["projection"].get("marginAnchorRefusal") == "kickoff_margin_pending"]
    lane, before = _by_home(snap, home), _by_home(raw, home)
    assert lane["projection"].pop("marginAnchorRefusal") == "kickoff_margin_pending"
    assert _no_clock(lane) == _no_clock(before)


def test_a_game_with_no_closing_spread_is_served_raw_and_names_why(monkeypatch):
    monkeypatch.setattr(lma, "_spread_quotes", lambda date: {})
    raw = _snapshot()
    snap = _snapshot()
    summary = lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
    assert summary == {"kickoff_sims": 0, "refused:no_closing_spread": 2}
    for home in ("Oregon", "Penn State"):
        lane, before = _by_home(snap, home), _by_home(raw, home)
        assert lane["projection"].pop("marginAnchorRefusal") == "no_closing_spread"
        assert _no_clock(lane) == _no_clock(before)


def test_a_market_implied_lane_is_refused_by_name_and_left_alone():
    snap = _snapshot()
    _by_home(snap, "Oregon")["ratingSource"] = "fcs_market_implied"
    before = json.loads(json.dumps(_by_home(snap, "Oregon")))
    summary = lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
    assert summary["refused:market_implied_ratings"] == 1 and summary["anchored"] == 1
    lane = _by_home(snap, "Oregon")
    assert lane["projection"].pop("marginAnchorRefusal") == "market_implied_ratings"
    assert lane == before


def test_refused_lanes_are_left_alone():
    snap = lr.build_live_lens_snapshot("2026-11-14", games=_games(), live_index={}, ratings=RATINGS, sims=20)
    before = json.loads(json.dumps(snap))
    summary = lma.anchor_snapshot_margins(snap, ratings=RATINGS, date_str="2026-11-14", env=ON)
    assert summary == {"kickoff_sims": 0}
    snap.pop("marginAnchor")
    assert snap == before


def test_the_close_is_read_in_the_LANE_orientation_and_a_swapped_feed_is_negated(monkeypatch):
    # the odds feed lists Boise State as home at -3 (Boise State by 3): in the lane's orientation Oregon is -3
    monkeypatch.setattr(lma, "_spread_quotes", lambda date: _quotes({("boise state", "oregon"): [-3.0, -3.0]}))
    assert lma.closing_home_margin_for(["2026-11-14"], "Oregon", "Boise State") == (-3.0, 2)
    assert lma.closing_home_margin_for(["2026-11-14"], "Boise State", "Oregon") == (3.0, 2)


def test_the_close_is_each_books_last_line_before_the_commence_then_the_median(monkeypatch):
    later = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    after = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    rows = {("oregon", "boise state"): [(_SEEN, "a", -9.0, _KICK), (later, "a", -10.0, _KICK),
                                        (after, "a", -20.0, _KICK), (_SEEN, "b", -12.0, _KICK)]}
    monkeypatch.setattr(lma, "_spread_quotes", lambda date: rows)
    assert lma.closing_home_margin_for(["2026-11-14"], "Oregon", "Boise State") == (11.0, 2)


def test_the_close_falls_back_to_the_previous_shard_for_games_past_midnight_utc(monkeypatch):
    shards = {"2026-11-15": {}, "2026-11-14": _quotes({("oregon", "boise state"): [-10.5]})}
    monkeypatch.setattr(lma, "_spread_quotes", lambda date: shards[date])
    assert lma.anchor_dates("2026-11-15") == ["2026-11-15", "2026-11-14"]
    assert lma.closing_home_margin_for(lma.anchor_dates("2026-11-15"), "Oregon", "Boise State") == (10.5, 1)
    assert lma.closing_home_margin_for(["2026-11-15"], "Oregon", "Boise State") is None


# --------------------------------------------------------------------------
# CORRECTNESS of the transform
# --------------------------------------------------------------------------

@pytest.mark.parametrize("offset, expected", [(0.0, 0.375), (3.0, 0.75), (-3.0, 0.25), (-4.0, 0.125), (8.0, 1.0)])
def test_at_a_whole_point_offset_the_win_probability_is_the_exact_shift_ties_half(offset, expected):
    dist = {"-3": 2, "0": 1, "4": 1}
    assert lma.anchored_win_prob(dist, offset) == pytest.approx(expected)


def _smooth_win_prob(dist, offset):
    """The continuous version: each draw's weight split between its two integer neighbours by the offset's fraction."""
    import math

    base = math.floor(offset)
    frac = offset - base

    def w(x):
        return 1.0 if x > 0 else 0.5 if x == 0 else 0.0

    n = sum(dist.values())
    return sum(int(c) * ((1 - frac) * w(int(k) + base) + frac * w(int(k) + base + 1)) for k, c in dist.items()) / n


def test_the_win_probability_follows_the_offset_continuously():
    """No jump as the offset crosses a half or a whole point (it moves with the clock every tick): within one draw of
    the smooth split at every offset, the integer counts being the only difference."""
    dist = {"-14": 3, "-7": 6, "-3": 9, "0": 1, "3": 11, "7": 8, "10": 4, "14": 3, "21": 2}
    n = sum(dist.values())
    for o in [x / 20.0 for x in range(-160, 161)]:
        assert lma.anchored_win_prob(dist, o) == pytest.approx(_smooth_win_prob(dist, o), abs=1.0 / n + 1e-12), o


def test_a_shifted_pile_landing_on_zero_is_split_and_keeps_the_mean_and_the_moneyline():
    dist = {"-3": 2, "7": 9, "10": 1}
    for offset in (-7.0, -6.6, -7.4):
        plain = {}
        from syndicate.features.ncaab.live_resim import _shift_margin_hist

        for m, c in _shift_margin_hist(dist, offset).items():
            plain[m] = plain.get(m, 0) + c
        split = {int(k): v for k, v in lma.shifted_margin_dist(dist, offset).items()}
        assert split.get(0, 0) <= 1
        assert sum(split.values()) == sum(plain.values())
        assert sum(k * v for k, v in split.items()) == sum(k * v for k, v in plain.items())
        assert lma.win_prob_of(split) == pytest.approx(lma.win_prob_of({str(k): v for k, v in plain.items()}))


def test_the_moved_histogram_keeps_its_count_and_moves_its_mean_by_the_offset():
    dist = {"-14": 3, "-3": 5, "0": 1, "3": 7, "7": 9, "10": 4, "21": 2}
    n = sum(dist.values())
    mean = sum(int(k) * v for k, v in dist.items()) / n
    for offset in (-6.8, -0.3, 0.0, 2.5, 4.49, 11.0):
        moved = {int(k): v for k, v in lma.shifted_margin_dist(dist, offset).items()}
        assert sum(moved.values()) == n
        assert sum(k * v for k, v in moved.items()) / n == pytest.approx(mean + offset, abs=1.0 / n)


def test_the_shift_shrinks_with_the_game_and_is_zero_in_overtime():
    for period, clock, share in ((1, 900, 1.0), (2, 0, 0.5), (4, 450, 0.125), (5, 600, 0.0)):
        lane = {"modelHomeWinProb": 0.6, "projection": {"homeMargin": 2.0, "marginDist": {"-3": 4, "3": 6},
                                                         "period": period, "clockSeconds": clock}}
        block = lma.anchor_lane(lane, market_margin=7.0, kickoff=3.0, books=4)
        assert block["remainingShare"] == pytest.approx(share)
        assert block["appliedOffset"] == pytest.approx(4.0 * share)
        assert lane["projection"]["homeMargin"] == pytest.approx(2.0 + 4.0 * share)
    assert lane["modelHomeWinProb"] == 0.6 and lane["projection"]["marginDist"] == {"-3": 4, "3": 6}


def test_the_moneyline_and_the_spread_stay_COHERENT_after_the_anchor():
    """`test_ncaaf_live_resim`'s tripwire, on anchored lanes: the moneyline (the replay's rule on the draws) and the
    spread at the pivot (the moved histogram) must not drift apart toward the ~9 pp publish bar."""
    from syndicate.features.shared.prop_projections import _dist_prob_over

    for home_score, away_score, period in ((17, 14, 3), (7, 7, 2), (3, 10, 3), (0, 0, 1)):
        state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=period, clock_seconds=400,
                                      home_score=home_score, away_score=away_score, possession_owner="home")
        result = lr.resim_live_game(state, home_offense=0.8, home_defense=0.4, away_offense=0.2, away_defense=0.1,
                                    sims=400)
        for offset in (-7.3, -2.5, 0.6, 3.5, 9.9):
            lane = {"modelHomeWinProb": result["home_win_prob"],
                    "projection": {"homeMargin": result["home_margin_mean"], "marginDist": dict(result["margin_dist"]),
                                   "period": 1, "clockSeconds": 900}}
            lma.anchor_lane(lane, market_margin=offset, kickoff=0.0, books=1)
            pivot = _dist_prob_over(lane["projection"]["marginDist"], 0.5)
            gap_pp = abs(lane["modelHomeWinProb"] - pivot) * 100.0
            assert gap_pp < 5.0, f"{gap_pp:.2f}pp at {home_score}-{away_score} Q{period}, offset {offset}"


@pytest.mark.parametrize("raw, on", [("on", True), ("1", True), ("TRUE", True), ("yes", True), ("", False),
                                     ("off", False), ("0", False), ("enabled", False)])
def test_the_switch_reads_only_explicit_on_values(raw, on):
    assert lma.enabled({lma.SWITCH_ENV: raw}) is on
