"""NHL SGP correlations (lane `nhl-sgp-builder`, 2026-10-16): roles, proxy lines, pairs, and the estimator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("scipy")
from scipy.special import ndtri  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_nhl_sgp_correlations.py"
_spec = importlib.util.spec_from_file_location("build_nhl_sgp_correlations", _PATH)
nhl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nhl)


# ------------------------------------------------------------------------------------------- the estimator
def test_the_estimator_and_shrinkage_are_the_nfl_studys_own():
    # One estimator for both sports: a cell's rho means the same thing to `rho_for` whichever sport fitted it.
    for fn in (nhl.fit_rho, nhl.shrink_cells, nhl.clustered_se, nhl.four_cell):
        assert fn.__module__ == "build_nfl_sgp_correlations"


def _simulated_legs(n_games: int, r_team: float, c_same: float, seed: int) -> pd.DataFrame:
    """Each team: 3 L1 forwards with SOG and POINTS legs. SOG latents share a team factor (teammate rho r_team);
    a player's POINTS latent loads c_same on his own SOG latent; opponents independent. Each leg its own line."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for team in ("AAA", "BBB"):
            f = rng.standard_normal()
            for k in range(3):
                pid = (g * 10 + (0 if team == "AAA" else 5) + k)
                z = np.sqrt(r_team) * f + np.sqrt(1 - r_team) * rng.standard_normal()
                w = c_same * z + np.sqrt(1 - c_same ** 2) * rng.standard_normal()
                for market, latent in (("SOG", z), ("POINTS", w)):
                    p = rng.uniform(0.3, 0.7)
                    rows.append({"game_id": 2023020000 + g, "team": team, "pid": pid, "market": market, "role": "L1",
                                 "type": f"{market}|L1", "p": p, "over": int(latent > ndtri(1 - p))})
    return pd.DataFrame(rows)


def test_the_cells_recover_known_teammate_same_player_and_opponent_correlations():
    legs = _simulated_legs(2500, r_team=0.3, c_same=0.6, seed=7)
    cells = nhl.fit_cells(nhl.build_pairs(legs, ("p",)), "p")
    team = cells["type"]["SOG|L1~SOG|L1~teammate"]
    same = cells["type"]["POINTS|L1~SOG|L1~same_player"]
    opp = cells["type"]["SOG|L1~SOG|L1~opponent"]
    cross = cells["type"]["POINTS|L1~SOG|L1~teammate"]
    assert abs(team["rho"] - 0.3) < 3 * team["se"] + 0.02
    assert abs(same["rho"] - 0.6) < 3 * same["se"] + 0.02
    assert abs(opp["rho"]) < 3 * opp["se"] + 0.01
    assert abs(cross["rho"] - 0.18) < 3 * cross["se"] + 0.02          # c * r through the shared team factor
    assert same["n"] == 2500 * 6 and same["games"] == 2500


def test_the_copula_beats_independence_out_of_sample_through_the_consumer_lookup():
    # Unshrunk: `shrink_cells` pools a relation's cells, and this fixture has one same-player cell per level.
    cells = nhl.fit_cells(nhl.build_pairs(_simulated_legs(1500, 0.3, 0.6, seed=1), ("p",)), "p")
    out = nhl.evaluate(nhl.build_pairs(_simulated_legs(1500, 0.3, 0.6, seed=2), ("p",)), cells, "p")
    assert out["relation=same_player"]["diff"] < 0 and out["relation=same_player"]["z"] < -5
    assert out["relation=teammate"]["diff"] < 0 and out["relation=teammate"]["z"] < -3
    assert abs(out["relation=opponent"]["z"] or 0.0) < 4
    assert out["level=role"]["pairs"] == out["all"]["pairs"]          # every pair found its cell via `rho_for`


def test_the_shared_shrinkage_erases_a_common_level_that_the_second_moment_keeps():
    # `shrink_cells` (the NFL study's, used as is) takes tau^2 from var(rho) -- the spread about the cells' mean --
    # but shrinks toward 0. Four teammate cells all near +0.20 with SE 0.03 are a real, shared correlation; the
    # spread (5e-5) is below the noise (9e-4), so it zeroes all four. The diagnostic uses mean(rho^2).
    def group():
        return {"type": {f"a{i}~b~teammate": {"rho": r, "se": 0.03} for i, r in enumerate([0.20, 0.21, 0.19, 0.20])},
                "market": {}}
    shared, second = group(), group()
    nhl.shrink_cells(shared)
    nhl.shrink_second_moment(second)
    assert all(v["rho"] == 0 for v in shared["type"].values())
    assert all(v["rho"] > 0.18 for v in second["type"].values())


def test_pairs_are_keyed_the_way_the_consumer_builds_its_keys():
    legs = pd.DataFrame([
        {"game_id": 1, "team": "AAA", "pid": 11, "market": "SOG", "role": "L1", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "AAA", "pid": 11, "market": "POINTS", "role": "L1", "p": 0.5, "over": 0},
        {"game_id": 1, "team": "AAA", "pid": 12, "market": "ASSISTS", "role": "D1", "p": 0.4, "over": 1},
        {"game_id": 1, "team": "BBB", "pid": 21, "market": "SAVES", "role": "G", "p": 0.5, "over": 0},
        {"game_id": 2, "team": "CCC", "pid": 31, "market": "SOG", "role": "L2", "p": 0.5, "over": 1}])
    legs["type"] = legs.market + "|" + legs.role
    pr = nhl.build_pairs(legs, ("p",))
    assert len(pr["game"]) == 6 and set(pr["game"]) == {1}           # within a game only; a lone leg pairs with nobody
    for k in range(6):
        ta, tb = pr["types"][pr["ta"][k]], pr["types"][pr["tb"][k]]
        assert ta <= tb                                              # `rho_for` sorts the two types
        assert pr["markets"][pr["ma"][k]] == ta.split("|")[0] and pr["markets"][pr["mb"][k]] == tb.split("|")[0]
    rel = {(pr["types"][a], pr["types"][b]): nhl.REL[r] for a, b, r in zip(pr["ta"], pr["tb"], pr["rel"])}
    assert rel[("POINTS|L1", "SOG|L1")] == "same_player"
    assert rel[("ASSISTS|D1", "SOG|L1")] == "teammate"
    assert rel[("SAVES|G", "SOG|L1")] == "opponent"


# ------------------------------------------------------------------------------------------- thresholds
@pytest.mark.parametrize("past,market,line", [
    ([2, 2, 3, 1, 2], "SOG", 1.5),           # integer median 2, mean 2.0 not above it -> down
    ([2, 3, 3, 2, 4], "SOG", 2.5),           # median 3, mean 2.8 -> down
    ([3, 3, 4, 2, 4], "SOG", 3.5),           # median 3, mean 3.2 -> up
    ([3, 4, 3, 4], "SOG", 3.5),              # an even count's median is already x.5
    ([9, 9, 9, 9, 9], "SOG", 5.5),           # snapped to the highest typical line
    ([0, 0, 1, 0, 0], "POINTS", 0.5),
    ([1, 0, 1, 1, 2], "POINTS", 0.5),        # median 1, mean 1.0 -> 0.5
    ([1, 2, 1, 1, 3], "POINTS", 1.5),        # median 1, mean 1.6 -> 1.5 where the rate supports it
    ([0, 1, 2, 0, 1], "GOALS", 0.5),         # goals and assists are 0.5 whatever the rate
    ([25, 30, 22, 28, 27], "SAVES", 26.5),   # median 27, mean 26.4 -> down
])
def test_proxy_line(past, market, line):
    assert nhl.proxy_line(past, market) == line


def test_marginals_shrink_a_players_prior_rate_to_his_roles():
    legs = pd.DataFrame([{"market": "SOG", "role": "L1", "line": 2.5, "over": o, "prior_n": 0, "prior_overs": 0}
                         for o in [1] * 49 + [0] * 49])
    rates = nhl.role_rates(legs)
    one = pd.DataFrame([{"market": "SOG", "role": "L1", "line": 2.5, "prior_n": 10, "prior_overs": 8},
                        {"market": "SOG", "role": "L4", "line": 2.5, "prior_n": 10, "prior_overs": 8}])
    out = nhl.attach_marginals(one, rates, k=20.0)
    assert out.p_role.iloc[0] == pytest.approx(0.5)                    # (49 + 1) / (98 + 2)
    assert out.p_player.iloc[0] == pytest.approx((8 + 20 * 0.5) / 30)
    assert out.p_role.iloc[1] == pytest.approx(0.5)                    # unseen role -> the (market, line) rate


# ------------------------------------------------------------------------------------------- leak-free roles
def _season(n_games: int = 12, star_game: int | None = None) -> pd.DataFrame:
    """Two teams; forward k plays 20 - k minutes and shoots k % 4. In `star_game` the 4th-line forward plays 99
    minutes and shoots 9 -- what happens tonight must not move tonight's role or line."""
    rows = []
    for g in range(n_games):
        for team, opp in (("AAA", "BBB"), ("BBB", "AAA")):
            base = 1000 if team == "AAA" else 2000
            for k in range(12):
                toi, shots = 20.0 - k, k % 4
                if g == star_game and team == "AAA" and k == 11:
                    toi, shots = 99.0, 9
                rows.append({"game_id": 2023020000 + g, "start": f"2023-10-{10 + g:02d}T23:00:00Z", "team": team,
                             "opp": opp, "pid": base + k, "name": f"F. P{k}", "pos": "F", "toi": toi, "shots": shots,
                             "goals": 0, "assists": k % 2, "points": k % 2, "saves": 0, "starter": None})
            for k in range(6):
                rows.append({"game_id": 2023020000 + g, "start": f"2023-10-{10 + g:02d}T23:00:00Z", "team": team,
                             "opp": opp, "pid": base + 50 + k, "name": f"D. Q{k}", "pos": "D", "toi": 25.0 - k,
                             "shots": 1, "goals": 0, "assists": 0, "points": 0, "saves": 0, "starter": None})
            rows.append({"game_id": 2023020000 + g, "start": f"2023-10-{10 + g:02d}T23:00:00Z", "team": team,
                         "opp": opp, "pid": base + 99, "name": "G. Keeper", "pos": "G", "toi": 60.0, "shots": 0,
                         "goals": 0, "assists": 0, "points": 0, "saves": 25 + g, "starter": True})
    return pd.DataFrame(rows).sort_values(["start", "game_id", "team", "pid"]).reset_index(drop=True)


def test_roles_come_from_earlier_games_only():
    plain, star = _season(), _season(star_game=9)
    r_plain, r_star = nhl.line_slots(plain), nhl.line_slots(star)
    g0, g9 = 2023020000, 2023020009
    assert r_plain[(g0, 1000)] == "UNK"                         # no earlier game, no slot
    assert r_plain[(g9, 1000)] == "L1" and r_plain[(g9, 1011)] == "L4"
    assert r_plain[(g9, 1050)] == "D1" and r_plain[(g9, 1055)] == "D3"
    assert r_plain[(g9, 1099)] == "G"
    assert r_star[(g9, 1011)] == "L4"                           # 99 minutes TONIGHT does not promote him tonight
    assert r_star[(2023020010, 1011)] == "L1"                   # ... it counts from the next game on (avg 20.25)


def test_proxy_lines_come_from_earlier_games_only():
    plain, star = _season(), _season(star_game=9)
    h_plain, h_star = nhl.season_history(plain), nhl.season_history(star)
    key = (h_plain.game_id == 2023020009) & (h_plain.pid == 1011)
    a, b = h_plain[key].iloc[0], h_star[(h_star.game_id == 2023020009) & (h_star.pid == 1011)].iloc[0]
    assert a.prior_n == b.prior_n == 9
    assert a.line_SOG == b.line_SOG == nhl.proxy_line([3] * 9, "SOG")   # tonight's 9 shots unseen
    early = h_plain[(h_plain.game_id == 2023020003) & (h_plain.pid == 1011)].iloc[0]
    assert early.prior_n == 3 and pd.isna(early.get("line_SOG"))       # < MIN_PRIOR earlier games: no leg
    legs = nhl.proxy_legs(star, h_star, nhl.line_slots(star), 2023)
    tonight = legs[(legs.game_id == 2023020009) & (legs.pid == 1011) & (legs.market == "SOG")].iloc[0]
    assert tonight.over == 1 and tonight.role == "L4"                   # graded on tonight, typed on before
    saves = legs[(legs.market == "SAVES") & (legs.game_id == 2023020009) & (legs.pid == 1099)].iloc[0]
    assert saves.line == nhl.proxy_line([25 + g for g in range(9)], "SAVES") and saves.role == "G"


# ------------------------------------------------------------------------------------------- box scores and books
def _box(game_type: int = 2) -> dict:
    def sk(pid, name, pos, toi, sog, g, a):
        return {"playerId": pid, "name": {"default": name}, "position": pos, "toi": toi, "sog": sog, "goals": g,
                "assists": a, "points": g + a, "blockedShots": 0}

    def gk(pid, name, toi, saves, starter):
        return {"playerId": pid, "name": {"default": name}, "position": "G", "toi": toi, "saves": saves,
                "shotsAgainst": saves + 2, "starter": starter, "decision": "W"}
    return {"id": 2025020500, "gameType": game_type, "gameState": "OFF", "startTimeUTC": "2025-12-14T00:00:00Z",
            "homeTeam": {"abbrev": "NYR", "placeName": {"default": "New York"}, "commonName": {"default": "Rangers"}},
            "awayTeam": {"abbrev": "OTT", "placeName": {"default": "Ottawa"}, "commonName": {"default": "Senators"}},
            "playerByGameStats": {
                "homeTeam": {"forwards": [sk(1, "A. Panarin", "L", "19:30", 0, 0, 1), sk(2, "S. Scratch", "C", "00:00", 0, 0, 0)],
                             "defense": [sk(3, "A. Fox", "D", "23:10", 2, 0, 0)],
                             "goalies": [gk(4, "I. Shesterkin", "60:00", 30, True), gk(5, "J. Backup", "00:00", 0, False)]},
                "awayTeam": {"forwards": [sk(6, "T. Stützle", "C", "20:01", 5, 1, 0)], "defense": [],
                             "goalies": [gk(7, "L. Ullmark", "58:30", 25, True)]}}}


def test_player_rows_keep_the_regular_season_players_who_played():
    rows = {r["pid"]: r for r in nhl.player_rows(_box())}
    assert set(rows) == {1, 3, 4, 6, 7}                         # 0:00 ice time = did not play (a book voids him)
    assert rows[1]["shots"] == 0 and rows[1]["points"] == 1     # a zero stays a zero (boxscore_log's fix)
    assert rows[1]["team"] == "NYR" and rows[1]["opp"] == "OTT" and rows[3]["pos"] == "D"
    assert rows[4]["saves"] == 30 and rows[4]["starter"] is True and rows[6]["toi"] == pytest.approx(20 + 1 / 60)
    assert nhl.player_rows(_box(game_type=1)) == [] and nhl.player_rows(_box(game_type=3)) == []


def test_book_names_meet_box_score_names_across_accents():
    assert nhl._key("Tim Stützle") == nhl._key("T. Stützle") == nhl._key("Tim Stutzle") == ("t", "stutzle")


def test_the_consensus_leg_is_the_line_most_books_quote_two_way_at_the_median_devig():
    snap = {"bookmakers": [
        {"key": "dk", "markets": [{"key": "player_shots_on_goal", "outcomes": [
            {"name": "Over", "description": "Tim Stutzle", "price": -130, "point": 2.5},
            {"name": "Under", "description": "Tim Stutzle", "price": 100, "point": 2.5}]}]},
        {"key": "fd", "markets": [{"key": "player_shots_on_goal", "outcomes": [
            {"name": "Over", "description": "Tim Stutzle", "price": -120, "point": 2.5},
            {"name": "Under", "description": "Tim Stutzle", "price": -110, "point": 2.5},
            {"name": "Over", "description": "Tim Stutzle", "price": 150, "point": 3.5},
            {"name": "Under", "description": "Tim Stutzle", "price": -200, "point": 3.5}]}]},
        {"key": "mgm", "markets": [{"key": "player_shots_on_goal", "outcomes": [
            {"name": "Over", "description": "Tim Stutzle", "price": 140, "point": 3.5}]}]},     # one side: not a line
    ]}
    legs = nhl.consensus_legs(nhl.snapshot_quotes(snap))
    assert len(legs) == 1
    leg = legs[0]
    assert leg["market"] == "SOG" and leg["line"] == 2.5 and leg["n_books"] == 2
    dk = (130 / 230) / (130 / 230 + 0.5)
    fd = (120 / 220) / (120 / 220 + 110 / 210)
    assert leg["fair"] == pytest.approx((dk + fd) / 2)
