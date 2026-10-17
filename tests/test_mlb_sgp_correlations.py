"""MLB SGP correlations (2026-10-17): game logs, proxy lines, market-cell keys, the estimator, falsification."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("scipy")
from scipy.special import ndtri  # noqa: E402

from syndicate.features.nfl.sgp import rho_for  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_mlb_sgp_correlations.py"
_spec = importlib.util.spec_from_file_location("build_mlb_sgp_correlations", _PATH)
mlb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mlb)


# ------------------------------------------------------------------------------------------- shared machinery
def test_the_estimator_is_the_nfl_studys_and_the_pairs_are_the_nhl_studys():
    # One estimator for every sport: a cell's rho means the same thing to `rho_for` whichever sport fitted it.
    for fn in (mlb.fit_rho, mlb.shrink_cells, mlb.clustered_se, mlb.four_cell):
        assert fn.__module__ == "build_nfl_sgp_correlations"
    for fn in (mlb.build_pairs, mlb.lookup_rho, mlb.attach_marginals, mlb.consensus_legs, mlb.shrink_second_moment):
        assert fn.__module__ == "build_nhl_sgp_correlations"


# ------------------------------------------------------------------------------------------- cell keys
def test_market_keys_are_built_the_way_rho_for_builds_them():
    # '_' sorts before '|', so `batter_hits_runs_rbis|UNK` < `batter_hits|UNK` -- the opposite of the bare names.
    assert mlb.cell_key("batter_hits", "batter_hits_runs_rbis", "same_player") == \
        "batter_hits_runs_rbis~batter_hits~same_player"
    assert mlb.cell_key("strikeouts", "batter_hits", "opponent") == "batter_hits~strikeouts~opponent"
    for a in mlb.MARKETS:
        for b in mlb.MARKETS:
            key = mlb.cell_key(a, b, "teammate")
            payload = {"cells": {"type": {}, "market": {key: {"rho": 0.123}}}}
            assert rho_for(payload, f"{a}|UNK", f"{b}|UNK", "teammate") == (0.123, "market")
            assert rho_for(payload, f"{b}|UNK", f"{a}|UNK", "teammate") == (0.123, "market")


def test_nested_same_player_pairs_are_the_eight_contained_stats_in_lookup_order():
    assert len(mlb.NESTED_SAME_PLAYER) == 8 and len(set(mlb.NESTED_SAME_PLAYER)) == 8
    assert "batter_hits_runs_rbis~batter_hits~same_player" in mlb.NESTED_SAME_PLAYER
    assert "batter_home_runs~batter_total_bases~same_player" in mlb.NESTED_SAME_PLAYER
    for key in mlb.NESTED_SAME_PLAYER:
        a, b, rel = key.split("~")
        assert rel == "same_player" and mlb.cell_key(a, b, rel) == key and mlb.KIND[a] == mlb.KIND[b] == "B"


# ------------------------------------------------------------------------------------------- game logs
def _logs() -> tuple[pd.DataFrame, pd.DataFrame]:
    def h(game, gtype, pid, name, team, opp, pa, hits, tb, hr, rbi, r, so, date="2026-04-01"):
        return {"date": date, "season": 2026, "game_type": gtype, "game_pk": game, "player_id": pid, "player_name": name,
                "team": team, "opponent": opp, "is_home": 1, "pa": pa, "ab": pa, "h": hits, "tb": tb, "hr": hr,
                "rbi": rbi, "r": r, "so": so, "bb": 0, "hbp": 0}

    def p(game, gtype, pid, name, team, opp, starter, k, hits, er, outs):
        return {"date": "2026-04-01", "season": 2026, "game_type": gtype, "game_pk": game, "player_id": pid,
                "player_name": name, "team": team, "opponent": opp, "is_home": 1, "is_starter": starter, "outs": outs,
                "k": k, "bb": 1, "er": er, "h": hits, "hr": 0, "pitches": 90, "batters_faced": 24}
    nyy, bos = "New York Yankees", "Boston Red Sox"
    hit = pd.DataFrame([
        h(1, "R", 592450, "Aaron Judge", nyy, bos, 4, 2, 5, 1, 2, 1, 1),
        h(1, "R", 11, "Pinch Hitter", nyy, bos, 1, 1, 1, 0, 0, 0, 0),
        h(1, "R", 12, "Defensive Sub", nyy, bos, 0, 0, 0, 0, 0, 0, 0),
        h(1, "R", 646240, "Rafael Devers", bos, nyy, 4, 0, 0, 0, 0, 0, 3),
        h(1, "R", 660271, "Shohei Ohtani", bos, nyy, 3, 1, 1, 0, 0, 1, 1),
        h(2, "D", 592450, "Aaron Judge", nyy, bos, 4, 4, 16, 4, 8, 4, 0, date="2026-10-05")])
    pit = pd.DataFrame([
        p(1, "R", 543037, "Gerrit Cole", nyy, bos, 1, 7, 5, 2, 18),
        p(1, "R", 21, "Some Reliever", nyy, bos, 0, 2, 0, 0, 3),
        p(1, "R", 660271, "Shohei Ohtani", bos, nyy, 1, 7, 4, 1, 17),
        p(2, "D", 543037, "Gerrit Cole", nyy, bos, 1, 12, 1, 0, 27)])
    return hit, pit


def test_player_games_keep_regular_season_started_hitters_and_starting_pitchers():
    hit, pit = _logs()
    pg, bench, audit = mlb.player_games(hit, pit, min_pa=2)
    assert set(pg.game_id) == {1}                                    # the postseason game is not in a fit
    rows = {(r.pid, r.kind): r for r in pg.itertuples(index=False)}
    assert set(rows) == {(592450, "B"), (646240, "B"), (660271, "B"), (543037, "P"), (660271, "P")}
    judge = rows[(592450, "B")]
    assert (judge.batter_hits, judge.batter_total_bases, judge.batter_home_runs) == (2, 5, 1)
    assert judge.batter_hits_runs_rbis == 2 + 1 + 2 and judge.batter_strikeouts == 1
    cole = rows[(543037, "P")]
    assert (cole.strikeouts, cole.hits_allowed, cole.earned_runs, cole.outs) == (7, 5, 2, 18)
    assert set(bench.pid) == {11, 12}                                # pa 1 and pa 0: not the posted population
    assert audit["hitter_rows_pa0"] == 1 and audit["hitter_rows_below_min_pa_with_pa"] == 1
    assert audit["starter_games"] == 2 and audit["games_with_two_teams"] == 1


@pytest.mark.parametrize("past,market,line", [
    ([1, 1, 0, 2, 1], "batter_hits", 0.5),            # median 1, mean 1.0 not above it -> down
    ([1, 2, 1, 1, 2], "batter_hits", 1.5),            # median 1, mean 1.4 -> up
    ([0, 0, 1, 0, 0], "batter_home_runs", 0.5),       # one line whatever the rate
    ([0, 0, 0, 0, 0], "batter_rbis", 0.5),            # median 0 -> -0.5, snapped to the lowest line
    ([1, 2, 4, 0, 2], "batter_total_bases", 1.5),     # median 2, mean 1.8 -> down
    ([3, 2, 4, 1, 2, 3], "batter_hits_runs_rbis", 2.5),   # an even count's median is already x.5
    ([6, 7, 5, 8, 6], "strikeouts", 6.5),             # median 6, mean 6.4 -> up
    ([18, 15, 17, 16, 19], "outs", 16.5),             # median 17, mean 17.0 -> down
    ([2, 9, 9, 9, 9], "earned_runs", 6.5),            # snapped to the highest line
])
def test_proxy_line(past, market, line):
    assert mlb.proxy_line(past, market) == line


def _season(n_games: int = 8, star_game: int | None = None) -> pd.DataFrame:
    """One hitter (pid 1) with one hit a game and one pitcher (pid 9) with 6 K a start; in `star_game` the hitter
    has 4 hits and the pitcher 14 K -- what happens tonight must not move tonight's line."""
    rows = []
    for g in range(n_games):
        hits, k = (4, 14) if g == star_game else (1, 6)
        base = {"game_id": 100 + g, "date": f"2026-04-{g + 1:02d}", "team": "AAA", "opp": "BBB", "pa": 4}
        rows.append({**base, "pid": 1, "name": "A. Hitter", "kind": "B",
                     **{m: 0.0 for m in mlb.BATTER_MARKETS}, "batter_hits": hits, "batter_total_bases": hits,
                     **{m: np.nan for m in mlb.PITCHER_MARKETS}})
        rows.append({**base, "pid": 9, "name": "P. Starter", "kind": "P", "team": "BBB", "opp": "AAA",
                     **{m: np.nan for m in mlb.BATTER_MARKETS}, "strikeouts": k, "hits_allowed": 5.0,
                     "earned_runs": 2.0, "outs": 18.0})
    return pd.DataFrame(rows)


def test_proxy_lines_come_from_earlier_games_only():
    plain, star = _season(), _season(star_game=6)
    h_plain, h_star = mlb.season_history(plain), mlb.season_history(star)
    for h in (h_plain, h_star):
        row = h[(h.game_id == 106) & (h.pid == 1)].iloc[0]
        assert row.prior_n == 6 and row.line_batter_hits == 0.5       # tonight's 4 hits unseen
        sp = h[(h.game_id == 106) & (h.pid == 9)].iloc[0]
        assert sp.line_strikeouts == 5.5 and sp.overs_strikeouts == 6
    early = h_plain[(h_plain.game_id == 103) & (h_plain.pid == 1)].iloc[0]
    assert early.prior_n == 3 and pd.isna(early.get("line_batter_hits"))   # < MIN_PRIOR earlier games: no leg
    legs = mlb.proxy_legs(star, h_star, 2026)
    tonight = legs[(legs.game_id == 106) & (legs.pid == 1) & (legs.market == "batter_hits")].iloc[0]
    assert tonight.over == 1 and tonight.type == "batter_hits|UNK"         # graded on tonight, lined on before
    assert set(legs[legs.pid == 9].market) == set(mlb.PITCHER_MARKETS)
    assert set(legs[legs.pid == 1].market) == set(mlb.BATTER_MARKETS)


# ------------------------------------------------------------------------------------------- the estimator
def _simulated_legs(n_games: int, r_team: float, c_same: float, s_pitch: float, seed: int) -> pd.DataFrame:
    """Each team: 3 batters with hits and runs legs and a starter with a strikeouts leg. Hits latents share the
    team's offense factor (teammate rho r_team); a batter's runs latent loads c_same on his hits latent; a starter's
    strikeouts latent loads -s_pitch on the OPPOSING offense factor. Each leg its own line."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        f = {"AAA": rng.standard_normal(), "BBB": rng.standard_normal()}
        for team, opp in (("AAA", "BBB"), ("BBB", "AAA")):
            for k in range(3):
                pid = g * 10 + (0 if team == "AAA" else 5) + k
                z = np.sqrt(r_team) * f[team] + np.sqrt(1 - r_team) * rng.standard_normal()
                w = c_same * z + np.sqrt(1 - c_same ** 2) * rng.standard_normal()
                for market, latent in (("batter_hits", z), ("batter_runs_scored", w)):
                    p = rng.uniform(0.3, 0.7)
                    rows.append({"game_id": 700000 + g, "team": team, "pid": pid, "market": market, "p": p,
                                 "over": int(latent > ndtri(1 - p))})
            kz = -s_pitch * f[opp] + np.sqrt(1 - s_pitch ** 2) * rng.standard_normal()
            p = rng.uniform(0.3, 0.7)
            rows.append({"game_id": 700000 + g, "team": team, "pid": g * 10 + (4 if team == "AAA" else 9),
                         "market": "strikeouts", "p": p, "over": int(kz > ndtri(1 - p))})
    legs = pd.DataFrame(rows)
    legs["role"] = "UNK"
    legs["type"] = legs.market + "|UNK"
    return legs


def test_market_cells_recover_known_teammate_same_player_and_pitcher_opponent_correlations():
    legs = _simulated_legs(2500, r_team=0.3, c_same=0.6, s_pitch=0.6, seed=7)
    cells = mlb.fit_cells(mlb.build_pairs(legs, ("p",)), "p")
    assert cells["type"] == {}                                                 # no role level for MLB
    m = cells["market"]
    team = m[mlb.cell_key("batter_hits", "batter_hits", "teammate")]
    same = m[mlb.cell_key("batter_hits", "batter_runs_scored", "same_player")]
    cross = m[mlb.cell_key("batter_hits", "batter_runs_scored", "teammate")]
    opp = m[mlb.cell_key("batter_hits", "batter_hits", "opponent")]
    k_vs_bats = m[mlb.cell_key("strikeouts", "batter_hits", "opponent")]
    k_own_bats = m[mlb.cell_key("strikeouts", "batter_hits", "teammate")]
    assert abs(team["rho"] - 0.3) < 3 * team["se"] + 0.02
    assert abs(same["rho"] - 0.6) < 3 * same["se"] + 0.02
    assert abs(cross["rho"] - 0.18) < 3 * cross["se"] + 0.02                  # c * r through the team factor
    assert abs(opp["rho"]) < 3 * opp["se"] + 0.01
    assert abs(k_vs_bats["rho"] + 0.6 * np.sqrt(0.3)) < 3 * k_vs_bats["se"] + 0.02   # SP K x opposing hits < 0
    assert abs(k_own_bats["rho"]) < 3 * k_own_bats["se"] + 0.01
    assert same["n"] == 2500 * 6 and same["games"] == 2500


def test_seasons_fitted_as_parts_equal_the_fit_on_their_union():
    # The fleet shares memory with production: the refit never concatenates the seasons' pairs.
    legs = _simulated_legs(800, 0.3, 0.6, 0.6, seed=5)
    early, late = legs[legs.game_id < 700400], legs[legs.game_id >= 700400]
    parts = [mlb.build_pairs(early, ("p",)), mlb.build_pairs(late, ("p",))]
    split = mlb.fit_cells(parts, "p")
    union = mlb.fit_cells(mlb.concat_pairs(parts), "p")
    assert split.keys() == union.keys() and split["market"].keys() == union["market"].keys()
    for key, cell in union["market"].items():
        assert split["market"][key] == cell


def test_a_prefix_market_pair_is_fitted_under_the_key_rho_for_reads():
    rng = np.random.default_rng(3)
    rows = []
    for g in range(400):
        for pid in range(4):
            z = rng.standard_normal()
            for market in ("batter_hits", "batter_hits_runs_rbis"):
                rows.append({"game_id": g, "team": "AAA" if pid < 2 else "BBB", "pid": pid, "market": market,
                             "p": 0.5, "over": int(z + 0.3 * rng.standard_normal() > 0)})
    legs = pd.DataFrame(rows).assign(role="UNK")
    legs["type"] = legs.market + "|UNK"
    cells = mlb.fit_cells(mlb.build_pairs(legs, ("p",)), "p")
    assert "batter_hits_runs_rbis~batter_hits~same_player" in cells["market"]
    rho, level = rho_for({"cells": cells}, "batter_hits|UNK", "batter_hits_runs_rbis|UNK", "same_player")
    assert level == "market" and rho > 0.8


def test_the_copula_beats_independence_out_of_sample_through_the_consumer_lookup():
    cells = mlb.fit_cells(mlb.build_pairs(_simulated_legs(1500, 0.3, 0.6, 0.6, seed=1), ("p",)), "p")
    out = mlb.evaluate(mlb.build_pairs(_simulated_legs(1500, 0.3, 0.6, 0.6, seed=2), ("p",)), cells, "p")
    assert out["relation=same_player_not_nested"]["z"] < -5
    assert out["relation=teammate"]["diff"] < 0 and out["relation=teammate"]["z"] < -3
    assert out["opponent:pitcher_batter"]["diff"] < 0 and out["opponent:pitcher_batter"]["z"] < -3
    assert abs(out["opponent:batter_batter"]["z"] or 0.0) < 4
    assert out["level=market"]["pairs"] == out["all"]["pairs"]                # every pair found its cell
    sp = out["relation=same_player_not_nested"]
    assert abs(sp["both_over_predicted"] - sp["both_over_realised"]) < 0.02   # calibrated both-over


def test_pair_masks_split_batters_and_pitchers_and_flag_nested_pairs():
    legs = pd.DataFrame([
        {"game_id": 1, "team": "AAA", "pid": 1, "market": "batter_hits", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "AAA", "pid": 1, "market": "batter_total_bases", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "AAA", "pid": 1, "market": "batter_strikeouts", "p": 0.5, "over": 0},
        {"game_id": 1, "team": "AAA", "pid": 9, "market": "strikeouts", "p": 0.5, "over": 1},
        {"game_id": 1, "team": "BBB", "pid": 8, "market": "strikeouts", "p": 0.5, "over": 0},
        {"game_id": 1, "team": "BBB", "pid": 2, "market": "batter_hits", "p": 0.5, "over": 0}])
    legs["type"] = legs.market + "|UNK"
    pr = mlb.build_pairs(legs, ("p",))
    masks = dict(mlb.pair_masks(pr))
    assert masks["all"].sum() == 15
    assert masks["relation=same_player_nested"].sum() == 1                    # hits x total bases
    assert masks["relation=same_player_not_nested"].sum() == 2
    assert masks["teammate:pitcher_batter"].sum() == 4                        # each starter x his own hitters' legs
    assert masks["opponent:pitcher_batter"].sum() == 4                        # each starter x the other side's bats
    assert masks["opponent:pitcher_pitcher"].sum() == 1
    assert masks["opponent:batter_batter"].sum() == 3 and masks["teammate:batter_batter"].sum() == 0


def test_a_relation_without_an_out_of_sample_gain_is_reported_as_none_and_zeroed():
    summary = {"relation=same_player_not_nested": {"diff": -0.05, "z": -20.0, "pairs": 10},
               "relation=same_player": {"diff": -0.09, "z": -40.0, "pairs": 12},
               "relation=teammate": {"diff": -0.001, "z": -1.5, "pairs": 100},      # below zero, but |z| < 2
               "relation=opponent": {"diff": 0.0, "z": None, "pairs": 100}}         # shrunk to 0 everywhere
    verdict = mlb.falsification(summary)
    assert verdict["same_player"]["verdict"] == "measured" and verdict["same_player"]["z"] == -20.0
    assert verdict["teammate"]["verdict"] == verdict["opponent"]["verdict"] == "no measured correlation"
    cells = {"type": {}, "market": {"batter_hits~batter_runs_scored~same_player": {"rho": 0.4},
                                    "batter_rbis~batter_runs_scored~teammate": {"rho": 0.1},
                                    "batter_hits~strikeouts~opponent": {"rho": -0.2}}}
    assert mlb.apply_falsification(cells, verdict) == 2
    m = cells["market"]
    assert m["batter_hits~batter_runs_scored~same_player"]["rho"] == 0.4
    assert m["batter_rbis~batter_runs_scored~teammate"] == {"rho": 0.0, "rho_before_falsification": 0.1,
                                                            "falsified": True}
    assert m["batter_hits~strikeouts~opponent"]["rho"] == 0.0


# ------------------------------------------------------------------------------------------- real book lines
def _snap(ts: str, start: str, quotes: list[tuple[str, str, str, float, int, int]]) -> dict:
    books: dict = {}
    for book, key, player, line, over, under in quotes:
        mk = books.setdefault(book, {}).setdefault(key, [])
        mk += [{"name": "Over", "description": player, "point": line, "price": over},
               {"name": "Under", "description": player, "point": line, "price": under}]
    return {"snap": {"timestamp": ts, "data": {"commence_time": start, "bookmakers": [
        {"key": b, "markets": [{"key": k, "outcomes": o} for k, o in mks.items()]} for b, mks in books.items()]}}}


def test_book_legs_grade_pregame_consensus_lines_against_the_game_log(tmp_path):
    hit, pit = _logs()
    pg, bench, _ = mlb.player_games(hit, pit)
    pre = _snap("2026-04-01T22:55:00Z", "2026-04-01T23:05:00Z", [
        ("dk", "batter_hits", "Aaron Judge", 0.5, -200, 160), ("fd", "batter_hits", "Aaron Judge", 0.5, -190, 150),
        ("dk", "batter_total_bases", "Aaron Judge", 1.5, 110, -140),
        ("dk", "batter_hits", "Pinch Hitter", 0.5, 120, -150),           # pa 1: did not start -> void
        ("dk", "batter_hits", "Nobody Here", 0.5, 120, -150),            # not in the log -> void
        ("dk", "pitcher_strikeouts", "Gerrit Cole", 6.5, -120, -110),
        ("dk", "pitcher_strikeouts", "Some Reliever", 1.5, -120, -110),  # not the starter -> dropped
        ("dk", "pitcher_strikeouts", "Shohei Ohtani", 7.0, -110, -110),  # 7 K at 7.0 -> push
        ("dk", "batter_hits", "Shohei Ohtani", 0.5, -150, 120)])         # his bat, not his arm
    (tmp_path / "1.json").write_text(json.dumps(pre), encoding="utf-8")
    late = _snap("2026-04-01T23:10:00Z", "2026-04-01T23:05:00Z", [("dk", "batter_hits", "Aaron Judge", 0.5, -200, 160)])
    (tmp_path / "2.json").write_text(json.dumps(late), encoding="utf-8")
    files = {1: [str(tmp_path / "1.json")], 2: [str(tmp_path / "2.json")]}
    legs, audit = mlb.book_legs(files, pg, 2026, bench)
    got = {(r.pid, r.market): r for r in legs.itertuples(index=False)}
    assert set(got) == {(592450, "batter_hits"), (592450, "batter_total_bases"), (543037, "strikeouts"),
                        (660271, "batter_hits")}
    assert got[(592450, "batter_hits")].over == 1 and got[(592450, "batter_hits")].n_books == 2
    assert got[(592450, "batter_total_bases")].over == 1 and got[(543037, "strikeouts")].over == 1
    assert got[(660271, "batter_hits")].type == "batter_hits|UNK"
    assert audit["snapshot_not_pregame"] == 1 and audit["legs_push"] == 1
    assert audit["legs_hitter_below_min_pa_void"] == 1 and audit["legs_void_or_unmatched"] == 1
    assert audit["legs_pitcher_not_starter_or_unmatched"] == 1
    judge = got[(592450, "batter_hits")]
    dk = (200 / 300) / (200 / 300 + 100 / 260)
    fd = (190 / 290) / (190 / 290 + 100 / 250)
    assert judge.fair == pytest.approx((dk + fd) / 2)
