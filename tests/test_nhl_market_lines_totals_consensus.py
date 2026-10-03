"""NHL totals line consensus (`market_lines.load_market_lines`) -- lane `nhl-game-lines-model`.

The defect: `total_line = median(every totals point captured)` priced lines no book hung -- on the
fleet 2026-09-30..10-04 the priced line differed from the modal pregame book line on 24 of 31 games
(LAK@COL 2026-09-30 priced 9.0 with 8 of 11 books at 6.5), because the oddsapi.csv capture keeps one
row per point a book EVER hung, in-play included, with no capture time.

Fixtures are REAL production rows (fleet, read-only copies), not invented:
  * book_quotes_2026-09-30_COL_LAK.jsonl -- the per-book quote log for LAK@COL: each of the 11
    books' latest pregame totals snapshot, two earlier pregame quotes from books that later moved
    (bovada / mybookieag at 6.0), and 12 post-puck-drop in-play quotes at far-off lines.
  * oddsapi_2026-09-30_COL_LAK.csv -- the same game's oddsapi.csv rows (13 totals points, 5.5..12.5).
  * oddsapi_2026-10-03_NYI_NJD.csv -- a pregame game with three books at 6.5 / 6.0 / 5.5.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.features import market_lines as ML

FX = Path(__file__).parent / "fixtures" / "nhl_totals_consensus"


def _root(tmp_path: Path, date: str, oddsapi: str, quotes: str | None = None) -> Path:
    root = tmp_path / "nhl_source"
    team = root / "data" / "odds" / "team" / f"date={date}"
    team.mkdir(parents=True)
    (root / "data" / "odds" / "games").mkdir(parents=True)
    shutil.copy(FX / oddsapi, team / "oddsapi.csv")
    if quotes:
        q = root / "tracking" / "book_quotes"
        q.mkdir(parents=True)
        shutil.copy(FX / quotes, q / f"{date}.jsonl")
    return root


def test_quote_log_gives_the_books_modal_pregame_line(tmp_path):
    root = _root(tmp_path, "2026-09-30", "oddsapi_2026-09-30_COL_LAK.csv", "book_quotes_2026-09-30_COL_LAK.jsonl")
    m = ML.market_for_game(ML.load_market_lines("2026-09-30", root=root), "Colorado Avalanche", "Los Angeles Kings")
    assert m is not None
    assert m.total_line == pytest.approx(6.5)       # 8 of 11 books; the old median priced 9.0
    assert m.over_odds is not None and m.under_odds is not None


def test_in_play_quotes_and_superseded_pregame_lines_are_ignored(tmp_path):
    root = _root(tmp_path, "2026-09-30", "oddsapi_2026-09-30_COL_LAK.csv", "book_quotes_2026-09-30_COL_LAK.jsonl")
    per_book = ML._quote_log_pregame_totals("2026-09-30", root).get(ML._game_key("Colorado Avalanche", "Los Angeles Kings"))
    assert per_book and len(per_book) == 11
    # one line per book, and it is the book's LATEST pregame line (the fixture's far in-play
    # lines and the two superseded 6.0 quotes never appear)
    assert all(len(points) == 1 for points in per_book.values())
    lines = sorted(next(iter(p)) for p in per_book.values())
    assert set(lines) <= {6.0, 6.5}
    assert lines.count(6.5) == 8


def test_the_old_median_rule_would_have_priced_a_phantom_line(tmp_path):
    """Pins the defect, measured on the same real rows: the median of every captured point."""
    import csv
    import statistics

    rows = list(csv.DictReader((FX / "oddsapi_2026-09-30_COL_LAK.csv").open(encoding="utf-8")))
    pts = [float(r["outcome_point"]) for r in rows if r["market"] == "totals" and r["outcome_point"]]
    assert statistics.median(pts) >= 8.0          # what production priced (9.0 in predictions_2026-09-30)


def test_fallback_without_quote_log_uses_a_line_a_book_actually_hangs(tmp_path):
    root = _root(tmp_path, "2026-10-03", "oddsapi_2026-10-03_NYI_NJD.csv")
    m = ML.market_for_game(ML.load_market_lines("2026-10-03", root=root), "New York Islanders", "New Jersey Devils") \
        or ML.market_for_game(ML.load_market_lines("2026-10-03", root=root), "New Jersey Devils", "New York Islanders")
    assert m is not None
    # three books at 6.5 / 6.0 / 5.5 tie on count; betmgm's 6.0 is closest to even money
    assert m.total_line == pytest.approx(6.0)
    assert (m.over_odds, m.under_odds) == (-115, -105)   # priced from the book AT that line only


def test_a_book_quoting_several_points_does_not_vote(tmp_path):
    by_book = {"a": {6.5: {"over": -110, "under": -110}, 9.0: {"over": -110, "under": -110}},
               "b": {6.0: {"over": -110, "under": -110}}}
    line, overs, unders = ML._consensus_total(by_book)
    assert line == 6.0 and overs == [-110] and unders == [-110]


def test_no_usable_book_is_an_honest_none():
    assert ML._consensus_total({}) == (None, [], [])
    assert ML._consensus_total({"a": {6.5: {"over": -110}}})[0] is None   # one-sided
