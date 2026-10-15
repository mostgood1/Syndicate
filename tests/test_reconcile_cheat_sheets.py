"""Reconciled cheat sheets (user 2026-10-15: "reconcile the historical cheat sheets ... a button that toggles between
pregame sheets and reconciled sheets"): production's grader settles every prop and game line, a file beside the sheet
holds the results, the sheet itself never changes, and a failed pull never wipes results already on disk."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs

DAY = "2026-10-14"


def _script():
    spec = importlib.util.spec_from_file_location(
        "reconcile_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "reconcile_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sheet():
    return {"sport": "nhl", "date": DAY, "generated_at": "2026-10-14T20:00:00Z",
            "rows": [{"event_id": "e1", "player": "Cole Caufield", "market": "SOG", "side": "under", "line": 3.5, "check": {"price": -110}},
                     {"event_id": "e1", "player": "Cole Caufield", "market": "SOG", "side": "over", "line": 3.5, "check": {"price": 105}},
                     {"event_id": "e1", "player": "Juraj Slafkovský", "market": "ASSISTS", "side": "over", "line": 0.5, "check": {"price": 150}},
                     {"event_id": "e1", "player": "Zack Bolduc", "market": "ASSISTS", "side": "over", "line": 0.5, "check": {"price": 200}}],
            "game_lines": [{"event_id": "e1", "market": "totals", "side": "over", "line": 6.0, "check": {"price": -105}},
                           {"event_id": "e1", "market": "h2h", "side": "home", "line": None, "check": {"price": -150}}]}


GRADED = [  # what `score_ranking_backtest pull` writes: one row per graded side
    {"sport": "nhl", "market": "sog", "player": "Cole Caufield", "side": "under", "line": 3.5, "segment": "full", "y": 1.0, "game": "nhl|e1"},
    {"sport": "nhl", "market": "sog", "player": "Cole Caufield", "side": "over", "line": 3.5, "segment": "full", "y": 0.0, "game": "nhl|e1"},
    {"sport": "nhl", "market": "assists", "player": "Juraj Slafkovsky", "side": "over", "line": 0.5, "segment": "full", "y": 1.0, "game": "nhl|e1"},
    {"sport": "nhl", "market": "assists", "player": "Juraj Slafkovsky", "side": "over", "line": 0.5, "segment": "p1", "y": 0.0, "game": "nhl|e1"},
    {"sport": "nhl", "market": "totals", "player": None, "side": "over", "line": 6, "segment": "full", "y": 0.0, "game": "nhl|e1"},
    {"sport": "nhl", "market": "h2h", "player": None, "side": "home", "line": None, "segment": "full", "y": None, "game": "nhl|e1"},
]


def test_props_and_lines_match_on_the_graders_own_key():
    m = _script()
    props, lines = m.graded_index(GRADED)
    rec = m.reconcile(_sheet(), props, lines, now=__import__("datetime").datetime(2026, 10, 15, 13, 0))
    # case, accents and a 6 vs 6.0 line all agree; a period segment never stands in for the full game
    assert rec["props"][cs.prop_result_key(_sheet()["rows"][0])] == {"y": 1.0}
    assert rec["props"][cs.prop_result_key(_sheet()["rows"][2])] == {"y": 1.0}
    assert cs.prop_result_key(_sheet()["rows"][3]) not in rec["props"]                     # never graded: no result
    assert rec["lines"] == {cs.line_result_key(_sheet()["game_lines"][0]): {"y": 0.0}}      # an ungraded h2h is absent
    assert rec["counts"] == {"props": 4, "props_graded": 3, "lines": 2, "lines_graded": 1}


def test_the_page_payload_puts_a_result_and_units_on_each_bet():
    m = _script()
    props, lines = m.graded_index(GRADED)
    sheet = dict(_sheet(), reconciled=m.reconcile(_sheet(), props, lines, now=__import__("datetime").datetime(2026, 10, 15)))
    doc = cs.page_payload([sheet])["nhl"]
    assert [r["result"] for r in doc["rows"]] == [{"y": 1.0, "units": 0.909}, {"y": 0.0, "units": -1.0},
                                                   {"y": 1.0, "units": 1.5}, None]
    assert [g["result"] for g in doc["game_lines"]] == [{"y": 0.0, "units": -1.0}, None]
    assert set(doc["reconciled"]) == {"reconciled_at", "source", "counts"}                   # the page gets the summary only
    assert "result" not in cs.page_payload([_sheet()])["nhl"]["rows"][0]                     # no file -> pregame only


def test_main_writes_beside_the_sheet_merges_and_never_wipes_on_a_failed_pull(tmp_path, monkeypatch):
    m = _script()
    folder = tmp_path / "cheatsheets" / "nhl"
    folder.mkdir(parents=True)
    (folder / f"{DAY}.json").write_text(json.dumps(_sheet()), encoding="utf-8")
    calls = []

    class Grader:
        rows, code = GRADED, 0

        def main(self, argv):
            calls.append(argv)
            if self.code:
                return self.code
            out = Path(argv[argv.index("--out") + 1])
            out.write_text("\n".join(json.dumps(g) for g in self.rows), encoding="utf-8")
            return 0

    grader = Grader()
    monkeypatch.setattr(m, "_load", lambda name: grader)
    assert m.main(["--data-root", str(tmp_path), "--date", DAY]) == 0
    assert calls[0][:5] == ["pull", "--start", DAY, "--end", DAY] and "--source" in calls[0]
    target = folder / f"{DAY}.reconciled.json"
    first = json.loads(target.read_text(encoding="utf-8"))
    assert first["counts"]["props_graded"] == 3 and first["sport"] == "nhl" and first["date"] == DAY
    assert json.loads((folder / f"{DAY}.json").read_text(encoding="utf-8")) == _sheet()        # the sheet is untouched

    grader.rows = GRADED[:1]                                       # a later run that grades fewer keeps the earlier ones
    m.main(["--data-root", str(tmp_path), "--date", DAY])
    assert json.loads(target.read_text(encoding="utf-8"))["props"] == first["props"]

    grader.code = 2                                                # no ADMIN_TOKEN / web down: nothing is written
    before = target.read_bytes()
    m.main(["--data-root", str(tmp_path), "--date", DAY])
    assert target.read_bytes() == before


def test_a_future_day_is_never_reconciled(tmp_path, monkeypatch):
    m = _script()
    monkeypatch.setattr(m, "central_today", lambda: DAY)
    monkeypatch.setattr(m, "_load", lambda name: (_ for _ in ()).throw(AssertionError("no pull for a future day")))
    assert m.main(["--data-root", str(tmp_path), "--date", "2026-10-15"]) == 0


def test_nothing_settled_yet_writes_no_file(tmp_path, monkeypatch):
    m = _script()
    folder = tmp_path / "cheatsheets" / "nhl"
    folder.mkdir(parents=True)
    (folder / f"{DAY}.json").write_text(json.dumps(_sheet()), encoding="utf-8")

    class Grader:
        def main(self, argv):
            Path(argv[argv.index("--out") + 1]).write_text("", encoding="utf-8")
            return 0

    monkeypatch.setattr(m, "_load", lambda name: Grader())
    assert m.main(["--data-root", str(tmp_path), "--date", DAY]) == 0
    assert not (folder / f"{DAY}.reconciled.json").exists()          # no toggle onto a sheet of dashes
