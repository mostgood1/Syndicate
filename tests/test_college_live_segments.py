"""Live college halves and quarters priced off the re-sim's own segment results (lane wncaab-module, 2026-11-04).

Before this, every live NCAAB h1/h2 row was refused `segment_is_not_full_game` (83 of 161 live rows on the
11-04 board) while the re-sim already held each segment's histograms. These pin the three things that make a
segment price honest: it comes from that segment alone, the second half carries overtime the way it settles,
and the margin takes the same market anchor as the full game, scaled to the segment.
"""

from __future__ import annotations

import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.shared.live_gameline_join import (
    REASON_SEGMENT_MARGIN_UNANCHORED,
    REASON_SEGMENT_OVER,
    attach_live_gamelines,
    build_live_gameline_index,
    college_segment_pricing_enabled,
)


def _facts(period: int, clock: float) -> lr.ResumeFacts:
    return lr.ResumeFacts(event_id="1", home_id="10", away_id="20", home_score=0, away_score=0, period=period,
                          clock_seconds=clock, possession=None, last_seq=0, as_of="", score_source="official",
                          tip_wallclock="")


# ------------------------------------------------------------------------------------- the producer

def _fake_sims(per_sim):
    """`simulate` returning the given (home periods, away periods, home OT, away OT) per call, in turn."""
    it = iter(per_sim)

    def simulate(_rng, _gs):
        hq, aq, hot, aot = next(it)
        return ({"ot_pts": list(hot)} if hot else {}), ({"ot_pts": list(aot)} if aot else {}), list(hq), list(aq)
    return simulate


@pytest.mark.parametrize("league,hq,aq", [("ncaab", (40, 30), (38, 32)), ("wncaab", (20, 20, 15, 15), (18, 22, 15, 15))])
def test_the_second_half_settles_with_overtime_and_the_first_without(league, hq, aq):
    sims = [(hq, aq, (9,), (5,))] * lr.MIN_SIMS
    out = lr.resim_live_game({}, None, sims=lr.MIN_SIMS, simulate=_fake_sims(sims), league=league)
    seg = out["segments"]
    reg = len(hq)
    second = range(reg // 2, reg)
    h2_total = sum(hq[i] + aq[i] for i in second) + 14
    h2_margin = sum(hq[i] - aq[i] for i in second) + 4
    assert seg["h2"]["total_dist"] == {str(h2_total): lr.MIN_SIMS}
    assert seg["h2"]["margin_dist"] == {str(h2_margin): lr.MIN_SIMS}
    assert seg["h2"]["includesOvertime"] is True
    first = range(0, reg // 2)
    assert seg["h1"]["total_dist"] == {str(sum(hq[i] + aq[i] for i in first)): lr.MIN_SIMS}
    assert seg["h1"]["sims"] == lr.MIN_SIMS
    if league == "wncaab":
        # A fourth quarter settles on the fourth quarter alone.
        assert seg["q4"]["total_dist"] == {str(hq[3] + aq[3]): lr.MIN_SIMS}
        assert seg["q4"]["includesOvertime"] is False


def test_the_full_game_counts_overtime_so_an_overtime_game_is_not_a_tie():
    """A game resumed in overtime used to be ALL ties: total at the regulation score, win probability a coin flip."""
    regulation = ((40, 30), (38, 32))   # 70-70 after regulation
    n_home = lr.MIN_SIMS * 3 // 4
    sims = [(regulation[0], regulation[1], (9,), (5,))] * n_home + \
           [(regulation[0], regulation[1], (6,), (8,))] * (lr.MIN_SIMS - n_home)
    out = lr.resim_live_game({}, None, sims=lr.MIN_SIMS, simulate=_fake_sims(sims), league="ncaab")
    assert out["total_dist"] == {"154": lr.MIN_SIMS}        # 140 + the overtime points, never 140
    assert out["margin_dist"] == {"-2": lr.MIN_SIMS - n_home, "4": n_home}
    assert out["home_win_prob"] == pytest.approx(0.75)        # was 0.0: every draw a tie, none a home win
    no_ot = lr.resim_live_game({}, None, sims=lr.MIN_SIMS, simulate=_fake_sims([(regulation[0], regulation[1], (), ())] * lr.MIN_SIMS),
                               league="ncaab")
    assert no_ot["total_dist"] == {"140": lr.MIN_SIMS}   # a regulation-only sim is unchanged


@pytest.mark.parametrize("league,period,clock", [
    ("ncaab", 1, 1200), ("ncaab", 1, 600), ("ncaab", 2, 300), ("ncaab", 3, 120),
    ("wncaab", 1, 600), ("wncaab", 2, 131), ("wncaab", 3, 0), ("wncaab", 4, 45), ("wncaab", 5, 200),
])
def test_the_segment_shares_add_up_to_the_full_games(league, period, clock):
    """The anchor's per-segment shifts must sum to the full game's, or a half and the game disagree."""
    parts = ("h1", "h2") if league == "ncaab" else ("q1", "q2", "q3", "q4")
    shares = sum(lr.segment_progress(league, s, period, clock)[0] for s in parts)
    assert shares == pytest.approx(lr.remaining_regulation_fraction(_facts(period, clock), league))


def test_a_segment_is_over_when_its_last_period_ends_and_the_second_half_only_with_the_game():
    assert lr.segment_progress("ncaab", "h1", 1, 1.0) == (pytest.approx(1 / 2400), False)
    assert lr.segment_progress("ncaab", "h1", 1, 0.0)[1] is True     # halftime
    assert lr.segment_progress("ncaab", "h1", 2, 900)[1] is True
    assert lr.segment_progress("ncaab", "h2", 2, 0.0) == (0.0, False)  # tied at the buzzer: overtime is still h2
    assert lr.segment_progress("ncaab", "h2", 3, 120)[1] is False
    assert lr.segment_progress("wncaab", "q4", 5, 200)[1] is True    # overtime is not the fourth quarter
    assert lr.segment_progress("wncaab", "h1", 3, 600)[1] is True


def test_each_segment_takes_the_anchor_scaled_by_its_own_share():
    result = {"margin_dist": {"0": 50, "4": 50}, "home_win_prob": 0.5, "home_margin_mean": 2.0,
              "segments": {"h1": {"margin_dist": {"0": 100}}, "h2": {"margin_dist": {"2": 100}}}}
    stamped = lr.stamp_segment_progress(result, _facts(1, 600), "ncaab")    # 10:00 left in the first half
    anchored = lr.anchor_result(stamped, lr.MarginAnchor(market_home_margin=10.0, sim_home_margin=2.0, books=3),
                                remaining_fraction=0.75)
    seg = anchored["segments"]
    assert seg["h1"]["marginAnchorOffset"] == pytest.approx(2.0)   # 8 x 0.25
    assert seg["h2"]["marginAnchorOffset"] == pytest.approx(4.0)   # 8 x 0.50
    assert seg["h1"]["margin_dist"] == {"2": 100}
    assert seg["h2"]["margin_dist"] == {"6": 100}
    assert seg["h1"]["marginAnchored"] is True
    assert anchored["margin_anchor"]["appliedOffset"] == pytest.approx(6.0)   # 2 + 4: the halves add up


def test_an_unstamped_segment_is_left_raw_and_marked_unanchored():
    result = {"margin_dist": {"0": 100}, "segments": {"h1": {"margin_dist": {"0": 100}}}}
    anchored = lr.anchor_result(result, lr.MarginAnchor(10.0, 2.0, 3), remaining_fraction=1.0)
    assert anchored["segments"]["h1"]["marginAnchored"] is False
    assert anchored["segments"]["h1"]["margin_dist"] == {"0": 100}


# ------------------------------------------------------------------------------------- the join

H1_TOTALS = {str(t): c for t, c in ((60, 100), (70, 100))}          # P(over 64.5) = 0.5
FULL_TOTALS = {str(t): c for t, c in ((120, 20), (150, 180))}        # P(over 64.5) = 1.0 -- the wrong answer


def _snapshot(*, settled=False, anchored=True):
    h1 = {"total_dist": H1_TOTALS, "margin_dist": {"-3": 100, "5": 100}, "total_mean": 65.0, "sims": 200,
          "remainingFraction": 0.0 if settled else 0.25, "settled": settled}
    if anchored:
        h1["marginAnchored"] = True
    return {"games": [{
        "home": "Duke Blue Devils", "away": "Army Black Knights",
        "gameLens": [{"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200,
                      "projection": {"total": 140.0, "homeMargin": 20.0, "totalRunsDist": FULL_TOTALS,
                                     "marginDist": {"20": 200}, "segments": {"h1": h1}}}],
    }]}


def _row(segment="h1", market="totals", line=64.5, market_prob=0.40):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    return {"kind": "game", "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": "Army Black Knights", "home_team": "Duke Blue Devils", "age_seconds": 20.0,
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(grid, snapshot, *, enabled=True, with_segments=True):
    idx = build_live_gameline_index(snapshot, sources=("live_resim",), sport="ncaab")
    segs = {"h1": build_live_gameline_index(snapshot, sources=("live_resim",), sport="ncaab", segment="h1"),
            "h2": build_live_gameline_index(snapshot, sources=("live_resim",), sport="ncaab", segment="h2")}
    return attach_live_gamelines(grid, idx, sport="ncaab", segment_indexes=segs if with_segments else None,
                                 segment_pricing_enabled=enabled)


def test_an_h1_total_is_priced_from_the_h1_histogram_and_never_the_full_games():
    grid = [_row()]
    cov = _attach(grid, _snapshot())
    block = grid[0]["live_gameline"]
    assert block["model_prob"] == pytest.approx(0.5, abs=0.02)   # the h1 histogram; the full game's would be 1.0
    assert block["sims_run"] == 200
    assert cov["rows_live_gameline_projected"] == 1


def test_off_is_not_on():
    """Reachability: the switch must change the answer, and off says so by name."""
    on, off, absent = [_row()], [_row()], [_row()]
    _attach(on, _snapshot(), enabled=True)
    cov_off = _attach(off, _snapshot(), enabled=False)
    cov_absent = _attach(absent, _snapshot(), with_segments=False)
    assert "live_gameline" in on[0]
    assert "live_gameline" not in off[0] and "live_gameline" not in absent[0]
    assert cov_off["withheld_by_reason"] == {"segment_pricing_disabled": 1}
    assert cov_absent["withheld_by_reason"] == {"segment_is_not_full_game": 1}


def test_a_segment_with_no_block_of_its_own_is_not_priced():
    grid = [_row(segment="h2")]
    cov = _attach(grid, _snapshot())
    assert "live_gameline" not in grid[0]
    assert cov["withheld_by_reason"] == {"no_live_gameline_projection": 1}


def test_a_finished_segment_is_refused_by_name():
    grid = [_row()]
    cov = _attach(grid, _snapshot(settled=True))
    assert "live_gameline" not in grid[0]
    assert cov["withheld_by_reason"] == {REASON_SEGMENT_OVER: 1}


def test_an_unanchored_segment_prices_its_total_but_never_its_margin():
    grid = [_row(), _row(market="spreads", line=-1.5, market_prob=0.5)]
    cov = _attach(grid, _snapshot(anchored=False))
    assert grid[0]["live_gameline"]["model_prob"] == pytest.approx(0.5, abs=0.02)
    assert grid[1]["live_gameline"]["withheld_reason"] == REASON_SEGMENT_MARGIN_UNANCHORED
    assert cov["withheld_by_reason"].get(REASON_SEGMENT_MARGIN_UNANCHORED) == 1


def test_an_anchored_segment_spread_reads_the_segment_margin():
    grid = [_row(market="spreads", line=-1.5, market_prob=0.40)]
    _attach(grid, _snapshot())
    # home -1.5 covers when the h1 margin is 5 (half the sims), never at -3; the full game's +20 would say 1.0
    assert grid[0]["live_gameline"]["model_prob"] == pytest.approx(0.5, abs=0.02)


@pytest.mark.parametrize("raw,expected", [("", False), ("0", False), ("off", False), ("junk", False),
                                          ("1", True), ("on", True), ("true", True), ("yes", True)])
def test_the_switch_is_off_unless_turned_on(raw, expected):
    """Absent is OFF: the 11-05 replay measured quote lag, not edge (`COLLEGE_SEGMENT_PRICING_ENV`'s note)."""
    assert college_segment_pricing_enabled({"SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING": raw}) is expected
    assert college_segment_pricing_enabled({}) is False
