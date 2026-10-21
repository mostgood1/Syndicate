"""NBA live props reach more board rows (user 2026-10-20: "fix the live prop matching so more props get projections").

Measured 19:35 CT on PHI @ NYK: 42 of 166 live NBA prop rows had a live projection. The re-sim published four stats at
ONE line each (the mode across books), so the board's combos (73 rows), steals/blocks (5) and every other book's line
(18 rows whose player and market were projected at another line) could never join. These tests pin the producer side
and then run the real join, because a producer row the join cannot key is the same miss as no row at all.
"""
from __future__ import annotations

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared.live_projection_join import attach_live_projections, build_live_prop_index

HDR = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
GAME = "New York Knicks,Philadelphia 76ers"


def _csv(tmp_path, rows):
    f = tmp_path / "props.csv"
    f.write_text(HDR + "\n".join(rows) + "\n", encoding="utf-8")
    return f


def test_combos_are_summed_per_draw_so_the_correlation_survives():
    # Two draws: 10 points and no boards, then no points and 10 boards. Per draw P+R is 10 both times; convolving
    # the marginals would spread it over 0 / 10 / 20 as if the two were independent.
    zeros = [0, 0]
    rem = {"home": {"Josh Hart": {"pts": [10, 0], "reb": [0, 10], "ast": list(zeros), "threes": list(zeros),
                                  "stl": list(zeros), "blk": [1, 0], "tov": list(zeros)}}, "away": {}}
    hists = lr._player_remainder_hists(rem, 2)["home"]["Josh Hart"]
    assert hists["pr"] == {"10": 2}
    assert hists["pra"] == {"10": 2} and hists["pa"] == {"0": 1, "10": 1} and hists["ra"] == {"0": 1, "10": 1}
    assert hists["blk"] == {"0": 1, "1": 1}
    assert "stl" not in hists                     # an all-zero stat stays absent, as before


def test_every_posted_line_both_sides_and_the_new_markets_for_this_game_only(tmp_path):
    f = _csv(tmp_path, [
        f"t,e1,c,dk,DK,player_points,Over,Josh Hart,12.5,-110,t,{GAME}",
        f"t,e1,c,fd,FD,player_points,Over,Josh Hart,13.5,-110,t,{GAME}",
        f"t,e1,c,mg,MG,player_points,Under,Josh Hart,11.5,-110,t,{GAME}",     # quoted on one side only: still a line
        f"t,e1,c,dk,DK,player_points_rebounds_assists,Over,Josh Hart,25.5,-115,t,{GAME}",
        f"t,e1,c,dk,DK,player_steals,Over,Josh Hart,0.5,-150,t,{GAME}",
        f"t,e1,c,dk,DK,player_turnovers,Over,Josh Hart,1.5,120,t,{GAME}",
        f"t,e1,c,dk,DK,player_double_double,Yes,Josh Hart,,150,t,{GAME}",    # yes/no: not a line, not here
        "t,e2,c,dk,DK,player_points,Over,LeBron James,24.5,-110,t,Los Angeles Lakers,Sacramento Kings",
    ])
    out = lr.lines_from_props_csv(f, "New York Knicks", "Philadelphia 76ers")
    assert out == {("josh hart", "pts"): (11.5, 12.5, 13.5), ("josh hart", "pra"): (25.5,),
                   ("josh hart", "stl"): (0.5,), ("josh hart", "tov"): (1.5,)}


def test_actuals_read_steals_blocks_turnovers_from_espns_box():
    box = {"boxscore": {"players": [{"statistics": [{
        "names": ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"],
        "athletes": [{"athlete": {"displayName": "LeBron James"},
                      "stats": ["18", "5", "2-5", "0-2", "1-2", "4", "4", "1", "0", "2", "0", "4", "1", "-6"]}]}]}]}}
    assert lr.actuals_from_summary(box)["lebron james"] == {"pts": 5, "reb": 4, "ast": 4, "threes": 0, "stl": 0,
                                                            "blk": 2, "tov": 1}


def test_combo_banked_is_the_sum_and_a_missing_component_is_not_a_zero():
    result = {"sims_run": 100, "player_remainders": {"home": {
        "Josh Hart": {"pra": {"5": 50, "15": 50}, "pts": {"2": 100}},
        "Mikal Bridges": {"pr": {"4": 100}}}, "away": {}}}
    actuals = {"josh hart": {"pts": 6, "reb": 4, "ast": 2}, "mikal bridges": {"pts": 9}}  # Bridges' REB unread
    lines = {("josh hart", "pra"): (19.5, 24.5), ("josh hart", "pts"): (7.5,), ("mikal bridges", "pr"): (14.5,)}
    rows, cov = lr.build_live_props(result, actuals, lines)
    got = {(r["prop"], r["line"]): r for r in rows}
    assert got[("player_points_rebounds_assists", 19.5)]["actualSoFar"] == 12.0
    assert got[("player_points_rebounds_assists", 19.5)]["liveModelProbOver"] == 0.5     # 12+15 clears, 12+5 does not
    assert got[("player_points_rebounds_assists", 24.5)]["liveModelProbOver"] == 0.5
    assert got[("player_points", 7.5)]["liveModelProbOver"] is None                    # 6+2 = 8 every draw: decided
    assert ("player_points_rebounds", 14.5) not in got
    assert cov["no_actual"] == 1 and cov["rows"] == 3


def test_the_board_join_now_reaches_combos_steals_and_a_second_books_line(tmp_path):
    # Producer -> snapshot -> the real join, on board-shaped rows. Before: one row (points at the mode, 12.5).
    f = _csv(tmp_path, [
        f"t,e1,c,dk,DK,player_points,Over,Josh Hart,12.5,-110,t,{GAME}",
        f"t,e1,c,mg,MG,player_points,Over,Josh Hart,12.5,-110,t,{GAME}",
        f"t,e1,c,fd,FD,player_points,Over,Josh Hart,13.5,-110,t,{GAME}",
        f"t,e1,c,dk,DK,player_points_rebounds,Over,Josh Hart,23.5,-110,t,{GAME}",
        f"t,e1,c,dk,DK,player_blocks,Over,Josh Hart,0.5,140,t,{GAME}",
    ])
    lines = lr.lines_from_props_csv(f, "New York Knicks", "Philadelphia 76ers")
    zeros = [0, 0, 0, 0]
    rem = {"home": {"Josh Hart": {"pts": [3, 8, 1, 10], "reb": [6, 2, 9, 4], "ast": list(zeros), "threes": list(zeros),
                                  "stl": list(zeros), "blk": [0, 1, 0, 1], "tov": list(zeros)}}, "away": {}}
    result = {"sims_run": 4, "player_remainders": lr._player_remainder_hists(rem, 4)}
    actuals = {"josh hart": {"pts": 7, "reb": 5, "ast": 1, "threes": 0, "stl": 0, "blk": 0, "tov": 0}}
    props, _cov = lr.build_live_props(result, actuals, lines)
    snapshot = {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": props}]}
    grid = [{"kind": "prop", "player_name": "Josh Hart", "market": m, "line": ln, "side": "over", "game": {"state": "live"}}
            for m, ln in (("player_points", 12.5), ("player_points", 13.5), ("player_points_rebounds", 23.5),
                          ("player_blocks", 0.5))]
    coverage = attach_live_projections(grid, build_live_prop_index(snapshot))
    assert coverage["rows_live_projected"] == 4, coverage
    pr = grid[2]["projection"]
    assert pr["live_aware"] and pr["actual_so_far"] == 12.0
    # P+R banked 7 + 5 = 12; per draw + (9, 10, 10, 14) = 21, 22, 22, 26 -> over 23.5 in one draw of four
    assert pr["model_prob_over"] == 0.25 and pr["live_projected"] == 22.75


def test_neighbour_lines_cover_a_moved_line_and_never_go_below_half_a_point():
    out = lr.with_neighbour_lines({("josh hart", "pts"): (12.5, 13.5), ("josh hart", "stl"): (0.5,)}, window=3)
    assert out[("josh hart", "pts")] == (9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5)
    assert out[("josh hart", "stl")] == (0.5, 1.5, 2.5, 3.5)
