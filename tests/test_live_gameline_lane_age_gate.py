"""A live lane older than its sport's ceiling is not priced (`#762`, lane live-gameline-lane-age-gate).

`attach_live_gamelines` refused a row on QUOTE age only, so a re-sim lane was priced however old it was when the board
read it. Measured on the fleet's live-gameline ledgers 10-21..11-07: NCAAB carried lanes were priced at a median
987 s and up to 5,750 s old (`ncaab/live_resim._carry` has no age bound), while every FRESH basketball lane was under
600 s. 95.6% of the stale NCAAB records measurable against the re-sim's tick logs came from ticks that exhausted
their budget, so the loop's capacity is the cure and this gate keeps those lanes off the price.

It ships behind `SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE` (off | shadow | on), DEFAULT SHADOW: refusing ~19% of priced
NCAAB rows is the user's decision, so only an explicit `on` prices differently, and main reaches the fleet with any
session's fast-forward. Shadow changes no row (user 2026-11-07 "Yes, shadow"). These pin the gate:

  - shadow (absent, unrecognised) and off price exactly as before, shadow counting what it would refuse; on refuses;
  - each measured sport refuses past its ceiling and prices at it; an unmeasured sport is untouched;
  - an absent lane time refuses on a gated sport (`unknown must not default permissive`);
  - through the join, `off != on`: the same row and lane price fresh and refuse stale, with only the build time moved;
  - the EDGE is withheld and the NBA display number is kept;
  - the two quote reasons count exactly what they did; this reason counts only the rows it newly refuses;
  - the production caller (`board_enrichment`) reaches the gate with the wall clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared.live_gameline_join import (
    LANE_AGE_GATE_ENV,
    LIVE_DISPLAY_KEY,
    MAX_LANE_AGE_ENV,
    REASON_LANE_TIME_ABSENT,
    REASON_STALE_LANE,
    REASON_STALE_QUOTE,
    attach_live_gamelines,
    build_live_gameline_index,
    lane_age_gate_mode,
    lane_age_verdict,
    max_lane_age_seconds,
)

LANE_AT = datetime(2026, 11, 7, 1, 0, 0, tzinfo=timezone.utc)
HOME, AWAY = "Atlanta Hawks", "Washington Wizards"
REFUSED_STALE = {"priceable": False, "withheld_reason": REASON_STALE_LANE,
                 "model_prob": None, "market_prob": None, "edge_pp": None}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv(MAX_LANE_AGE_ENV, raising=False)
    monkeypatch.delenv(LANE_AGE_GATE_ENV, raising=False)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv(LANE_AGE_GATE_ENV, "on")


def _at(seconds: float) -> datetime:
    return LANE_AT + timedelta(seconds=seconds)


# --------------------------------------------------------------------------------------------- the switch

@pytest.mark.parametrize("raw,mode", [(None, "shadow"), ("", "shadow"), ("onn", "shadow"), ("garbage", "shadow"),
                                      ("shadow", "shadow"), (" Shadow ", "shadow"), ("off", "off"), ("OFF", "off"),
                                      ("0", "off"), ("false", "off"), ("no", "off"), ("on", "on"), ("1", "on"),
                                      ("true", "on"), ("yes", "on")])
def test_only_an_explicit_on_prices_differently_and_the_default_is_shadow(raw, mode):
    assert lane_age_gate_mode({} if raw is None else {LANE_AGE_GATE_ENV: raw}) == mode


# --------------------------------------------------------------------------------------------- the verdict

@pytest.mark.parametrize("sport,ceiling", [("nba", 600.0), ("ncaab", 600.0), ("wncaab", 600.0),
                                           ("ncaaf", 1800.0), ("nfl", 1800.0), (" NBA ", 600.0)])
def test_each_measured_sport_prices_at_its_ceiling_and_refuses_past_it(sport, ceiling):
    assert max_lane_age_seconds(sport) == ceiling
    assert lane_age_verdict(LANE_AT.isoformat(), _at(ceiling), sport=sport) is None
    assert lane_age_verdict(LANE_AT.isoformat(), _at(ceiling + 0.5), sport=sport) == REFUSED_STALE


@pytest.mark.parametrize("sport", ["mlb", "wnba", "soccer", "nhl", None, ""])
def test_an_unmeasured_sport_is_not_gated_not_even_on_an_absent_time(sport):
    """MLB, WNBA and soccer lanes reach the join with no lane time at all; a ceiling there would refuse everything."""
    assert max_lane_age_seconds(sport) is None
    assert lane_age_verdict(LANE_AT.isoformat(), _at(99_999), sport=sport) is None
    assert lane_age_verdict(None, _at(0), sport=sport) is None


@pytest.mark.parametrize("as_of", [None, "", "t", "not a time"])
def test_an_absent_lane_time_refuses_by_name_on_a_measured_sport(as_of):
    verdict = lane_age_verdict(as_of, _at(0), sport="ncaab")
    assert verdict["withheld_reason"] == REASON_LANE_TIME_ABSENT and verdict["priceable"] is False


@pytest.mark.parametrize("spelled", ["2026-11-07T01:00:00Z", "2026-11-07T01:00:00+00:00", "2026-11-07 01:00:00",
                                     "2026-11-06T19:00:00-06:00", "2026-11-07T01:00:00.000000+00:00"])
def test_every_writers_spelling_is_one_instant(spelled):
    """NBA writes "+00:00", NCAAF/NFL microseconds, a naive time reads as UTC (the writers' convention)."""
    assert lane_age_verdict(spelled, _at(599), sport="nba") is None
    assert lane_age_verdict(spelled, _at(601), sport="nba") == REFUSED_STALE


def test_a_lane_stamped_after_the_build_is_not_stale_and_a_naive_build_time_is_utc():
    assert lane_age_verdict(_at(120).isoformat(), LANE_AT, sport="nba") is None
    assert lane_age_verdict(LANE_AT.isoformat(), _at(601).replace(tzinfo=None), sport="nba") == REFUSED_STALE


@pytest.mark.parametrize("raw,expected", [("900", 900.0), ("0", 600.0), ("-5", 600.0), ("abc", 600.0),
                                          ("inf", 600.0), ("nan", 600.0), ("", 600.0)])
def test_the_override_moves_every_measured_sport_and_cannot_switch_the_gate_off(monkeypatch, raw, expected):
    monkeypatch.setenv(MAX_LANE_AGE_ENV, raw)
    assert max_lane_age_seconds("nba") == expected
    assert max_lane_age_seconds("ncaaf") == (expected if expected != 600.0 else 1800.0)
    # And it never gates a sport the table leaves out.
    assert max_lane_age_seconds("mlb") is None


# --------------------------------------------------------------------------------------------- through the join

def _snapshot(*, as_of=LANE_AT.isoformat(), carried=False, source="live_resim"):
    lane = {"key": "live", "source": source, "modelHomeWinProb": 0.9, "simsRun": 200,
            "projection": {"total": 230.0, "homeMargin": 9.0, "totalRunsDist": {"220": 100, "240": 100},
                           "marginDist": {"4": 100, "14": 100}}}
    if as_of is not None:
        lane["liveStateAsOf"] = as_of
    if carried:
        lane["liveStateCarriedForward"] = True
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(*, market="h2h", line=None, market_prob=0.40, age=20.0, updated_at=None):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    row = {"kind": "game", "market": market, "segment": "full", "line": line, "sides": sides,
           "away_team": AWAY, "home_team": HOME, "age_seconds": age,
           "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}
    if updated_at is not None:
        row["updated_at"] = updated_at
    return row


def _attach(rows, snapshot, *, sport="nba", now=None, source="live_resim"):
    index = build_live_gameline_index(snapshot, sources=(source,), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=now)


def _assert_priced(row, coverage):
    assert row["projection"]["live_aware"] is True
    assert row["live_gameline"]["priceable"] is True
    assert row["projection"].get("edge_vs_market_pct") is not None
    assert coverage["rows_live_gameline_priceable"] == 1


def _assert_edge_withheld(row, coverage, reason):
    assert "live_aware" not in row["projection"]
    assert "live_gameline" not in row
    assert row["projection"].get("edge_vs_market_pct") is None
    assert coverage["rows_live_gameline_priceable"] == 0
    assert coverage["withheld_by_reason"] == {reason: 1}


@pytest.mark.parametrize("raw,mode,counted", [(None, "shadow", 1), ("garbage", "shadow", 1), ("off", "off", 0)])
def test_the_default_and_off_price_a_stale_lane_exactly_as_before(monkeypatch, raw, mode, counted):
    """Absent or unrecognised (shadow, the default) and off: the row prices as it always did; only shadow counts it.
    The instrument reads the lane's age either way."""
    if raw is not None:
        monkeypatch.setenv(LANE_AGE_GATE_ENV, raw)
    rows = [_row()]
    cov = _attach(rows, _snapshot(), now=_at(5_000))
    _assert_priced(rows[0], cov)
    assert cov["lane_age_gate"] == mode
    assert cov["withheld_by_reason"] == {}
    expected = {REASON_STALE_LANE: 1} if counted else {}
    assert cov["lane_age_would_refuse"] == expected and cov["lane_age_would_refuse_priced"] == expected
    assert cov["lane_age_max_s"] == 5_000.0


def test_off_shadow_and_on_differ_on_the_same_row_and_lane(monkeypatch):
    """`off != on` through `attach_live_gamelines`, with shadow between: it prices exactly as off and counts what on
    refuses -- including that the row it would refuse was a PRICED one."""
    out = {}
    for mode in ("off", "shadow", "on"):
        monkeypatch.setenv(LANE_AGE_GATE_ENV, mode)
        rows = [_row()]
        out[mode] = (rows[0], _attach(rows, _snapshot(), now=_at(700)))

    row, cov = out["off"]
    _assert_priced(row, cov)
    row, cov = out["shadow"]
    _assert_priced(row, cov)
    assert row["live_gameline"] == out["off"][0]["live_gameline"]
    assert cov["withheld_by_reason"] == {}
    assert cov["lane_age_would_refuse"] == {REASON_STALE_LANE: 1}
    assert cov["lane_age_would_refuse_priced"] == {REASON_STALE_LANE: 1}
    row, cov = out["on"]
    _assert_edge_withheld(row, cov, REASON_STALE_LANE)
    assert cov["lane_age_would_refuse"] == {}


def test_shadow_counts_only_rows_the_quote_gates_let_through(monkeypatch):
    """A row a quote gate refuses is that gate's; shadow must not count it as the lane gate's newly refused row."""
    monkeypatch.setenv(LANE_AGE_GATE_ENV, "shadow")
    rows = [_row(age=900.0), _row(), _row(market_prob=0.88)]
    cov = _attach(rows, _snapshot(), now=_at(700))
    assert cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1, "prob_interval_swamps_edge": 1}
    assert cov["lane_age_would_refuse"] == {REASON_STALE_LANE: 2}
    # Only the 0.40 row was priced; the 0.88 row's edge is inside the model's noise.
    assert cov["lane_age_would_refuse_priced"] == {REASON_STALE_LANE: 1}


def test_on_the_same_row_and_lane_price_fresh_and_refuse_stale(gate_on):
    """Only the build time moves. Without the pair, a refusal here could come from any gate."""
    fresh, stale = [_row()], [_row()]
    cov_fresh = _attach(fresh, _snapshot(), now=_at(100))
    cov_stale = _attach(stale, _snapshot(), now=_at(700))

    _assert_priced(fresh[0], cov_fresh)
    assert REASON_STALE_LANE not in cov_fresh["withheld_by_reason"]
    _assert_edge_withheld(stale[0], cov_stale, REASON_STALE_LANE)
    assert cov_fresh["lane_age_max_s"] == 100.0 and cov_stale["lane_age_max_s"] == 700.0


def test_the_stale_lane_keeps_its_display_number(gate_on):
    """The edge is withheld; the live number is about the game and stays on the NBA Live column (`#762`)."""
    fresh, stale = [_row()], [_row()]
    _attach(fresh, _snapshot(), now=_at(100))
    cov = _attach(stale, _snapshot(), now=_at(700))
    assert stale[0][LIVE_DISPLAY_KEY]["basis"] == REASON_STALE_LANE
    assert stale[0][LIVE_DISPLAY_KEY]["prob_over"] == pytest.approx(fresh[0][LIVE_DISPLAY_KEY]["prob_over"])
    assert cov["rows_live_display"] == 1


def test_a_carried_college_lane_past_the_ceiling_is_refused_and_the_fresh_one_prices(gate_on):
    """The measured case: `ncaab/live_resim._carry` republishes a lane with no age bound. The quote is newer than
    the score, so the college quote-order gate passes it either way; only the lane's age differs."""
    quote_at = _at(5).isoformat()
    fresh = [_row(market="totals", line=225.5, market_prob=0.20, updated_at=quote_at)]
    carried = [_row(market="totals", line=225.5, market_prob=0.20, updated_at=quote_at)]
    cov_fresh = _attach(fresh, _snapshot(), sport="ncaab", now=_at(120))
    cov_carried = _attach(carried, _snapshot(carried=True), sport="ncaab", now=_at(987))

    _assert_priced(fresh[0], cov_fresh)
    _assert_edge_withheld(carried[0], cov_carried, REASON_STALE_LANE)
    # College has no display number: nothing is shown in its place.
    assert LIVE_DISPLAY_KEY not in carried[0]


def test_a_row_a_quote_gate_refuses_is_counted_there_and_only_there(gate_on):
    """The lane is judged LAST, so the quote reasons count exactly what they did before this gate existed."""
    rows = [_row(age=900.0)]
    cov = _attach(rows, _snapshot(), now=_at(5_000))
    assert cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
    # The instrument still sees the lane the quote gate stopped.
    assert cov["lane_age_max_s"] == 5_000.0


def test_a_measured_lane_with_no_time_is_refused_by_name_and_still_shown(gate_on):
    rows = [_row()]
    cov = _attach(rows, _snapshot(as_of=None), now=_at(0))
    _assert_edge_withheld(rows[0], cov, REASON_LANE_TIME_ABSENT)
    assert cov["lane_age_max_s"] is None
    assert rows[0][LIVE_DISPLAY_KEY]["basis"] == REASON_LANE_TIME_ABSENT


def test_the_override_reaches_the_join(monkeypatch, gate_on):
    rows = [_row()]
    monkeypatch.setenv(MAX_LANE_AGE_ENV, "1000")
    cov = _attach(rows, _snapshot(), now=_at(700))
    _assert_priced(rows[0], cov)


def test_an_unmeasured_sports_old_lane_prices_exactly_as_before(gate_on):
    """MLB is not gated: an hour-old lane prices as it always did, and the instrument still reports its age."""
    rows = [_row()]
    cov = _attach(rows, _snapshot(source="live_mc"), sport="mlb", now=_at(3_600), source="live_mc")
    _assert_priced(rows[0], cov)
    assert cov["lane_age_max_s"] == 3_600.0


def test_the_sport_falls_back_to_the_callers_when_the_index_stamps_none(gate_on):
    """An index built without `sport` must not skip the gate for a sport the caller names."""
    rows = [_row()]
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",))
    assert all(hit.get("sport") is None for hit in index.values())
    cov = attach_live_gamelines(rows, index, sport="nba", now=_at(700))
    _assert_edge_withheld(rows[0], cov, REASON_STALE_LANE)


# --------------------------------------------------------------------------------------------- the production caller

def test_the_board_caller_judges_the_lane_against_the_wall_clock_and_reads_the_switch(monkeypatch):
    """`board_enrichment.attach_live_gamelines_for_sport` passes no `now`: the default must be the build's wall
    clock, or the gate is inert on the one path that prices. Same row, same producer; only the lane's age and the
    switch change -- and with the switch absent, the production default (shadow), the stale lane still prices."""
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    wall = datetime.now(timezone.utc)
    outcomes = {}
    for mode in (None, "on"):
        if mode is None:
            monkeypatch.delenv(LANE_AGE_GATE_ENV, raising=False)
        else:
            monkeypatch.setenv(LANE_AGE_GATE_ENV, mode)
        for label, age in (("fresh", 30), ("stale", 3_600)):
            snapshot = _snapshot(as_of=(wall - timedelta(seconds=age)).isoformat())
            monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path, s=snapshot: s)
            rows = [_row()]
            cov = board_enrichment.attach_live_gamelines_for_sport(rows, sport="nba", selected_date="2026-11-07")
            outcomes[(mode, label)] = (rows[0], cov)

    for key in ((None, "fresh"), (None, "stale"), ("on", "fresh")):
        _assert_priced(*outcomes[key])
    # The production default counts the stale, priced row it would refuse, and refuses nothing.
    row, cov = outcomes[(None, "stale")]
    assert cov["lane_age_gate"] == "shadow" and cov["withheld_by_reason"] == {}
    assert cov["lane_age_would_refuse_priced"] == {REASON_STALE_LANE: 1}
    assert outcomes[(None, "fresh")][1]["lane_age_would_refuse"] == {}
    row, cov = outcomes[("on", "stale")]
    _assert_edge_withheld(row, cov, REASON_STALE_LANE)
    assert cov["lane_age_max_s"] >= 3_600.0 and cov["lane_age_gate"] == "on"
