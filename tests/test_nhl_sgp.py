"""NHL same-game parlays from the consistency ladder's rungs (lane nhl-sgp-builder, user 2026-10-16)."""
from __future__ import annotations

import pytest

from syndicate.features.nhl import sgp

CELLS = {"cells": {"type": {"POINTS|F1~SOG|F1~same_player": {"rho": 0.55},
                            "POINTS|F1~POINTS|F1~teammate": {"rho": 0.35},
                            "SAVES|G~SOG|F1~opponent": {"rho": 0.25}},
                   "market": {}}}
ROLES = {"nazemkadri": "F1", "nathanmackinnon": "F1", "tristanjarry": "G"}


def _ladder(player, market, rungs, team="COL", event="e1"):
    return {"player": player, "market": market, "team": team, "event_id": event, "line": rungs[0][0],
            "rungs": [{"rung": r, "label": f"{int(r + 0.5)}+", "hits": 5, "games": 10, "p_market": p,
                       "prices": prices} for r, p, prices in rungs]}


def _sheet(ladders, rows=()):
    return {"sport": "nhl", "ladders": ladders, "rows": list(rows),
            "games": [{"event_id": "e1", "matchup": "Pittsburgh Penguins @ Colorado Avalanche"}]}


def test_ladder_rungs_become_legs_inside_the_probability_band():
    sheet = _sheet([_ladder("Nazem Kadri", "SOG", [(0.5, 0.95, {"dk": -1800}), (2.5, 0.52, {"dk": -120}),
                                                    (3.5, 0.32, {"dk": 200}), (6.5, 0.06, {"dk": 1500})])])
    legs = sgp.legs_by_game(sheet, ROLES)["e1"]
    assert sorted(l["line"] for l in legs) == [2.5, 3.5]          # 1+ at 95% and 7+ at 6% add nothing but vig
    assert all(l["type"] == "SOG|F1" and l["side"] == "over" for l in legs)


def test_linemates_points_pair_at_one_book_with_the_measured_rho():
    sheet = _sheet([_ladder("Nazem Kadri", "POINTS", [(0.5, 0.55, {"dk": -110, "fd": -115})]),
                    _ladder("Nathan MacKinnon", "POINTS", [(0.5, 0.65, {"dk": -170})])])
    [s] = sgp.suggest(sheet, CELLS, ROLES)
    assert s["relation"] == "teammate" and s["rho"] == 0.35 and s["book"] == "dk"
    assert s["p_joint"] > s["p_independent"] and s["worth_it_odds"] > s["fair_odds"]


def test_two_rungs_of_one_player_and_stat_never_pair_but_his_other_stat_can():
    sheet = _sheet([_ladder("Nazem Kadri", "SOG", [(2.5, 0.52, {"dk": -120}), (3.5, 0.32, {"dk": 200})]),
                    _ladder("Nazem Kadri", "POINTS", [(0.5, 0.55, {"dk": -110})])])
    out = sgp.suggest(sheet, CELLS, ROLES)
    assert out and all({l["market"] for l in s["legs"]} == {"SOG", "POINTS"} for s in out)
    assert len(out) == 1                                           # one ticket per pair of players (here, one player)


def test_goalie_saves_pair_with_the_opposing_shooter():
    sheet = _sheet([_ladder("Tristan Jarry", "SAVES", [(27.5, 0.5, {"dk": -110})], team="PIT"),
                    _ladder("Nathan MacKinnon", "SOG", [(3.5, 0.45, {"dk": 120})])])
    [s] = sgp.suggest(sheet, CELLS, ROLES)
    assert s["relation"] == "opponent" and s["rho"] == 0.25


def test_no_correlations_file_means_no_section():
    assert sgp.suggest(_sheet([]), None, ROLES) == []


def test_lineup_roles_read_slots_and_the_starting_goalie(tmp_path):
    p = tmp_path / "nhl_source" / "data" / "processed"
    p.mkdir(parents=True)
    (p / "lineups_2026-10-16.csv").write_text(
        "player_id,full_name,position,line_slot,proj_toi,team\n"
        "1,Nathan MacKinnon,C,L1,21.0,Colorado Avalanche\n2,Cale Makar,D,D1,25.0,Colorado Avalanche\n"
        "3,Mackenzie Blackwood,G,,59.0,Colorado Avalanche\n4,Scott Wedgewood,G,,1.0,Colorado Avalanche\n",
        encoding="utf-8")
    roles = sgp.lineup_roles(tmp_path, "2026-10-16")
    assert roles == {"nathanmackinnon": "F1", "calemakar": "D1", "mackenzieblackwood": "G"}
