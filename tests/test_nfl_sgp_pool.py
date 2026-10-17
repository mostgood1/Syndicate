"""High-hit-rate NFL parlays from every priced alt rung (lane `nfl-sgp-builder`, user 2026-10-17: "once NHL is up and
running we need NFL to function the same way"). The NHL design with NFL's reads: the market, the player's last 10 in
the usage files, the sim's Normal on its projected mean and spread; ACTIVE on the roster and not Out / Doubtful."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from syndicate.features.nfl import sgp as core
from syndicate.features.nfl import sgp_pool as N
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import sgp_hit_rate as shared

DAY = "2026-10-18"
HOME, AWAY = "Atlanta Falcons", "Chicago Bears"


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)


def _world(root: Path, *, sim_mean=80.0, out=False) -> Path:
    nfl = root / "nfl_source"
    _csv(nfl / "schedule_2026.csv", [{"game_id": "2026_06_CHI_ATL", "season": 2026, "game_type": "REG", "week": 6,
                                       "gameday": DAY, "away_team": "CHI", "home_team": "ATL"}])
    # Bijan and Brian Robinson share an initial and a team: the full name has to decide
    _csv(nfl / "tracking" / "nflverse" / "roster" / "roster_2026.csv", [
        {"season": 2026, "team": "ATL", "position": "RB", "status": "ACT", "full_name": "Bijan Robinson", "gsis_id": "B1", "week": 6,
         "headshot_url": "https://x/b1.png"},
        {"season": 2026, "team": "ATL", "position": "RB", "status": "ACT", "full_name": "Brian Robinson", "gsis_id": "B2", "week": 6},
        {"season": 2026, "team": "CHI", "position": "WR", "status": "ACT", "full_name": "DJ Moore", "gsis_id": "D1", "week": 6},
        {"season": 2026, "team": "CHI", "position": "WR", "status": "RES", "full_name": "Rome Odunze", "gsis_id": "R1", "week": 6}])
    _csv(nfl / "tracking" / "nflverse" / "injuries" / "injuries_2026.csv",
         [{"season": 2026, "week": 6, "team": "CHI", "gsis_id": "D1", "full_name": "DJ Moore", "report_status": "Out" if out else ""}])
    lines = []
    for i in range(12):                                   # weeks 1-5 of 2026 and 7 of 2025's last weeks
        season, week = (2026, 5 - i) if i < 5 else (2025, 18 - (i - 5))
        lines.append({"player_id": "B1", "player_name": "B.Robinson", "team": "ATL", "season": season, "week": week,
                      "game_id": f"{season}_{week:02d}_ATL_X", "rush_yards": 90 + (i % 3) * 10, "receptions": 3})
        lines.append({"player_id": "D1", "player_name": "D.Moore", "team": "CHI", "season": season, "week": week,
                      "game_id": f"{season}_{week:02d}_CHI_X", "rec_yards": 20 + (i % 4) * 25, "receptions": 4})
    lines.append({"player_id": "B1", "season": 2026, "week": 6, "game_id": "2026_06_CHI_ATL", "rush_yards": 41})
    for year in (2026, 2025):
        (nfl / "fantasy").mkdir(parents=True, exist_ok=True)
        (nfl / "fantasy" / f"nfl_fantasy_usage_{year}.json").write_text(
            json.dumps({"player_game_lines": [l for l in lines if l["season"] == year]}), encoding="utf-8")
    (nfl / "nfl_prop_projections_2026_wk6.json").write_text(json.dumps({"sim_rows": [
        {"market": "rushing_yards::bijan robinson::79.5", "entity": "Bijan Robinson", "projected_value": sim_mean, "projected_sd": 18.0},
        {"market": "receiving_yards::dj moore::54.5", "entity": "DJ Moore", "projected_value": 55.0, "projected_sd": 22.0}]}), encoding="utf-8")
    alt = nfl / "tracking" / "alt_ladders"
    alt.mkdir(parents=True)
    with open(alt / f"{DAY}.jsonl", "w", encoding="utf-8") as fh:
        for player, base, line, price in (("Bijan Robinson", "player_rush_yds", 59.5, -500), ("Bijan Robinson", "player_rush_yds", 79.5, -120),
                                          ("DJ Moore", "player_reception_yds", 14.5, -700), ("Rome Odunze", "player_reception_yds", 9.5, -900)):
            for book in ("draftkings", "fanduel"):
                fh.write(json.dumps({"event_id": "nfl1", "home_team": HOME, "away_team": AWAY, "player": player,
                                     "base_market": base, "side": "Over", "line": line, "price": price, "bookmaker": book,
                                     "captured_at": "2026-10-18T16:00:00Z", "commence_time": "2026-10-18T17:00:00Z"}) + "\n")
    return root


def _sheet():
    return {"sport": "nfl", "date": DAY, "rows": [], "games": [{"event_id": "nfl1", "matchup": f"{AWAY} @ {HOME}"}]}


def test_the_week_and_the_season_come_from_the_schedule(tmp_path):
    root = _world(tmp_path)
    assert N.season_of(DAY) == 2026 and N.season_of("2027-01-10") == 2026 and N.week_of(root, DAY) == 6
    assert N.week_of(root, "2026-10-17") is None


def test_full_name_decides_when_initials_collide_on_one_team(tmp_path):
    roster = N.Roster.load(_world(tmp_path), 2026)
    assert roster.resolve("Bijan Robinson", (HOME, AWAY))["gsis_id"] == "B1"
    assert roster.resolve("Brian Robinson Jr.", (HOME, AWAY))["gsis_id"] == "B2"
    assert roster.resolve("DJ Moore", ("Green Bay Packers",)) is None              # not in this game


def test_a_leg_needs_the_three_reads_and_an_active_player(tmp_path):
    root = _world(tmp_path)
    pool, info = N.legs_by_game(_sheet(), root, DAY, {})
    got = {(l["player"], l["line"]) for l in pool.get("nfl1", [])}
    # Bijan 79.5 at -120 is a coin flip (market gate); Odunze is on reserve (not active)
    assert got == {("Bijan Robinson", 59.5), ("DJ Moore", 14.5)}
    assert info["counts"]["market_gate"] >= 1 and info["counts"]["not_active"] == 1 and info["week"] == 6
    leg = next(l for l in pool["nfl1"] if l["player"] == "Bijan Robinson")
    assert leg["player_id"] == "B1" and leg["games"] == 10 and leg["hits"] == 10 and leg["p_sim"] > 0.8
    assert leg["headshot_url"] == "https://x/b1.png" and leg["type"] == "Rushing Yards|UNK"
    # this week's own game (week 6) is never part of the record
    assert all(not g.startswith("2026_06") for g, _v in leg["_history"])


def test_ruled_out_and_a_disbelieving_sim_both_remove_the_leg(tmp_path):
    pool, info = N.legs_by_game(_sheet(), _world(tmp_path, out=True, sim_mean=40.0), DAY, {})
    assert not pool.get("nfl1") or all(l["player"] not in ("DJ Moore", "Bijan Robinson") for l in pool["nfl1"])
    assert info["counts"]["not_active"] == 2 and info["counts"]["sim_gate"] >= 1


def test_the_reconcile_grades_a_pool_leg_from_the_usage_file(tmp_path):
    root = _world(tmp_path)
    ticket = {"legs": [{"player": "Bijan Robinson", "market": "Rushing Yards", "side": "over", "line": 59.5, "player_id": "B1"}]}
    acts = N.leg_actuals(root, DAY, [ticket])
    graded = cs.sgp_results([ticket], {"props": {}, "void": {}, "leg_actuals": acts})[0]
    assert graded["legs"][0]["actual"] == 41.0 and graded["status"] == "lost"


def test_suggest_builds_the_tiers_from_the_pool_when_given_the_data_root(tmp_path):
    root = _world(tmp_path)
    out = core.suggest(_sheet(), {"cells": {}}, {}, data_root=root, day=DAY)
    assert all(t["family"] == "hit_rate" for t in out if t.get("tier"))
    for t in out:
        if t.get("tier"):
            spec = next(s for s in shared.TIERS if s["tier"] == t["tier"])
            assert t["p_joint"] >= spec["min_joint"] and core.payout(t["legs_product_odds"]) >= spec["min_decimal"] - 0.01


def test_the_cap_spreads_the_pool_across_players_near_the_sweet_spot():
    legs = [{"player": f"P{i}", "market": "Receptions", "p_market": 0.80 + 0.01 * (i % 10), "line": i} for i in range(30)]
    legs += [{"player": "P0", "market": "Receptions", "p_market": 0.95, "line": 99}]
    kept = shared.cap({"e": legs})["e"]
    assert len(kept) == shared.POOL_CAP and len({(l["player"], l["market"]) for l in kept}) == shared.POOL_CAP
    assert all(abs(l["p_market"] - shared.SWEET_SPOT) <= 0.06 for l in kept)
