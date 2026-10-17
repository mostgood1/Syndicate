"""Basketball SGP correlations (lane `basketball-sgp-builder`, 2026-10-17): roles, proxy lines, names, books, verdicts."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("scipy")
from scipy.special import ndtri  # noqa: E402

from syndicate.features.nfl.sgp import rho_for  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_basketball_sgp_correlations.py"
_spec = importlib.util.spec_from_file_location("build_basketball_sgp_correlations", _PATH)
bb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bb)


# ------------------------------------------------------------------------------------------- shared machinery
def test_the_estimator_is_the_nfl_studys_and_the_pairs_the_nhl_studys():
    for fn in (bb.fit_rho, bb.shrink_cells, bb.clustered_se, bb.four_cell):
        assert fn.__module__ == "build_nfl_sgp_correlations"
    for fn in (bb.build_pairs, bb.fit_cells, bb.evaluate, bb.consensus_legs, bb.attach_marginals):
        assert fn.__module__ == "build_nhl_sgp_correlations"
    assert bb.fit_cells.__globals__["fit_rho"] is bb.fit_rho             # one estimator instance, not a second load


def test_nested_same_player_lists_every_contained_pair_and_nothing_else():
    brief = {("PTS", "PRA"), ("REB", "PRA"), ("AST", "PRA"), ("PTS", "PR"), ("REB", "PR"), ("PTS", "PA"),
             ("AST", "PA"), ("REB", "RA"), ("AST", "RA"), ("PR", "PRA"), ("PA", "PRA"), ("RA", "PRA")}
    got = [k.split("~") for k in bb.NESTED_SAME_PLAYER]
    assert all(rel == "same_player" for _, _, rel in got)
    assert {frozenset((a, b)) for a, b, _ in got} == {frozenset(p) for p in brief}
    assert len(got) == 12
    # Keys are in the order `rho_for` builds market cells ('PRA|..' sorts before 'PR|..'): the list names cells.
    assert "PRA~PR~same_player" in bb.NESTED_SAME_PLAYER and "PRA~PTS~same_player" in bb.NESTED_SAME_PLAYER


def _legs(rows):
    legs = pd.DataFrame(rows)
    legs["type"] = legs.market + "|" + legs.role
    return legs


def test_pairs_keep_the_consumer_key_order_and_nested_pairs_are_split_off():
    legs = _legs([
        {"game_id": 1, "team": "ATL", "pid": 11, "market": "PR", "role": "S1", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "ATL", "pid": 11, "market": "PRA", "role": "S1", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "ATL", "pid": 11, "market": "FG3M", "role": "S1", "p": 0.5, "over": 0},
        {"game_id": 1, "team": "ATL", "pid": 12, "market": "PTS", "role": "B1", "p": 0.4, "over": 1},
        {"game_id": 1, "team": "CHI", "pid": 21, "market": "PRA", "role": "S2", "p": 0.5, "over": 0}])
    pr = bb.build_pairs(legs, ("p",))
    for k in range(len(pr["game"])):
        ta, tb = pr["types"][pr["ta"][k]], pr["types"][pr["tb"][k]]
        assert (ta, tb) == tuple(sorted((ta, tb)))
    main, nested = bb.split_nested(pr)
    assert len(nested["game"]) == 1                                      # PR x PRA, same player
    assert nested["markets"][nested["ma"][0]] == "PRA" and nested["markets"][nested["mb"][0]] == "PR"
    assert len(main["game"]) == len(pr["game"]) - 1                      # teammate / opponent PRA pairs stay


# ------------------------------------------------------------------------------------------- the estimator, end to end
def _simulated(n_games: int, r_team: float, c_same: float, seed: int) -> pd.DataFrame:
    """Two teams of 3 starters with PTS and AST legs: PTS latents share a team factor (teammate rho r_team); a player's
    AST latent loads c_same on his PTS latent; opponents independent."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        for t, team in enumerate(("ATL", "CHI")):
            f = rng.standard_normal()
            for k in range(3):
                z = np.sqrt(r_team) * f + np.sqrt(1 - r_team) * rng.standard_normal()
                w = c_same * z + np.sqrt(1 - c_same ** 2) * rng.standard_normal()
                for market, latent in (("PTS", z), ("AST", w)):
                    p = rng.uniform(0.3, 0.7)
                    rows.append({"game_id": 401000000 + g, "team": team, "pid": g * 10 + t * 5 + k, "market": market,
                                 "role": "S1", "p": p, "over": int(latent > ndtri(1 - p))})
    return _legs(rows)


def test_cells_recover_known_correlations_and_beat_independence_through_rho_for():
    cells = bb.fit_cells(bb.build_pairs(_simulated(2000, 0.3, 0.6, seed=3), ("p",)), "p")
    team, same = cells["type"]["PTS|S1~PTS|S1~teammate"], cells["type"]["AST|S1~PTS|S1~same_player"]
    opp = cells["type"]["PTS|S1~PTS|S1~opponent"]
    assert abs(team["rho"] - 0.3) < 3 * team["se"] + 0.02
    assert abs(same["rho"] - 0.6) < 3 * same["se"] + 0.02
    assert abs(opp["rho"]) < 3 * opp["se"] + 0.01
    out = bb.evaluate(bb.build_pairs(_simulated(1500, 0.3, 0.6, seed=4), ("p",)), cells, "p")
    assert out["relation=same_player"]["z"] < -5 and out["relation=teammate"]["z"] < -3
    assert out["level=role"]["pairs"] == out["all"]["pairs"]
    assert rho_for({"cells": bb.strip_cells(cells)}, "PTS|S1", "AST|S1", "same_player") == (same["rho"], "role")


def test_the_falsification_line_zeroes_a_whole_relation_and_leaves_the_others():
    cells = {"type": {"PTS|S1~PTS|S2~teammate": {"rho": 0.1, "se": 0.02}, "PTS|S1~PTS|S1~opponent": {"rho": 0.05, "se": 0.02},
                      "AST|S1~PTS|S1~same_player": {"rho": 0.3, "se": 0.02}},
             "market": {"PTS~PTS~opponent": {"rho": 0.04, "se": 0.01}, "PTS~PTS~teammate": {"rho": 0.08, "se": 0.01}}}
    oos = {"relation=same_player": {"diff": -0.02, "z": -9.0, "pairs": 10},
           "relation=teammate": {"diff": -0.001, "z": -1.9, "pairs": 10},          # below zero but |z| < 2
           "relation=opponent": {"diff": 0.0004, "z": 3.0, "pairs": 10}}           # worse than independence
    verdict = bb.falsify(cells, oos, "test")
    assert verdict["same_player"]["verdict"] == "measured"
    assert verdict["teammate"]["verdict"] == verdict["opponent"]["verdict"] == "no measured correlation"
    assert cells["type"]["AST|S1~PTS|S1~same_player"]["rho"] == 0.3
    for key in ("PTS|S1~PTS|S2~teammate", "PTS|S1~PTS|S1~opponent"):
        assert cells["type"][key]["rho"] == 0.0 and cells["type"][key]["falsified"] is True
    assert cells["market"]["PTS~PTS~opponent"]["rho"] == 0.0 and cells["market"]["PTS~PTS~opponent"]["rho_fitted"] == 0.04
    assert rho_for({"cells": cells}, "PTS|S2", "PTS|S1", "teammate") == (0.0, "role")   # independent at runtime
    assert bb.falsify({"type": {}, "market": {}}, {}, "empty")["teammate"]["verdict"] == "no measured correlation"


def test_masking_counts_zeroed_role_cells_that_hide_a_live_market_cell_and_the_ablation_reaches_it():
    cells = {"type": {"AST|S1~PTS|S2~teammate": {"rho": 0.0, "n": 400}, "AST|S1~PTS|S3~teammate": {"rho": 0.05, "n": 300},
                      "PTS|S1~PTS|S2~teammate": {"rho": 0.0, "n": 350},                      # its market cell is 0 too
                      "PTS|S1~PTS|S1~opponent": {"rho": 0.0, "n": 500, "falsified": True}},
             "market": {"AST~PTS~teammate": {"rho": 0.08}, "PTS~PTS~teammate": {"rho": 0.0},
                        "PTS~PTS~opponent": {"rho": 0.0, "falsified": True}}}
    m = bb.masking(cells)
    assert m["teammate"] == {"role_cells": 3, "role_cell_pairs": 1050, "masked_cells": 1, "masked_pairs": 400,
                             "masked_market_rho_mean_abs": 0.08}
    assert m["opponent"]["role_cells"] == 0 and m["same_player"]["masked_cells"] == 0
    assert rho_for({"cells": cells}, "AST|S1", "PTS|S2", "teammate") == (0.0, "role")          # hidden ...
    assert rho_for({"cells": bb.market_only(cells)}, "AST|S1", "PTS|S2", "teammate") == (0.08, "market")  # ... reached


# ------------------------------------------------------------------------------------------- thresholds
@pytest.mark.parametrize("past,market,line", [
    ([10, 12, 14, 9, 20], "PTS", 12.5),       # median 12, mean 13 -> up
    ([12, 12, 12, 12, 12], "PTS", 11.5),      # median 12, mean 12 -> down
    ([20, 22, 21, 23], "PTS", 21.5),          # an even count's median is already x.5
    ([0, 2, 1, 3, 2], "PTS", 4.5),            # floored at the book's 1st-percentile line
    ([0, 0, 1, 0, 0], "STL", 0.5),
    ([1, 2, 1, 1, 3], "BLK", 1.5),            # median 1, mean 1.6 -> up
    ([0, 0, 0, 0, 0], "FG3M", 0.5),           # median 0 -> -0.5 -> floor
    ([30, 25, 28, 31, 29], "PRA", 28.5),      # median 29, mean 28.6 -> down
])
def test_proxy_line(past, market, line):
    assert bb.proxy_line(past, market) == line


# ------------------------------------------------------------------------------------------- box scores and roles
_COLS = ["game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
         "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "source"]
_TEAMS = ("ATL", "CHI", "CON", "DAL")
_SCHEDULE = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
_FIRST = ("Alma", "Bree", "Cleo", "Dina", "Esme", "Faye", "Gwen", "Hana", "Iris", "Jade")
_LAST = ("Atwood", "Castillo", "Conroy", "Dunlap")      # unique full names AND unique initial + last


def _season_rows(season: int, n_games: int, seed: int, star: tuple[int, int] | None = None) -> list[dict]:
    """Four teams, ten players each; player k plays 36 - 3k minutes; stats Poisson around minutes, with a per-team-game
    factor so teammates co-move. `star` = (game index, team index): that team's 10th man plays 60 minutes."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        hi, ai = _SCHEDULE[g % len(_SCHEDULE)]
        gid = 401000000 + season * 1000 + g
        date = (pd.Timestamp(f"{season}-05-10") + pd.Timedelta(days=g // 2)).strftime("%Y-%m-%d")
        for ti, oi, ha in ((hi, ai, "home"), (ai, hi, "away")):
            pace = rng.gamma(20, 1 / 20)
            for k in range(10):
                mins = 36.0 - 3 * k
                if star == (g, ti) and k == 9:
                    mins = 60.0
                lam = mins / 36 * pace
                rows.append({"game_id": gid, "date": date, "season": season, "season_type": "regular",
                             "TEAM_ABBREVIATION": _TEAMS[ti], "opponent": _TEAMS[oi], "home_away": ha,
                             "PLAYER_ID": 1000 * (ti + 1) + k, "PLAYER_NAME": f"{_FIRST[k]} {_LAST[ti]}",
                             "position": "G", "starter": int(k < 5), "MIN": mins, "PTS": rng.poisson(15 * lam),
                             "REB": rng.poisson(5 * lam), "AST": rng.poisson(3 * lam), "FG3M": rng.poisson(1.5 * lam),
                             "STL": rng.poisson(0.8 * lam), "BLK": rng.poisson(0.5 * lam), "TOV": 1, "source": "espn"})
    return rows


def _write_log(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS)
        w.writeheader()
        w.writerows(rows)


def test_the_game_log_keeps_regular_season_players_who_played_and_drops_exhibitions(tmp_path):
    rows = _season_rows(2026, 2, seed=1)
    rows.append(dict(rows[0], PLAYER_ID=9999, MIN=0.0))                                   # did not play
    rows.append(dict(rows[0], game_id=1, season_type="playoffs"))                          # another population
    rows += [dict(rows[0], game_id=2, TEAM_ABBREVIATION="USA", opponent="WNBASTARS"),     # All-Star, labelled regular
             dict(rows[0], game_id=2, TEAM_ABBREVIATION="WNBASTARS", opponent="USA", PLAYER_ID=5)]
    _write_log(tmp_path / "log.csv", rows)
    pg, audit = bb.load_game_log(tmp_path / "log.csv", "wnba")
    assert set(pg.game_id) == {401000000 + 2026 * 1000, 401000000 + 2026 * 1000 + 1}
    assert audit["exhibition_games_dropped"] == 1 and audit["exhibition_teams"] == ["USA", "WNBASTARS"]
    assert audit["rows_no_minutes_dropped"] == 1 and 9999 not in set(pg.pid)
    r = pg.iloc[0]
    assert r.PRA == r.PTS + r.REB + r.AST and r.PR == r.PTS + r.REB and r.PA == r.PTS + r.AST and r.RA == r.REB + r.AST


def _pg(rows: list[dict], tmp_path: Path) -> pd.DataFrame:
    _write_log(tmp_path / "log.csv", rows)
    return bb.load_game_log(tmp_path / "log.csv", "wnba")[0]


def test_roles_come_from_earlier_games_only(tmp_path):
    plain = _pg(_season_rows(2026, 24, seed=2), tmp_path)
    star = _pg(_season_rows(2026, 24, seed=2, star=(18, 0)), tmp_path)
    r_plain, r_star = bb.rotation_roles(plain), bb.rotation_roles(star)
    g0, g18 = 401000000 + 2026 * 1000, 401000000 + 2026 * 1000 + 18
    assert r_plain[(g0, 1000)] == "UNK"                         # no earlier game, no role
    assert r_plain[(g18, 1000)] == "S1" and r_plain[(g18, 1004)] == "S5"
    assert r_plain[(g18, 1005)] == "B1" and r_plain[(g18, 1007)] == "B3" and r_plain[(g18, 1009)] == "UNK"
    assert r_star[(g18, 1009)] == "UNK"                         # 60 minutes TONIGHT does not promote him tonight
    later = [g for g in sorted(set(star.game_id)) if g > g18 and 1009 in set(star[star.game_id == g].pid)]
    # ... it counts from his team's next game on: (7 x 9 + 60) / 8 = 15.4 minutes ranks him 8th, past the 15-minute man.
    assert r_star[(later[0], 1009)] == "B3" and r_star[(later[0], 1007)] == "UNK"


def test_proxy_lines_and_legs_come_from_earlier_games_only(tmp_path):
    rows = _season_rows(2026, 24, seed=5)
    pg = _pg(rows, tmp_path)
    gid = sorted(set(pg.game_id))[18]
    bumped = _pg([dict(r, PTS=99) if (r["game_id"] == gid and r["PLAYER_ID"] == 1000) else r for r in rows], tmp_path)
    h_a, h_b = bb.season_history(pg), bb.season_history(bumped)
    a = h_a[(h_a.game_id == gid) & (h_a.pid == 1000)].iloc[0]
    b = h_b[(h_b.game_id == gid) & (h_b.pid == 1000)].iloc[0]
    past = pg[(pg.pid == 1000) & (pg.game_id < gid)].PTS.tolist()
    assert a.prior_n == b.prior_n == len(past) and a.line_PTS == b.line_PTS == bb.proxy_line(past, "PTS")
    legs = bb.proxy_legs(bumped, h_b, bb.rotation_roles(bumped), 2026)
    tonight = legs[(legs.game_id == gid) & (legs.pid == 1000) & (legs.market == "PTS")].iloc[0]
    assert tonight.over == 1 and tonight.role == "S1"          # graded on tonight, lined and typed on before
    assert set(legs.role) <= set(bb.SLOTS) and (legs.prior_n >= bb.MIN_PRIOR).all()
    assert set(legs.market) == set(bb.MARKETS)


# ------------------------------------------------------------------------------------------- names and books
def test_names_match_full_first_and_never_guess_between_two_williamses():
    idx = bb.name_index([1, 2, 3, 4, 5], ["Jalen Williams", "Jaylin Williams", "P.J. Washington", "Nikola Jokić",
                                          "Jaren Jackson Jr."])
    assert bb.match_name(idx, "Jalen Williams") == (1, "full")
    assert bb.match_name(idx, "Jaylin Williams") == (2, "full")
    assert bb.match_name(idx, "J. Williams") == (None, "ambiguous")      # first initial + last name names two players
    assert bb.match_name(idx, "PJ Washington") == (3, "full")
    assert bb.match_name(idx, "Nikola Jokic") == (4, "full")
    assert bb.match_name(idx, "Jaren Jackson") == (5, "full")
    assert bb.match_name(idx, "Nic Jokic") == (4, "short")
    assert bb.match_name(idx, "Someone Else") == (None, "unmatched")
    # The books' hyphenated surname against ESPN's short one (WNBA 2026: 'Skylar Diggins-Smith' / 'Skylar Diggins').
    espn = bb.name_index([7, 8], ["Skylar Diggins", "Shai Gilgeous-Alexander"])
    assert bb.match_name(espn, "Skylar Diggins-Smith") == (7, "hyphen")
    assert bb.match_name(espn, "Shai Gilgeous-Alexander") == (8, "full")
    two = bb.name_index([1, 2], ["Sam Diggins", "Skylar Diggins"])
    assert bb.match_name(two, "S. Diggins-Smith") == (None, "ambiguous")
    # The engine's registered alias table: the books' 'Carlton Carrington' is ESPN's 'Bub Carrington'.
    assert bb.match_name(bb.name_index([9], ["Bub Carrington"]), "Carlton Carrington") == (9, "full")


def test_a_looser_key_never_hands_an_absent_players_leg_to_his_namesake():
    season = bb.name_index([1, 2], ["Jalen Williams", "Jaylin Williams"])
    tonight = bb.name_index([2], ["Jaylin Williams"])                     # Jalen is out
    assert bb.match_name(tonight, "Jalen Williams") == (2, "short")      # what the bare rule would do
    assert bb.match_leg(tonight, season, "Jalen Williams", {2}) == (None, "void_namesake")
    assert bb.match_leg(tonight, season, "Jaylin Williams", {2}) == (2, "full")
    assert bb.match_leg(tonight, season, "J. Williams", {2}) == (2, "short")   # no full name to name anyone else


def _snap(players: list[tuple[str, str, float, int, int]], ts: str, commence: str) -> dict:
    books = {}
    for book, player, line, over, under in players:
        books.setdefault(book, []).extend([{"name": "Over", "description": player, "price": over, "point": line},
                                           {"name": "Under", "description": player, "price": under, "point": line}])
    return {"timestamp": ts, "data": {"commence_time": commence, "bookmakers": [
        {"key": b, "markets": [{"key": "player_points_rebounds_assists", "outcomes": o},
                               {"key": "player_turnovers", "outcomes": o}]} for b, o in books.items()]}}


def test_snapshot_quotes_map_the_basketball_markets_and_the_consensus_is_the_nfl_rule():
    snap = _snap([("dk", "A'ja Wilson", 30.5, -120, -110), ("fd", "A'ja Wilson", 30.5, -115, -105)], "t", "c")
    legs = bb.consensus_legs(bb.snapshot_quotes(snap["data"]))
    assert len(legs) == 1 and legs[0]["market"] == "PRA" and legs[0]["line"] == 30.5 and legs[0]["n_books"] == 2


def test_local_day_and_event_matching_through_the_team_registry():
    assert bb.local_day("2025-10-22T02:30:00Z") == "2025-10-21"           # a 10:30 PM ET tip
    pg = pd.DataFrame({"game_id": [7, 7, 8, 8], "team": ["GSW", "LAL", "BOS", "NYK"],
                       "start": ["2025-10-21", "2025-10-21", "2025-10-22", "2025-10-22"]})
    meta = {"e1": ("Los Angeles Lakers", "Golden State Warriors", "2025-10-22T02:30:00Z"),
            "e2": ("Boston Celtics", "New York Knicks", "2025-10-22T23:30:00Z"),
            "e3": ("New York Knicks", "Boston Celtics", "2025-10-22T23:30:00Z"),     # home / away swapped: still game 8
            "e4": ("Boston Celtics", "Golden State Warriors", "2025-10-22T23:30:00Z")}
    games, how = bb.match_events(meta, pg, "nba")
    assert games == {"e1": 7, "e2": 8, "e3": 8, "e4": None}
    assert how["events_unmatched"] == 1


def test_book_legs_grade_the_played_void_the_absent_and_keep_pregame_only(tmp_path):
    pg = _pg(_season_rows(2026, 12, seed=9), tmp_path)
    roles = bb.rotation_roles(pg)
    gid = int(sorted(set(pg.game_id))[10])
    star = pg[(pg.game_id == gid)].sort_values("MIN", ascending=False).iloc[0]
    odds = tmp_path / "odds"
    odds.mkdir()
    snap = _snap([("dk", star["name"], 10.5, -110, -110), ("dk", "Nobody Here", 10.5, -110, -110)],
                 "2026-05-15T22:45:00Z", "2026-05-15T23:00:00Z")
    (odds / f"{gid}.json").write_text(json.dumps({"game": str(gid), "snap": snap}))
    late = _snap([("dk", star["name"], 10.5, -110, -110)], "2026-05-15T23:05:00Z", "2026-05-15T23:00:00Z")
    (odds / "401999999.json").write_text(json.dumps({"game": "401999999", "snap": late}))
    quotes, q_audit = bb.snapshot_json_quotes(odds)
    assert set(quotes) == {gid} and q_audit["snapshot_not_pregame"] == 1
    legs, audit = bb.book_legs(quotes, pg, roles, 2026)
    assert len(legs) == 1 and audit["legs_unmatched_name"] == 1
    leg = legs.iloc[0]
    assert leg.pid == star.pid and leg.actual == star.PRA and leg.over == int(star.PRA > 10.5)
    assert leg.role == roles[(gid, star.pid)] and leg.type == f"PRA|{leg.role}" and leg.p_fair == pytest.approx(0.5)


# ------------------------------------------------------------------------------------------- the whole run, small
def test_a_small_run_writes_both_files_in_the_runtime_schema(tmp_path):
    root = tmp_path / "data"
    proc = root / "wnba_source" / "data" / "processed"
    proc.mkdir(parents=True)
    for season, seed in ((2024, 11), (2025, 12), (2026, 13)):
        _write_log(proc / f"player_game_log_{season}.csv", _season_rows(season, 18, seed=seed))
    pg = bb.load_game_log(proc / "player_game_log_2026.csv", "wnba")[0]
    odds = root / "backfill" / "wnba_props_2026" / "odds"
    odds.mkdir(parents=True)
    for gid, g in pg.groupby("game_id"):
        day = g.start.iloc[0]
        quotes = [(b, r.name, float(r.PTS) + (0.5 if (r.pid + gid) % 2 else -0.5), -110, -110)
                  for b in ("dk", "fd") for r in g.itertuples() if r.MIN >= 24]
        snap = _snap(quotes, f"{day}T22:45:00Z", f"{day}T23:00:00Z")
        for bk in snap["data"]["bookmakers"]:
            bk["markets"][0]["key"] = "player_points"
        (odds / f"{gid}.json").write_text(json.dumps({"game": str(gid), "snap": snap}))
    out = tmp_path / "out"
    assert bb.main(["--sport", "wnba", "--data-root", str(root), "--out", str(out), "--real-split", "2026-05-15"]) == 0
    for name in ("wnba_sgp_correlations.json", "wnba_sgp_correlations_proxy.json"):
        doc = json.loads((out / name).read_text(encoding="utf-8"))
        assert doc["schema"] == "wnba_sgp_correlations_v1" and doc["season_type"] == "REG"
        assert set(doc["cells"]) == {"type", "market"} and doc["nested_same_player"] == list(bb.NESTED_SAME_PLAYER)
        assert set(doc["falsification"]) >= set(bb.REL)
        for level in ("type", "market"):
            for key, cell in doc["cells"][level].items():
                ta, tb, rel = key.split("~")
                assert rel in bb.REL and {"rho", "se", "n"} <= set(cell)
                if level == "type":
                    assert rho_for(doc, ta, tb, rel) == (cell["rho"], "role")
                elif not doc["cells"]["type"]:                    # the consumer reaches a market cell by its key
                    assert rho_for(doc, f"{ta}|S1", f"{tb}|S2", rel) == (cell["rho"], "market")
    proxy = json.loads((out / "wnba_sgp_correlations_proxy.json").read_text(encoding="utf-8"))
    assert proxy["out_of_sample"]["A_proxy"]["train"] == [2024, 2025] and proxy["out_of_sample"]["A_proxy"]["holdout"] == [2026]
    # A role cell needs 300 pairs (one or two a game here); market cells pool the roles.
    assert proxy["cells"]["market"]["PTS~PTS~teammate"]["n"] >= 300
    assert proxy["engine_read"]["residuals"]["all_games"]
    assert all(not k.startswith(("PRA~PTS~same", "PRA~PR~same")) for k in proxy["cells"]["market"])  # nested: never fit
