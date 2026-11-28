"""The cheat-sheet scorecard (todo #862, lane cheat-sheet-optimization): it must count exactly what the season record
counts -- per bet instead of per tally, so a cell can carry an interval -- and say so against `record.json`; and it
grades each section-rules change forward on the sheets the new rules built."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc


def _script():
    spec = importlib.util.spec_from_file_location(
        "cheat_sheet_scorecard", Path(__file__).resolve().parents[1] / "scripts" / "cheat_sheet_scorecard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(player, side="under", price=-139, verdict="value", hits=9, event="e1", **extra):
    return {"event_id": event, "player": player, "market": "Receptions", "line": 2.5, "side": side, "books_quoting": 4,
            "commence_time": "2026-11-20T23:15:00Z",
            "check": {"verdict": verdict, "ev_market": 3.0 if verdict == "value" else -1.0, "price": price, "p_market": 0.6,
                      "form10": {"games": 10, "hits": hits, "rate": hits / 10}, "form5": {"games": 5, "hits": min(hits, 5)}},
            **extra}


def _line(event, market, side, value, ev):
    return {"event_id": event, "market": market, "side": side, "line": value, "commence_time": "2026-11-20T23:15:00Z",
            "check": {"verdict": "value", "ev_market": ev, "price": -110, "book": "fanduel", "p_market": 0.5}}


def _pick(pid, line, label):
    return {"pick_id": pid, "kind": "game", "event_id": "e7", "market": "totals", "side": "over", "line": line,
            "segment": "full", "price": 110, "p_market": 0.5, "label": label}


def _mixed_day(day="2026-11-20", sport="nfl", rules=None):
    """Every kind of featured bet the record counts: row sections, a row in two of them, a both-sided pair that is
    never featured, picks and price plays, a game-line value bet, and a posted row graded at its posted price."""
    rows = [_row("A"), _row("B", price=120, event="e2"), _row("C", verdict="neutral", hits=3, event="e3"),
            _row("C", side="over", verdict="neutral", hits=3, event="e3"), _row("D", price=-150, hits=8, event="e4")]
    lines = [_line("e5", "totals", "over", 44.5, 3.0), _line("e6", "h2h", "home", None, 2.5)]
    picks = [_pick("a", 47.5, "SYNDICATE PICK"), _pick("b", 48.5, "PRICE PLAY")]
    sheet = {"sport": sport, "date": day, "rows": rows, "game_lines": lines, "picks": picks}
    if rules is not None:
        sheet["section_rules"] = rules
    results = {"A": 1.0, "B": 0.0, "C": 1.0, "D": 1.0}
    rec = {"props": {cs.prop_result_key(r): {"y": results[r["player"]]} for r in rows},
           "lines": {cs.line_result_key(lines[0]): {"y": 1.0}, cs.line_result_key(lines[1]): {"y": 0.0}},
           "picks": {cs.pick_result_key(picks[0]): {"y": 1.0}, cs.pick_result_key(picks[1]): {"y": 0.5}},   # a push
           "counts": {}}
    posted = {"sport": sport, "date": day, "posts": [{"section": "consistency", "posted_at": f"{day}T17:00:00Z", "lines": [],
              "rows": [{"card_id": pc.card_id(sport, day, rows[4]), "price": -105, "book": "dk", "item": dict(rows[4])}]}]}
    return sheet, rec, posted


@pytest.mark.parametrize("rules", [None, 3, 4, 5])
def test_day_bets_counts_exactly_what_the_season_record_counts(rules):
    m = _script()
    sheet, rec, posted = _mixed_day(rules=rules)
    bets = m.day_bets(sheet, rec, posted)
    record_day = csr.day_record(sheet, rec, posted)
    assert m.check_day(bets, record_day) == []
    sections = {b["section"] for b in bets}
    # not vacuous: every kind of bet is in it (Value needs the sim's backing from v2 on), and the push is in none
    assert {"picks", "consistency", "lines_value", csr.ALL} <= sections and "price_plays" not in sections
    assert ("value" in sections) == (rules is None)
    assert record_day["sections"]["price_plays"]["n"] == 0
    # the posted row counts at its POSTED price (-105), not the sheet's (-150)
    d = next(b for b in bets if b["section"] == "consistency" and b["price"] == -105)
    assert abs(d["units"] - round(100 / 105, 3)) < 1e-9
    # "All featured picks" once a bet: under v1 A sits in value AND consistency
    a_key = cs.pick_result_key(sheet["rows"][0])
    assert sum(1 for b in bets if b["key"] == a_key and b["section"] != csr.ALL) == (2 if rules is None else 1)
    assert sum(1 for b in bets if b["key"] == a_key and b["section"] == csr.ALL) == 1


def test_check_day_names_the_section_that_differs():
    m = _script()
    sheet, rec, posted = _mixed_day()
    record_day = csr.day_record(sheet, rec, posted)
    record_day["sections"]["value"] = dict(record_day["sections"]["value"], w=record_day["sections"]["value"]["w"] + 1)
    diff = m.check_day(m.day_bets(sheet, rec, posted), record_day)
    assert len(diff) == 1 and diff[0].startswith("value: scorecard")


def _write_day(root, sheet, rec, posted=None):
    folder = root / "cheatsheets" / sheet["sport"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sheet['date']}.json").write_text(json.dumps(sheet), encoding="utf-8")
    (folder / f"{sheet['date']}.reconciled.json").write_text(json.dumps(rec), encoding="utf-8")
    if posted:
        (folder / f"{sheet['date']}{cs.POSTED_SUFFIX}").write_text(json.dumps(posted), encoding="utf-8")


def _write_record(root, days, generated_at):
    record = csr.season_record([csr.day_record(*d) for d in days], generated_at=generated_at)
    (root / "cheatsheets" / "record.json").write_text(json.dumps(record), encoding="utf-8")
    return record


def test_main_reconciles_with_the_record_and_exits_3_on_a_mismatch(tmp_path, capsys):
    m = _script()
    days = [_mixed_day("2026-11-19", "nfl", rules=3), _mixed_day("2026-11-20", "nhl", rules=4),
            _mixed_day("2026-10-10", "nfl")]                                       # beta: never in the scorecard
    for d in days:
        _write_day(tmp_path, *d)
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    _write_record(tmp_path, days, later)
    out_json = tmp_path / "sc.json"
    assert m.main(["--data-root", str(tmp_path), "--json", str(out_json), "--resamples", "50"]) == 0
    captured = capsys.readouterr()
    assert "# Cheat-sheet scorecard -- official days 2026-11-19..2026-11-20" in captured.out
    assert "2 of 2 sport-days equal" in captured.out and "record_check=2/2" in captured.err
    sc = json.loads(out_json.read_text(encoding="utf-8"))
    assert sc["scope"]["sheets"] == 2 and set(sc["versions"]) == {"v3", "v4"}
    cons = {c["rules"]: c for c in sc["by_rules"] if c["section"] == "consistency"}
    assert set(cons) == {3, 4} and cons[3]["n"] == cons[4]["n"] == 3

    rec_path = tmp_path / "cheatsheets" / "record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    day = next(d for d in record["days"] if d["sport"] == "nhl")
    day["sections"]["consistency"]["w"] += 1
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    assert m.main(["--data-root", str(tmp_path), "--resamples", "50"]) == 3
    captured = capsys.readouterr()
    assert "MISMATCH nhl 2026-11-20: consistency: scorecard" in captured.out and "MISMATCH 1" in captured.err


def test_a_day_whose_files_changed_after_the_record_is_skipped_not_failed(tmp_path, capsys):
    m = _script()
    days = [_mixed_day("2026-11-20", "nhl", rules=4)]
    _write_day(tmp_path, *days[0])
    record = _write_record(tmp_path, days, "2026-11-21T12:00:00+00:00")             # older than the files on disk
    day = record["days"][0]
    day["sections"]["consistency"]["w"] += 1                                             # would mismatch if it were checked
    (tmp_path / "cheatsheets" / "record.json").write_text(json.dumps(record), encoding="utf-8")
    assert m.main(["--data-root", str(tmp_path), "--resamples", "50"]) == 0
    out = capsys.readouterr().out
    assert "0 of 0 sport-days equal; 1 skipped (a file changed after the record was built)" in out


def _v5_rows():
    """Two Consistency rows (9 of 10), one with a one-sided fair: v4 features both, v5 only the two-sided one."""
    def row(player, verdict, event):
        return {"event_id": event, "player": player, "market": "player_points", "side": "over", "line": 20.5,
                "books_quoting": 5, "commence_time": "2026-11-28T00:10:00Z",
                "check": {"verdict": verdict, "ev_market": 0.0, "price": -110, "p_market": 0.55,
                          "form10": {"games": 10, "hits": 9, "rate": 0.9}, "form5": {"games": 5, "hits": 5, "rate": 1.0}}}
    return [row("OneSided", "one_sided_fair", "g1"), row("TwoSided", "neutral", "g2")]


def test_rule_changes_grade_what_v5_removed_on_the_sheets_v5_built(tmp_path):
    m = _script()
    rows = _v5_rows()
    assert [rows[i]["player"] for i in cs.sections(rows, rules=4)["consistency"]] == ["OneSided", "TwoSided"]
    assert [rows[i]["player"] for i in cs.sections(rows, rules=5)["consistency"]] == ["TwoSided"]
    sheet = {"sport": "nba", "date": "2026-11-28", "rows": rows, "section_rules": 5}
    rec = {"props": {cs.prop_result_key(rows[0]): {"y": 0.0}, cs.prop_result_key(rows[1]): {"y": 1.0}}, "lines": {}, "counts": {}}
    _write_day(tmp_path, sheet, rec)
    sc = m.build(tmp_path / "cheatsheets", record=None, resamples=50)
    removed = {(c["change"], c["section"], c["side"]): c for c in sc["rule_changes"]}
    cons = removed[("v4 -> v5", "consistency", "removed")]
    assert (cons["w"], cons["l"], cons["units"]) == (0, 1, -1.0)
    assert removed[("v4 -> v5", csr.ALL, "removed")]["n"] == 1                  # gone from All featured picks too
    assert not any(c["side"] == "added" for c in sc["rule_changes"])
    # the sheet's own record is v5's: TwoSided alone
    own = {(c["section"], c["rules"]): c for c in sc["by_rules"]}
    assert own[("consistency", 5)]["n"] == 1 and own[("consistency", 5)]["w"] == 1
    # a replay of v4 on the same sheet is the mirror image, and is labelled in sample
    sc = m.build(tmp_path / "cheatsheets", record=None, replay=4, resamples=50)
    rp = {(c["section"], c["side"]): c for c in sc["replay"]["rows"]}
    assert rp[("consistency", "added")]["n"] == 1 and ("consistency", "removed") not in rp
    assert "(IN SAMPLE)" in m.render(sc)


def test_a_cell_carries_an_interval_only_with_enough_bets_on_enough_games():
    m = _script()

    def bets(n, games):
        return [{"event_id": f"g{i % games}", "date": "2026-11-20", "y": float(i % 2), "units": 0.91 if i % 2 else -1.0,
                 "p_market": 0.5} for i in range(n)]
    small = m.cell(bets(20, 10), resamples=50)
    assert "roi_ci" not in small and small["verdict"] == "reading (20 bets on 10 games)"
    one_game = m.cell(bets(40, 1), resamples=50)
    assert "roi_ci" not in one_game                                             # 40 bets on one game is one draw
    big = m.cell(bets(40, 10), resamples=200)
    lo, hi = big["roi_ci"]
    assert lo < big["roi_pct"] < hi and big["excess_ci"][0] < 0 < big["excess_ci"][1]
    assert big["vs_price"] == "not separable from" and big["games"] == 10 and big["n"] == 40
    assert big["verdict"] == "within noise"
    # the verdict is the GAME interval's, not the review's per-bet z: 40 straight losses on one game stay a reading
    lost = [{"event_id": "g0", "date": "2026-11-20", "y": 0.0, "units": -1.0, "p_market": 0.5} for _ in range(40)]
    assert m.cell(lost, resamples=50)["verdict"] == "reading (40 bets on 1 games)"
    losing = m.cell([dict(b, event_id=f"g{i}") for i, b in enumerate(lost)], resamples=50)
    assert losing["verdict"] == "losing beyond noise" and losing["roi_ci"][1] < 0


def test_a_rule_change_is_graded_against_the_rules_the_sport_last_ran(tmp_path):
    # 11-13: the sheets went v1 -> v3 (v2 never built a final sheet), so a v3 sheet is compared with v1, not v2
    m = _script()
    for day, rules in (("2026-11-12", None), ("2026-11-13", 3)):
        sheet, rec, posted = _mixed_day(day, "nhl", rules=rules)
        _write_day(tmp_path, sheet, rec, posted)
    sc = m.build(tmp_path / "cheatsheets", record=None, resamples=50)
    changes = {c["change"] for c in sc["rule_changes"]}
    assert changes == {"v1 -> v3"}
    value = next(c for c in sc["rule_changes"] if c["section"] == "value")
    assert value["side"] == "removed" and value["dates"] == ["2026-11-13", "2026-11-13"]   # Value needs the sim from v2
    assert sc["rule_change_sheets"] == {"v1 -> v3": 1}
    # a change the rows cannot re-derive (v4 stored its verdict at build time) is named, not dropped
    sheet, rec, posted = _mixed_day("2026-11-25", "nhl", rules=4)
    _write_day(tmp_path, sheet, rec, posted)
    sc = m.build(tmp_path / "cheatsheets", record=None, resamples=50)
    assert sc["rule_change_sheets"] == {"v1 -> v3": 1, "v3 -> v4": 1}
    assert "No featured bet changes when these are re-derived from the same rows: v3 -> v4 (1 sheets)" in m.render(sc)
    # with no earlier sheet in scope the comparison is vN-1
    sc = m.build(tmp_path / "cheatsheets", since="2026-11-13", until="2026-11-13", record=None, resamples=50)
    assert sc["rule_change_sheets"] == {"v2 -> v3": 1}
