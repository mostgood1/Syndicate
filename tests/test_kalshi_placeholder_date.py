"""Kalshi's placeholder-dated NCAAF games: one exception, shared by the order guard and the board.

User decision 2026-10-20 "Narrow exception" (todo `#710`). Oregon @ Illinois is
`KXNCAAFGAME-26OCT23OREILL` (Kalshi time 10-24T03:00Z placeholder, close
10-26T00:00Z) while the game kicks off Saturday 10-24 19:00Z. These pin that it
is ACCEPTED on both paths, and that every neighbouring case is still refused:
Troy/JMU 10-29 (wrong game), a one-day-early ticker at a real time, another
matchup's blob, two days early, and a non-NCAAF ticker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import kalshi_ticker_date_guard as guard
from syndicate.features.shared.kalshi_placeholder_date import (
    eastern_game_date,
    kalshi_event_time,
    placeholder_one_day_early,
)
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    _h2h_alias_keys_shaped,
    apply_venue_quotes_to_grid,
)

ORE = "KXNCAAFGAME-26OCT23OREILL-ORE"
KICKOFF = "2026-10-24T19:00:00Z"
AWAY, HOME = "Oregon Ducks", "Illinois Fighting Illini"
PLACEHOLDER = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
PLACEHOLDER_CLOSE = "2026-10-26T00:00:00Z"  # measured: close - expected = 45h


def _accept(ticker=ORE, *, kickoff=KICKOFF, away=AWAY, home=HOME, kalshi_time=PLACEHOLDER):
    return placeholder_one_day_early(
        ticker, eastern_game_date=eastern_game_date(kickoff), away_team=away,
        home_team=home, sport="ncaaf", kalshi_time=kalshi_time,
    )


# --- the predicate --------------------------------------------------------------


def test_ore_ill_is_accepted():
    accepted, detail = _accept()
    assert accepted, detail
    assert "blob=OREILL" in detail


def test_kalshi_time_is_read_from_the_stated_field_or_close_minus_45h():
    assert kalshi_event_time({"expected_expiration_time": "2026-10-24T03:00:00Z"}) == PLACEHOLDER
    assert kalshi_event_time({"close_time": PLACEHOLDER_CLOSE}) == PLACEHOLDER
    assert kalshi_event_time({}) is None


@pytest.mark.parametrize(
    "case, kwargs, reason",
    [
        ("Troy/JMU 10-29 on UM@TRO 10-24", dict(ticker="KXNCAAFGAME-26OCT29TROYJMU-TROY",
         kickoff="2026-10-24T20:00:00Z", away="UL Monroe Warhawks", home="Troy Trojans"), "not_one_day_early"),
        ("one day early at a REAL time", dict(kalshi_time=datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)), "not_placeholder"),
        ("another matchup's blob", dict(ticker="KXNCAAFGAME-26OCT23TTUCIN-TTU"), "teams_not_matched"),
        ("two days early", dict(ticker="KXNCAAFGAME-26OCT22OREILL-ORE"), "not_one_day_early"),
        ("not NCAAF", dict(ticker="KXNFLGAME-26OCT23OREILL-ORE"), "not_ncaaf_ticker"),
        ("kalshi time unknown", dict(kalshi_time=None), "kalshi_time_unknown"),
        ("team missing", dict(home=None), "teams_unknown"),
        ("reversed teams", dict(away=HOME, home=AWAY), "teams_not_matched"),
    ],
)
def test_every_other_case_is_refused(case, kwargs, reason):
    accepted, detail = _accept(**kwargs)
    assert not accepted, case
    assert detail.startswith(reason), (case, detail)


# --- the order guard ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(guard, "_placeholder_market_cache", {})
    monkeypatch.delenv("SYNDICATE_EXECUTION_TICKER_DATE_GUARD", raising=False)


def _stub_fetch(monkeypatch, result):
    import syndicate.features.shared.kalshi_client as client

    calls = []

    def _fetch(ticker):
        calls.append(ticker)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(client, "fetch_market", _fetch)
    return calls


def test_guard_without_the_new_kwargs_is_unchanged(monkeypatch):
    calls = _stub_fetch(monkeypatch, {"status": "ok", "market": {"close_time": PLACEHOLDER_CLOSE}})
    assert guard.ticker_date_refusal(ORE, KICKOFF) == (
        guard.REFUSAL_MISMATCH, "ticker=2026-10-23 eastern=2026-10-24"
    )
    assert calls == []


def test_guard_off_vs_on_for_ore_ill(monkeypatch, capsys):
    """off != on: the same order is refused without the teams and accepted with them."""
    calls = _stub_fetch(monkeypatch, {"status": "ok", "market": {"close_time": PLACEHOLDER_CLOSE}})
    off, _ = guard.ticker_date_refusal(ORE, KICKOFF)
    on, detail = guard.ticker_date_refusal(ORE, KICKOFF, away_team=AWAY, home_team=HOME, sport="ncaaf")
    assert off == guard.REFUSAL_MISMATCH
    assert on is None, detail
    assert calls == [ORE]
    assert "TICKER_DATE_PLACEHOLDER_ACCEPTED" in capsys.readouterr().out


def test_guard_caches_the_kalshi_read_per_ticker(monkeypatch):
    calls = _stub_fetch(monkeypatch, {"status": "ok", "market": {"close_time": PLACEHOLDER_CLOSE}})
    for _ in range(3):
        guard.ticker_date_refusal(ORE, KICKOFF, away_team=AWAY, home_team=HOME, sport="ncaaf")
    assert calls == [ORE]


@pytest.mark.parametrize(
    "result",
    [
        OSError("network"),
        {"status": "error", "reason": "http_500"},
        {"status": "ok", "market": {"close_time": "2026-10-25T23:00:00Z"}},  # real 02:00Z game
    ],
)
def test_guard_keeps_the_refusal_when_kalshi_does_not_confirm(monkeypatch, result):
    _stub_fetch(monkeypatch, result)
    refusal, detail = guard.ticker_date_refusal(ORE, KICKOFF, away_team=AWAY, home_team=HOME, sport="ncaaf")
    assert refusal == guard.REFUSAL_MISMATCH, detail


def test_guard_still_refuses_troy_jmu(monkeypatch):
    calls = _stub_fetch(monkeypatch, {"status": "ok", "market": {"close_time": PLACEHOLDER_CLOSE}})
    refusal, _ = guard.ticker_date_refusal(
        "KXNCAAFGAME-26OCT29TROYJMU-TROY", "2026-10-24T20:00:00Z",
        away_team="UL Monroe Warhawks", home_team="Troy Trojans", sport="ncaaf",
    )
    assert refusal == guard.REFUSAL_MISMATCH
    assert calls == [], "a non-one-day-early mismatch must not even ask Kalshi"


# --- the board fan-in (the grid path the board build runs) ----------------------


def _grid_row():
    return {
        "sport": "ncaaf", "event_id": "evt-ore-ill", "market": "h2h", "line": None,
        "away_team": AWAY, "home_team": HOME, "commence_time": KICKOFF,
        "sides": ["home", "away"],
        "best": {
            "home": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
            "away": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
        },
        "game": {"state": "pregame"},
    }


def _quote(row, *, close_time):
    from syndicate.features.shared.venue_quote_adapters import probability_to_american

    key = _h2h_alias_keys_shaped(row, "ncaaf", "h2h", "away", [])[0][1]
    return key, Quote(
        key=key, source="kalshi", sport="", market="h2h", side="", line=None,
        probability=0.30, american=probability_to_american(0.30),
        fetched_at=1_000_000.0, venue_ref=ORE, game=None, venue_close_time=close_time,
    )


@pytest.mark.parametrize(
    "close_time, expect_priced",
    [(PLACEHOLDER_CLOSE, True), (None, False), ("2026-10-25T23:00:00Z", False)],
)
def test_board_grid_prices_ore_ill_only_on_the_placeholder(close_time, expect_priced, capsys):
    row = _grid_row()
    key, quote = _quote(row, close_time=close_time)
    out = apply_venue_quotes_to_grid(
        [row], "ncaaf", "2026-10-20", now=1_000_010.0, collected={"quotes": {key: quote}}
    )
    assert (out["repriced"] == 1) is expect_priced, out
    assert (out["cross_date_rejected"] == 0) is expect_priced, out
    log = capsys.readouterr().out
    assert f"placeholder_accepted={1 if expect_priced else 0}" in log
