"""R1 rebounds-unders forward grader: the registered close, fair, price, voids and per-league bar (signal-engine-nba)."""
from __future__ import annotations

import csv
import importlib.util
from collections import defaultdict
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "grade_rebounds_unders_forward", Path(__file__).resolve().parents[1] / "scripts" / "grade_rebounds_unders_forward.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CSV = ["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
       "player_name", "point", "price", "last_update", "home_team", "away_team"]
LOG = ["game_id", "date", "season", "season_type", "TEAM_ABBREVIATION", "opponent", "home_away", "PLAYER_ID",
       "PLAYER_NAME", "position", "starter", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "source"]
TIP = "2026-11-03T00:30:00Z"   # 7:30 PM Central on 2026-11-02; cutoff 00:20Z


def _write(path: Path, cols, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _q(snap, book, player, point, over, under, event="e1", home="Boston Celtics", away="New York Knicks", tip=TIP):
    base = {"snapshot_ts": snap, "event_id": event, "commence_time": tip, "bookmaker": book, "market": "player_rebounds",
            "player_name": player, "point": point, "home_team": home, "away_team": away}
    return [dict(base, outcome_name="Over", price=over), dict(base, outcome_name="Under", price=under)]


def _fixture(root: Path) -> None:
    rows = []
    rows += _q("2026-11-03T00:15:00Z", "draftkings", "Jayson Tatum", 8.5, -110, -110)
    rows += _q("2026-11-03T00:15:00Z", "fanduel", "Jayson Tatum", 8.5, -120, 100)
    rows += _q("2026-11-03T00:15:00Z", "pinnacle", "Jayson Tatum", 8.5, -105, -105)           # in the fair, not a price
    rows += _q("2026-11-03T00:15:00Z", "polymarket", "Jayson Tatum", 8.5, 400, -900)          # never in the fair
    rows += _q("2026-11-03T00:25:00Z", "draftkings", "Jayson Tatum", 9.5, -110, -110)         # after tip - 10: ignored
    rows += _q("2026-11-02T20:00:00Z", "draftkings", "Star A", 6.5, -110, -110, event="as", home="Team Clark",
               away="Team Collier")                                                            # an All-Star style event
    _write(root / "nba_source" / "data" / "raw" / "odds_nba_player_props_history_2026-11-02.csv", CSV, rows)
    _write(root / "nba_source" / "data" / "processed" / "player_game_log_2026.csv", LOG, [
        {"game_id": "1", "date": "2026-11-02", "season_type": "regular", "TEAM_ABBREVIATION": "BOS",
         "PLAYER_NAME": "Jayson Tatum", "MIN": 36, "REB": 7, "PTS": 30, "AST": 5, "FG3M": 3},
        {"game_id": "as", "date": "2026-11-02", "season_type": "regular", "TEAM_ABBREVIATION": "CLK",
         "PLAYER_NAME": "Star A", "MIN": 20, "REB": 2, "PTS": 9, "AST": 1, "FG3M": 0}])


def test_r1_grades_the_close_with_the_registered_fair_and_price(tmp_path, monkeypatch) -> None:
    g = _load()
    monkeypatch.setattr(g, "REGISTERED_AT", g.REGISTERED_AT.replace(year=2026, month=10, day=14))
    _fixture(tmp_path)
    counts: dict = defaultdict(int)
    rows = g.grade_league(tmp_path, "R1-NBA", "2026-11-02", counts)
    assert len(rows) == 1 and rows[0]["point"] == 8.5 and rows[0]["y"] == 1.0
    assert rows[0]["price"] == 100                      # best US under; Pinnacle prices the fair only
    from syndicate.features.shared.opportunity_signals import devig
    fairs = sorted(devig([o, u], method="shin")[0] for o, u in ((-110, -110), (-120, 100), (-105, -105)))
    assert abs(rows[0]["p"] - round(1 - fairs[1], 5)) < 1e-9   # the median over dk, fd, pinnacle -- no polymarket
    assert counts["R1-NBA:not_two_league_clubs"] == 1


def test_r1_drops_games_that_tipped_before_the_registration(tmp_path, monkeypatch) -> None:
    g = _load()
    _fixture(tmp_path)
    monkeypatch.setattr(g, "REGISTERED_AT", g.REGISTERED_AT.replace(year=2026, month=11, day=4))
    counts: dict = defaultdict(int)
    assert g.grade_league(tmp_path, "R1-NBA", "2026-11-02", counts) == [] and counts["R1-NBA:pre_registration"] == 1


def test_r1_each_league_is_read_alone_at_its_own_bar() -> None:
    g = _load()
    rows = [{"league": "R1-NBA", "date": "2027-04-10", "game": f"g{i}", "y": 1.0, "p": 0.5, "pnl": 0.9} for i in range(30)]
    rep = g.report(rows, "2027-04-11", {})
    nba, wnba = rep["hypotheses"]["R1-NBA"], rep["hypotheses"]["R1-WNBA"]
    assert nba["final_read"] and nba["verdict"] == "SUPPORTED" and nba["alpha"] == 0.0125
    assert wnba["verdict"].startswith("INTERIM") and wnba["residual_under"]["n"] == 0
    assert g.report(rows, "2027-03-01", {})["hypotheses"]["R1-NBA"]["verdict"].startswith("INTERIM")
