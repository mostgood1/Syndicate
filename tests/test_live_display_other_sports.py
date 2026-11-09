"""The DISPLAY-ONLY Live proj. (`#762`'s NBA pattern) for ncaab, wncaab, ncaaf, nfl and nhl (lane
live-display-other-sports, user "Yes, lend them" 2026-11-09).

Served board 2026-11-08 23:35Z: ncaab 15 of 43 live game rows showed a Live proj. (h1/h2 totals 0 of 14, h2h 0 of 2),
wncaab 2 of 29, nfl h2h 0 of 4. The join refused those rows (`quote_older_than_the_score_the_model_saw`,
`segment_pricing_disabled`) or, on a moneyline, never published its number; `LIVE_DISPLAY_SPORTS` was `{"nba"}`.

These pin, per sport, what is shown and, as much, what must NOT be:
  - nothing prices: a display row carries no edge, no `live_aware`, no `model_ev_pct`, and the table on vs off
    changes nothing on any row but the display key itself;
  - college shows a segment total and an ANCHORED segment margin, never a raw one;
  - outside NBA a lane past its pricing ceiling, or with no time, shows nothing (college's carry is unbounded);
  - NFL spreads stay blank: the lane's own `margin_dist` was graded a measured FAIL and is never read here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.nfl import live_resim as nfl_live_resim
from syndicate.features.shared import board_enrichment, live_gameline_join as lgj
from syndicate.features.shared.layer2_board import _live_projection_columns
from syndicate.features.shared.live_gameline_join import (
    LIVE_DISPLAY_KEY,
    REASON_QUOTE_BEHIND_SCORE,
    REASON_SEGMENT_PRICING_DISABLED,
    REASON_STALE_LANE,
    REASON_STALE_QUOTE,
    REFUSAL_KEY,
    attach_live_gamelines,
    build_live_gameline_index,
)

HOME, AWAY = "Home State", "Away Tech"
LANE_AT = datetime(2026, 11, 9, 1, 0, 0, tzinfo=timezone.utc)
FRESH_NOW = LANE_AT + timedelta(seconds=60)
H1_TOTALS = {"60": 100, "70": 100}           # P(over 64.5) = 0.5
H1_MARGIN = {"-4": 100, "6": 100}            # home -1.5 covers half the draws
FULL_TOTALS = {"130": 100, "150": 100}       # P(over 140.5) = 0.5
FULL_MARGIN = {"-2": 60, "8": 140}           # home covers the away-frame line 3.5 in 0.7 of draws
PRICING_FIELDS = ("edge_vs_market_pct", "edge_vs_line", "live_aware", "model_ev_pct")


def _at(seconds: float) -> datetime:
    return LANE_AT + timedelta(seconds=seconds)


def _college_lane(*, anchored=True, settled=False, as_of=LANE_AT.isoformat(), score_changed_at=None):
    h1 = {"total_dist": H1_TOTALS, "margin_dist": H1_MARGIN, "total_mean": 65.0, "sims": 200,
          "settled": settled, "remainingFraction": 0.4, "marginAnchored": anchored}
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "projection": {"total": 140.0, "homeMargin": 4.0, "totalRunsDist": FULL_TOTALS,
                           "marginDist": FULL_MARGIN, "segments": {"h1": h1}}}
    if as_of is not None:
        lane["liveStateAsOf"] = as_of
    if score_changed_at is not None:
        lane["liveScoreChangedAt"] = score_changed_at
    return lane


def _football_lane(*, margin=True, totals=True):
    """NCAAF's shape (`ncaaf/live_resim.build_game_lens`): both distributions on `projection`."""
    projection = {"total": 48.0, "homeMargin": 6.0}
    if totals:
        projection["totalRunsDist"] = {"40": 100, "56": 100}
    if margin:
        projection["marginDist"] = FULL_MARGIN
    return {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(), "projection": projection}


def _nfl_lane():
    """The REAL NFL lane: `build_game_lens` puts the re-sim's `margin_dist` / `total_dist` at the TOP level (the
    `**result` spread) and withholds `marginDist` / `totalRunsDist` from `projection` on purpose."""
    result = {"model_home_win_prob": 0.7, "sims_run": 200, "total_mean": 44.0, "margin_mean": 6.0,
              "margin_dist": FULL_MARGIN, "total_dist": {"40": 100, "48": 100}}
    (lane,) = nfl_live_resim.build_game_lens(None, result, live_state_as_of=LANE_AT.isoformat())
    assert "margin_dist" in lane and "marginDist" not in lane["projection"]   # the premise, read off the producer
    return lane


def _nhl_lane():
    """NHL's shape (`nhl/live_resim.build_game_lens`): a probability and the means, no distribution."""
    return {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.7, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(), "projection": {"total": 5.8, "homeMargin": 0.6}}


def _snapshot(lane):
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(sport, *, segment="full", market="totals", line=140.5, market_prob=0.40, age=20.0,
         updated_at=None, side=None):
    sides = ["over", "under"] if market.startswith("totals") else ["home", "away"]
    row = {"kind": "game", "sport": sport, "market": market, "segment": segment, "line": line, "sides": sides,
           "away_team": AWAY, "home_team": HOME, "age_seconds": age,
           "updated_at": updated_at if updated_at is not None else _at(30).isoformat(),
           "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}
    if side is not None:
        row["side"] = side
    return row


def _attach(grid, snapshot, sport, *, now=FRESH_NOW, segments=("h1",)):
    idx = build_live_gameline_index(snapshot, sources=("live_resim",), sport=sport)
    segment_indexes = None
    if sport in ("ncaab", "wncaab"):
        segment_indexes = {s: build_live_gameline_index(snapshot, sources=("live_resim",), sport=sport, segment=s)
                           for s in segments}
    return attach_live_gamelines(grid, idx, sport=sport, segment_indexes=segment_indexes,
                                 segment_pricing_enabled=False,
                                 segment_display_only=sport in lgj.LIVE_DISPLAY_SPORTS, now=now)


def _assert_nothing_priced(row):
    projection = row.get("projection") or {}
    for field in PRICING_FIELDS:
        assert projection.get(field) is None, field
        assert row.get(field) is None, field
    assert "live_gameline" not in row


@pytest.fixture
def gate_on(monkeypatch):
    for key in (lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV, "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS",
                lgj.COLLEGE_SEGMENT_PRICING_ENV, lgj.QUOTE_ORDER_BASIS_ENV):
        monkeypatch.delenv(key, raising=False)


# ------------------------------------------------------------------------------------------------- the table

def test_the_table_names_the_five_sports_and_keeps_nba():
    assert lgj.LIVE_DISPLAY_SPORTS == frozenset({"nba", "ncaab", "wncaab", "ncaaf", "nfl", "nhl"})
    # College's raw segment margin and every non-NBA stale lane stay off the Live column.
    assert lgj._RAW_MARGIN_DISPLAY_SPORTS == frozenset({"nba"})
    assert lgj._DISPLAY_PAST_LANE_CEILING_SPORTS == frozenset({"nba"})


# ------------------------------------------------------------------------------------------------- college

@pytest.mark.parametrize("sport", ["ncaab", "wncaab"])
def test_a_college_half_total_shows_its_own_live_number_and_is_still_refused(gate_on, sport):
    grid = [_row(sport, segment="h1", line=64.5)]
    cov = _attach(grid, _snapshot(_college_lane()), sport)
    block = grid[0][LIVE_DISPLAY_KEY]
    assert block["prob_over"] == pytest.approx(0.5, abs=0.02)      # the h1 histogram; the full game's would be ~0
    assert block["total_mean"] == 65.0 and block["segment"] == "h1"
    assert block["basis"] == REASON_SEGMENT_PRICING_DISABLED
    # NOTHING PRICED: the refusal, its ledger record and the projection are exactly what they were.
    _assert_nothing_priced(grid[0])
    assert grid[0][REFUSAL_KEY]["withheld_reason"] == REASON_SEGMENT_PRICING_DISABLED
    assert grid[0]["projection"] == {"market_fair_prob_over": 0.40}
    assert cov["rows_live_gameline_projected"] == 0 and cov["rows_live_display"] == 1


def test_a_college_half_margin_is_shown_only_when_the_producer_anchored_it(gate_on):
    anchored, raw = [_row("ncaab", segment="h1", market="spreads", line=-1.5, market_prob=0.5)], \
        [_row("ncaab", segment="h1", market="spreads", line=-1.5, market_prob=0.5)]
    _attach(anchored, _snapshot(_college_lane(anchored=True)), "ncaab")
    _attach(raw, _snapshot(_college_lane(anchored=False)), "ncaab")
    assert anchored[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.5, abs=0.02)
    # The raw college margin runs at half to two-thirds of the market's: never shown.
    assert LIVE_DISPLAY_KEY not in raw[0]
    _assert_nothing_priced(anchored[0])
    _assert_nothing_priced(raw[0])


def test_a_settled_college_half_shows_nothing(gate_on):
    grid = [_row("ncaab", segment="h1", line=64.5)]
    _attach(grid, _snapshot(_college_lane(settled=True)), "ncaab")
    assert LIVE_DISPLAY_KEY not in grid[0]


def test_a_college_quote_behind_the_score_shows_the_live_number_and_prices_nothing(gate_on):
    """The 11-08 ncaab case: 58 full-game rows refused `quote_older_than_the_score_the_model_saw`, display=0."""
    lane = _college_lane(score_changed_at=_at(-5).isoformat())
    grid = [_row("ncaab", updated_at=_at(-30).isoformat())]
    cov = _attach(grid, _snapshot(lane), "ncaab")
    assert cov["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}
    assert grid[0][LIVE_DISPLAY_KEY]["basis"] == REASON_QUOTE_BEHIND_SCORE
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.5, abs=0.02)
    _assert_nothing_priced(grid[0])


def test_a_college_stale_quote_on_a_spread_reads_the_anchored_full_game_margin(gate_on):
    grid = [_row("wncaab", market="spreads", line=3.5, market_prob=0.5, age=900.0)]
    _attach(grid, _snapshot(_college_lane()), "wncaab")
    assert grid[0][LIVE_DISPLAY_KEY]["basis"] == REASON_STALE_QUOTE
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.02)
    _assert_nothing_priced(grid[0])


@pytest.mark.parametrize("gate", ["", "shadow", "off"])
def test_a_college_lane_past_its_ceiling_shows_nothing_whatever_the_gate(monkeypatch, gate_on, gate):
    """College's carry has no age bound (p50 987 s, max 5,750 s): a stale lane is not a live number, on any branch,
    and switching the PRICE gate to shadow or off must not put it on the Live column either."""
    if gate:
        monkeypatch.setenv(lgj.LANE_AGE_GATE_ENV, gate)
    grid = [_row("ncaab", segment="h1", line=64.5),                                    # segment branch
            _row("ncaab", age=900.0),                                                  # stale-quote branch
            _row("ncaab", market="h2h", line=None, market_prob=0.6)]                   # moneyline branch
    cov = _attach(grid, _snapshot(_college_lane()), "ncaab", now=_at(987))
    assert all(LIVE_DISPLAY_KEY not in row for row in grid)
    assert "rows_live_display" not in cov
    if not gate:
        assert grid[2]["projection"].get("live_aware") is None
        assert cov["withheld_by_reason"].get(REASON_STALE_LANE) == 1


def test_a_college_lane_with_no_time_shows_nothing(gate_on):
    grid = [_row("ncaab", segment="h1", line=64.5), _row("ncaab", age=900.0)]
    cov = _attach(grid, _snapshot(_college_lane(as_of=None)), "ncaab")
    assert all(LIVE_DISPLAY_KEY not in row for row in grid)
    assert "rows_live_display" not in cov


def test_a_college_moneyline_carries_its_home_probability_for_display_only(gate_on):
    grid = [_row("ncaab", market="h2h", line=None, market_prob=0.6)]
    _attach(grid, _snapshot(_college_lane()), "ncaab")
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.01)
    assert grid[0][LIVE_DISPLAY_KEY]["basis"] == "moneyline_not_published"
    # Still NOT published where the plausibility gate reads it.
    assert "live_model_prob_over" not in grid[0]["projection"]


# ------------------------------------------------------------------------------------------------- football + hockey

def test_nfl_spreads_stay_blank_and_its_moneyline_shows(gate_on):
    """NFL margins were graded a measured FAIL (worst bucket 0.4290 vs 0.150): the lane's own top-level
    `margin_dist` is never read, so a spread row has no display number on any branch. The moneyline does."""
    lane = _nfl_lane()
    grid = [_row("nfl", market="spreads", line=3.5, market_prob=0.5, age=900.0),   # stale quote
            _row("nfl", market="spreads", line=3.5, market_prob=0.5),              # fresh quote
            _row("nfl", market="h2h", line=None, market_prob=0.6),
            _row("nfl", market="totals", line=44.5, age=900.0)]
    _attach(grid, _snapshot(lane), "nfl")
    assert LIVE_DISPLAY_KEY not in grid[0] and LIVE_DISPLAY_KEY not in grid[1]
    for spread in grid[:2]:
        assert "live_model_probability" not in _live_projection_columns({**spread, "side": "home"})
    assert grid[2][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.01)
    # A totals row shows its live COUNT and no probability: there is no distribution to read one from.
    assert grid[3][LIVE_DISPLAY_KEY]["prob_over"] is None and grid[3][LIVE_DISPLAY_KEY]["total_mean"] == 44.0


def test_nhl_shows_the_moneyline_and_the_total_count_but_no_puck_line(gate_on):
    grid = [_row("nhl", market="h2h", line=None, market_prob=0.6, age=900.0),
            _row("nhl", market="spreads", line=-1.5, market_prob=0.4, age=900.0),
            _row("nhl", market="totals", line=5.5, age=900.0),
            _row("nhl", market="h2h", line=None, market_prob=0.6)]
    _attach(grid, _snapshot(_nhl_lane()), "nhl", now=_at(5_000))   # NHL has no lane ceiling: not gated
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.01)
    assert LIVE_DISPLAY_KEY not in grid[1]
    assert grid[2][LIVE_DISPLAY_KEY]["total_mean"] == 5.8 and grid[2][LIVE_DISPLAY_KEY]["prob_over"] is None
    assert grid[3][LIVE_DISPLAY_KEY]["basis"] == "moneyline_not_published"


def test_ncaaf_stale_quote_reads_its_graded_margin_and_its_moneyline_shows(gate_on):
    grid = [_row("ncaaf", market="spreads", line=3.5, market_prob=0.5, age=900.0),
            _row("ncaaf", market="h2h", line=None, market_prob=0.6)]
    _attach(grid, _snapshot(_football_lane()), "ncaaf")
    assert grid[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.02)
    assert grid[1][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(0.7, abs=0.01)
    _assert_nothing_priced(grid[0])


def test_a_football_lane_past_its_ceiling_shows_nothing(gate_on):
    grid = [_row("ncaaf", market="spreads", line=3.5, market_prob=0.5, age=900.0)]
    _attach(grid, _snapshot(_football_lane()), "ncaaf", now=_at(1_801))
    assert LIVE_DISPLAY_KEY not in grid[0]


# ------------------------------------------------------------------------------------------------- nothing prices

def _every_case():
    return [
        ("ncaab", _college_lane(score_changed_at=_at(-5).isoformat()), [
            _row("ncaab", segment="h1", line=64.5),
            _row("ncaab", segment="h1", market="spreads", line=-1.5, market_prob=0.5),
            _row("ncaab", updated_at=_at(-30).isoformat()),
            _row("ncaab", market="h2h", line=None, market_prob=0.6),
            _row("ncaab", market="h2h", line=None, market_prob=0.4, age=900.0),
            _row("ncaab", market="spreads", line=3.5, market_prob=0.5)]),
        ("wncaab", _college_lane(), [
            _row("wncaab", segment="h1", line=64.5),
            _row("wncaab", market="totals", age=900.0),
            _row("wncaab", market="h2h", line=None, market_prob=0.6)]),
        ("ncaaf", _football_lane(), [
            _row("ncaaf", market="spreads", line=3.5, market_prob=0.5, age=900.0),
            _row("ncaaf", market="h2h", line=None, market_prob=0.6),
            _row("ncaaf", market="totals", line=48.5, market_prob=0.5)]),
        ("nfl", _nfl_lane(), [
            _row("nfl", market="spreads", line=3.5, market_prob=0.5, age=900.0),
            _row("nfl", market="h2h", line=None, market_prob=0.6),
            _row("nfl", market="h2h", line=None, market_prob=0.6, age=900.0)]),
        ("nhl", _nhl_lane(), [
            _row("nhl", market="h2h", line=None, market_prob=0.6),
            _row("nhl", market="totals", line=5.5, age=900.0)]),
    ]


@pytest.mark.parametrize("sport,lane,rows", _every_case(), ids=lambda v: v if isinstance(v, str) else "")
def test_the_table_on_vs_off_changes_nothing_but_the_display_key(monkeypatch, gate_on, sport, lane, rows):
    """Reachability AND the no-pricing invariant in one: on adds display blocks (off != on), and every row minus
    `live_display` is byte-identical to the off run -- same edges, same `live_aware`, same refusals, same ledger."""
    import copy

    on, off = copy.deepcopy(rows), copy.deepcopy(rows)
    cov_on = _attach(on, _snapshot(lane), sport)
    monkeypatch.setattr(lgj, "LIVE_DISPLAY_SPORTS", frozenset({"nba"}))
    cov_off = _attach(off, _snapshot(lane), sport)
    assert sum(LIVE_DISPLAY_KEY in row for row in on) > 0
    assert all(LIVE_DISPLAY_KEY not in row for row in off)
    assert [{k: v for k, v in row.items() if k != LIVE_DISPLAY_KEY} for row in on] == off
    assert {k: v for k, v in cov_on.items() if k != "rows_live_display"} == cov_off
    assert cov_on["rows_live_display"] == sum(LIVE_DISPLAY_KEY in row for row in on)


@pytest.mark.parametrize("sport,lane,rows", _every_case(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_display_only_row_carries_an_edge_live_aware_or_model_ev(gate_on, sport, lane, rows):
    """A row whose Live number comes ONLY from the display block: 0 of them carry `edge_vs_market_pct`,
    `live_aware` or `model_ev_pct`, on the grid row or on the board's Live columns."""
    _attach(rows, _snapshot(lane), sport)
    display_only = [row for row in rows if LIVE_DISPLAY_KEY in row and "live_gameline" not in row]
    assert display_only, "the case set must exercise a display-only row"
    for row in display_only:
        _assert_nothing_priced(row)
        for side in row["sides"]:
            assert "live_aware" not in _live_projection_columns({**row, "side": side})


# ------------------------------------------------------------------------------------------------- the board

def test_a_college_half_total_feeds_both_live_cells_in_its_own_side(gate_on):
    grid = [_row("ncaab", segment="h1", line=64.5)]
    _attach(grid, _snapshot(_college_lane()), "ncaab")
    over = _live_projection_columns({**grid[0], "side": "over"})
    under = _live_projection_columns({**grid[0], "side": "under"})
    assert over["live_total"] == 65.0 and under["live_total"] == 65.0
    assert over["live_model_probability"] + under["live_model_probability"] == pytest.approx(1.0)
    assert "live_aware" not in over


def test_an_away_moneyline_row_shows_its_own_sides_win_percent(gate_on):
    grid = [_row("nfl", market="h2h", line=None, market_prob=0.6)]
    _attach(grid, _snapshot(_nfl_lane()), "nfl")
    home = _live_projection_columns({**grid[0], "side": "home"})["live_model_probability"]
    away = _live_projection_columns({**grid[0], "side": "away"})["live_model_probability"]
    assert home == pytest.approx(0.7, abs=0.01) and away == pytest.approx(1.0 - home, abs=1e-5)


@pytest.mark.parametrize("sport,segmented", [("ncaab", True), ("wncaab", True), ("ncaaf", False),
                                             ("nfl", False), ("nhl", False), ("mlb", False)])
def test_the_board_caller_passes_the_display_flag_from_the_table(monkeypatch, sport, segmented):
    """College gets segment indexes and the display flag with its pricing OFF; a sport outside the table gets no
    flag. The flag is inert without segment indexes, so football and hockey segments stay blank."""
    seen = {}

    def fake_attach(grid, index, **kwargs):
        seen.update(kwargs)
        return lgj.new_coverage()

    monkeypatch.delenv(lgj.COLLEGE_SEGMENT_PRICING_ENV, raising=False)
    monkeypatch.setattr(lgj, "attach_live_gamelines", fake_attach)
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: _snapshot(_college_lane()))
    board_enrichment.attach_live_gamelines_for_sport([_row(sport)], sport=sport, selected_date="2026-11-09")
    assert seen["segment_pricing_enabled"] is False
    assert seen["segment_display_only"] is (sport in lgj.LIVE_DISPLAY_SPORTS)
    assert (seen["segment_indexes"] is not None) is segmented
