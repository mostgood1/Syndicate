"""NCAAF weekly recommendation summary producer (lane intelligence-evidence-coverage, goal item 5)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaaf_recommendation_summary", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaaf_recommendation_summary.py"
)
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)


def _cells(prices):
    return {book: {side: {"price": price, "line": line, "stale": False} for side, (price, line) in sides.items()}
            for book, sides in prices.items()}


def _row(market, line, p, prices, side="Louisville Cardinals"):
    return {"kind": "game", "segment": "full", "market": market, "line": line, "home_team": "Louisville Cardinals",
            "away_team": "Pitt Panthers", "projection": {"model_prob_over": p, "side": side, "model_skill": {"verdict": "loses"}},
            "cells": _cells(prices)}


def test_spread_is_in_the_away_frame_and_quotes_must_sit_on_the_row_line():
    # line 3.5 is the AWAY line; p is P(home covers at -3.5)
    row = _row("spreads", 3.5, 0.6, {
        "a": {"home": (-110, -3.5), "away": (-110, 3.5)},
        "b": {"home": (-105, -3.5), "away": (-115, 3.5)},
        "c": {"home": (+150, -6.5), "away": (-180, 6.5)},  # another line: another bet, never "best"
    })
    out = {r["side"]: r for r in rs.side_rows(row)}
    home, away = out["Louisville Cardinals -3.5"], out["Pitt Panthers +3.5"]
    assert home["model_prob"] == 0.6 and home["provider"] == "b" and home["price_american"] == -105
    assert away["model_prob"] == 0.4 and away["provider"] == "a"
    assert home["books_quoting"] == 2 and home["edge"] > 0 and away["stake"] == 0.0


def test_a_quote_far_from_the_market_median_is_not_the_best_price():
    row = _row("h2h", None, 0.45, {
        "a": {"home": (+120, None), "away": (-140, None)},
        "b": {"home": (+125, None), "away": (-145, None)},
        "x": {"home": (+19900, None), "away": (-200, None)},  # the measured week-6 novig quote
    })
    home = next(r for r in rs.side_rows(row) if r["side"] == "Louisville Cardinals")
    assert home["provider"] == "b" and home["price_american"] == 125


def test_one_book_is_not_a_market():
    row = _row("totals", 50.5, 0.55, {"a": {"over": (-110, 50.5), "under": (-110, 50.5)}}, side="over")
    assert rs.side_rows(row) == []


def test_build_week_writes_summary_and_index(tmp_path, monkeypatch):
    data = tmp_path / "ncaaf_source" / "data"
    (data / "book_grid").mkdir(parents=True)
    (data / "smartsim2_projections_2026_wk6.csv").write_text(
        "game_id,season,week,home_team,away_team\n1,2026,6,Louisville Cardinals,Pitt Panthers\n", encoding="utf-8")
    grid = {"rows": [_row("h2h", None, 0.6, {"a": {"home": (+110, None), "away": (-130, None)},
                                             "b": {"home": (+105, None), "away": (-125, None)}})]}
    (data / "book_grid" / "book_grid_2026-10-08.json").write_text(json.dumps(grid), encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    summary = rs.build_week(2026, 6)
    assert summary["games_with_prices"] == 1 and len(summary["results"]) == 2
    assert summary["model_skill"] == [{"market": "ML", "verdict": "loses"}]
    index = json.loads((data / "recommendations_summary" / "index.json").read_text())
    assert index["weeks"] == [{"week": 6, "season": 2026, "count": 2, "path": str(data / "recommendations_summary" / "week_6.json"),
                               "fetch": index["weeks"][0]["fetch"]}]
