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
    props, lines, _picks = m.graded_index(GRADED)
    rec = m.reconcile(_sheet(), props, lines, now=__import__("datetime").datetime(2026, 10, 15, 13, 0))
    # case, accents and a 6 vs 6.0 line all agree; a period segment never stands in for the full game
    assert rec["props"][cs.prop_result_key(_sheet()["rows"][0])] == {"y": 1.0}
    assert rec["props"][cs.prop_result_key(_sheet()["rows"][2])] == {"y": 1.0}
    assert cs.prop_result_key(_sheet()["rows"][3]) not in rec["props"]                     # never graded: no result
    assert rec["lines"] == {cs.line_result_key(_sheet()["game_lines"][0]): {"y": 0.0}}      # an ungraded h2h is absent
    assert rec["counts"] == {"props": 4, "props_graded": 3, "props_valued": 0, "props_from_actual": 0, "lines": 2, "lines_graded": 1,
                             "picks": 0, "picks_graded": 0}


def test_the_page_payload_puts_a_result_and_units_on_each_bet():
    m = _script()
    props, lines, _picks = m.graded_index(GRADED)
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
    record = json.loads((tmp_path / "cheatsheets" / "record.json").read_text(encoding="utf-8"))  # the season record follows
    assert record["beta"]["days"] == 1 and record["days"][0]["sport"] == "nhl"

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


def test_the_value_tap_reads_the_number_each_settler_graded_on_and_changes_nothing():
    # User 2026-10-15: "add the actual stat line too". The value must be the one the RESULT was decided on, so it is
    # read from production's own comparisons -- wrapped for one pull, in this process only, results untouched.
    m = _script()
    from syndicate.features.mlb import prop_outcomes
    from syndicate.features.shared import population_outcomes as po
    from syndicate.features.shared import population_outcomes_espn as espn
    from syndicate.features.shared import population_outcomes_mlb as mlbm
    from syndicate.features.shared import population_outcomes_soccer as soccer

    def fake(shaped, view):                         # stands in for the real settlers, calling the same module functions
        market = shaped["market"]
        if market == "receptions":
            return espn.resolve_bet_status(market="receptions", side=shaped["side"], line=shaped["line"], current_value=6.0, is_final=True)
        if market == "player_shots":
            return soccer.settle_over_under(3.0, shaped["side"], shaped["line"])
        if market == "batter_hits":
            return prop_outcomes.settle_prop(shaped["side"], shaped["line"], 2)
        return mlbm.settle_runs(market, shaped["side"], shaped["line"], 4, 5)

    composite = po.CompositeSettler([("fake", fake, "1")])
    rows = [{"sport": "nfl", "event_id": "e1", "market": "receptions", "side": "over", "line": 4.5, "player_name": "Courtland Sutton"},
            {"sport": "soccer", "event_id": "e2", "market": "player_shots", "side": "over", "line": 2.5, "player_name": "Agustín Bouzat"},
            {"sport": "mlb", "event_id": "e3", "market": "batter_hits", "side": "under", "line": 0.5, "player_name": "Andy Pages"},
            {"sport": "mlb", "event_id": "e3", "market": "totals", "side": "over", "line": 8.5, "player_name": None},
            {"sport": "mlb", "event_id": "e3", "market": "spreads", "side": "home", "line": -1.5, "player_name": None}]
    plain = [composite(r, {}) for r in rows]
    originals = (espn.resolve_bet_status, soccer.settle_over_under, prop_outcomes.settle_prop, mlbm.settle_runs,
                 po.CompositeSettler.__call__, prop_outcomes.MlbPropGrader.settle)
    with m.ValueTap() as tap:
        assert [composite(r, {}) for r in rows] == plain                         # every result unchanged
    assert tap.missing == []                                                     # every hook found its target
    assert (espn.resolve_bet_status, soccer.settle_over_under, prop_outcomes.settle_prop, mlbm.settle_runs,
            po.CompositeSettler.__call__, prop_outcomes.MlbPropGrader.settle) == originals   # and put back
    key = cs.pick_result_key
    assert [tap.values[key(r)]["v"] for r in rows[:3]] == [6.0, 3.0, 2.0]
    assert tap.values[cs.pick_result_key(rows[3])] == {"v": 9.0}         # a total: the combined score
    assert cs.pick_result_key(rows[4]) not in tap.values                   # a spread is graded on a margin: no "actual"


def test_values_ride_the_index_the_merge_and_the_page():
    m = _script()
    sheet = _sheet()
    k0 = cs.prop_result_key(sheet["rows"][0])
    props, lines, _picks = m.graded_index(GRADED, {cs.pick_result_key(sheet["rows"][0]): {"v": 2.0},
                                                    cs.pick_result_key(sheet["game_lines"][0]): {"v": 5.0}})
    assert props[k0] == {"y": 1.0, "v": 2.0} and lines[cs.line_result_key(sheet["game_lines"][0])] == {"y": 0.0, "v": 5.0}
    assert m.merge_results({k0: {"y": 1.0, "v": 2.0}}, {k0: {"y": 1.0}}) == {k0: {"y": 1.0, "v": 2.0}}   # a value is never lost
    doc = cs.page_payload([dict(sheet, reconciled=m.reconcile(sheet, props, lines, now=__import__("datetime").datetime(2026, 10, 15)))])["nhl"]
    assert doc["rows"][0]["result"] == {"y": 1.0, "units": 0.909, "v": 2.0}
    assert doc["game_lines"][0]["result"] == {"y": 0.0, "units": -1.0, "v": 5.0}
    assert m.reconcile(sheet, props, lines, now=__import__("datetime").datetime(2026, 10, 15))["counts"]["props_valued"] == 1


def test_a_bet_with_no_result_says_why_and_each_game_carries_its_final():
    # User 2026-10-15: "some of the section reconciles are missing for 10-14" -- a bare dash explained nothing.
    m = _script()
    from syndicate.features.shared import game_line_bet
    from syndicate.features.shared import population_outcomes as po
    from syndicate.features.shared import population_outcomes_soccer as soccer

    def fake(shaped, view):
        if shaped["market"] == "assists":
            return None, "nhl_player_name_unmatched"
        if shaped["market"] == "player_goal_scorer_anytime":
            soccer.qualifying_goals({"score_home": 2, "score_away": 1, "goals": []})
            return None, "dnp_void"
        return game_line_bet.game_line_view(sport="nhl", market="h2h", side="home", line=None, home_team="WSH", away_team="MTL",
                                            home_score=4, away_score=2, draw_possible=False) and ("win", "nhl_api")

    rows = [{"sport": "nhl", "event_id": "e1", "market": "assists", "side": "over", "line": 0.5, "player_name": "Zack Bolduc"},
            {"sport": "soccer", "event_id": "e9", "market": "player_goal_scorer_anytime", "side": "yes", "line": None, "player_name": "Sam Williams"},
            {"sport": "nhl", "event_id": "e1", "market": "h2h", "side": "home", "line": None, "player_name": None, "segment": "full"}]
    with m.ValueTap() as tap:
        for r in rows:
            po.CompositeSettler([("fake", fake, "1")])(r, {})
    assert tap.reasons[cs.pick_result_key({"player_name": "Zack Bolduc", "market": "assists", "side": "over", "line": 0.5})] == "nhl_player_name_unmatched"
    assert tap.scores == {"e9": {"home": 2.0, "away": 1.0}, "e1": {"home": 4.0, "away": 2.0}}
    sheet = dict(_sheet(), games=[{"event_id": "e1", "home_team": "WSH", "away_team": "MTL"}])
    props, lines, _picks = m.graded_index(GRADED)
    rec = m.reconcile(sheet, props, lines, now=__import__("datetime").datetime(2026, 10, 15), reasons=tap.reasons, scores=tap.scores)
    assert rec["void"] == {cs.prop_result_key(sheet["rows"][3]): "nhl_player_name_unmatched"} and rec["scores"] == {"e1": {"home": 4.0, "away": 2.0}}
    doc = cs.page_payload([dict(sheet, reconciled=rec)])["nhl"]
    assert doc["rows"][3]["result"] is None and doc["rows"][3]["result_note"] == "Not in the box score"
    assert doc["games"][0]["final"] == {"home": 4.0, "away": 2.0}
    assert [cs.void_label(r) for r in ("push", "extra_dnp_void", "player_not_in_box", "game_not_final", "odd")] == [
        "Push", "Void: did not play", "Not in the box score", "Not final", "Not gradeable"]



def test_syndicate_picks_grade_on_their_segment_and_say_why_when_they_cannot():
    # User 2026-10-15: the board's suggested opps are the sheet's picks -- a 1st-3-innings moneyline grades on that
    # segment, never on the full game.
    m = _script()
    graded = [{"sport": "mlb", "market": "h2h", "player": None, "side": "away", "line": None, "segment": "first3", "y": 1.0, "game": "mlb|e7"},
              {"sport": "mlb", "market": "h2h", "player": None, "side": "away", "line": None, "segment": "full", "y": 0.0, "game": "mlb|e7"},
              {"sport": "mlb", "market": "strikeouts", "player": "Griffin Jax", "side": "over", "line": 3.5, "segment": "full", "y": 1.0, "game": "mlb|e8"}]
    picks = [{"pick_id": "l2_aaaaaaaa", "kind": "game", "event_id": "e7", "market": "h2h", "side": "away", "line": None, "segment": "first3", "price": 138},
             {"pick_id": "l2_bbbbbbbb", "kind": "prop", "event_id": "e8", "player_name": "Griffin Jax", "market": "strikeouts", "side": "over",
              "line": 3.5, "segment": "full", "price": 108},
             {"pick_id": "l2_cccccccc", "kind": "prop", "event_id": "e8", "player_name": "Nobody", "market": "strikeouts", "side": "over",
              "line": 3.5, "segment": "full", "price": 100}]
    sheet = {"sport": "mlb", "date": DAY, "rows": [], "picks": picks}
    props, lines, pick_results = m.graded_index(graded, {cs.pick_result_key(picks[1]): {"v": 5.0}})
    reasons = {cs.pick_result_key(picks[2]): "player_not_in_box"}
    rec = m.reconcile(sheet, props, lines, now=__import__("datetime").datetime(2026, 10, 15), reasons=reasons, picks=pick_results)
    assert rec["picks"][cs.pick_result_key(picks[0])] == {"y": 1.0}                 # the segment's result, not the full game's
    assert rec["picks"][cs.pick_result_key(picks[1])] == {"y": 1.0, "v": 5.0}
    assert rec["picks_void"] == {cs.pick_result_key(picks[2]): "player_not_in_box"}
    assert rec["counts"]["picks"] == 3 and rec["counts"]["picks_graded"] == 2
    doc = cs.page_payload([dict(sheet, reconciled=rec)])["mlb"]
    assert [p.get("result") for p in doc["picks"]] == [{"y": 1.0, "units": 1.38}, {"y": 1.0, "units": 1.08, "v": 5.0}, None]
    assert doc["picks"][2]["result_note"] == "Not in the box score"
