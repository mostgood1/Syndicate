"""Every category on every scorecard (user 2026-10-19: "make sure reconciliation and tracking is happening for every
category by every sport and that the overall scorecards and scorecards by sports show all categories").

What changed:
  - Same-game parlays were graded on each reconciled day and in the paper ledger, but the season record and the
    per-sport scorecards never showed them. They now do, as paper: won-lost against what our probabilities said, no
    units, and never inside "All featured picks".
  - A scorecard listed only the categories that happened to have bets, so a category with none read like one that is
    not tracked. It now lists every category that applies to its sport, and every sport gets a scorecard.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from syndicate.app import app
from syndicate.blueprints import cheat_sheets as route
from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs

ROOT = Path(__file__).resolve().parents[1]


def _leg(player, side, line, market="SOG"):
    return {"player": player, "market": market, "side": side, "line": line, "bet": f"{player} {side} {line} {market}"}


def _day(date="2026-10-17", sport="nhl"):
    a, b, c = _leg("A Skater", "over", 1.5), _leg("B Skater", "over", 2.5), _leg("C Skater", "under", 3.5)
    rows = [dict(x, event_id="e1", check={"price": -150, "verdict": "neutral"}) for x in (a, b, c)]
    tickets = [{"sgp_id": "sgp_1", "event_id": "e1", "p_joint": 0.6, "size": 2, "family": "hit_rate", "tier": "safer", "legs": [a, b]},
               {"sgp_id": "sgp_2", "event_id": "e1", "p_joint": 0.4, "size": 2, "family": "hit_rate", "tier": "payout", "legs": [a, c]},
               {"sgp_id": "sgp_3", "event_id": "e2", "p_joint": 0.5, "size": 2, "family": "hit_rate", "tier": "safer",
                "legs": [_leg("D Nobody", "over", 0.5), _leg("E Nobody", "over", 0.5)]}]
    sheet = {"sport": sport, "date": date, "rows": rows, "sgp": tickets}
    rec = {"props": {cs.prop_result_key(rows[0]): {"y": 1.0}, cs.prop_result_key(rows[1]): {"y": 1.0},
                     cs.prop_result_key(rows[2]): {"y": 0.0}}, "lines": {}, "counts": {}}
    return sheet, rec


def test_a_days_parlays_are_tallied_as_paper_and_kept_out_of_the_featured_count():
    d = csr.day_record(*_day())
    assert d["sgp"] == {"w": 1, "l": 1, "n": 2, "win_pct": 50.0, "expected": 1.0, "expected_pct": 50.0, "pending": 1,
                        "void": 0, "paper": True}
    assert d["featured"]["n"] == 0                                 # no row was featured; parlays never count here
    assert "units" not in d["sgp"]


def test_the_season_and_each_sport_carry_the_parlays():
    rec = csr.season_record([csr.day_record(*_day()), csr.day_record(*_day("2026-10-18", "mlb"))], generated_at="x")
    off = rec["official"]
    assert off["totals"]["sgp"]["w"] == 2 and off["totals"]["sgp"]["n"] == 4 and off["totals"]["sgp"]["expected"] == 2.0
    assert off["by_sport"]["nhl"]["sgp"]["n"] == 2 and off["by_sport"]["mlb"]["sgp"]["n"] == 2
    assert rec["sections"][-1] == {"key": "sgp", "label": csr.SGP_LABEL, "paper": True}


def test_every_scorecard_names_every_category_that_applies_to_its_sport():
    rec = csr.season_record([], generated_at="x")
    assert rec["sports"] == list(cs.SPORT_ORDER)
    assert rec["applies"]["value"] == sorted(cs.SPORT_ORDER) and rec["applies"]["picks"] == sorted(cs.SPORT_ORDER)
    assert rec["applies"]["pvp_batters"] == ["mlb"] and rec["applies"]["pvp_skaters"] == ["nhl"]
    assert rec["applies"]["pvp_scorers"] == ["nba"] and rec["applies"]["pvp_qbs"] == ["nfl"]
    assert set(rec["applies"]["sgp"]) == set(csr.SGP_SPORTS)
    assert {k for k, _ in csr.FEATURED} | {"sgp"} == set(rec["applies"])


def test_the_parlay_sports_are_the_builders():
    spec = importlib.util.spec_from_file_location("build_cheat_sheets", ROOT / "scripts" / "build_cheat_sheets.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    assert set(b.SGP_SPORTS) == set(csr.SGP_SPORTS)


def test_the_page_lists_categories_with_no_bets_and_a_tab_for_every_sport(tmp_path, monkeypatch):
    monkeypatch.setattr(route, "_data_root", lambda: tmp_path)
    rec = csr.season_record([csr.day_record(*_day())], generated_at="2026-10-19T12:45:00+00:00")
    (tmp_path / "cheatsheets").mkdir()
    (tmp_path / "cheatsheets" / "record.json").write_text(json.dumps(rec), encoding="utf-8")
    page = app.test_client().get("/cheatsheets/record").get_data(as_text=True)
    assert "No bets yet" in page and "recordTable(R, totals, REC.sport)" in page and "R.sports" in page
    assert "paper, no units" in page
