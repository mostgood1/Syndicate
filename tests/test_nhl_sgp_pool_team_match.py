"""The NHL hit-rate pool matches a player's club by club, not by spelling, todo #743 (e) (lane
`nhl-hitrate-pool-team-match`).

The NHL game log spells one club several ways ('MIN' and 'Minnesota Wild'; 'St. Louis Blues' where the board writes
'St Louis Blues'), and `GameLog.resolve` compared raw strings: on the 2026-10-28 fleet snapshot, 90 lineup player-days in
12 days missed the pool on spelling alone. Tickets tell teammate from opponent by comparing leg teams as strings, so
every pool leg must carry the board's spelling, never the log's."""
from __future__ import annotations

import csv

from syndicate.features.nfl import sgp as core
from syndicate.features.nhl import sgp as nsgp
from syndicate.features.nhl import sgp_pool as P
from tests.test_nhl_sgp_pool import AWAY, DAY, HOME, _sheet, _write_world


def _row(pid, name, team, pk="2025020100"):
    return {"player_id": pid, "gamePk": pk, "timeOnIce": "18:02", "team": team, "player": name,
            "date": "2026-10-20T23:00:00Z", "shots": "2"}


def test_resolve_matches_an_abbreviated_log_team_to_the_boards_full_name():
    log = P.GameLog([_row("8", "K. Kaprizov", "MIN")])
    assert log.resolve("Kirill Kaprizov", ["Minnesota Wild", "Boston Bruins"]) == "8"
    assert log.board_team("8", ["Minnesota Wild", "Boston Bruins"]) == "Minnesota Wild"


def test_resolve_matches_st_louis_with_and_without_the_period():
    log = P.GameLog([_row("9", "R. Thomas", "St. Louis Blues")])
    assert log.resolve("Robert Thomas", ["Nashville Predators", "St Louis Blues"]) == "9"
    assert log.board_team("9", ["Nashville Predators", "St Louis Blues"]) == "St Louis Blues"


def test_an_exact_spelling_still_matches_when_the_alias_map_does_not_know_it():
    log = P.GameLog([_row("5", "A. Player", "Some Exhibition Club")])
    assert log.resolve("Alex Player", ["Some Exhibition Club", "Boston Bruins"]) == "5"


def test_a_player_whose_latest_club_is_not_in_the_game_still_refuses():
    log = P.GameLog([_row("6", "D. Mercer", "Winnipeg Jets")])
    assert log.resolve("Dawson Mercer", ["New Jersey Devils", "Washington Capitals"]) is None


def test_two_players_in_the_game_with_one_key_stay_ambiguous_across_spellings():
    log = P.GameLog([_row("1", "J. Smith", "NYR"), _row("2", "J. Smith", "Boston Bruins", pk="2025020101")])
    assert log.resolve("Jack Smith", ["New York Rangers", "Boston Bruins"]) is None


def test_a_namesake_from_a_past_season_does_not_make_the_current_player_ambiguous():
    """Measured on the 10-28 snapshot: matching by club alone made Jaccob Slavin (CAR, this season) tie a J. Slavin
    whose only 2 games were last season, logged 'CAR' -- 6 day-games refused that had resolved before."""
    log = P.GameLog([_row("8476958", "J. Slavin", "Carolina Hurricanes", pk="2026020100"),
                     _row("8481004", "J. Slavin", "CAR", pk="2025021300")])
    assert log.resolve("Jaccob Slavin", ["Carolina Hurricanes", "Boston Bruins"]) == "8476958"


def _respell(root, teams_by_pid):
    path = root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_stats.csv"
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    for row in rows:
        row["team"] = teams_by_pid.get(row["player_id"], row["team"])
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_the_pool_admits_abbreviated_players_and_every_leg_carries_the_boards_team(tmp_path):
    """Ovechkin's and Hughes's log rows say 'WSH' / 'NJD'; Strome's and Noesen's say the full name. Before the fix the
    two abbreviated players were `no_game_log` and the pool held Strome only."""
    root = _write_world(tmp_path)
    _respell(root, {"1": "WSH", "3": "NJD"})
    pool, info = P.legs_by_game(_sheet(), root, DAY, nsgp.lineup_roles(root, DAY))
    got = {(leg["player"], leg["line"]) for leg in pool["ev1"]}
    assert {("Alex Ovechkin", 0.5), ("Dylan Strome", 0.5), ("Jack Hughes", 0.5), ("Jack Hughes", 1.5)} == got
    assert info["counts"].get("no_game_log", 0) == 0
    assert {leg["team"] for leg in pool["ev1"]} == {HOME, AWAY}
    by = {leg["player"]: leg for leg in pool["ev1"]}
    assert core.relation_of(by["Alex Ovechkin"], by["Dylan Strome"]) == "teammate"
    assert core.relation_of(by["Alex Ovechkin"], by["Jack Hughes"]) == "opponent"
