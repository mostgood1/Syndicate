"""NHL live puck-line rows get a DISPLAY-ONLY live number from the re-sim's own margin histogram (`#773`).

`[2026-11-10, lane nhl-live-puckline-display]`. Served 2026-11-09 NYR@EDM: the NHL live moneyline (1 of 1) and
totals (2 of 2) showed a live number and the puck line (0 of 1) did not, refused
`live_resim_published_no_distribution_for_this_market`. `nhl/live_resim` had the 200 per-sim margins in hand
and threw them away at the return.

The producer now publishes them as `projection.displayMarginDist` -- NOT `marginDist`, which opens spread
pricing on an estimator nobody has graded. These pin:
  - REACHABILITY FIRST (`model_engine_standard.md`): the REAL producer's snapshot, indexed by the join's own
    call, puts a number on a puck-line row; the same snapshot without the key (the old producer) does not;
  - NOTHING PRICES: with a market price the same histogram WOULD price as `marginDist` (the control proves it),
    the display-only row carries no edge, no `live_model_prob_over`, and is refused by its own name;
  - the number is P(home covers) in the away-frame line, and the board restates it per side.
"""
from __future__ import annotations

import copy

import pytest

from syndicate.features.nhl import live_resim as LR
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared.layer2_board import _live_projection_columns
from syndicate.features.shared.live_gameline_join import (
    LIVE_DISPLAY_KEY,
    REASON_MARGIN_DISPLAY_ONLY,
    REASON_NO_LIVE_DISTRIBUTION,
    REASON_STALE_QUOTE,
    agresti_coull_point,
    attach_live_gamelines,
    build_live_gameline_index,
    lens_sources_for_sport,
)
from tests.test_nhl_live_resim import _StubFeatures

DATE = "2026-10-08"
GAME_PK = "2026020123"
HOME, AWAY = "Toronto Maple Leafs", "Ottawa Senators"
SIMS = 60


def _score_row(*, period=2, seconds=600, home=1, away=1):
    return {
        "id": int(GAME_PK),
        "gameState": "LIVE",
        "periodDescriptor": {"number": period, "periodType": "REG"},
        "clock": {"timeRemaining": f"{seconds // 60:02d}:{seconds % 60:02d}", "secondsRemaining": seconds,
                  "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": home},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": away},
    }


@pytest.fixture(scope="module")
def snapshot():
    """ONE real producer run (stub features carry rosters, as `build_slate_features` does)."""
    feats = _StubFeatures(GAME_PK, HOME, AWAY)
    snap = LR.build_live_lens_snapshot(DATE, sims=SIMS, score_rows=[_score_row()], slate_features=[feats])
    lane = snap["games"][0]["gameLens"][0]
    assert lane.get("source") == LR.LIVE_RESIM_LENS_SOURCE, lane   # the branch that publishes a probability
    return snap


@pytest.fixture
def gate_on(monkeypatch):
    for key in (lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV, "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS"):
        monkeypatch.delenv(key, raising=False)


def _lane(snap):
    return snap["games"][0]["gameLens"][0]


def _hist(snap):
    return _lane(snap)["projection"]["displayMarginDist"]


def _p_over(hist, line):
    n = sum(hist.values())
    return sum(c for m, c in hist.items() if float(m) > line) / n


def _without_display(snap):
    """The OLD producer: the same lane with no display histogram."""
    old = copy.deepcopy(snap)
    _lane(old)["projection"].pop("displayMarginDist")
    return old


def _as_priced(snap):
    """The CONTROL: the same histogram published under the key that opens pricing."""
    priced = copy.deepcopy(snap)
    proj = _lane(priced)["projection"]
    proj["marginDist"] = proj.pop("displayMarginDist")
    return priced


def _row(market="spreads", line=1.5, market_prob=0.5, age=20.0):
    sides = ["over", "under"] if market.startswith("totals") else ["home", "away"]
    return {"kind": "game", "sport": "nhl", "market": market, "segment": "full", "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": age,
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(grid, snap):
    index = build_live_gameline_index(snap, sources=lens_sources_for_sport("nhl"), sport="nhl", slate_date=DATE)
    return attach_live_gamelines(grid, index, sport="nhl")


# ------------------------------------------------------------------------------------------------ the producer

def test_the_lane_publishes_the_sims_margins_for_display_and_no_priced_distribution(snapshot):
    lane = _lane(snapshot)
    proj = lane["projection"]
    hist = proj["displayMarginDist"]
    # Every sim, once; the same draws the moneyline and the mean were counted from.
    assert sum(hist.values()) == lane["simsRun"] == SIMS
    assert sum(c for m, c in hist.items() if int(m) > 0) / SIMS == pytest.approx(lane["modelHomeWinProb"])
    assert sum(int(m) * c for m, c in hist.items()) / SIMS == pytest.approx(proj["homeMargin"])
    # The shootout credits a goal: no final margin is level, as books settle a puck line.
    assert "0" not in hist
    # NOT the keys a pricer reads -- on the lane or on its projection.
    for key in ("marginDist", "totalRunsDist"):
        assert key not in lane and key not in proj


def test_a_result_without_draws_publishes_an_empty_display_histogram():
    st = LR.live_state_from_score_row(_score_row())
    (lane,) = LR.build_game_lens(st, {"home_win_prob": 0.4, "sims_run": 200, "home_margin_mean": -0.2,
                                      "total_mean": 5.6})
    assert lane["projection"]["displayMarginDist"] == {}


# ------------------------------------------------------------------------------------------------ reachability

def test_reachability_the_real_snapshot_puts_a_number_on_a_puck_line_row_and_the_old_one_does_not(gate_on,
                                                                                                    snapshot):
    """off != on, through the join's own index and attach calls, on a row the board actually carries."""
    on, off = [_row(line=1.5), _row(market="spreads_alt", line=-1.5)], \
              [_row(line=1.5), _row(market="spreads_alt", line=-1.5)]
    cov_on = _attach(on, snapshot)
    cov_off = _attach(off, _without_display(snapshot))
    assert cov_on["index_size"] == cov_off["index_size"] == 1                  # the game WAS joined both times
    assert all(LIVE_DISPLAY_KEY in row for row in on)
    assert all(LIVE_DISPLAY_KEY not in row for row in off)
    # The refusal the board log prints, by name: the old one is gone from puck-line rows.
    assert cov_on["withheld_by_reason"] == {REASON_MARGIN_DISPLAY_ONLY: 2}
    assert cov_off["withheld_by_reason"] == {REASON_NO_LIVE_DISTRIBUTION: 2}
    assert cov_on["rows_live_display"] == 2 and "rows_live_display" not in cov_off


def test_the_number_is_p_home_covers_in_the_away_frame_line(gate_on, snapshot):
    """`#262`: a spreads row's `line` is the AWAY point, and home covers when margin > line (no negation)."""
    hist = _hist(snapshot)
    grid = [_row(line=1.5), _row(market="spreads_alt", line=-1.5), _row(market="spreads_alt", line=2.5)]
    _attach(grid, snapshot)
    for row in grid:
        expected = agresti_coull_point(_p_over(hist, row["line"]), SIMS)
        block = row[LIVE_DISPLAY_KEY]
        assert block["prob_over"] == pytest.approx(expected, abs=1e-4)   # the pricer rounds P to 4 dp
        assert block["basis"] == REASON_MARGIN_DISPLAY_ONLY
        assert block["sims_run"] == SIMS and block["home_margin"] == _lane(snapshot)["projection"]["homeMargin"]
    # Home -1.5 (line +1.5) can never be likelier than home +1.5 (line -1.5).
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] < grid[1][LIVE_DISPLAY_KEY]["prob_over"]


# ------------------------------------------------------------------------------------------------ nothing prices

def _a_market_price_that_would_price(snapshot, line=1.5):
    p = _p_over(_hist(snapshot), line)
    return 0.95 if p < 0.5 else 0.05


def test_the_control_the_same_histogram_as_marginDist_would_price(gate_on, snapshot):
    """Makes the next test's null non-vacuous: this market price DOES clear the precision bar off this histogram."""
    grid = [_row(market_prob=_a_market_price_that_would_price(snapshot))]
    cov = _attach(grid, _as_priced(snapshot))
    assert cov["rows_live_gameline_priceable"] == 1
    assert grid[0]["projection"]["edge_vs_market_pct"] is not None


def test_a_display_only_puck_line_carries_no_edge_and_no_live_probability(gate_on, snapshot):
    grid = [_row(market_prob=_a_market_price_that_would_price(snapshot))]
    cov = _attach(grid, snapshot)
    row = grid[0]
    projection = row["projection"]
    assert cov["rows_live_gameline_priceable"] == 0 and cov["rows_live_gameline_edged"] == 0
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == REASON_MARGIN_DISPLAY_ONLY
    assert "edge_basis" not in projection
    # Not where the plausibility gate reads a live probability: the number is on the display block only.
    assert "live_model_prob_over" not in projection and "live_projected" not in projection
    verdict = row["live_gameline"]
    assert verdict["priceable"] is False and verdict["edge_pp"] is None and verdict["model_prob"] is None
    assert verdict["withheld_reason"] == REASON_MARGIN_DISPLAY_ONLY


def test_on_vs_off_changes_only_the_refusal_name_and_the_display_key(gate_on, snapshot):
    """Everything a pricer, the ledger or the board's `live_aware` reads is what the old producer gave the row."""
    price = _a_market_price_that_would_price(snapshot)
    on, off = [_row(market_prob=price), _row(market="totals", line=5.5)], \
              [_row(market_prob=price), _row(market="totals", line=5.5)]
    _attach(on, snapshot)
    _attach(off, _without_display(snapshot))

    def _strip(row):
        out = copy.deepcopy({k: v for k, v in row.items() if k != LIVE_DISPLAY_KEY})
        out["projection"].pop("edge_unavailable_reason", None)
        out["live_gameline"].pop("withheld_reason", None)
        return out

    assert [_strip(r) for r in on] == [_strip(r) for r in off]
    # The totals row is untouched outright: its live number is the mean, and no total histogram is published.
    assert on[1] == off[1]
    assert on[1]["projection"]["edge_unavailable_reason"] == REASON_NO_LIVE_DISTRIBUTION


def test_a_priced_histogram_wins_over_the_display_one(gate_on, snapshot):
    """A producer that publishes BOTH is priced off `marginDist`; the display key never shadows a price."""
    both = _as_priced(snapshot)
    _lane(both)["projection"]["displayMarginDist"] = {"5": SIMS}   # a different shape, to tell them apart
    grid = [_row(market_prob=_a_market_price_that_would_price(snapshot))]
    _attach(grid, both)
    assert grid[0]["live_gameline"]["withheld_reason"] != REASON_MARGIN_DISPLAY_ONLY
    assert grid[0]["live_gameline"]["priceable"] is True
    assert LIVE_DISPLAY_KEY not in grid[0]


def test_a_stale_quote_puck_line_shows_the_number_too(gate_on, snapshot):
    """The stale-quote branch reads the same display histogram (`#762`): the quote is dead, not the game."""
    on, off = [_row(age=900.0)], [_row(age=900.0)]
    cov_on = _attach(on, snapshot)
    _attach(off, _without_display(snapshot))
    assert cov_on["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
    assert on[0][LIVE_DISPLAY_KEY]["basis"] == REASON_STALE_QUOTE
    assert on[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(
        agresti_coull_point(_p_over(_hist(snapshot), 1.5), SIMS), abs=1e-4)
    assert LIVE_DISPLAY_KEY not in off[0]
    assert "live_gameline" not in on[0] and on[0]["projection"] == {"market_fair_prob_over": 0.5}


def test_the_display_table_off_shows_nothing_and_still_names_the_refusal(gate_on, snapshot, monkeypatch):
    monkeypatch.setattr(lgj, "LIVE_DISPLAY_SPORTS", frozenset({"nba"}))
    grid = [_row()]
    cov = _attach(grid, snapshot)
    assert LIVE_DISPLAY_KEY not in grid[0]
    assert cov["withheld_by_reason"] == {REASON_MARGIN_DISPLAY_ONLY: 1}


# ------------------------------------------------------------------------------------------------ the board

def test_the_board_shows_each_side_its_own_live_cover_probability(gate_on, snapshot):
    grid = [_row()]
    _attach(grid, snapshot)
    home = _live_projection_columns({**grid[0], "side": "home"})
    away = _live_projection_columns({**grid[0], "side": "away"})
    shown = grid[0][LIVE_DISPLAY_KEY]["prob_over"]
    assert home["live_model_probability"] == pytest.approx(shown)
    assert away["live_model_probability"] == pytest.approx(1.0 - shown)
    # The game total is not this row's number: a spread row shows no live total.
    assert "live_total" not in home and "live_projection" not in home

    old = [_row()]
    _attach(old, _without_display(snapshot))
    before = _live_projection_columns({**old[0], "side": "home"})
    assert "live_model_probability" not in before
    # `live_aware` on the board is exactly what it was: the verdict block was already there.
    assert home.get("live_aware") == before.get("live_aware")
