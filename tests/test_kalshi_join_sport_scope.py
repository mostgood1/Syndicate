"""A Kalshi market resolves only onto a game of its OWN sport (lane kalshi-join-sport-scope).

THE CASE (11-21, F27): live order `373a43d7` was a men's NCAAB bet (UC Irvine @ San
Diego, tip 21:30Z) sent to `KXNCAAWBGAME-26NOV21UCIUSD-UCI`, the WOMEN'S game (tip
03:00Z). `_resolve_event` matched the market's club blob against every game on the
cross-sport board, and the sport only chose the club map. So with only the men's game
on the board, the women's market resolved `ok` onto it; with both games on the board
it read `ambiguous` and the right bet was refused.

`SYNDICATE_KALSHI_JOIN_SPORT_SCOPE`: absent = `report` (today's answer, byte-identical,
plus what `on` would do), `on` = scoped, `off` = no check. Reachability first: `off != on`.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_board_join as mod_join
from syndicate.features.shared.kalshi_board_join import (
    REASON_EVENT_AMBIGUOUS,
    REASON_EVENT_UNMATCHED,
    _distinct_games,
    _own_sport_games,
    _resolve_event,
    join_kalshi_to_board,
    kalshi_join_sport_scope_mode,
)

ENV = "SYNDICATE_KALSHI_JOIN_SPORT_SCOPE"

WOMENS_MARKET = {"ticker": "KXNCAAWBGAME-26NOV21UCIUSD-UCI", "series": "KXNCAAWBGAME"}
MENS_MARKET = {"ticker": "KXNCAAMBGAME-26NOV21UCIUSD-UCI", "series": "KXNCAAMBGAME"}


def _game(event_id, sport, commence):
    return {
        "event_id": event_id,
        "sport": sport,
        "home_team": "San Diego Toreros",
        "away_team": "UC Irvine Anteaters",
        "commence_time": commence,
        "market": "h2h",
    }


MENS_GAME = _game("mens-401", "ncaab", "2026-11-21 21:30:00+00:00")
WOMENS_GAME = _game("womens-402", "wncaab", "2026-11-22 03:00:00+00:00")


def _resolve(market, rows, mode, monkeypatch):
    if mode is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, mode)
    return _resolve_event(market, rows)


# --- the switch --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, mode",
    [
        (None, "report"),
        ("", "report"),
        ("garbage", "report"),
        ("report", "report"),
        ("on", "on"),
        ("1", "on"),
        ("enforce", "on"),
        ("off", "off"),
        ("0", "off"),
    ],
)
def test_absent_and_unknown_read_report_never_on(monkeypatch, raw, mode):
    """Absent must not be the behaviour change. An unknown value reads `report`,
    which places exactly today's bets."""
    if raw is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, raw)
    assert kalshi_join_sport_scope_mode() == mode


def test_distinct_games_carry_the_sport():
    games = _distinct_games([MENS_GAME, dict(MENS_GAME, market="spreads"), WOMENS_GAME])
    assert [(g["event_id"], g["sport"]) for g in games] == [("mens-401", "ncaab"), ("womens-402", "wncaab")]


def test_a_game_with_no_sport_stays_eligible_and_an_unknown_market_sport_filters_nothing():
    blank = dict(MENS_GAME, event_id="blank-1", sport=None)
    games = _distinct_games([MENS_GAME, WOMENS_GAME, blank])
    assert [g["event_id"] for g in _own_sport_games(games, "wncaab")] == ["womens-402", "blank-1"]
    assert [g["event_id"] for g in _own_sport_games(games, None)] == ["mens-401", "womens-402", "blank-1"]


# --- the 11-21 order, reproduced -------------------------------------------------


def test_the_womens_market_on_a_mens_only_board_lands_on_the_mens_game_today(monkeypatch):
    """The defect itself, pinned so `off` provably is today's code path."""
    off = _resolve(WOMENS_MARKET, [MENS_GAME], "off", monkeypatch)
    assert off["status"] == "ok"
    assert off["event_id"] == "mens-401"
    assert "sport_scope_would" not in off


def test_report_is_todays_answer_plus_what_on_would_do(monkeypatch):
    off = _resolve(WOMENS_MARKET, [MENS_GAME], "off", monkeypatch)
    report = _resolve(WOMENS_MARKET, [MENS_GAME], None, monkeypatch)
    would = report.pop("sport_scope_would")
    assert report == off
    assert would == {
        "kind": "other_sport_game",
        "status": "no_match",
        "event_id": None,
        "today_event_sport": "ncaab",
    }


def test_on_refuses_the_womens_market_on_the_mens_game(monkeypatch):
    on = _resolve(WOMENS_MARKET, [MENS_GAME], "on", monkeypatch)
    assert on["status"] == "no_match"
    assert on.get("event_id") is None


def test_and_the_reverse_a_mens_market_on_a_womens_only_board(monkeypatch):
    off = _resolve(MENS_MARKET, [WOMENS_GAME], "off", monkeypatch)
    on = _resolve(MENS_MARKET, [WOMENS_GAME], "on", monkeypatch)
    assert (off["status"], off.get("event_id")) == ("ok", "womens-402")
    assert on["status"] == "no_match"


def test_with_both_games_on_the_board_on_finds_the_right_one(monkeypatch):
    """Today: `ambiguous`, so the right bet is refused. `on`: each market finds its
    own sport's game."""
    rows = [MENS_GAME, WOMENS_GAME]
    off = _resolve(WOMENS_MARKET, rows, "off", monkeypatch)
    assert off["status"] == "ambiguous"
    report = _resolve(WOMENS_MARKET, rows, None, monkeypatch)
    assert report["status"] == "ambiguous"
    assert report["sport_scope_would"]["kind"] == "ambiguous_across_sports"
    assert report["sport_scope_would"]["event_id"] == "womens-402"
    on_w = _resolve(WOMENS_MARKET, rows, "on", monkeypatch)
    on_m = _resolve(MENS_MARKET, rows, "on", monkeypatch)
    assert (on_w["status"], on_w["event_id"]) == ("ok", "womens-402")
    assert (on_m["status"], on_m["event_id"]) == ("ok", "mens-401")


def test_a_market_on_its_own_sports_game_is_untouched_in_every_mode(monkeypatch):
    answers = [_resolve(WOMENS_MARKET, [WOMENS_GAME], mode, monkeypatch) for mode in (None, "off", "on")]
    assert all(a == answers[0] for a in answers)
    assert (answers[0]["status"], answers[0]["event_id"]) == ("ok", "womens-402")
    assert "sport_scope_would" not in answers[0]


def test_the_memo_does_not_carry_one_modes_answer_into_another(monkeypatch):
    """The mode is part of the answer, so it is part of the memo key."""
    memo: dict = {}
    games = _distinct_games([MENS_GAME])
    monkeypatch.setenv(ENV, "off")
    off = _resolve_event(WOMENS_MARKET, [MENS_GAME], games=games, memo=memo)
    monkeypatch.setenv(ENV, "on")
    on = _resolve_event(WOMENS_MARKET, [MENS_GAME], games=games, memo=memo)
    assert off["status"] == "ok"
    assert on["status"] == "no_match"


# --- the join: reachability (off != on) and the per-build report -------------------


def _total():
    """`test_kalshi_board_join`'s total shape: a game-line contract on MIN @ ATH."""
    return {
        "ticker": "KXTESTTOTAL-26AUG242140MINATH-8",
        "series": "KXTESTTOTAL",
        "title": "Over 7.5 runs scored?",
        "yes_american": -110,
        "no_american": -110,
    }


def _row(sport, event_id):
    return {
        "sport": sport,
        "event_id": event_id,
        "market": "totals",
        "away_team": "MIN",
        "home_team": "ATH",
        "side": "Over",
        "line": 7.5,
    }


def _join(rows, mode, monkeypatch):
    from syndicate.features.shared import kalshi_catalogue as cat

    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    if mode is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, mode)
    cat.SERIES_SPORT["KXTESTTOTAL"] = "mlb"
    try:
        return join_kalshi_to_board([_total()], rows, selected_date="2026-08-24")
    finally:
        cat.SERIES_SPORT.pop("KXTESTTOTAL", None)


def test_the_join_prices_another_sports_game_off_and_refuses_it_on(monkeypatch):
    """Reachability before correctness: the switch changes what the ORDER join
    pairs, not just a helper's return value."""
    rows = [_row("wnba", "wnba-evt")]
    off = _join(rows, "off", monkeypatch)
    on = _join(rows, "on", monkeypatch)
    assert off["matched"] == 1
    assert on["matched"] == 0
    assert on["reasons"][REASON_EVENT_UNMATCHED] == 1


def test_report_mode_pairs_exactly_what_off_pairs_and_counts_the_difference(monkeypatch, capsys):
    rows = [_row("wnba", "wnba-evt")]
    off = _join(rows, "off", monkeypatch)
    report = _join(rows, None, monkeypatch)
    assert report["matches"] == off["matches"]
    assert report["reasons"] == off["reasons"]
    scope = report["sport_scope"]
    assert scope["mode"] == "report"
    assert scope["would_change"] == 1
    assert scope["by_kind"] == {"other_sport_game": 1}
    assert scope["samples"][0]["today_event"] == "wnba-evt"
    assert scope["samples"][0]["today_event_sport"] == "wnba"
    assert scope["samples"][0]["on"] == "no_match"
    out = capsys.readouterr().out
    assert "[kalshi_board_join] SPORT_SCOPE mode=report would_change=1" in out


def test_the_join_resolves_the_both_sports_pair_only_when_on(monkeypatch):
    rows = [_row("mlb", "mlb-evt"), _row("wnba", "wnba-evt")]
    off = _join(rows, "off", monkeypatch)
    on = _join(rows, "on", monkeypatch)
    assert off["matched"] == 0
    assert off["reasons"][REASON_EVENT_AMBIGUOUS] == 1
    assert on["matched"] == 1
    assert [m["board_event_id"] for m in on["matches"]] == ["mlb-evt"]


def test_the_report_field_is_present_and_zero_on_a_clean_board(monkeypatch, capsys):
    """Absence of the field means the code is not deployed; zero means nothing to change."""
    report = _join([_row("mlb", "mlb-evt")], None, monkeypatch)
    assert report["matched"] == 1
    assert report["sport_scope"] == {"mode": "report", "would_change": 0, "by_kind": {}, "samples": []}
    assert "SPORT_SCOPE mode=report would_change=0 by_kind={}" in capsys.readouterr().out
    off = _join([_row("mlb", "mlb-evt")], "off", monkeypatch)
    assert off["sport_scope"]["mode"] == "off"


def test_the_module_exposes_the_switch_reader():
    assert mod_join.kalshi_join_sport_scope_mode is kalshi_join_sport_scope_mode
