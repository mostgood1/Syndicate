"""Sheet props the recorder never held, graded from the box by the production settler (lane `cheat-sheets`, 2026-10-21).

NCAAF 10-20: 47 of 147 sheet props were neither graded nor voided -- 35 from Missouri State @ Delaware, every player in
ESPN's box. The population grader settles only what the recorder captured, and `actuals_index` only knows players graded
at some other line. `settle_open_props` sends each still-open prop through the settler every pull uses.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reconcile_cheat_sheets_box", ROOT / "scripts" / "reconcile_cheat_sheets.py")
rec_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec_mod)
cs = rec_mod.cs

GAME = {"event_id": "dc65", "home_team": "Delaware Blue Hens", "away_team": "Missouri State Bears",
        "commence_time": "2026-10-20T23:00:00Z"}


def _row(player, market, side, line):
    return {"player": player, "market": market, "side": side, "line": line, "event_id": "dc65",
            "commence_time": "2026-10-20T23:00:00Z", "team": "Delaware"}


def _sheet(rows, sport="ncaaf"):
    return {"sport": sport, "date": "2026-10-20", "games": [GAME], "rows": rows}


class FakeSettler:
    """Stands in for the composite; records what it was asked, answers per player."""

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, shaped, view):
        self.seen.append(dict(shaped))
        return self.answers.get(shaped["player_name"])


def test_open_props_are_graded_from_the_box_with_the_game_identity_the_settler_joins_on():
    rows = [_row("Bryson Graves", "Receptions", "over", 2.5), _row("Donovan Lewis", "Receptions", "under", 3.5),
            _row("Camron Lacy", "Receptions", "over", 5.5)]
    rec = {"props": {cs.prop_result_key(rows[2]): {"y": 1.0}}, "void": {}, "counts": {"props": 3, "props_graded": 1}}
    settler = FakeSettler({"Bryson Graves": ("win", None), "Donovan Lewis": ("loss", None)})
    values = {cs.pick_result_key({"player_name": "Bryson Graves", "market": "Receptions", "side": "over", "line": 2.5,
                                  "segment": "full"}): {"v": 4.0}}
    assert rec_mod.settle_open_props(_sheet(rows), rec, settler, values) == 2
    assert [s["player_name"] for s in settler.seen] == ["Bryson Graves", "Donovan Lewis"]      # graded one never re-asked
    asked = settler.seen[0]
    assert (asked["home_team"], asked["away_team"], asked["commence_time"], asked["segment"]) == (
        "Delaware Blue Hens", "Missouri State Bears", "2026-10-20T23:00:00Z", "full")
    assert rec["props"][cs.prop_result_key(rows[0])] == {"y": 1.0, "by": "box", "v": 4.0}
    assert rec["props"][cs.prop_result_key(rows[1])] == {"y": 0.0, "by": "box"}
    assert rec["counts"]["props_graded"] == 3 and rec["counts"]["props_from_box"] == 2


def test_a_final_reason_voids_and_a_transient_one_leaves_the_prop_open():
    rows = [_row("Koraun Perdue", "Receiving Yards", "over", 15.5), _row("Late Game", "Receptions", "over", 1.5),
            _row("Push Guy", "Receptions", "over", 3.0)]
    rec = {"props": {}, "void": {}, "counts": {"props": 3, "props_graded": 0}}
    settler = FakeSettler({"Koraun Perdue": (None, "player_absent_unverifiable"), "Late Game": (None, "game_not_final"),
                           "Push Guy": ("push", None)})
    assert rec_mod.settle_open_props(_sheet(rows), rec, settler, {}) == 0
    assert rec["void"] == {cs.prop_result_key(rows[0]): "player_absent_unverifiable", cs.prop_result_key(rows[2]): "push"}
    assert cs.prop_result_key(rows[1]) not in rec["void"]                                      # next run retries it


def test_only_espn_settled_sports_take_the_box_pass():
    rows = [_row("Some Skater", "player_points", "over", 0.5)]
    rec = {"props": {}, "void": {}, "counts": {}}
    settler = FakeSettler({"Some Skater": ("win", None)})
    assert rec_mod.settle_open_props(_sheet(rows, sport="nhl"), rec, settler, {}) == 0 and settler.seen == []


def test_main_runs_the_box_pass_with_the_production_settler_under_the_value_tap():
    source = (ROOT / "scripts" / "reconcile_cheat_sheets.py").read_text(encoding="utf-8")
    body = source[source.index("def main("):]
    assert "build_extra_settler(cache_dir=cache / \"settlers\")" in body
    assert "with ValueTap() as box_tap:" in body and "settle_open_props(doc, rec, box_settler, box_tap.values)" in body
    assert body.index("settle_open_props(") < body.index("write_atomic(target, rec)")
