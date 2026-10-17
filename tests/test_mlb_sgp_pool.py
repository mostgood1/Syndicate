"""High-hit-rate MLB parlays from every priced alt rung (user 2026-10-17: "we need sgp work done for alll sports"). The
NHL design with MLB's reads: the market, the last 10 (hitters with a plate appearance, pitchers' starts), the sim's own
histogram; lineup hitters and listed starters only; accent-folded names; nested stat pairs never paired."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import mlb_sgp_pool as M

DAY = "2026-10-17"
HIT_COLS = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "opponent", "pa", "ab", "h", "tb",
            "hr", "rbi", "r", "so"]
PIT_COLS = ["date", "season", "game_type", "game_pk", "player_id", "player_name", "team", "is_starter", "outs", "k", "er", "h"]


def _csv(path: Path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _world(root: Path, *, ramirez_lineup=True):
    data = root / "mlb_source" / "source_artifacts" / "data"
    hits = []
    for i in range(12):
        d = f"2026-10-{16 - i:02d}" if i < 16 else "2026-09-30"
        hits.append({"date": d, "game_pk": 100 + i, "player_id": "608070", "player_name": "José Ramírez", "team": "Cleveland Guardians",
                     "pa": 4, "h": [1, 2, 1, 0, 1, 3, 1, 2, 1, 1, 2, 1][i], "tb": 2, "hr": 0, "rbi": 1, "r": 1, "so": 1})
        hits.append({"date": d, "game_pk": 100 + i, "player_id": "650490", "player_name": "Yandy Díaz", "team": "Tampa Bay Rays",
                     "pa": 4, "h": 1, "tb": 1, "hr": 0, "rbi": 0, "r": 0, "so": 1})
    hits.append({"date": "2026-10-04", "game_pk": 999, "player_id": "608070", "player_name": "José Ramírez", "team": "Cleveland Guardians",
                 "pa": 0, "h": 0})                                  # a pinch-run appearance: no plate appearance, not a game
    _csv(data / "derived" / "mlb_player_game_log_2026_hitting.csv", HIT_COLS, hits)
    starts = [{"date": f"2026-{9 - (i // 6):02d}-{28 - (i % 6) * 4:02d}", "game_pk": 200 + i, "player_id": "607259",
               "player_name": "Nick Martinez", "is_starter": 1, "k": [5, 6, 4, 7, 5, 6, 5, 4, 6, 5, 7, 5][i], "outs": 18, "er": 2, "h": 5}
              for i in range(12)]
    starts += [{"date": f"2026-10-{10 - i:02d}", "game_pk": 300 + i, "player_id": "542888", "player_name": "Shawn Armstrong",
                "is_starter": 0, "k": 2, "outs": 3} for i in range(8)]   # an opener: relief outings are not starts
    _csv(data / "derived" / "mlb_player_game_log_2026_pitching.csv", PIT_COLS, starts)
    sim = {"game_pk": 849816, "away": {"name": "Tampa Bay Rays", "abbreviation": "TB"},
           "home": {"name": "Cleveland Guardians", "abbreviation": "CLE"},
           "starters": {"away": 607259, "home": 542888}, "starter_names": {"away": "Nick Martinez", "home": "Shawn Armstrong"},
           "sim": {"hitter_props": {
               "608070": {"name": "José Ramírez", "team": "CLE", "is_lineup_batter": ramirez_lineup, "hits_dist": {"0": 200, "1": 400, "2": 300, "3": 100},
                          "total_bases_dist": {"0": 200, "1": 300, "2": 300, "3": 200}},
               "650490": {"name": "Yandy Díaz", "team": "TB", "is_lineup_batter": True, "hits_dist": {"0": 300, "1": 500, "2": 200}}},
               "pitcher_props": {"607259": {"so_dist": {"2": 50.5, "3": 100.2, "4": 200.0, "5": 300.3, "6": 349.0}},
                                 "542888": {"so_dist": {"0": 300, "1": 500, "2": 200}}}}}
    (data / "daily" / "sims" / DAY).mkdir(parents=True)
    (data / "daily" / "sims" / DAY / "sim_0_TB_at_CLE_pk849816_g1.json").write_text(json.dumps(sim), encoding="utf-8")
    alt = root / "mlb_source" / "tracking" / "alt_ladders"
    alt.mkdir(parents=True)
    with open(alt / f"{DAY}.jsonl", "w", encoding="utf-8") as fh:
        for player, base, line, price in (("Jose Ramirez", "batter_hits", 0.5, -500), ("Jose Ramirez", "batter_total_bases", 0.5, -450),
                                          ("Yandy Diaz", "batter_hits", 0.5, -400), ("Nick Martinez", "pitcher_strikeouts", 2.5, -600),
                                          ("Shawn Armstrong", "pitcher_strikeouts", 0.5, -500)):
            for book in ("draftkings", "fanduel"):
                fh.write(json.dumps({"event_id": "m1", "home_team": "Cleveland Guardians", "away_team": "Tampa Bay Rays",
                                     "player": player, "base_market": base, "side": "Over", "line": line, "price": price,
                                     "bookmaker": book, "captured_at": "2026-10-17T23:00:00Z", "commence_time": "2026-10-18T00:00:00Z"}) + "\n")
    return root


def _sheet():
    return {"sport": "mlb", "date": DAY, "rows": [], "games": [{"event_id": "m1", "matchup": "Tampa Bay Rays @ Cleveland Guardians"}]}


def test_accents_fold_and_the_three_reads_admit_a_leg(tmp_path):
    assert M.fold("José Ramírez") == M.fold("Jose Ramirez") == "joseramirez" and M.fold("Victor Mesa Jr.") == "victormesa"
    pool, info = M.legs_by_game(_sheet(), _world(tmp_path), DAY)
    got = {(l["player"], l["market"], l["line"]) for l in pool["m1"]}
    assert ("Jose Ramirez", "batter_hits", 0.5) in got and ("Nick Martinez", "strikeouts", 2.5) in got
    leg = next(l for l in pool["m1"] if l["player"] == "Jose Ramirez" and l["market"] == "batter_hits")
    assert leg["player_id"] == "608070" and leg["games"] == 10 and leg["hits"] == 9 and leg["p_sim"] == 0.8
    assert all(g != "999" for g, _v in leg["_history"])                              # pa 0: not a game


def test_an_opener_has_no_starts_and_a_benched_hitter_is_out(tmp_path):
    pool, info = M.legs_by_game(_sheet(), _world(tmp_path, ramirez_lineup=False), DAY)
    names = {l["player"] for l in pool.get("m1", [])}
    assert "Shawn Armstrong" not in names and "Jose Ramirez" not in names
    assert info["counts"]["short_history"] >= 1 and info["counts"]["not_in_lineup"] >= 1


def test_the_histogram_reads_fractional_weights():
    assert abs(M.dist_over({"2": 50.5, "3": 100.2, "4": 200.0, "5": 300.3, "6": 349.0}, 2.5) - (949.5 / 1000.0)) < 1e-9
    assert M.dist_over({}, 1.5) is None


def test_nested_pairs_are_never_a_ticket():
    a = {"player": "X", "market": "batter_hits"}
    assert M.exclude(a, {"player": "X", "market": "batter_total_bases"}) and not M.exclude(a, {"player": "Y", "market": "batter_total_bases"})
    assert not M.exclude(a, {"player": "X", "market": "batter_strikeouts"})
    assert M.exclude({"player": "X", "market": "batter_total_bases"}, {"player": "X", "market": "batter_hits_runs_rbis"})


def test_the_reconcile_grades_from_the_game_log_and_pitchers_by_their_start(tmp_path):
    root = _world(tmp_path)
    log_path = root / "mlb_source" / "source_artifacts" / "data" / "derived" / "mlb_player_game_log_2026_hitting.csv"
    with open(log_path, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=HIT_COLS, extrasaction="ignore").writerow(
            {"date": DAY, "game_pk": 849816, "player_id": "608070", "pa": 4, "h": 0, "tb": 0, "hr": 0, "rbi": 0, "r": 0, "so": 2})
    ticket = {"legs": [{"player": "Jose Ramirez", "market": "batter_hits", "side": "over", "line": 0.5, "player_id": "608070"}]}
    acts = M.leg_actuals(root, DAY, [ticket])
    graded = cs.sgp_results([ticket], {"props": {}, "void": {}, "leg_actuals": acts})[0]
    assert graded["legs"][0]["actual"] == 0.0 and graded["status"] == "lost"


def test_the_hook_builds_nothing_without_measured_correlations(tmp_path):
    hook = M.hook()
    assert hook.load_cells(_world(tmp_path)) is None and hook.suggest(_sheet(), None, {}, data_root=tmp_path, day=DAY) == []
