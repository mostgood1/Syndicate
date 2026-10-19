"""Every featured bet gets a result (user 2026-10-19: "make sure reconciliation and tracking is happening for every
category by every sport"). Measured that day on the fleet:
  - 33 NCAAF featured props on 10-15 / 10-16 were still open; re-pulling settled none, because the recorder never held
    those lines. The same player's stat was known from the lines it did hold.
  - 15 NBA preseason price plays were never graded; their sheets held picks and no prop rows, and the reconcile
    skipped them.
  - A result that lands after a day leaves the 2-day window was dropped for good.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs


def _script():
    spec = importlib.util.spec_from_file_location(
        "reconcile_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "reconcile_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(player, side, line, event="e1", market="Receiving Yards", verdict="value"):
    return {"event_id": event, "player": player, "market": market, "side": side, "line": line,
            "check": {"price": -110, "verdict": verdict, "ev_market": 3.0,
                      "form10": {"games": 10, "hits": 8, "rate": 0.8}, "form5": {"games": 5, "hits": 4}}}


GRADED = [{"sport": "ncaaf", "market": "receiving yards", "player": "Jackson Harper", "side": "over", "line": 40.5,
           "segment": "full", "y": 1.0, "game": "ncaaf|e1"}]


def test_a_line_the_grader_never_held_is_graded_from_the_players_actual_stat():
    m = _script()
    values = {cs.pick_result_key(m._graded_shape(GRADED[0])): {"v": 52.0}}
    actuals = m.actuals_index(GRADED, values)
    assert list(actuals.values()) == [52.0] and [k[1:] for k in actuals] == [("receiving yards", "e1")]
    rows = [_row("Jackson Harper", "over", 35.5), _row("Jackson Harper", "under", 60.5), _row("Jackson Harper", "over", 52.0),
            _row("Jackson Harper", "over", 40.5)]
    props, lines, _ = m.graded_index(GRADED, values)
    rec = m.reconcile({"sport": "ncaaf", "date": "2026-10-15", "rows": rows}, props, lines,
                      now=datetime(2026, 10, 19), actuals=actuals)
    got = rec["props"]
    assert got[cs.prop_result_key(rows[0])] == {"y": 1.0, "v": 52.0, "by": "actual"}       # 52 clears 35.5
    assert got[cs.prop_result_key(rows[1])] == {"y": 1.0, "v": 52.0, "by": "actual"}       # and stays under 60.5
    assert rec["void"][cs.prop_result_key(rows[2])] == "push"                              # 52 on 52: a push
    assert got[cs.prop_result_key(rows[3])] == {"y": 1.0, "v": 52.0}                        # the grader's own result wins
    assert rec["counts"]["props_from_actual"] == 2


def test_the_actual_is_read_only_for_the_same_game():
    m = _script()
    values = {cs.pick_result_key(m._graded_shape(GRADED[0])): {"v": 52.0}}
    rows = [_row("Jackson Harper", "over", 35.5, event="e2")]
    rec = m.reconcile({"sport": "ncaaf", "date": "2026-10-15", "rows": rows}, {}, {}, now=datetime(2026, 10, 19),
                      actuals=m.actuals_index(GRADED, values))
    assert rec["props"] == {}                                                              # e2's stat is not e1's


def test_a_sheet_of_picks_alone_is_reconciled(tmp_path, monkeypatch):
    m = _script()
    day = "2026-10-16"
    folder = tmp_path / "cheatsheets" / "nba"
    folder.mkdir(parents=True)
    pick = {"event_id": "g1", "market": "h2h", "side": "home", "line": None, "segment": "full", "price": 165,
            "label": "PRICE PLAY", "home_team": "Minnesota Timberwolves", "away_team": "X"}
    (folder / f"{day}.json").write_text(json.dumps({"sport": "nba", "date": day, "rows": [], "picks": [pick]}), encoding="utf-8")
    graded = [{"sport": "nba", "market": "h2h", "player": None, "side": "home", "line": None, "segment": "full", "y": 1.0,
               "game": "nba|g1"}]

    class Grader:
        def main(self, argv):
            Path(argv[argv.index("--out") + 1]).write_text("\n".join(json.dumps(g) for g in graded), encoding="utf-8")
            return 0

    monkeypatch.setattr(m, "_load", lambda name: Grader())
    assert m.main(["--data-root", str(tmp_path), "--date", day]) == 0
    rec = json.loads((folder / f"{day}.reconciled.json").read_text(encoding="utf-8"))
    assert rec["picks"] == {cs.pick_result_key(pick): {"y": 1.0}}


def test_days_past_the_window_with_an_open_featured_bet_are_caught_up(tmp_path):
    m = _script()
    sheets = tmp_path / "cheatsheets"
    (sheets / "ncaaf").mkdir(parents=True)
    open_row, done_row = _row("Open Guy", "over", 35.5), _row("Done Guy", "over", 35.5, event="e3")
    days = {"2026-10-14": [open_row], "2026-10-15": [done_row], "2026-10-11": [open_row], "2026-10-17": [open_row]}
    for day, rows in days.items():
        (sheets / "ncaaf" / f"{day}.json").write_text(json.dumps({"sport": "ncaaf", "date": day, "rows": rows}), encoding="utf-8")
    (sheets / "ncaaf" / "2026-10-15.reconciled.json").write_text(
        json.dumps({"props": {cs.prop_result_key(done_row): {"y": 0.0}}}), encoding="utf-8")
    # today 10-19: the regular window is 10-17..10-19; the catch-up looks at 10-12..10-16
    assert m.catchup_days(sheets, "2026-10-19") == ["2026-10-14"]
    assert m.open_featured({"rows": [open_row]}, {"void": {cs.prop_result_key(open_row): "dnp_void"}}) == 0   # a reason closes it
