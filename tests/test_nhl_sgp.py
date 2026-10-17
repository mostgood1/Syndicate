"""NHL same-game parlays from the consistency ladder's rungs (lane nhl-sgp-builder, user 2026-10-16)."""
from __future__ import annotations

import pytest

from syndicate.features.nhl import sgp

CELLS = {"cells": {"type": {"POINTS|L1~SOG|L1~same_player": {"rho": 0.55},
                            "POINTS|L1~POINTS|L1~teammate": {"rho": 0.35},
                            "SAVES|G~SOG|L1~opponent": {"rho": 0.25}},
                   "market": {}}}
ROLES = {"nazemkadri": "L1", "nathanmackinnon": "L1", "tristanjarry": "G"}


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
    assert all(l["type"] == "SOG|L1" and l["side"] == "over" for l in legs)


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
    assert roles == {"nathanmackinnon": "L1", "calemakar": "D1", "mackenzieblackwood": "G"}


def test_a_goal_and_a_point_by_the_same_player_never_pair():
    cells = {"cells": {"type": {"GOALS|L1~POINTS|L1~same_player": {"rho": 0.93}}, "market": {}},
             "nested_same_player": ["GOALS~POINTS~same_player"]}
    sheet = _sheet([_ladder("Nathan MacKinnon", "GOALS", [(0.5, 0.4, {"dk": 150})]),
                    _ladder("Nathan MacKinnon", "POINTS", [(0.5, 0.7, {"dk": -230})])])
    assert sgp.suggest(sheet, cells, ROLES) == []


def test_reachability_the_sheet_build_attaches_nhl_parlays_and_ledgers_them(tmp_path):
    # The first fleet run failed with `module ... nhl.sgp has no attribute merge_record` (the record helpers live in the
    # shared NFL module): the sheet built, the section was silently absent. Run the real attach step end to end.
    import importlib.util
    import json
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "build_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "build_cheat_sheets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    (tmp_path / "nhl_source" / "sgp").mkdir(parents=True)
    (tmp_path / "nhl_source" / "sgp" / "nhl_sgp_correlations.json").write_text(json.dumps(CELLS), encoding="utf-8")
    proc = tmp_path / "nhl_source" / "data" / "processed"
    proc.mkdir(parents=True)
    (proc / "lineups_2099-01-01.csv").write_text(
        "player_id,full_name,position,line_slot,proj_toi,team\n1,Nazem Kadri,C,L1,18,Colorado Avalanche\n"
        "2,Nathan MacKinnon,C,L1,21,Colorado Avalanche\n", encoding="utf-8")
    sheet = _sheet([_ladder("Nazem Kadri", "POINTS", [(0.5, 0.55, {"dk": -110})]),
                    _ladder("Nathan MacKinnon", "POINTS", [(0.5, 0.65, {"dk": -170})])])
    sheet["games"][0]["commence_time"] = "2099-01-01T23:00:00Z"
    m.attach_sgp(sheet, None, tmp_path, "2099-01-01", "nhl")
    assert len(sheet["sgp"]) == 1 and sheet["sgp_basis"].startswith("two seasons of NHL")
    assert len((tmp_path / "cheatsheets" / "nhl" / "sgp_ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 1


# ------------------------------------------------------------------------------- 3- and 4-leg tickets (user 2026-10-16)
def test_the_orthant_matches_scipy_for_three_and_four_legs():
    import numpy as np
    from scipy.stats import multivariate_normal

    from syndicate.features.nfl import sgp as core

    rng = np.random.default_rng(5)
    for k in (3, 4):
        A = rng.normal(size=(k, k))
        S = A @ A.T + k * np.eye(k)
        d = np.sqrt(np.diag(S))
        R = S / np.outer(d, d)
        b = rng.normal(scale=0.7, size=k)
        got = core.orthant_all(b[None, :], R[None, :, :])[0]
        assert got == pytest.approx(multivariate_normal(mean=np.zeros(k), cov=R).cdf(b), abs=2e-4)
    bad = np.array([[[1, .9, -.9], [.9, 1, .9], [-.9, .9, 1]]])        # pairwise rhos that cannot coexist
    assert np.isnan(core.orthant_all(np.zeros((1, 3)), bad)[0])


MULTI_CELLS = {"cells": {"type": {"POINTS|L1~POINTS|L1~teammate": {"rho": 0.35},
                                  "POINTS|L1~SOG|L1~same_player": {"rho": 0.3},
                                  "POINTS|L1~SOG|L1~teammate": {"rho": 0.15},
                                  "SOG|L1~SOG|L1~teammate": {"rho": 0.1}}, "market": {}}}


def _line(names):
    return [_ladder(n, "POINTS", [(0.5, 0.6, {"dk": -150, "fd": -145})]) for n in names] + \
           [_ladder(n, "SOG", [(1.5, 0.6, {"dk": -150})]) for n in names]


def test_three_and_four_leg_tickets_one_book_no_clash_ranked_by_lift_with_no_estimate():
    roles = {"aa": "L1", "bb": "L1", "cc": "L1"}
    sheet = _sheet(_line(["A A", "B B", "C C"]))
    out = sgp.suggest(sheet, MULTI_CELLS, {"aa": "L1", "bb": "L1", "cc": "L1", **{
        k: v for k, v in roles.items()}})
    multi = [s for s in out if s.get("size", 2) >= 3]
    assert {s["size"] for s in multi} == {3, 4}
    for s in multi:
        assert all(s["book"] in leg["prices"] for leg in s["legs"])      # one book quotes every leg
        assert s["show_estimate"] is False and s["lift"] >= 1.05 and s["p_joint"] >= 0.06
        keys = [(l["player"], l["market"]) for l in s["legs"]]
        assert len(keys) == len(set(keys))                              # never two rungs of one player's stat
    for size in (3, 4):
        lifts = [s["lift"] for s in multi if s["size"] == size]
        assert lifts == sorted(lifts, reverse=True)
    assert all(s["show_estimate"] for s in out if s.get("size", 2) == 2)


# ------------------------------------------------------------------- the hit-rate family (user 2026-10-16)
def _hr_ladder(player, market, rung, p, hits, prices, team="COL"):
    return {"player": player, "market": market, "team": team, "event_id": "e1", "line": rung,
            "rungs": [{"rung": rung, "label": f"{int(rung + 0.5)}+", "hits": hits, "games": 10, "p_market": p,
                       "p_shrunk": p, "prices": prices}]}


def test_hit_rate_tickets_use_consistent_legs_rank_by_the_whole_ticket_and_never_beat_the_book_product():
    sheet = _sheet([_hr_ladder("Nazem Kadri", "POINTS", 0.5, 0.62, 8, {"dk": -150}),
                    _hr_ladder("Nathan MacKinnon", "POINTS", 0.5, 0.70, 9, {"dk": -210}),
                    _hr_ladder("Cale Makar", "POINTS", 0.5, 0.60, 5, {"dk": -140}),         # 5/10: not consistent
                    _hr_ladder("Gabe Landeskog", "POINTS", 0.5, 0.58, 7, {"dk": -2000})])   # a price that never pays
    roles = {"nazemkadri": "L1", "nathanmackinnon": "L1", "calemakar": "L1", "gabelandeskog": "L1"}
    out = [s for s in sgp.suggest(sheet, MULTI_CELLS, roles) if s.get("family") == "hit_rate"]
    assert out, "a consistent, correlated pair must produce a hit-rate ticket"
    for s in out:
        players = {l["player"] for l in s["legs"]}
        assert "Cale Makar" not in players                               # cleared 5/10: below the 7/10 bar
        assert sgp.core.payout(s["legs"][0]["prices"][s["book"]]) is not None
        product = 1.0
        for leg in s["legs"]:
            product *= sgp.core.payout(leg["prices"][s["book"]])
        assert product >= 1.0 / s["p_joint"] - 1e-9                      # the legs' product can at least pay fair
        assert s["lift"] >= 1.0 and all(l["games"] >= 8 for l in s["legs"])
    pairs = [s for s in out if s["size"] == 2]
    assert [s["p_joint"] for s in pairs] == sorted((s["p_joint"] for s in pairs), reverse=True)
