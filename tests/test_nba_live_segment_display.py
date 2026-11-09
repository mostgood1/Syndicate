"""NBA quarter/half rows get a DISPLAY-ONLY live number and their live actual (`#762`, lane nba-live-proj-actuals).

On 2026-11-05 every live NBA quarter/half row on Layer 2 was blank in both live columns: 0 of 260 rows, about half
of each game's live game-line rows. The re-sim already held each segment's histograms; the only road to the Live
column ran through PRICING, which is off for segments. These pin what changes and, as much, what must NOT:

  - the producer: `h2` takes overtime the way the books settle it, blocks carry `sims` and `settled`;
  - the join: a display block appears, the refusal and the ledger record stay exactly as they were, nothing prices,
    and a college opt-in cannot price NBA segments;
  - the board: the live % is restated in the row's OWN side (an away spread row showed P(home covers)), and a
    quarter/half row reads its own segment's score.
"""
from __future__ import annotations

import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import board_enrichment, live_gameline_join as lgj
from syndicate.features.shared.layer2_board import _live_projection_columns
from syndicate.features.shared.live_gameline_join import (
    LIVE_DISPLAY_KEY,
    REASON_SEGMENT_PRICING_DISABLED,
    REASON_STALE_QUOTE,
    REFUSAL_KEY,
    attach_live_gamelines,
    build_live_gameline_index,
)
from syndicate.features.shared.segment_actuals import segment_actuals


class _State:
    def __init__(self, period):
        self.period = period


def _draws(rows):
    """`simulate` returning (home periods, away periods, home OT, away OT) per call, in turn."""
    it = iter(rows)

    def simulate(_rng, _gs):
        hq, aq, hot, aot = next(it)
        hb = {"players": [], "ot_pts": list(hot)} if hot else {"players": []}
        ab = {"players": [], "ot_pts": list(aot)} if aot else {"players": []}
        return hb, ab, list(hq), list(aq)
    return simulate


# ----------------------------------------------------------------------------------------------- the producer

def test_the_second_half_takes_overtime_and_the_fourth_quarter_does_not():
    rows = [((25, 25, 25, 25), (25, 25, 25, 25), (12,), (8,))] * lr.MIN_SIMS
    seg = lr.resim_live_game({}, None, sims=lr.MIN_SIMS, simulate=_draws(rows))["segments"]
    assert seg["h2"]["total_dist"] == {"120": lr.MIN_SIMS}     # 50 + 50 + the 20 OT points; it read 100
    assert seg["h2"]["margin_dist"] == {"4": lr.MIN_SIMS}      # the OT winner; it read a 0 tie
    assert seg["q4"]["total_dist"] == {"50": lr.MIN_SIMS}      # the fourth quarter alone
    assert seg["h1"]["total_dist"] == {"100": lr.MIN_SIMS}
    assert all(block["sims"] == lr.MIN_SIMS for block in seg.values())


@pytest.mark.parametrize("period,settled", [
    (None, set()), (1, set()), (2, {"q1"}), (3, {"q1", "q2", "h1"}), (4, {"q1", "q2", "q3", "h1"}),
    (5, {"q1", "q2", "q3", "q4", "h1"}),   # overtime: every quarter is over, the second half is not
])
def test_a_segment_settles_once_the_game_moves_past_it(period, settled):
    rows = [((25, 25, 25, 25), (20, 20, 20, 20), (), ())] * lr.MIN_SIMS
    gs = _State(period) if period is not None else None
    seg = lr.resim_live_game({}, gs, sims=lr.MIN_SIMS, simulate=_draws(rows))["segments"]
    assert {name for name, block in seg.items() if block["settled"]} == settled


# ----------------------------------------------------------------------------------------------- the join

HOME, AWAY = "Golden State Warriors", "Miami Heat"
Q1_TOTALS = {"50": 100, "60": 100}            # P(over 54.5) = 0.5
Q1_MARGIN = {"-4": 100, "6": 100}             # home -1.5 covers half the draws
FULL_TOTALS = {"220": 100, "240": 100}        # P(over 230.5) = 0.5; P(over 54.5) would be 1.0


def _snapshot(*, q1_settled=False):
    q1 = {"total_dist": Q1_TOTALS, "margin_dist": Q1_MARGIN, "total_mean": 55.0, "sims": 200, "settled": q1_settled}
    return {"games": [{
        "home": HOME, "away": AWAY,
        "gameLens": [{"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
                      "projection": {"total": 230.0, "homeMargin": 4.0, "totalRunsDist": FULL_TOTALS,
                                     "marginDist": {"-2": 60, "6": 140}, "segments": {"q1": q1}}}],
    }]}


def _row(segment="q1", market="totals", line=54.5, market_prob=0.40, age=20.0):
    sides = ["over", "under"] if market.startswith("totals") else ["home", "away"]
    return {"kind": "game", "sport": "nba", "market": market, "segment": segment, "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": age,
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(grid, snapshot, *, sport="nba", display=True, pricing=False):
    idx = build_live_gameline_index(snapshot, sources=("live_resim",), sport=sport)
    segs = {s: build_live_gameline_index(snapshot, sources=("live_resim",), sport=sport, segment=s)
            for s in ("q1", "q2", "q3", "q4", "h1", "h2")}
    return attach_live_gamelines(grid, idx, sport=sport, segment_indexes=segs,
                                 segment_pricing_enabled=pricing, segment_display_only=display)


def test_a_quarter_total_shows_its_own_live_number_and_is_still_refused():
    grid = [_row()]
    cov = _attach(grid, _snapshot())
    block = grid[0][LIVE_DISPLAY_KEY]
    assert block["prob_over"] == pytest.approx(0.5, abs=0.02)   # the q1 histogram; the full game's would be ~1.0
    assert block["total_mean"] == 55.0 and block["segment"] == "q1" and block["sims_run"] == 200
    # NOTHING PRICED: the refusal, its ledger record and the projection are exactly what they were.
    assert "live_gameline" not in grid[0]
    assert grid[0][REFUSAL_KEY]["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED
    assert grid[0]["projection"] == {"market_fair_prob_over": 0.40}
    assert cov["withheld_by_reason"] == {REASON_SEGMENT_PRICING_DISABLED: 1}
    assert cov["rows_live_gameline_projected"] == 0 and cov["rows_live_display"] == 1


def test_off_is_not_on():
    """Reachability: the flag changes the row, and off leaves it as it was."""
    on, off = [_row()], [_row()]
    _attach(on, _snapshot(), display=True)
    cov_off = _attach(off, _snapshot(), display=False)
    assert LIVE_DISPLAY_KEY in on[0] and LIVE_DISPLAY_KEY not in off[0]
    assert "rows_live_display" not in cov_off


def test_an_unanchored_nba_quarter_margin_is_shown_but_never_priced():
    grid = [_row(market="spreads", line=-1.5, market_prob=0.5)]
    _attach(grid, _snapshot())
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.5, abs=0.02)
    assert "live_gameline" not in grid[0]


def test_college_never_shows_a_raw_margin():
    """The raw margin is shown for NBA only; college's ran at half to two-thirds of the market's."""
    from datetime import datetime, timezone

    snapshot = _snapshot()
    # Outside NBA a display number needs a lane as fresh as a price would (lane live-display-other-sports,
    # 2026-11-09), so the college lane carries its time; this NBA fixture's lane has none.
    snapshot["games"][0]["gameLens"][0]["liveStateAsOf"] = datetime.now(timezone.utc).isoformat()
    grid = [_row(market="spreads", line=-1.5, market_prob=0.5), _row()]
    _attach(grid, snapshot, sport="ncaab")
    assert LIVE_DISPLAY_KEY not in grid[0]
    assert grid[1][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.5, abs=0.02)


def test_a_finished_quarter_shows_nothing():
    grid = [_row()]
    _attach(grid, _snapshot(q1_settled=True))
    assert LIVE_DISPLAY_KEY not in grid[0]


def test_a_quarter_with_no_block_of_its_own_shows_nothing():
    grid = [_row(segment="q3")]
    _attach(grid, _snapshot())
    assert LIVE_DISPLAY_KEY not in grid[0]


def test_a_stale_full_game_quote_shows_the_live_number_and_prices_nothing():
    grid = [_row(segment="full", line=230.5, age=900.0)]
    cov = _attach(grid, _snapshot())
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.5, abs=0.02)
    assert grid[0][LIVE_DISPLAY_KEY]["basis"] == REASON_STALE_QUOTE
    assert "live_gameline" not in grid[0]
    assert cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}


def test_another_sports_stale_quote_is_untouched():
    # A sport outside `LIVE_DISPLAY_SPORTS`. It read `ncaab` until college joined the table on 2026-11-09 (lane
    # live-display-other-sports; `tests/test_live_display_other_sports.py` pins college's own display rules).
    grid = [_row(segment="full", line=230.5, age=900.0)]
    _attach(grid, _snapshot(), sport="mlb")
    assert LIVE_DISPLAY_KEY not in grid[0]


def test_a_full_game_moneyline_carries_its_home_probability_for_display_only():
    grid = [_row(segment="full", market="h2h", line=None, market_prob=0.6)]
    _attach(grid, _snapshot())
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.01)
    # Still NOT published where the plausibility gate reads it.
    assert "live_model_prob_over" not in grid[0]["projection"]


def test_a_college_opt_in_cannot_price_nba_segments(monkeypatch):
    """`board_enrichment` passes the college switch for college only."""
    seen = {}

    def fake_attach(grid, index, **kwargs):
        seen.update(kwargs)
        return lgj.new_coverage()

    monkeypatch.setenv(lgj.COLLEGE_SEGMENT_PRICING_ENV, "1")
    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    monkeypatch.setattr(lgj, "attach_live_gamelines", fake_attach)
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: _snapshot())
    board_enrichment.attach_live_gamelines_for_sport([_row()], sport="nba", selected_date="2026-11-06")
    assert seen["segment_pricing_enabled"] is False and seen["segment_display_only"] is True
    assert set(seen["segment_indexes"]) == {"q1", "q2", "q3", "q4", "h1", "h2"}
    assert len(seen["segment_indexes"]["q1"]) == 1
    seen.clear()
    board_enrichment.attach_live_gamelines_for_sport([_row()], sport="ncaab", selected_date="2026-11-06")
    # College displays its segments too since 2026-11-09; with its pricing ON they are priced, never displayed.
    assert seen["segment_pricing_enabled"] is True and seen["segment_display_only"] is True


# ----------------------------------------------------------------------------------------------- the board

def _card(market, side, *, segment="full", prob=None, display=None, gameline=None, segment_score=None):
    projection = {"live_model_prob_over": prob} if prob is not None else {}
    row = {"kind": "game", "market": market, "side": side, "segment": segment, "projection": projection,
           "game": {"state": "live", "home_score": 60, "away_score": 50}}
    if display is not None:
        row["live_display"] = display
    if gameline is not None:
        row["live_gameline"] = gameline
    if segment_score is not None:
        row["game"]["segment_score"] = segment_score
    return row


def test_an_away_spread_row_shows_its_own_sides_live_percent():
    """It showed P(home covers): the two rows of one line read the same number."""
    gameline = {"total_mean": 230.0}
    home = _live_projection_columns(_card("spreads", "home", prob=0.7, gameline=gameline))
    away = _live_projection_columns(_card("spreads", "away", prob=0.7, gameline=gameline))
    assert home["live_model_probability"] == pytest.approx(0.7)
    assert away["live_model_probability"] == pytest.approx(0.3)


def test_an_under_row_is_restated_too_but_still_shows_the_total():
    out = _live_projection_columns(_card("totals", "under", prob=0.7, gameline={"total_mean": 230.0}))
    assert out["live_total"] == 230.0 and out["live_model_probability"] == pytest.approx(0.3)


def test_a_three_way_projection_answers_only_its_own_side():
    row = _card("h2h", "away", prob=0.5, gameline={})
    row["projection"]["draw_probability"] = 0.2
    assert "live_model_probability" not in _live_projection_columns(row)


def test_a_quarter_row_reads_its_display_number_and_its_own_score():
    display = {"prob_over": 0.6, "total_mean": 55.0, "segment": "q1"}
    score = {"segment": "q1", "home": 30, "away": 22}
    total = _live_projection_columns(_card("totals", "over", segment="q1", display=display, segment_score=score))
    assert total["live_total"] == 55.0 and total["live_model_probability"] == pytest.approx(0.6)
    assert total["actual"] == 52.0                      # the quarter's own score, never the game's 110
    assert "live_aware" not in total                    # display-only: the row is not live-joined
    spread = _live_projection_columns(_card("spreads", "away", segment="q1", display={"prob_over": 0.6},
                                            segment_score=score))
    assert spread["live_model_probability"] == pytest.approx(0.4) and "live_total" not in spread
    assert spread["actual"] == 8.0                      # home minus away over q1, the full game's convention


def test_a_quarter_row_without_its_own_score_shows_no_actual():
    row = _card("spreads", "home", segment="q2", display={"prob_over": 0.6},
                segment_score={"segment": "q1", "home": 30, "away": 22})
    assert "actual" not in _live_projection_columns(row)


def test_a_moneyline_shows_its_sides_win_percent_from_the_display_block():
    gameline = {"total_mean": 230.0}
    home = _live_projection_columns(_card("h2h", "home", gameline=gameline, display={"prob_over": 0.7}))
    away = _live_projection_columns(_card("h2h", "away", gameline=gameline, display={"prob_over": 0.7}))
    assert home["live_model_probability"] == pytest.approx(0.7) and away["live_model_probability"] == pytest.approx(0.3)
    assert "live_total" not in home


# ----------------------------------------------------------------------------------------------- live actuals

def test_nba_segment_actuals_follow_the_book_overtime_rule():
    record = {"home_linescores": [30, 25, 20, 25, 10], "away_linescores": [20, 25, 30, 25, 6], "in_progress": True,
              "final": False, "period": 5}
    assert segment_actuals("nba", "h2", record)["home_score"] == 55     # 20 + 25 + the 10 OT points
    assert segment_actuals("nba", "q4", record)["home_score"] == 25     # the fourth quarter alone
    assert segment_actuals("nba", "q4", record)["is_final"] is True
    assert segment_actuals("nba", "h2", record)["is_final"] is False


def test_an_nba_quarter_not_yet_started_has_no_score():
    record = {"home_linescores": [30, 12], "away_linescores": [20, 9], "in_progress": True, "final": False, "period": 2}
    assert segment_actuals("nba", "q3", record)["started"] is False
    assert segment_actuals("nba", "q2", record)["home_score"] == 12


def test_the_board_stamps_an_nba_rows_own_quarter_score_from_the_chip():
    chip = {"state": "live", "linescore": {"kind": "periods", "home": [30, 12], "away": [20, 9]}}
    got = board_enrichment._segment_score_for_row("nba", {"segment": "q2"}, chip)
    assert got == {"segment": "q2", "home": 12, "away": 9, "is_final": False}
    assert board_enrichment._segment_score_for_row("nba", {"segment": "q3"}, chip) is None
