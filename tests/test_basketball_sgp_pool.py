"""High-hit-rate WNBA / NBA parlays from every priced alt rung (lane `basketball-sgp-builder`, user 2026-10-17: "we need
sgp work done for alll sports - wnba needs all the same work done as NHL"). The NHL design with basketball's reads:
the market, the player's last 10 in the game log, the sim's Normal on its mean and spread; in tonight's sim with real
minutes; never a stat and a combo that contains it for one player."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from syndicate.features.shared import basketball_sgp_pool as B
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import sgp_hit_rate as shared

DAY = "2026-10-17"
HOME, AWAY = "Golden State Valkyries", "Atlanta Dream"
COLS = ["game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
        "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV"]


def _games(pid, name, team, pts, reb, mins=30, ast=None, start=0, kind="regular"):
    out = []
    for i, p in enumerate(pts):
        out.append({"game_id": f"g{team}{start + i}", "date": f"2026-10-{16 - i:02d}" if i < 16 else f"2026-09-{30 - (i - 16):02d}",
                    "season": 2026, "season_type": kind, "TEAM_ABBREVIATION": team, "PLAYER_ID": pid, "PLAYER_NAME": name,
                    "MIN": mins, "PTS": p, "REB": reb[i], "AST": (ast or [3] * len(pts))[i], "FG3M": 1})
    return out


def _world(root: Path, *, reese_min=34.0, preseason=False, log_end_shift=0):
    proc = root / "wnba_source" / "data" / "processed"
    proc.mkdir(parents=True)
    rows = (_games("1", "Angel Reese", "ATL", [18, 16, 20, 14, 22, 17, 19, 15, 21, 18, 16, 20], [12, 11, 13, 10, 14, 12, 9, 11, 13, 12, 10, 11], mins=36)
            + _games("2", "Rhyne Howard", "ATL", [20, 22, 15, 25, 18, 19, 24, 21, 17, 23], [4] * 10, mins=33)
            + _games("3", "Bench Player", "ATL", [2, 4, 0, 3, 5, 1, 2, 0, 3, 2], [1] * 10, mins=8)
            + _games("4", "Kayla Thornton", "GSV", [12, 14, 10, 15, 11, 13, 9, 16, 12, 14], [6] * 10, mins=31))
    if preseason:
        for r in rows[:12]:
            r["season_type"] = "preseason"
    with open(proc / "player_game_log_2026.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    sim = {"games": [{"home_tri": "GSV", "away_tri": "ATL", "sim": {"players": {
        "away": [{"player_name": "Angel Reese", "min_mean": reese_min, "pts_mean": 18.0, "pts_sd": 4.0, "reb_mean": 11.5,
                  "reb_sd": 2.5, "ast_mean": 3.0, "ast_sd": 1.2, "threes_mean": 0.4, "threes_sd": 0.6},
                 {"player_name": "Rhyne Howard", "min_mean": 32, "pts_mean": 20.0, "pts_sd": 5.0, "reb_mean": 4.0, "reb_sd": 1.5,
                  "ast_mean": 3.0, "ast_sd": 1.0, "threes_mean": 2.5, "threes_sd": 1.2}],
        "home": [{"player_name": "Kayla Thornton", "min_mean": 30, "pts_mean": 12.5, "pts_sd": 3.5, "reb_mean": 6.0,
                  "reb_sd": 2.0, "ast_mean": 2.0, "ast_sd": 1.0, "threes_mean": 1.5, "threes_sd": 1.0}]}}}]}
    (proc / f"cards_sim_detail_{DAY}.json").write_text(json.dumps(sim), encoding="utf-8")
    alt = root / "wnba_source" / "tracking" / "alt_ladders"
    alt.mkdir(parents=True)
    quotes = [("Angel Reese", "player_rebounds", 7.5, -600), ("Angel Reese", "player_points", 11.5, -500),
              ("Angel Reese", "player_points_rebounds", 22.5, -550), ("Rhyne Howard", "player_points", 12.5, -500),
              ("Rhyne Howard", "player_points", 24.5, 150), ("Kayla Thornton", "player_points", 7.5, -600),
              ("Bench Player", "player_points", 0.5, -700)]
    with open(alt / f"{DAY}.jsonl", "w", encoding="utf-8") as fh:
        for player, base, line, price in quotes:
            for book in ("draftkings", "fanduel"):
                fh.write(json.dumps({"event_id": "w1", "home_team": HOME, "away_team": AWAY, "player": player,
                                     "base_market": base, "side": "Over", "line": line, "price": price, "bookmaker": book,
                                     "captured_at": "2026-10-17T18:30:00Z", "commence_time": "2026-10-17T19:30:00Z"}) + "\n")
    return root


def _sheet():
    return {"sport": "wnba", "date": DAY, "rows": [], "games": [{"event_id": "w1", "matchup": f"{AWAY} @ {HOME}"}]}


def test_a_leg_needs_the_market_the_record_the_sim_and_real_minutes(tmp_path):
    pool, info = B.legs_by_game(_sheet(), _world(tmp_path), DAY, "wnba")
    got = {(l["player"], l["market"], l["line"]) for l in pool["w1"]}
    assert ("Angel Reese", "player_rebounds", 7.5) in got and ("Rhyne Howard", "player_points", 12.5) in got
    assert ("Rhyne Howard", "player_points", 24.5) not in got                 # +150: a long shot (market gate)
    assert not any(p == "Bench Player" for p, _m, _l in got)                  # not in tonight's sim
    assert info["counts"]["not_in_sim"] >= 1 and info["counts"]["market_gate"] >= 1
    reese = next(l for l in pool["w1"] if l["player"] == "Angel Reese" and l["market"] == "player_rebounds")
    assert reese["type"] == "REB|S1" and reese["hits"] == 10 and reese["player_id"] == "1" and reese["p_sim"] > 0.9


def test_a_short_minutes_projection_or_preseason_history_removes_the_player(tmp_path):
    pool, info = B.legs_by_game(_sheet(), _world(tmp_path, reese_min=8.0), DAY, "wnba")
    assert not any(l["player"] == "Angel Reese" for l in pool.get("w1", []))
    pool2, info2 = B.legs_by_game(_sheet(), _world(tmp_path / "pre", preseason=True), DAY, "wnba")
    c = info2["counts"]                         # every Reese game preseason: no regular/playoff history at all
    assert not any(l["player"] == "Angel Reese" for l in pool2.get("w1", [])) and c.get("no_game_log", 0) + c.get("short_history", 0) >= 1


def test_a_combo_sums_the_parts_and_never_pairs_with_its_own_part():
    sim = {"pts_mean": 18.0, "pts_sd": 4.0, "reb_mean": 11.0, "reb_sd": 3.0}
    assert abs(B.sim_over(sim, "PR", 29.0) - 0.5) < 1e-9 and B.sim_over(sim, "PRA", 30.0) is None   # no assists read
    a = {"player": "X", "type": "PTS|S1"}
    assert B.exclude(a, {"player": "X", "type": "PR|S1"}) and B.exclude(a, {"player": "X", "type": "PRA|S1"})
    assert not B.exclude(a, {"player": "X", "type": "REB|S1"}) and not B.exclude(a, {"player": "Y", "type": "PR|S1"})
    assert B.exclude({"player": "X", "type": "PA|S1"}, {"player": "X", "type": "PR|S1"})          # +0.92: one bet
    assert not B.exclude({"player": "X", "type": "PA|S1"}, {"player": "Y", "type": "PR|S1"})


def test_roles_rank_the_teams_minutes_over_its_recent_games(tmp_path):
    log = B.GameLog.load(_world(tmp_path), "wnba")
    roles = log.roles("ATL", before=DAY)
    assert roles["1"] == "S1" and roles["2"] == "S2" and roles["3"] == "S3"


def test_tickets_meet_their_tier_and_skip_nested_pairs(tmp_path):
    pool, _ = B.legs_by_game(_sheet(), _world(tmp_path), DAY, "wnba")
    out = B.tickets(pool, {}, _sheet()["games"])
    for t in out:
        spec = next(s for s in shared.TIERS if s["tier"] == t["tier"])
        assert t["p_joint"] >= spec["min_joint"]
        codes = {(l["player"], l["type"].split("|")[0]) for l in t["legs"]}
        assert not ({("Angel Reese", "REB"), ("Angel Reese", "PR")} <= codes)


def test_the_reconcile_grades_a_leg_from_the_game_log(tmp_path):
    root = _world(tmp_path)
    log_path = root / "wnba_source" / "data" / "processed" / "player_game_log_2026.csv"
    with open(log_path, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore").writerow(
            {"game_id": "final", "date": DAY, "season_type": "playoffs", "TEAM_ABBREVIATION": "ATL", "PLAYER_ID": "1",
             "PLAYER_NAME": "Angel Reese", "MIN": 35, "PTS": 9, "REB": 15, "AST": 2, "FG3M": 0})
    ticket = {"legs": [{"player": "Angel Reese", "market": "player_rebounds", "side": "over", "line": 7.5, "player_id": "1"},
                       {"player": "Angel Reese", "market": "player_points", "side": "over", "line": 11.5, "player_id": "1"}]}
    acts = B.leg_actuals(root, DAY, [ticket], sport="wnba")
    graded = cs.sgp_results([ticket], {"props": {}, "void": {}, "leg_actuals": acts})[0]
    assert [(l["result"], l["actual"]) for l in graded["legs"]] == [("won", 15.0), ("lost", 9.0)]


def test_the_sheet_hook_builds_nothing_without_measured_correlations(tmp_path):
    hook = B.for_sport("wnba")
    root = _world(tmp_path)
    assert hook.load_cells(root) is None and hook.suggest(_sheet(), None, {}, data_root=root, day=DAY) == []
    assert hook.current_roles(root, DAY) == {}


def test_the_newest_logged_game_is_reported_not_judged(tmp_path):
    # A schedule gap (WNBA 10-09 -> 10-17) and an offseason (NBA) both made a "stale" flag cry wolf: it is gone.
    pool, info = B.legs_by_game(_sheet(), _world(tmp_path), "2026-10-25", "wnba")
    assert info["log_last_date"] == "2026-10-16" and "stale_log" not in info


def test_nba_names_fold_accents_and_a_traded_player_is_found_league_wide(tmp_path):
    assert B._norm("Nikola Vučević") == B._norm("Nikola Vucevic") and B._norm("Pacôme Dadiet") == "pacomedadiet"
    log = B.GameLog([{"PLAYER_ID": "9", "game_id": "g1", "date": "2026-04-01", "season_type": "regular",
                      "TEAM_ABBREVIATION": "CHI", "PLAYER_NAME": "Nikola Vucevic", "MIN": 30, "PTS": 18}], "nba")
    assert log.resolve("Nikola Vučević", ("Boston Celtics", "Detroit Pistons")) == "9"   # now plays elsewhere


def test_the_sims_own_histogram_wins_over_its_normal():
    player = {"pts_mean": 20.0, "pts_sd": 5.0,
              "prop_distributions": {"pts": {"distribution": {"10": 100, "20": 300, "30": 100}}}}
    assert B.sim_over(player, "PTS", 15.5) == 0.8                               # 400 of 500 draws, not the Normal's 0.82
    assert abs(B.sim_over({"pra_mean": 30.0, "pra_sd": 10.0}, "PRA", 30.0) - 0.5) < 1e-9
