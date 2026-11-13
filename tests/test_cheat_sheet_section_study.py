"""The study behind section rules v2 measures the published rule: main line, the sim's side, featurable, two-sided."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs


def _script():
    spec = importlib.util.spec_from_file_location(
        "cheat_sheet_section_study", Path(__file__).resolve().parents[1] / "scripts" / "cheat_sheet_section_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(player, side, line, projected, *, price=-110, books=5, verdict="neutral", event="e1"):
    return {"player": player, "market": "player_points", "side": side, "line": line, "projected": projected,
            "books_quoting": books, "event_id": event,
            "check": {"verdict": verdict, "price": price, "p_market": 0.5, "ev_market": 0.0}}


def test_the_study_counts_only_the_published_rule_and_splits_the_fair_by_side():
    m = _script()
    rows = [_row("A", "under", 20.5, 16.0, books=8), _row("A", "over", 20.5, 16.0, books=8),       # main line, sim under
            _row("A", "under", 18.5, 16.0, books=2),                                                  # an alt rung: not main
            _row("B", "over", 10.5, 11.0),                                                            # 4.8%: under the bar
            _row("C", "over", 5.5, 9.0, price=300, event="e2"),                                       # outside the band
            _row("D", "over", 5.5, 9.0, verdict="one_sided_fair", event="e2")]                        # one-sided
    results = (1.0, 0.0, 1.0, 1.0, 1.0, 0.0)
    rec = {"props": {cs.prop_result_key(r): {"y": y} for r, y in zip(rows, results)}}
    out = m.study([({"sport": "nba", "date": "2026-11-01", "rows": rows}, rec)], start="2026-10-15", end=None)
    sim = out["sim_edge"]["nba"]
    assert sim["roi"]["n"] == 1 and sim["roi"]["mean_pct"] == round(100 * (100 / 110), 1)   # A under at -110, won
    lean = out["fair_lean"]["nba"]
    assert lean["over"]["n"] == 3 and lean["under"]["n"] == 2                                 # the one-sided row is out
    assert m.study([({"sport": "nba", "date": "2026-10-14", "rows": rows}, rec)], start="2026-10-15", end=None)["rows"] == 0
