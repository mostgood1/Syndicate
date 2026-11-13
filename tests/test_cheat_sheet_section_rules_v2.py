"""Cheat-sheet section rules v2 (lane cheat-sheet-section-optimization, user 2026-11-13).

Every rule is pinned against rules v1 on the same rows (off != on): a rule that never fires passes nothing here.
Evidence: .syndicate/findings_2026-11-13_cheat_sheet_section_assessment.md.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import cheat_sheet_record as csr
from syndicate.features.shared import cheat_sheets as cs


def _row(player, side="over", line=20.5, *, projected=None, verdict="neutral", ev=0.0, price=-110, market="player_points",
         books=5, **extra):
    f = {"games": 10, "hits": 5, "rate": 0.5}
    return {"player": player, "market": market, "side": side, "line": line, "projected": projected, "books_quoting": books,
            "check": {"verdict": verdict, "ev_market": ev, "price": price, "form5": f, "form10": f}} | extra


def test_sim_edge_is_the_projection_beyond_the_line_toward_the_side():
    assert cs.sim_edge(_row("A", "over", 20.0, projected=22.0)) == pytest.approx(0.10)
    assert cs.sim_edge(_row("A", "under", 20.0, projected=22.0)) == pytest.approx(-0.10)
    assert cs.sim_edge(_row("A", "under", 0.5, projected=0.2)) == pytest.approx(0.30)    # a line under 1 counts as 1
    assert cs.sim_edge(_row("A", "yes", 0.5, projected=0.8)) == pytest.approx(0.30)
    assert cs.sim_edge(_row("A", "over", 20.0)) is None and cs.sim_edge(_row("A", "over", None, projected=3.0)) is None
    assert cs.sim_edge(_row("A", "over", 0, projected=3.0)) is None
    assert cs.sim_backs(_row("A", "over", 20.0, projected=21.0)) and not cs.sim_backs(_row("A", "over", 20.0, projected=20.9))


def test_sheet_rules_reads_the_stamp_and_an_unstamped_sheet_is_v1():
    assert cs.sheet_rules({}) == 1 and cs.sheet_rules(None) == 1 and cs.sheet_rules({"section_rules": True}) == 1
    assert cs.sheet_rules({"section_rules": "2"}) == 1 and cs.sheet_rules({"section_rules": 2}) == 2
    assert cs.SECTION_RULES == 2


def test_v2_takes_the_sims_side_of_the_main_line_v1_the_better_ev_side():
    # The price likes the over (EV +4); the sim projects 18.0 against 20.5, the under by 12%.
    rows = [_row("A", "over", projected=18.0, verdict="value", ev=4.0), _row("A", "under", projected=18.0, ev=-6.0)]
    assert cs.primary_lines(rows, rules=1) == {0}
    assert cs.primary_lines(rows, rules=2) == {1}
    # No sim view (or under 5%): the EV rule decides, in both versions.
    flat = [_row("B", "over", projected=20.8, ev=4.0), _row("B", "under", projected=20.8, ev=-6.0)]
    assert cs.primary_lines(flat, rules=1) == cs.primary_lines(flat, rules=2) == {0}


def test_sim_vs_the_line_section_main_line_sim_side_biggest_edge_first():
    rows = [_row("Big", "under", projected=16.0), _row("Big", "over", projected=16.0),           # under by 22%
            _row("Small", "over", projected=22.0), _row("Small", "under", projected=22.0),       # over by 7%
            _row("Flat", "over", projected=21.0), _row("Flat", "under", projected=21.0),         # 2.4%: out
            _row("Long", "over", projected=30.0, price=300),                                      # outside the band
            _row("OneSided", "over", projected=30.0, verdict="one_sided_fair"),                   # no two-sided fair
            _row("Alt", "over", 25.5, projected=30.0, books=2), _row("Alt", "over", 20.5, projected=30.0, books=8)]
    s = cs.sections(rows, rules=2)
    assert [(rows[i]["player"], rows[i]["side"]) for i in s["sim_edge"]] == [("Alt", "over"), ("Big", "under"), ("Small", "over")]
    assert rows[s["sim_edge"][0]]["line"] == 20.5                                  # the main line, not the alt rung
    assert cs.sections(rows, rules=1)["sim_edge"] == []                            # v1 sheets never had it
    featured = [i for k, ids in s.items() if k not in ("every_prop", "shop_gaps") for i in ids]
    assert all(rows[i]["side"] == "under" for i in featured if rows[i]["player"] == "Big")   # one side per player + stat


def test_value_needs_the_sim_on_its_side_in_v2():
    rows = [_row("Backed", "over", projected=23.0, verdict="value", ev=3.0),
            _row("Alone", "over", projected=20.0, verdict="value", ev=6.0),
            _row("NoSim", "over", verdict="value", ev=5.0)]
    assert [rows[i]["player"] for i in cs.sections(rows, rules=1)["value"]] == ["Alone", "NoSim", "Backed"]
    assert [rows[i]["player"] for i in cs.sections(rows, rules=2)["value"]] == ["Backed"]


def test_hot_form_is_retired_in_v2_and_its_record_keeps_its_name():
    hot = _row("Shooter", "over", 0.5, verdict="one_sided_fair", price=120, market="player_shots")
    hot["check"]["form5"] = {"games": 5, "hits": 5, "rate": 1.0}
    hot["check"]["form10"] = {"games": 10, "hits": 9, "rate": 0.9}
    assert cs.sections([hot], rules=1)["hot_form"] == [0] and cs.sections([hot], rules=2)["hot_form"] == []
    rec = csr.season_record([], generated_at="2026-11-13T12:00:00+00:00")
    label = {s["key"]: s["label"] for s in rec["sections"]}
    assert label["hot_form"] == "Hot form, one-sided (retired 11/13)" and label["sim_edge"] == "Sim vs the line"
    assert rec["applies"]["hot_form"] == [] and "nba" in rec["applies"]["sim_edge"]


def test_matchups_admit_on_the_same_line_record_in_v2_not_on_a_rank_alone():
    rows = [_row("Rank", "over", matchup={"nth_most": 1, "of": 32}),
            _row("Record", "over", vs_opponent={"games": 4, "hits": 3, "same_line": True}),
            _row("Best", "under", vs_opponent={"games": 3, "hits": 3, "same_line": True}),
            _row("Few", "over", vs_opponent={"games": 2, "hits": 2, "same_line": True})]
    assert {rows[i]["player"] for i in cs.sections(rows, rules=1)["matchup_spots"]} == {"Rank", "Record", "Best"}
    assert [rows[i]["player"] for i in cs.sections(rows, rules=2)["matchup_spots"]] == ["Best", "Record"]


def test_player_vs_player_needs_its_history_to_point_to_the_side_in_v2():
    def skater(player, side, games, sog, market="SOG", line=2.5):
        return _row(player, side, line, market=market, pvp={"kind": "skater_vs_goalie", "line": {"games": games, "sog": sog, "goals": 0}})
    rows = [skater("Shooter", "over", 4, 14),          # 3.5 a game vs 2.5: over -- in
            skater("Quiet", "over", 4, 6),             # 1.5 a game: points to the under -- out of an over
            skater("Points", "over", 4, 14, market="POINTS", line=0.5)]  # no assists in the history: no direction
    assert {rows[i]["player"] for i in cs.sections(rows, rules=1)["pvp_skaters"]} == {"Shooter", "Quiet", "Points"}
    assert [rows[i]["player"] for i in cs.sections(rows, rules=2)["pvp_skaters"]] == ["Shooter"]


@pytest.mark.parametrize("kind,market,line,side,lean", [
    ("goalie_vs_team", "SAVES", 24.5, "under", {"games": 3, "saves": 66}),                                 # 22 a game
    ("scorer_vs_defenders", "player_points", 20.5, "over", {"poss": 80, "pts_per_100": 33.0, "overall_pts_per_100": 28.0}),
    ("receiver_vs_defenders", "Receptions", 4.5, "under", {"plays": 8, "catches": 4, "pbu": 2, "int": 1}),
    ("receiver_vs_defenders", "Receiving Yards", 48.5, "over", {"plays": 8, "catches": 7, "pbu": 0, "int": 0}),
    ("qb_vs_defenders", "Interceptions", 0.5, "over", {"games": 3, "int": 3}),
    ("batter_vs_pitcher", "batter_hits", 0.5, "over", {"plateAppearances": 12, "ops": "1.050"}),
    ("pitcher_vs_lineup", "strikeouts", 5.5, "under", {"plateAppearances": 40, "k_rate": 0.15}),
    ("pitcher_vs_lineup", "hits_allowed", 4.5, "over", {"plateAppearances": 40, "avg": ".300"}),
])
def test_each_history_kind_has_a_direction(kind, market, line, side, lean):
    row = _row("P", side, line, market=market, pvp={"kind": kind, "line": lean})
    assert cs.pvp_lean(row) == side and cs.pvp_points_to_side(row)
    other = _row("P", "over" if side == "under" else "under", line, market=market, pvp={"kind": kind, "line": lean})
    assert not cs.pvp_points_to_side(other)


def test_a_history_inside_its_dead_band_or_too_small_has_no_direction():
    assert cs.pvp_lean(_row("P", market="player_points", pvp={"kind": "scorer_vs_defenders",
                                                             "line": {"poss": 80, "pts_per_100": 29.0, "overall_pts_per_100": 28.0}})) is None
    assert cs.pvp_lean(_row("P", market="batter_hits", line=0.5, pvp={"kind": "batter_vs_pitcher",
                                                                      "line": {"plateAppearances": 4, "ops": "1.500"}})) is None
    assert cs.pvp_lean(_row("P", market="player_rebounds", pvp={"kind": "scorer_vs_defenders",
                                                               "line": {"poss": 80, "pts_per_100": 40.0, "overall_pts_per_100": 20.0}})) is None
    assert cs.pvp_lean(_row("P", line=2.0, market="SOG", pvp={"kind": "skater_vs_goalie", "line": {"games": 2, "sog": 4}})) is None


def test_picks_outside_the_featured_band_are_not_selected():
    base = {"suggested": True, "sport": "nba", "game_date": "2026-11-13", "market_state": "pregame", "kind": "game",
            "market": "h2h", "event_id": "e"}
    cards = [dict(base, pick_id="a", odds=250, side="home"), dict(base, pick_id="b", odds=300, side="away"),
             dict(base, pick_id="c", odds=-260, event_id="f", side="home"), dict(base, pick_id="d", odds=None, event_id="g")]
    assert [c["pick_id"] for c in cs.select_picks(cards, sport="nba", day="2026-11-13")] == ["a"]


def test_the_record_reads_each_day_under_its_own_stamp():
    rows = [_row("Big", "under", projected=16.0, ev=1.0), _row("Big", "over", projected=16.0, ev=2.5, verdict="value")]
    rec = {"props": {cs.prop_result_key(r): {"y": y} for r, y in zip(rows, (1.0, 0.0))}, "lines": {},
           "counts": {"props": 2, "props_graded": 2, "lines": 0, "lines_graded": 0}}
    old = csr.day_record({"sport": "nba", "date": "2026-11-12", "rows": rows}, rec)
    new = csr.day_record({"sport": "nba", "date": "2026-11-13", "rows": rows, "section_rules": 2}, rec)
    assert "value" in old["sections"] and "sim_edge" not in old["sections"]          # a past day keeps what it featured
    assert new["sections"]["sim_edge"]["w"] == 1 and "value" not in new["sections"]


def test_the_page_derives_sections_under_the_sheets_stamp_and_says_what_the_sim_measured():
    rows = [_row("Big", "under", projected=16.0, event_id="e"), _row("Big", "over", projected=16.0, event_id="e")]
    v2 = cs.page_payload([{"sport": "nba", "date": "2026-11-13", "rows": rows, "games": [], "section_rules": 2}])["nba"]
    v1 = cs.page_payload([{"sport": "nba", "date": "2026-11-12", "rows": rows, "games": []}])["nba"]
    assert v2["section_rules"] == 2 and v2["sections"]["sim_edge"] == [0] and v2["game_sections"]["e"]["sim_edge"] == [0]
    assert v1["section_rules"] == 1 and v1["sections"]["sim_edge"] == []
    assert "1,251 bets, ROI +8.0%" in v2["sim_edge_measured"]
    assert "has not beaten the price" in cs.sim_edge_measured_text("nfl")
