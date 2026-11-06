"""Live NBA double-double / triple-double rows show a live number and are never priced (`#762` (c)).

User "Yes, build it", 2026-11-06. Measured 11-05: 12 of ~280 live NBA prop rows were these two markets and none had a
Live proj. -- the re-sim published per-stat rows only, and a double-double is a JOINT threshold. The re-sim now keeps
each draw's five stats together, so the count of stats reaching ten is read per draw (the grader's framing:
`bet_status_nba._MARKET_TO_DOUBLES`, Yes = over 1.5 / 2.5).

DISPLAY ONLY. The join writes the Live and Actual columns and never `model_prob_over` / `live_aware`: on a one-sided
quote `layer2_board._model_value_ev` ranks by EV against `model_prob_over`, and the pregame join has never priced these
markets. The tests below pin both halves, through the real producer and the real join.
"""
from __future__ import annotations

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_projection_join as J
from syndicate.features.shared.board_enrichment import attach_modelled_fair_edges
from syndicate.features.shared.layer2_board import _live_projection_columns, _model_value_ev
from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason

HDR = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
GAME = "New York Knicks,Philadelphia 76ers"
# Banked: 12 points (already 10+), 7 rebounds, 3 assists, 1 steal, 0 blocks -> one stat at 10+.
BANKED = {"pts": 12, "reb": 7, "ast": 3, "threes": 1, "stl": 1, "blk": 0, "tov": 2}
# Rest-of-game draws "pts,reb,ast,stl,blk" -> count. Finals: 40 draws reach 2 (reb 10), 30 reach 2 (ast 11),
# 10 reach 3 (reb 10 + ast 10), 20 stay at 1. P(DD) = 0.8, P(TD) = 0.1, mean final count 1.9.
JOINT = {"5,3,1,0,0": 40, "5,2,8,0,0": 30, "5,3,7,0,0": 10, "3,0,0,0,0": 20}


def _result(joint=JOINT, sims=100):
    return {"sims_run": sims, "player_remainders": {"home": {"Josh Hart": {"pts": {"5": 80, "3": 20},
                                                                          lr.DOUBLES_JOINT_KEY: dict(joint)}},
                                                    "away": {}}}


def _lines():
    return {("josh hart", "dd"): (1.5,), ("josh hart", "td"): (2.5,)}


# ------------------------------------------------------------------------------------------------ the producer

def test_the_joint_keeps_each_draws_stats_together_capped_at_ten():
    rem = {"home": {"Josh Hart": {"pts": [14, 0], "reb": [0, 3], "ast": [2, 0], "threes": [0, 0], "stl": [0, 1],
                                  "blk": [0, 0], "tov": [0, 0]}}, "away": {}}
    hists = lr._player_remainder_hists(rem, 2)["home"]["Josh Hart"]
    assert hists[lr.DOUBLES_JOINT_KEY] == {"0,3,0,1,0": 1, "10,0,2,0,0": 1}   # 14 points capped at 10: lossless


def test_double_and_triple_double_rows_count_stats_at_ten_per_draw():
    rows, cov = lr.build_live_props(_result(), {"josh hart": BANKED}, _lines())
    got = {r["prop"]: r for r in rows}
    dd, td = got["player_double_double"], got["player_triple_double"]
    assert (dd["line"], dd["liveModelProbOver"], dd["liveProjection"], dd["actualSoFar"]) == (1.5, 0.8, 1.9, 1.0)
    assert (td["line"], td["liveModelProbOver"], td["liveProjection"], td["actualSoFar"]) == (2.5, 0.1, 1.9, 1.0)
    assert cov["doubles_rows"] == 2 and cov["priced"] == 2


def test_a_double_double_already_made_is_refused_as_certain_but_still_shown():
    rows, cov = lr.build_live_props(_result(), {"josh hart": {**BANKED, "reb": 10}}, _lines())
    dd = next(r for r in rows if r["prop"] == "player_double_double")
    assert dd["liveModelProbOver"] is None and dd["unpricedReason"] == "certainty_refused"
    assert dd["actualSoFar"] == 2.0 and dd["liveProjection"] > 2.0
    assert cov["certainty_refused"] == 1


def test_a_missing_component_actual_is_not_a_zero():
    banked = {k: v for k, v in BANKED.items() if k != "blk"}       # ESPN's BLK cell unreadable
    rows, cov = lr.build_live_props(_result(), {"josh hart": banked}, _lines())
    assert rows == [] and cov["no_actual"] == 2 and cov["doubles_rows"] == 0


def test_no_posted_market_no_row():
    rows, _cov = lr.build_live_props(_result(), {"josh hart": BANKED}, {("josh hart", "dd"): (1.5,)})
    assert [r["prop"] for r in rows] == ["player_double_double"]


def test_csv_yes_no_quotes_become_the_fixed_line_and_never_get_neighbours(tmp_path):
    f = tmp_path / "props.csv"
    f.write_text(HDR + "\n".join([
        f"t,e1,c,dk,DK,player_double_double,Yes,Josh Hart,,150,t,{GAME}",
        f"t,e1,c,fd,FD,player_double_double,No,Josh Hart,,-190,t,{GAME}",
        f"t,e1,c,dk,DK,player_triple_double,Yes,Josh Hart,,1400,t,{GAME}",
        f"t,e1,c,dk,DK,player_points,Over,Josh Hart,12.5,-110,t,{GAME}",
        "t,e2,c,dk,DK,player_double_double,Yes,LeBron James,,120,t,Los Angeles Lakers,Sacramento Kings",
    ]) + "\n", encoding="utf-8")
    lines = lr.lines_from_props_csv(f, "New York Knicks", "Philadelphia 76ers")
    assert lines == {("josh hart", "dd"): (1.5,), ("josh hart", "td"): (2.5,), ("josh hart", "pts"): (12.5,)}
    wide = lr.with_neighbour_lines(lines, window=3)
    assert wide[("josh hart", "dd")] == (1.5,) and wide[("josh hart", "td")] == (2.5,)
    assert len(wide[("josh hart", "pts")]) == 7


def test_resim_live_game_carries_the_joint_end_to_end():
    # The real aggregator over a fake engine: 3 draws of Josh Hart's rest-of-game box.
    boxes = iter([{"pts": 2, "reb": 3, "ast": 0, "stl": 0, "blk": 0}, {"pts": 0, "reb": 1, "ast": 8, "stl": 0, "blk": 0},
                  {"pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0}] * 34)

    def simulate(rng, gs):
        row = {"player_name": "Josh Hart", "threes": 0, "tov": 0, **next(boxes)}
        return {"players": [row]}, {"players": []}, [30, 0, 0, 0], [20, 0, 0, 0]

    out = lr.resim_live_game({}, None, sims=100, simulate=simulate)
    rows, _cov = lr.build_live_props(out, {"josh hart": BANKED}, _lines())
    dd = next(r for r in rows if r["prop"] == "player_double_double")
    # reb 7+3 = 10 in draws 1,4,7..; ast 3+8 = 11 in draws 2,5,8..; nothing in the third: 67 of 100 draws.
    assert dd["liveModelProbOver"] == 0.67 and dd["simsRun"] == 100


# ---------------------------------------------------------------------------------------------- the board join

def _snapshot():
    rows, _cov = lr.build_live_props(_result(), {"josh hart": BANKED}, _lines())
    return {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": rows}]}


def _dd_row(side="Yes", market="player_double_double", **over):
    row = {"sport": "nba", "kind": "prop", "player_name": "Josh Hart", "market": market, "line": None, "side": side,
           "sides": [side.lower()], "game": {"state": "live"}, "modelled_fair": {side.lower(): 0.4}}
    row.update(over)
    return row


def test_the_join_shows_the_live_count_and_actual_and_prices_nothing():
    grid = [_dd_row(), _dd_row(market="player_triple_double")]
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot()))
    assert cov["rows_live_display_only"] == 2 and cov["rows_live_projected"] == 0 and cov["miss_no_line"] == 0
    p = grid[0]["projection"]
    assert (p["live_projected"], p["actual_so_far"], p["live_display_prob_over"]) == (1.9, 1.0, 0.8)
    assert p["live_display_only"] is True
    for forbidden in ("model_prob_over", "live_aware", "basis", "edge_vs_market_pct", "live_prob_over"):
        assert forbidden not in p, forbidden
    assert grid[1]["projection"]["live_display_prob_over"] == 0.1


def test_off_is_not_on_without_the_yes_no_key(monkeypatch):
    monkeypatch.setattr(J, "_YES_NO_LINE_KEYS", {"player_goal_scorer_anytime": ("player_goals", 0.5)})
    grid = [_dd_row()]
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot()))
    assert cov["miss_no_line"] == 1 and cov["rows_live_display_only"] == 0 and "projection" not in grid[0]


def test_nothing_downstream_can_rank_or_price_it():
    grid = [_dd_row()]
    J.attach_live_projections(grid, J.build_live_prop_index(_snapshot()))
    row = grid[0]
    # The live-edge policy still refuses: the projection is not live-aware.
    assert live_edge_unavailable_reason(row) is not None
    # The one-sided ranking term has no model probability to read.
    assert _model_value_ev(row, "yes", 150, "book_margin_model") is None
    # The modelled-fair hop finds no probability either.
    out = attach_modelled_fair_edges(grid)
    assert out["modelled_edge_rows_priced"] == 0
    assert "edge_vs_modelled_fair_pct" not in row["projection"]


def test_board_columns_show_count_actual_and_the_rows_own_side():
    yes, no = _dd_row(), _dd_row(side="No")
    J.attach_live_projections([yes, no], J.build_live_prop_index(_snapshot()))
    cols_yes, cols_no = _live_projection_columns(yes), _live_projection_columns(no)
    assert (cols_yes["live_projection"], cols_yes["actual"]) == (1.9, 1.0)
    assert cols_yes["live_model_probability"] == 0.8
    assert abs(cols_no["live_model_probability"] - 0.2) < 1e-9
    assert "live_aware" not in cols_yes


def test_web_read_time_refresh_keys_the_same_row():
    hit = J.live_prop_hit(J.build_live_prop_index(_snapshot()), "Josh Hart", "player_double_double", None)
    assert hit is not None and hit["live_projection"] == 1.9 and hit["actual_so_far"] == 1.0
    assert J.live_prop_hit(J.build_live_prop_index(_snapshot()), "Josh Hart", "player_triple_double", None)["live_prob_over"] == 0.1


def test_an_ordinary_prop_still_joins_live_aware():
    rows, _cov = lr.build_live_props(_result(), {"josh hart": BANKED}, {("josh hart", "pts"): (15.5,)})
    snapshot = {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": rows}]}
    grid = [{"sport": "nba", "kind": "prop", "player_name": "Josh Hart", "market": "player_points", "line": 15.5,
             "side": "over", "game": {"state": "live"}}]
    cov = J.attach_live_projections(grid, J.build_live_prop_index(snapshot))
    assert cov["rows_live_projected"] == 1 and cov["rows_live_display_only"] == 0
    assert grid[0]["projection"]["live_aware"] is True
