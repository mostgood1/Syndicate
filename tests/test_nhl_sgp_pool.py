"""High-hit-rate NHL parlays from every priced alt rung (lane `nhl-sgp-builder`, user 2026-10-17: "use the consistency
sheets to build them so we can deliver high hit rates, not long shots ... alt lines hit rates and consistency data in
general + our sim engine data"; "Two tiers"; long shots "Off the sheet").

A leg needs three reads to agree -- the market, the player's last 10 in the game log, the sim -- and every leg carries
its game-log id so the reconcile can grade players the sheet never graded."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from syndicate.features.nfl import sgp as core
from syndicate.features.nhl import sgp as nsgp
from syndicate.features.nhl import sgp_pool as P
from syndicate.features.shared import cheat_sheets as cs

DAY = "2026-10-17"
HOME, AWAY = "Washington Capitals", "New Jersey Devils"
LOG_COLS = ["gamePk", "date", "team", "player_id", "player", "primary_position", "role", "shots", "goals", "assists",
            "blocked", "timeOnIce", "saves", "shotsAgainst", "decision"]


def _log_rows(pid, name, team, shots, *, start=20000, saves=None):
    rows = []
    for i, s in enumerate(shots):              # newest first: game i is i days before 10-17
        day = 16 - i
        rows.append({"gamePk": f"202602{start + i:04d}", "date": f"2026-10-{day:02d}T23:00:00Z", "team": team,
                     "player_id": pid, "player": f"{{'default': '{name}'}}", "shots": "" if saves else s, "goals": 0,
                     "assists": 0, "timeOnIce": "18:00", "saves": saves[i] if saves else ""})
    return rows


def _write_world(root: Path, *, sim_lambda=3.0, preseason=False):
    raw = root / "nhl_source" / "source_artifacts" / "data" / "raw"
    raw.mkdir(parents=True)
    rows = (_log_rows("1", "A. Ovechkin", HOME, [3, 2, 4, 1, 2, 3, 5, 2, 1, 3])
            + _log_rows("2", "D. Strome", HOME, [2, 1, 1, 2, 3, 1, 1, 2, 1, 2], start=20100)
            + _log_rows("3", "J. Hughes", AWAY, [4, 3, 5, 2, 3, 4, 2, 3, 6, 3], start=20200)
            + _log_rows("4", "S. Noesen", AWAY, [0, 1, 0, 2, 0, 1, 0, 0, 1, 0], start=20300))
    if preseason:
        rows[0]["gamePk"] = "2026010001"            # a preseason game is another population
    with open(raw / "player_game_stats.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    proc = root / "nhl_source" / "data" / "processed"
    proc.mkdir(parents=True)
    with open(proc / f"props_recommendations_{DAY}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["player", "market", "proj_lambda"])
        w.writeheader()
        for name, lam in (("Alex Ovechkin", sim_lambda), ("Dylan Strome", 2.4), ("Jack Hughes", 3.6), ("Stefan Noesen", 0.6)):
            w.writerow({"player": name, "market": "SOG", "proj_lambda": lam})
    with open(proc / f"lineups_{DAY}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["full_name", "team", "position", "line_slot", "proj_toi"])
        w.writeheader()
        for name, team, slot in (("Alex Ovechkin", "WSH", "L1"), ("Dylan Strome", "WSH", "L1"), ("Jack Hughes", "NJD", "L1"),
                                 ("Stefan Noesen", "NJD", "L3")):
            w.writerow({"full_name": name, "team": team, "position": "F", "line_slot": slot, "proj_toi": 18})
    alt = root / "nhl_source" / "tracking" / "alt_ladders"
    alt.mkdir(parents=True)
    # Three legs priced just inside the 75% gate (-375 de-vigs to 75.1%): every ticket must pay +100 or better
    # (2026-10-20), and three legs at the gate multiply to about +103 -- heavier favourites cannot reach it.
    quotes = [("Alex Ovechkin", 0.5, -375), ("Alex Ovechkin", 1.5, -300), ("Alex Ovechkin", 2.5, 120),
              ("Dylan Strome", 0.5, -375), ("Jack Hughes", 0.5, -380), ("Jack Hughes", 1.5, -450),
              ("Stefan Noesen", 0.5, -600)]
    with open(alt / f"{DAY}.jsonl", "w", encoding="utf-8") as fh:
        for player, line, price in quotes:
            for book in ("draftkings", "fanduel"):
                fh.write(json.dumps({"event_id": "ev1", "home_team": HOME, "away_team": AWAY, "player": player,
                                     "base_market": "player_shots_on_goal", "side": "Over", "line": line, "price": price,
                                     "bookmaker": book, "captured_at": "2026-10-17T15:40:00Z",
                                     "commence_time": "2026-10-17T17:10:00Z"}) + "\n")
    return root


def _sheet():
    return {"sport": "nhl", "date": DAY, "rows": [], "ladders": [],
            "games": [{"event_id": "ev1", "matchup": f"{AWAY} @ {HOME}", "commence_time": "2026-10-17T17:10:00Z"}]}


def test_a_leg_needs_the_market_the_record_and_the_sim_to_agree(tmp_path):
    root = _write_world(tmp_path)
    pool, info = P.legs_by_game(_sheet(), root, DAY, nsgp.lineup_roles(root, DAY))
    got = {(l["player"], l["line"]) for l in pool["ev1"]}
    # Ovechkin o2.5 is a long shot and o1.5 at -300 de-vigs to 71% (market gate, 75%); Noesen o0.5 cleared 4 of 10
    assert ("Alex Ovechkin", 2.5) not in got and ("Alex Ovechkin", 1.5) not in got and ("Stefan Noesen", 0.5) not in got
    assert {("Alex Ovechkin", 0.5), ("Dylan Strome", 0.5), ("Jack Hughes", 0.5), ("Jack Hughes", 1.5)} == got
    c = info["counts"]
    assert c["market_gate"] == 2 and c["record_gate"] >= 1 and c["legs"] == 4
    leg = next(l for l in pool["ev1"] if l["player"] == "Alex Ovechkin" and l["line"] == 0.5)
    assert leg["player_id"] == "1" and leg["hits"] == 10 and leg["games"] == 10 and leg["p_sim"] > 0.9
    assert abs(leg["p_side"] - cs.consistency_posterior(leg["p_market"], 10, 10)) < 2e-4    # market-anchored


def test_the_sim_vetoes_a_leg_it_does_not_believe(tmp_path):
    root = _write_world(tmp_path, sim_lambda=0.9)          # the sim makes Ovechkin 1+ SOG ~59%: out, whatever his record
    pool, info = P.legs_by_game(_sheet(), root, DAY, nsgp.lineup_roles(root, DAY))
    assert not any(l["player"] == "Alex Ovechkin" for l in pool["ev1"]) and info["counts"]["sim_gate"] >= 1


def test_preseason_games_never_count_toward_the_record(tmp_path):
    root = _write_world(tmp_path, preseason=True)
    pool, info = P.legs_by_game(_sheet(), root, DAY, nsgp.lineup_roles(root, DAY))
    assert not any(l["player"] == "Alex Ovechkin" for l in pool["ev1"]) and info["counts"]["short_history"] >= 1


def test_tickets_meet_their_tier_and_one_rung_per_player_stat(tmp_path):
    root = _write_world(tmp_path)
    pool, _ = P.legs_by_game(_sheet(), root, DAY, nsgp.lineup_roles(root, DAY))
    out = P.tickets(pool, {}, _sheet()["games"])
    assert out and all(t["family"] == "hit_rate" and t["tier"] in ("safer", "payout") for t in out)
    for t in out:
        spec = next(s for s in P.TIERS if s["tier"] == t["tier"])
        assert t["size"] in spec["sizes"] and t["p_joint"] >= spec["min_joint"]
        assert core.payout(t["legs_product_odds"]) >= spec["min_decimal"] - 0.01
        assert len({(l["player"], l["market"]) for l in t["legs"]}) == t["size"]
        assert all("_history" not in l for l in t["legs"]) and t["show_estimate"] is False


def test_together_counts_the_teams_games_where_every_leg_cleared():
    a = {"team": "X", "line": 0.5, "_history": [("g1", 1), ("g2", 0), ("g3", 2)]}
    b = {"team": "X", "line": 1.5, "_history": [("g1", 2), ("g2", 3), ("g4", 2)]}
    assert P._together([a, b]) == {"hits": 1, "games": 2}               # g1 both cleared; g2 a missed; g3/g4 not shared
    assert P._together([a, dict(b, team="Y")]) is None


def test_the_reconcile_grades_a_pool_leg_from_the_box_score(tmp_path):
    root = _write_world(tmp_path)
    raw = root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_stats.csv"
    with open(raw, "a", newline="", encoding="utf-8") as fh:     # tonight's box score: Ovechkin 0 shots, Hughes 4
        w = csv.DictWriter(fh, fieldnames=LOG_COLS, extrasaction="ignore")
        w.writerow({"gamePk": "2026029999", "date": "2026-10-17T17:10:00Z", "team": HOME, "player_id": "1",
                    "player": "{'default': 'A. Ovechkin'}", "shots": 0, "goals": 0, "assists": 0, "timeOnIce": "17:00"})
        w.writerow({"gamePk": "2026029999", "date": "2026-10-17T17:10:00Z", "team": AWAY, "player_id": "3",
                    "player": "{'default': 'J. Hughes'}", "shots": 4, "goals": 0, "assists": 0, "timeOnIce": "19:00"})
    ticket = {"legs": [{"player": "Alex Ovechkin", "market": "SOG", "side": "over", "line": 0.5, "player_id": "1"},
                       {"player": "Jack Hughes", "market": "SOG", "side": "over", "line": 1.5, "player_id": "3"}]}
    acts = P.leg_actuals(root, DAY, [ticket])
    graded = cs.sgp_results([ticket], {"props": {}, "void": {}, "leg_actuals": acts})[0]
    assert [(l["result"], l["actual"]) for l in graded["legs"]] == [("lost", 0.0), ("won", 4.0)]
    assert graded["status"] == "lost"


def test_the_sheet_shows_hit_rate_tickets_and_ledgers_the_long_shots(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("bcs", Path(__file__).resolve().parents[1] / "scripts" / "build_cheat_sheets.py")
    bcs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bcs)
    root = _write_world(tmp_path)
    (root / "nhl_source" / "sgp").mkdir(parents=True)
    (root / "nhl_source" / "sgp" / "nhl_sgp_correlations.json").write_text(json.dumps({"cells": {}}), encoding="utf-8")
    long_shot = {"sgp_id": "sgp_000000000001", "event_id": "ev1", "family": "correlation", "legs": [], "p_joint": 0.05}
    real = nsgp.suggest
    monkeypatch.setattr(nsgp, "suggest", lambda *a, **k: real(*a, **k) + [long_shot])
    sheet = dict(_sheet(), games=[dict(g, commence_time="2099-01-01T00:00:00Z") for g in _sheet()["games"]])
    bcs.attach_sgp(sheet, None, root, DAY, "nhl")
    assert sheet["sgp"] and all(t["family"] == "hit_rate" for t in sheet["sgp"])
    ledger = [json.loads(x) for x in (root / "cheatsheets" / "nhl" / "sgp_ledger.jsonl").read_text().splitlines()]
    assert any(r["sgp_id"] == "sgp_000000000001" for r in ledger)             # the long shot: ledger only
    assert sheet["sgp_alt_rows"] == bcs.alt_row_count(root, "nhl", DAY) == 14
