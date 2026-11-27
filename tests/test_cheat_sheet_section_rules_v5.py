"""Cheat-sheet section rules v5 (todo #862, user 2026-11-27 "Build proposals 1-3 as v5 rules").

Every rule is pinned against rules v4 on the same rows (off != on), and the build's stamp is driven through `main`, so
a rule that never reaches a sheet fails here. Evidence: .syndicate/findings_2026-11-27_cheat_sheet_optimization.md.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs


def _row(player, side="over", line=20.5, *, projected=None, verdict="neutral", ev=0.0, price=-110, market="player_points",
         books=5, form10=(10, 5), **extra):
    f5 = {"games": 5, "hits": min(5, form10[1]), "rate": min(5, form10[1]) / 5}
    f10 = {"games": form10[0], "hits": form10[1], "rate": form10[1] / form10[0]}
    return {"player": player, "market": market, "side": side, "line": line, "projected": projected, "books_quoting": books,
            "check": {"verdict": verdict, "ev_market": ev, "price": price, "form5": f5, "form10": f10}} | extra


def test_the_current_version_is_5():
    assert cs.SECTION_RULES == 5 and cs.RETIRED_IN_V5 == ("pvp_skaters", "pvp_receivers")


def test_v5_never_features_a_one_sided_fair_and_v4_did():
    strong = {"games": 4, "hits": 4, "same_line": True}
    rows = [_row("OneCons", form10=(10, 9), verdict="one_sided_fair"),
            _row("TwoCons", form10=(10, 9)),
            _row("OneMatch", vs_opponent=strong, verdict="one_sided_fair"),
            _row("TwoMatch", vs_opponent=strong),
            _row("OneScorer", verdict="one_sided_fair",
                 pvp={"kind": "scorer_vs_defenders", "line": {"poss": 80, "pts_per_100": 33.0, "overall_pts_per_100": 28.0}}),
            _row("OneShop", verdict="one_sided_fair", shop={"gap_pp": 4.0})]
    names = lambda s, key: {rows[i]["player"] for i in s[key]}
    v4, v5 = cs.sections(rows, rules=4), cs.sections(rows, rules=5)
    assert names(v4, "consistency") == {"OneCons", "TwoCons"} and names(v5, "consistency") == {"TwoCons"}
    assert names(v4, "matchup_spots") == {"OneMatch", "TwoMatch"} and names(v5, "matchup_spots") == {"TwoMatch"}
    assert names(v4, "pvp_scorers") == {"OneScorer"} and v5["pvp_scorers"] == []
    # a price comparison, not a pick: Price shopping keeps it; Every prop keeps every row
    assert names(v5, "shop_gaps") == names(v4, "shop_gaps") == {"OneShop"}
    assert sorted(v5["every_prop"]) == list(range(len(rows)))
    featured = {rows[i]["player"] for k, ids in v5.items() if k not in ("every_prop", "shop_gaps") for i in ids}
    assert not any(rows[i]["check"]["verdict"] == "one_sided_fair" for k, ids in v5.items()
                   if k not in ("every_prop", "shop_gaps") for i in ids), featured


def test_a_v1_day_keeps_hot_form_which_was_one_sided_by_design():
    hot = _row("Shooter", "over", 0.5, verdict="one_sided_fair", price=120, market="player_shots", form10=(10, 9))
    assert cs.sections([hot], rules=1)["hot_form"] == [0]


def test_v5_retires_skater_vs_goalie_and_defenders_on_his_targets():
    rows = [_row("Shooter", "over", 2.5, market="SOG", pvp={"kind": "skater_vs_goalie", "line": {"games": 4, "sog": 14, "goals": 0}}),
            _row("Catcher", "over", 48.5, market="Receiving Yards",
                 pvp={"kind": "receiver_vs_defenders", "line": {"plays": 8, "catches": 7, "pbu": 0, "int": 0}}),
            _row("Keeper", "under", 24.5, market="SAVES", pvp={"kind": "goalie_vs_team", "line": {"games": 3, "saves": 66}})]
    v4, v5 = cs.sections(rows, rules=4), cs.sections(rows, rules=5)
    assert v4["pvp_skaters"] == [0] and v5["pvp_skaters"] == []
    assert v4["pvp_receivers"] == [1] and v5["pvp_receivers"] == []
    assert v4["pvp_goalies"] == v5["pvp_goalies"] == [2]                     # only the two retired sections change
    assert all(r.get("pvp") for r in rows)                                    # the rows keep their history
    rec = csr.season_record([], generated_at="2026-11-28T12:00:00+00:00")
    label = {s["key"]: s["label"] for s in rec["sections"]}
    assert label["pvp_skaters"] == "Skater vs goalie (retired 11/28)"
    assert label["pvp_receivers"] == "Defenders on his targets (retired 11/28)"
    assert rec["applies"]["pvp_skaters"] == [] and rec["applies"]["pvp_receivers"] == []
    assert rec["applies"]["pvp_goalies"] == ["nhl"]


def _record(**by_sport):
    return {"generated_at": "2026-11-27T12:55:37+00:00",
            "official": {"by_sport": {s: {"sim_edge": t} for s, t in by_sport.items()}},
            "days": [{"date": "2026-11-13", "sport": "nba", "beta": False, "sections": {"sim_edge": {}}},
                     {"date": "2026-11-25", "sport": "nba", "beta": False, "sections": {"sim_edge": {}}},
                     {"date": "2026-11-26", "sport": "nba", "beta": False, "sections": {"value": {}}},   # no sim_edge that day
                     {"date": "2026-11-10", "sport": "nba", "beta": True, "sections": {"sim_edge": {}}}]}  # beta: not official


def test_sim_vs_the_line_since_launch_reads_the_official_record():
    rec = _record(nba={"w": 162, "l": 153, "n": 315, "units": -13.49, "win_pct": 51.4, "roi_pct": -4.3},
                  nhl={"w": 0, "l": 0, "n": 0, "units": 0.0})
    got = cs.sim_edge_since_launch(rec, "NBA")
    assert got == {"n": 315, "w": 162, "l": 153, "units": -13.49, "roi_pct": -4.3, "from": "2026-11-13",
                   "through": "2026-11-25", "record_at": "2026-11-27T12:55:37+00:00"}
    assert cs.sim_edge_since_launch(rec, "nhl") is None and cs.sim_edge_since_launch(rec, "nfl") is None
    assert cs.sim_edge_since_launch(None, "nba") is None and cs.sim_edge_since_launch({"official": []}, "nba") is None
    text = cs.sim_edge_measured_text("nba", since=got)
    assert "1,251 bets, ROI +8.0%" in text                                   # the pre-launch line stays
    assert ("Since launch, official sheets Nov 13 - Nov 25: 315 bets (162-153), ROI -4.3% at the best price -- it has "
            "not beaten the price since launch.") in text
    assert cs.sim_edge_measured_text("nba") == cs.sim_edge_measured_text("nba", since=None) and "Since launch" not in cs.sim_edge_measured_text("nba")
    win = cs.sim_edge_measured_text("nhl", since=dict(got, roi_pct=3.1))
    assert "ROI +3.1% at the best price." in win and "not beaten the price since launch" not in win


def test_the_page_prints_the_since_launch_record_only_under_v5():
    rows = [_row("Big", "under", projected=16.0, event_id="e"), _row("Big", "over", projected=16.0, event_id="e")]
    since = {"n": 315, "w": 162, "l": 153, "units": -13.49, "roi_pct": -4.3, "from": "2026-11-13", "through": "2026-11-26"}
    v5 = cs.page_payload([{"sport": "nba", "date": "2026-11-28", "rows": rows, "games": [], "section_rules": 5,
                           "sim_edge_record": since}])["nba"]
    v4 = cs.page_payload([{"sport": "nba", "date": "2026-11-27", "rows": rows, "games": [], "section_rules": 4,
                           "sim_edge_record": since}])["nba"]
    assert "Since launch, official sheets Nov 13 - Nov 26: 315 bets" in v5["sim_edge_measured"]
    assert "Since launch" not in v4["sim_edge_measured"] and "1,251 bets" in v4["sim_edge_measured"]
    assert v5["section_rules"] == 5 and v5["sections"]["sim_edge"] == [0]


def _script():
    spec = importlib.util.spec_from_file_location(
        "build_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_day_keeps_its_rules_once_a_game_on_it_has_started():
    from datetime import datetime, timezone
    m = _script()
    now = datetime(2026, 11, 27, 21, 0, tzinfo=timezone.utc)
    later = {"section_rules": 4, "rows": [{"commence_time": "2026-11-28T00:30:00Z"}], "games": []}
    begun = {"section_rules": 4, "rows": [{"commence_time": "2026-11-28T00:30:00Z"}],
             "games": [{"commence_time": "2026-11-27T20:00:00Z"}]}
    unreadable = {"section_rules": 4, "rows": [{"commence_time": "soon"}], "games": []}
    assert m.build_rules(None, now=now) == m.build_rules({}, now=now) == 5
    assert m.build_rules(later, now=now) == 5                       # nothing started: the day takes v5
    assert m.build_rules(begun, now=now) == 4                       # a game started: the day keeps v4
    assert m.build_rules(unreadable, now=now) == 4                  # an unreadable start counts as started


def _unset_data_root_until_teardown(monkeypatch):
    # `align_data_root` (reached through `main`) WRITES the variable; see test_build_cheat_sheets (todo #697).
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", "set-by-test")
    monkeypatch.delenv("SYNDICATE_DATA_ROOT")


@pytest.mark.parametrize("prior_start,want", [(None, 5), ("2026-11-27T20:00:00Z", 4)])
def test_the_build_stamps_v5_and_the_since_launch_record_unless_the_day_has_begun(monkeypatch, capsys, tmp_path,
                                                                                 prior_start, want):
    # Reachability (off != on through `main`): the stamp and the record are what every reader re-derives a day under.
    _unset_data_root_until_teardown(monkeypatch)
    m = _script()
    from datetime import datetime as real_dt, timezone
    import syndicate.features.shared.interval_history as ih
    import syndicate.features.shared.layer2_row_context as rc

    class Fixed(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 11, 27, 21, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(m, "datetime", Fixed)
    monkeypatch.setattr(m, "central_today", lambda: "2026-11-27")
    monkeypatch.setattr(m, "latest_nfl_dvp", lambda root: {})
    monkeypatch.setattr(m, "_position_indexes", lambda: {})
    monkeypatch.setattr(m, "fetch_board_cards", lambda base: [])
    monkeypatch.setattr(ih.IntervalHistory, "warm", lambda self, sport, day: 0)
    monkeypatch.setattr(rc, "load_layer2_row_context", lambda day: {})
    real_steady = m.steady_rows
    monkeypatch.setattr(m, "steady_rows", lambda *a, **k: real_steady(*a, **dict(k, sleep=lambda s: None)))
    rows = [{"kind": "prop", "game_state": "pregame", "segment": "full", "event_id": "e1", "player_name": f"P{i}",
             "market": "Receptions", "commence_time": "2026-11-28T00:15:00Z"} for i in range(2)]
    monkeypatch.setattr(m, "fetch_rows", lambda base, sport, day=None: list(rows))
    sheets = tmp_path / "cheatsheets"
    (sheets / "nfl").mkdir(parents=True)
    (sheets / "record.json").write_text(json.dumps(_record(nfl={"w": 80, "l": 79, "n": 159, "units": -10.55,
                                                                "roi_pct": -6.6})), encoding="utf-8")
    target = sheets / "nfl" / "2026-11-27.json"
    if prior_start:
        target.write_text(json.dumps({"date": "2026-11-27", "generated_at": "2026-11-27T17:30:00Z", "section_rules": 4,
                                      "games": [], "sections": {},
                                      "rows": [{"event_id": "e0", "player": "Q", "market": "Receptions", "line": 4.5,
                                                "side": "over", "commence_time": prior_start}]}), encoding="utf-8")
    m.main(["--data-root", str(tmp_path), "--date", "2026-11-27", "--sports", "nfl", "--base-url", "http://127.0.0.1:9"])
    out = capsys.readouterr().out
    sheet = json.loads(target.read_text(encoding="utf-8"))
    assert sheet["section_rules"] == want
    if want == 5:
        assert sheet["sim_edge_record"]["n"] == 159 and sheet["sim_edge_record"]["roi_pct"] == -6.6
        assert "keeps section rules" not in out
    else:
        assert "sim_edge_record" not in sheet
        assert "CHEAT_SHEET nfl date=2026-11-27 keeps section rules v4 (a game on it has started; current v5)" in out
