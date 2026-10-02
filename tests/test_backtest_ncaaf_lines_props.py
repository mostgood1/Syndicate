"""The arithmetic `scripts/backtest_ncaaf_lines_props.py` rests on.

Each test pins a place where a sign or a frame error would make the backtest
read a losing model as a winner (or the reverse) without failing loudly.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import backtest_ncaaf_lines_props as bt


def test_devig_is_proportional_and_symmetric():
    assert bt.devig_two_way(-110, -110) == pytest.approx(0.5)
    fair = bt.devig_two_way(-200, 170)
    assert fair == pytest.approx((200 / 300) / (200 / 300 + 100 / 270))
    assert bt.devig_two_way(-200, 170) + bt.devig_two_way(170, -200) == pytest.approx(1.0)
    assert bt.devig_two_way(None, -110) is None


def test_cfbd_book_market_margin_is_minus_home_spread_and_prefers_draftkings():
    row = {"lines": [
        {"provider": "ESPN Bet", "spread": -10.0, "overUnder": 50.0, "homeMoneyline": -400, "awayMoneyline": 300},
        {"provider": "DraftKings", "spread": -8.5, "overUnder": 52.5, "homeMoneyline": -345, "awayMoneyline": 275},
    ]}
    book = bt.cfbd_book(row)
    # LSU -8.5 at home: spread is the HOME line, so the market's home margin is +8.5
    assert book["spread"] == -8.5 and -book["spread"] == 8.5
    assert book["total"] == 52.5 and book["provider"] == "DraftKings"
    assert book["ml_home_fair"] == pytest.approx(bt.devig_two_way(-345, 275))


def test_cfbd_book_falls_back_to_the_median_without_draftkings():
    row = {"lines": [{"provider": "A", "spread": 3.0, "overUnder": 40.0},
                     {"provider": "B", "spread": 4.0, "overUnder": 44.0},
                     {"provider": "C", "spread": 7.0, "overUnder": 45.0}]}
    book = bt.cfbd_book(row)
    assert book["spread"] == 4.0 and book["total"] == 44.0 and book["ml_home_fair"] is None


def _q(book, sel, line, price, minutes_before=60, market="totals", ko="2026-09-26T16:00:00+00:00"):
    kickoff = datetime.fromisoformat(ko)
    return {"bookmaker": book, "selection": sel, "line": line, "price": price, "market": market,
            "captured_at": (kickoff - timedelta(minutes=minutes_before)).isoformat(), "commence_time": ko}


def test_consensus_takes_each_books_latest_pair_and_the_modal_line():
    qs = [
        _q("dk", "over", 50.5, -110, 300), _q("dk", "under", 50.5, -110, 300),  # stale
        _q("dk", "over", 50.5, -130, 30), _q("dk", "under", 50.5, 110, 30),     # latest
        _q("fd", "over", 50.5, -120, 30), _q("fd", "under", 50.5, 100, 30),
        _q("mgm", "over", 49.5, -110, 30), _q("mgm", "under", 49.5, -110, 30),  # minority line
    ]
    res = bt.consensus_fair(qs, side_a="over", side_b="under", line_key=lambda q: q["line"])
    assert res["line"] == 50.5 and res["books"] == 2
    expected = (bt.devig_two_way(-130, 110) + bt.devig_two_way(-120, 100)) / 2
    assert res["fair_a"] == pytest.approx(expected)


def test_one_sided_book_contributes_nothing():
    qs = [_q("dk", "over", 50.5, -110), _q("fd", "over", 50.5, -110), _q("fd", "under", 50.5, -110)]
    res = bt.consensus_fair(qs, side_a="over", side_b="under", line_key=lambda q: q["line"])
    assert res["books"] == 1


def test_spread_pairs_home_line_with_the_opposite_away_line():
    ko = "2026-09-26T16:00:00+00:00"
    qs = [dict(_q("dk", "home", -10.0, -105, market="spreads", ko=ko), event_id="e", segment="full",
               home_team="H", away_team="A"),
          dict(_q("dk", "away", 10.0, -115, market="spreads", ko=ko), event_id="e", segment="full",
               home_team="H", away_team="A")]
    books = bt.oddsapi_game_books(qs)
    res = books[("e", "spreads", "full")]
    assert res["line"] == -10.0  # the HOME line; home covers when margin > 10
    assert res["fair_a"] == pytest.approx(bt.devig_two_way(-105, -115))


def test_quotes_at_or_after_kickoff_are_dropped(tmp_path):
    ko = "2026-09-26T16:00:00+00:00"
    pre = dict(_q("dk", "over", 50.5, -110, 10, ko=ko), kind="game")
    post = dict(_q("dk", "over", 50.5, -110, -5, ko=ko), kind="game")
    at = dict(_q("dk", "over", 50.5, -110, 0, ko=ko), kind="game")
    path = tmp_path / "q.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in (pre, post, at)), encoding="utf-8")
    kept = bt.load_quotes([path], ("game",))
    assert len(kept) == 1 and kept[0]["captured_at"] == pre["captured_at"]


def test_h2_is_regulation_only_and_halves_add_up():
    g = {"homeLineScores": [7, 3, 0, 14, 6], "awayLineScores": [0, 10, 7, 0, 0]}
    ls = bt.line_scores(g)
    assert ls["h1"] == (10.0, 10.0)
    assert ls["h2"] == (14.0, 7.0)  # the overtime 6 is excluded
    assert bt.line_scores({"homeLineScores": [7, 3], "awayLineScores": [0, 0]}) is None


def test_naive_baseline_refuses_under_two_games_and_never_reads_week_n(monkeypatch):
    class _Gen:
        @staticmethod
        def norm(name):
            return name.lower()

    monkeypatch.setattr(bt, "_gen", lambda: _Gen)
    games = [
        {"week": 1, "homeTeam": "A", "awayTeam": "B", "homePoints": 30, "awayPoints": 10, "neutralSite": False},
        {"week": 2, "homeTeam": "B", "awayTeam": "A", "homePoints": 20, "awayPoints": 20, "neutralSite": False},
        {"week": 3, "homeTeam": "A", "awayTeam": "B", "homePoints": 99, "awayPoints": 0, "neutralSite": False},
    ]
    base = bt.naive_baseline(games, week=3)
    nv = bt.naive_game(base, "a", "b", neutral=True)
    # A: PF 30,20 PA 10,20; B: PF 10,20 PA 30,20 -> home (25+25)/2, away (15+15)/2
    assert nv["margin"] == pytest.approx(10.0) and nv["total"] == pytest.approx(40.0)
    assert bt.naive_game(bt.naive_baseline(games, week=2), "a", "b", neutral=True) is None


def test_cluster_bootstrap_moves_a_games_rows_together():
    rows = [("g1", 1.0)] * 50 + [("g2", -1.0)] * 50
    ci = bt.cluster_boot(rows, reps=400)
    assert ci["games"] == 2 and ci["n"] == 100
    # with two clusters the CI must span both cluster means, not shrink like n=100 iid rows
    assert ci["lo"] <= -0.9 and ci["hi"] >= 0.9
    assert bt.verdict(ci).startswith("insufficient")  # two games is never a verdict
    assert bt.verdict({"n": 5, "games": 30, "lo": -0.3, "hi": -0.1}) == "MODEL BETTER"
    assert bt.verdict({"n": 5, "games": 30, "lo": 0.1, "hi": 0.3}) == "MODEL WORSE"
    assert bt.verdict({"n": 5, "games": 30, "lo": -0.1, "hi": 0.3}) == "unresolved"
