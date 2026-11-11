"""NCAAB, WNCAAB, NBA and NCAAF price live game lines only against quotes <= 120 s old (`#780`).

User 2026-11-11 "Yes, set 120 s", on the measurement in `live_gameline_join`'s comment above
`_MAX_QUOTE_AGE_BY_SPORT` (`.syndicate/findings_2026-11-10_live_totals_grade.md`): under 120 s of quote age the model's
live edge realises ~0 and loses to the market on Brier in totals, spreads and h2h alike; the "edge" appears only once the
quote has gone stale (180-300 s and up). MLB already had 120 s for the same reason. NFL and NHL are unmeasured and keep
600 s.

Reachability first (`off != on`): the same row and lane, priced at 119 s and refused at 180 s, through the join and
through the production caller; the env knob raised back to 600 prices the very row the table refuses; an unmeasured
sport still prices it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared.live_gameline_join import (
    REASON_STALE_QUOTE,
    attach_live_gamelines,
    build_live_gameline_index,
    max_quote_age_seconds,
    quote_age_verdict,
)

ENV = "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS"
MEASURED = ("ncaab", "wncaab", "nba", "ncaaf")
LANE_AT = datetime(2026, 11, 11, 2, 0, 0, tzinfo=timezone.utc)
HOME, AWAY = "Atlanta Hawks", "Washington Wizards"
FRESH, STALE = 119.0, 180.0  # 180 s: the bottom of the band where the measured "edge" appeared
MARKETS = [("h2h", None), ("totals", 230.5), ("spreads", 9.5)]


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


def _snapshot(as_of: datetime = LANE_AT):
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200,
            "liveStateAsOf": as_of.isoformat(),
            "projection": {"total": 230.0, "homeMargin": 9.0, "totalRunsDist": {"220": 100, "240": 100},
                           "marginDist": {"4": 100, "14": 100}}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(market="h2h", line=None, *, age, quote_at: datetime = LANE_AT, market_prob=0.20):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    # `updated_at` at the lane's own time: the college quote-order gate (a quote taken > 30 s before the score the
    # re-sim saw) passes it, so only the quote's AGE differs between the priced and the refused row.
    return {"kind": "game", "market": market, "segment": "full", "line": line, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": age, "updated_at": quote_at.isoformat(),
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(rows, sport):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=LANE_AT + timedelta(seconds=10))


def _priced(row, cov):
    return (row.get("live_gameline", {}).get("priceable") is True
            and row["projection"].get("edge_vs_market_pct") is not None
            and cov["rows_live_gameline_priceable"] == 1)


def _refused_stale(row, cov):
    return (cov["withheld_by_reason"] == {REASON_STALE_QUOTE: 1}
            and cov["rows_live_gameline_priceable"] == 0
            and row["projection"].get("edge_vs_market_pct") is None)


# --------------------------------------------------------------------------------------------- the table

@pytest.mark.parametrize("sport", MEASURED + (" NBA ", "NCAAB", "mlb"))
def test_each_measured_sport_is_120s(sport):
    assert max_quote_age_seconds(sport) == pytest.approx(120.0)
    assert quote_age_verdict(120.0, sport=sport) is None
    assert quote_age_verdict(120.5, sport=sport)["withheld_reason"] == REASON_STALE_QUOTE


@pytest.mark.parametrize("sport", ["nfl", "nhl", "wnba", "soccer", None, ""])
def test_an_unmeasured_sport_keeps_600s(sport):
    assert max_quote_age_seconds(sport) == pytest.approx(600.0)
    assert quote_age_verdict(STALE, sport=sport) is None
    assert quote_age_verdict(600.5, sport=sport)["withheld_reason"] == REASON_STALE_QUOTE


@pytest.mark.parametrize("raw", ["0", "-1", "off", "", "   "])
def test_a_junk_or_disabling_knob_falls_back_to_120_not_600(monkeypatch, raw):
    """A typo must not loosen the new sports back to 600 s."""
    monkeypatch.setenv(ENV, raw)
    for sport in MEASURED:
        assert max_quote_age_seconds(sport) == pytest.approx(120.0)


# --------------------------------------------------------------------------------------------- through the join

@pytest.mark.parametrize("market,line", MARKETS)
@pytest.mark.parametrize("sport", MEASURED)
def test_off_is_not_on_through_the_join(monkeypatch, sport, market, line):
    """119 s prices, 180 s is refused by name, and the knob at 600 prices the same 180 s row again."""
    fresh, stale, knob = ([_row(market, line, age=a)] for a in (FRESH, STALE, STALE))
    cov_fresh = _attach(fresh, sport)
    cov_stale = _attach(stale, sport)
    monkeypatch.setenv(ENV, "600")
    cov_knob = _attach(knob, sport)

    assert _priced(fresh[0], cov_fresh), (sport, market, cov_fresh)
    assert _refused_stale(stale[0], cov_stale), (sport, market, cov_stale)
    assert _priced(knob[0], cov_knob), (sport, market, cov_knob)
    # Looked at, then refused: a decision, not a skip.
    assert cov_stale["rows_live_gameline_considered"] == 1


@pytest.mark.parametrize("market,line", MARKETS)
def test_nfl_still_prices_a_180s_quote(market, line):
    """The control: the same lane and row on an unmeasured sport with the same producer stamp."""
    rows = [_row(market, line, age=STALE)]
    cov = _attach(rows, "nfl")
    assert _priced(rows[0], cov), cov


# --------------------------------------------------------------------------------------------- the production caller

@pytest.mark.parametrize("sport", MEASURED)
def test_the_board_caller_refuses_a_180s_quote_and_prices_a_119s_one(monkeypatch, sport):
    """`board_enrichment.attach_live_gamelines_for_sport` is the path that prices on the fleet. It builds the index
    with `sport=` (the ceiling reads the index's sport, not the caller's), so the table must reach it there."""
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    wall = datetime.now(timezone.utc)
    snapshot = _snapshot(as_of=wall - timedelta(seconds=20))
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: snapshot)
    out = {}
    for label, age in (("fresh", FRESH), ("stale", STALE)):
        rows = [_row("totals", 230.5, age=age, quote_at=wall - timedelta(seconds=10))]
        cov = board_enrichment.attach_live_gamelines_for_sport(rows, sport=sport, selected_date=wall.date().isoformat())
        out[label] = (rows[0], cov)
    assert _priced(*out["fresh"]), (sport, out["fresh"][1])
    assert _refused_stale(*out["stale"]), (sport, out["stale"][1])
