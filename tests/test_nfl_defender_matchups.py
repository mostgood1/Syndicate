"""NFL defender matchups = plays on the ball (NOT coverage): breakups, interceptions and tackles after the catch by
TODAY's opponent's active defenders, read from the nflverse play-by-play and roster on the data root."""
from __future__ import annotations

import csv
from pathlib import Path

from syndicate.features.nfl import defender_matchups as dm
from syndicate.features.shared import cheat_sheets as cs

SUTTON, NIX, MIMS, LOVE, SPOON, CUT, BONITTO, TROTTER = ("R1", "Q1", "R2", "D1", "D2", "D3", "D4", "D5")
PBP_COLS = ["game_id", "season_type", "pass_attempt", "sack", "two_point_attempt", "play_deleted", "complete_pass",
            "interception", "passer_player_id", "receiver_player_id", "receiving_yards", "interception_player_id",
            "pass_defense_1_player_id", "pass_defense_2_player_id", "solo_tackle_1_player_id", "assist_tackle_1_player_id"]


def play(game, receiver, *, complete=False, yards=0, intc="", pbu="", tackle="", sack=False, passer=NIX, kind="REG"):
    return {"game_id": game, "season_type": kind, "pass_attempt": "1", "sack": "1" if sack else "0",
            "two_point_attempt": "0", "play_deleted": "0", "complete_pass": "1" if complete else "0",
            "interception": "1" if intc else "0", "passer_player_id": passer, "receiver_player_id": receiver,
            "receiving_yards": str(yards) if complete else "", "interception_player_id": intc,
            "pass_defense_1_player_id": pbu, "pass_defense_2_player_id": "", "solo_tackle_1_player_id": tackle,
            "assist_tackle_1_player_id": ""}


def write(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def data_root(tmp_path: Path) -> Path:
    nv = tmp_path / "nfl_source" / "tracking" / "nflverse"
    write(nv / "pbp" / "pbp_2025.csv", PBP_COLS, [
        play("2025_05_DEN_SEA", SUTTON, complete=True, yards=12, tackle=LOVE),            # a catch Love tackled
        play("2025_05_DEN_SEA", SUTTON, complete=True, yards=30, tackle=CUT),             # CUT player: not today's defense
        play("2025_05_DEN_SEA", SUTTON, complete=True, yards=8, tackle=BONITTO),          # his own team's defender: never
    ])
    write(nv / "pbp" / "pbp_2026.csv", PBP_COLS, [
        play("2026_06_DEN_SEA", SUTTON, pbu=SPOON),                                        # a breakup
        play("2026_06_DEN_SEA", SUTTON, intc=LOVE, pbu=LOVE),                              # INT counted once, not also a PBU
        play("2026_06_DEN_SEA", SUTTON, complete=True, yards=25),                          # a TD: no tackler, credits no one
        play("2026_06_DEN_SEA", SUTTON, sack=True, tackle=LOVE),                           # a sack is not a target
        play("2026_03_LV_SEA", MIMS, passer="Q9", pbu=SPOON),                              # Spoon's other plays this season
        play("2026_03_LV_SEA", MIMS, passer="Q9", pbu=TROTTER),
    ])
    cols = ["season", "team", "position", "depth_chart_position", "status", "full_name", "football_name", "last_name",
            "gsis_id", "week"]
    roster = [("DEN", "WR", "WR", "ACT", "Courtland Sutton", SUTTON), ("DEN", "QB", "QB", "ACT", "Bo Nix", NIX),
              ("DEN", "WR", "WR", "ACT", "Marvin Mims", MIMS), ("SEA", "DB", "SS", "ACT", "Julian Love", LOVE),
              ("SEA", "DB", "CB", "ACT", "Devon Witherspoon", SPOON), ("SEA", "DB", "CB", "CUT", "Cut Guy", CUT),
              ("DEN", "LB", "OLB", "ACT", "Nik Bonitto", BONITTO), ("SEA", "LB", "ILB", "ACT", "Jeremiah Trotter Jr.", TROTTER)]
    write(nv / "roster" / "roster_2026.csv", cols, [
        {"season": "2026", "team": t, "position": p, "depth_chart_position": d, "status": s, "full_name": n,
         "football_name": n.split()[0], "last_name": n.split()[-1], "gsis_id": g, "week": "6"} for t, p, d, s, n, g in roster])
    return tmp_path


def test_a_receivers_line_is_plays_by_todays_active_defenders_on_his_targets(tmp_path):
    src = dm.Source(data_root(tmp_path), "2026-10-15")
    assert src.seasons == [2026, 2025, 2024]
    rows = [{"player": "Courtland Sutton", "market": "Receiving Yards", "team": "DEN", "opponent": "SEA"},
            {"player": "Courtland Sutton", "market": "Rushing Yards", "team": "DEN", "opponent": "SEA"}]
    got = dm.matchups(rows, date="2026-10-15", source=src)
    assert set(got) == {("courtlandsutton", "receiving yards")}                   # a rushing prop gets no defender line
    m = got[("courtlandsutton", "receiving yards")]
    ln = m["line"]
    assert m["kind"] == "receiver_vs_defenders" and m["opponent"] == "SEA defense"
    assert {k: ln[k] for k in ("plays", "catches", "yards", "pbu", "int", "games")} == {
        "plays": 3, "catches": 1, "yards": 12, "pbu": 1, "int": 1, "games": 2}
    assert [d["name"] for d in ln["defenders"]] == ["Julian Love", "Devon Witherspoon"]
    assert m["summary"].startswith("J. Love (SS): 1 INT, 1 catch for 12 yds tackled (2 games)")
    assert [(h["name"], h["int"], h["pbu"]) for h in ln["hawks"]] == [            # this season, every receiver; an INT
        ("Devon Witherspoon", 0, 2), ("Julian Love", 1, 0)]                        # weighs 2 PBUs, ties go to more plays


def test_a_quarterbacks_line_is_on_his_throws(tmp_path):
    src = dm.Source(data_root(tmp_path), "2026-10-15")
    rows = [{"player": "Bo Nix", "market": "Interceptions", "team": "DEN", "opponent": "SEA"}]
    m = dm.matchups(rows, date="2026-10-15", source=src)[("bonix", "interceptions")]
    assert m["kind"] == "qb_vs_defenders" and m["line"]["int"] == 1 and m["line"]["pbu"] == 1
    assert m["summary"] == "1 INT and 1 PBU by today's SEA defenders on his throws since 2024"


def test_names_teams_and_markets(tmp_path):
    src = dm.Source(data_root(tmp_path), "2026-10-15")
    assert dm.find_player(src.roster, "Jeremiah Trotter", "SEA") == TROTTER                       # suffix dropped
    assert dm.find_player(src.roster, "Nobody", "SEA") is None
    assert dm.team_code("LAR") == "LA" and dm.team_code("WSH") == "WAS"
    assert dm.market_role("Receptions") == "receiver" and dm.market_role("Passing Yards") == "passer"
    assert dm.market_role("Rushing Yards") is None and dm.market_role("Anytime TD") is None
    assert dm.seasons_for("2027-01-10") == [2026, 2025, 2024]                                     # a January game


def test_the_sheet_sections_need_two_plays_and_keep_every_quarterback():
    def row(player, plays, kind="receiver_vs_defenders", market="Receiving Yards", hawks=()):
        return {"player": player, "market": market, "side": "over", "check": {"verdict": "neutral", "price": -110},
                "pvp": {"kind": kind, "line": {"plays": plays, "hawks": list(hawks)}}}

    rows = [row("Sutton", 3), row("Once", 1), row("Waddle", 5),
            row("Nix", 0, kind="qb_vs_defenders", market="Interceptions", hawks=[{"name": "Julian Love"}]),
            row("Nobody", 0, kind="qb_vs_defenders", market="Passing Yards")]
    s = cs.sections(rows)
    assert [rows[i]["player"] for i in s["pvp_receivers"]] == ["Waddle", "Sutton"]
    assert [rows[i]["player"] for i in s["pvp_qbs"]] == ["Nix"]
