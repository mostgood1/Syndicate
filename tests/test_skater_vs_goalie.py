"""NHL skater vs goalie: the likely starter from the game's goalie comparison, the games both played on opposite sides
from their game logs, and shot-by-shot counts with that goalie in net -- all through an injectable fetch."""
from __future__ import annotations

from syndicate.features.nhl import skater_vs_goalie as svg
from syndicate.features.shared import cheat_sheets as cs

MATTHEWS, NYLANDER, UPL, ELLIS, BOB = 8479318, 8477939, 8480045, 8481551, 8475683


def fake(url: str):
    if "/schedule/" in url:
        return {"gameWeek": [{"date": "2026-10-15", "games": [{"id": 9, "homeTeam": {"abbrev": "TOR"}, "awayTeam": {"abbrev": "BUF"}}]}]}
    if "/landing" in url:
        return {"matchup": {"goalieComparison": {
            "homeTeam": {"leaders": [{"playerId": BOB, "name": {"default": "S. Bobrovsky"}, "gamesPlayed": 4}]},
            "awayTeam": {"leaders": [{"playerId": UPL, "name": {"default": "U. Luukkonen"}, "gamesPlayed": 5},
                                     {"playerId": ELLIS, "name": {"default": "C. Ellis"}, "gamesPlayed": 3}]}}}}
    if "/roster/TOR" in url:
        return {"forwards": [{"id": MATTHEWS, "firstName": {"default": "Auston"}, "lastName": {"default": "Matthews"}},
                             {"id": NYLANDER, "firstName": {"default": "William"}, "lastName": {"default": "Nylander"}}],
                "goalies": [{"id": BOB, "firstName": {"default": "Sergei"}, "lastName": {"default": "Bobrovsky"}}]}
    if "/roster/BUF" in url:
        return {"goalies": [{"id": UPL, "firstName": {"default": "Ukko-Pekka"}, "lastName": {"default": "Luukkonen"}}]}
    if "/game-log/20252026/" in url:
        pid = int(url.split("/player/")[1].split("/")[0])
        if pid == MATTHEWS:
            return {"gameLog": [{"gameId": 1, "teamAbbrev": "TOR"}, {"gameId": 2, "teamAbbrev": "TOR"}, {"gameId": 3, "teamAbbrev": "TOR"}]}
        if pid == UPL:   # met Matthews in games 1 and 2; game 4 was against someone else
            return {"gameLog": [{"gameId": 1, "teamAbbrev": "BUF", "opponentAbbrev": "TOR", "shotsAgainst": 30, "goalsAgainst": 3},
                                {"gameId": 2, "teamAbbrev": "BUF", "opponentAbbrev": "TOR", "shotsAgainst": 25, "goalsAgainst": 1},
                                {"gameId": 4, "teamAbbrev": "BUF", "opponentAbbrev": "MTL", "shotsAgainst": 20, "goalsAgainst": 2}]}
        return {"gameLog": []}
    if "/game-log/" in url:
        return {"gameLog": []}
    if "/play-by-play" in url:
        game = int(url.split("/gamecenter/")[1].split("/")[0])
        plays = {1: [("shot-on-goal", MATTHEWS, UPL), ("goal", MATTHEWS, UPL), ("shot-on-goal", MATTHEWS, ELLIS)],
                 2: [("shot-on-goal", MATTHEWS, UPL), ("shot-on-goal", NYLANDER, UPL)]}[game]
        return {"plays": [{"typeDescKey": k, "details": ({"scoringPlayerId": s} if k == "goal" else {"shootingPlayerId": s}) | {"goalieInNetId": g}}
                          for k, s, g in plays] + [{"typeDescKey": "faceoff", "details": {}}]}
    raise AssertionError(url)


def test_a_skater_counts_only_shots_with_the_likely_starter_in_net(tmp_path):
    api = svg.NhlApi(tmp_path / "d", tmp_path / "p", fetch=fake)
    rows = [{"player": "Auston Matthews", "market": "SOG"}, {"player": "Ukko-Pekka Luukkonen", "market": "Saves"}]
    got = svg.matchups(rows, date="2026-10-15", api=api)
    m = got[("austonmatthews", "sog")]
    assert m["opponent"] == "U. Luukkonen (likely starter)" and m["line"] == {"games": 2, "sog": 3, "goals": 1}   # Ellis's shot not counted
    assert m["summary"] == "1 G on 3 SOG in 2 games vs U. Luukkonen"
    g = got[("ukkopekkaluukkonen", "saves")]
    assert g["kind"] == "goalie_vs_team" and g["line"]["games"] == 2 and g["line"]["sv_pct"] == round(51 / 55, 3)   # vs TOR only
    offline = svg.NhlApi(tmp_path / "d", tmp_path / "p", fetch=lambda u: (_ for _ in ()).throw(AssertionError(u)))
    assert svg.matchups(rows, date="2026-10-15", api=offline) == got and offline.calls == 0                 # all cached


def test_seasons_and_goalie_markets():
    assert svg.seasons_for("2026-10-15") == ["20262027", "20252026", "20242025", "20232024"]
    assert svg.seasons_for("2027-03-01")[0] == "20262027"
    assert svg.is_goalie_market("Saves") and svg.is_goalie_market("player_total_saves") and not svg.is_goalie_market("SOG")


def test_the_sheet_sections_need_two_meetings_one_row_a_player():
    def row(player, games, kind="skater_vs_goalie", market="SOG", ev=0.0, price=-110):
        return {"player": player, "market": market, "side": "over", "pvp": {"kind": kind, "line": {"games": games, "sog": games * 3}},
                "check": {"verdict": "neutral", "price": price, "ev_market": ev}}

    rows = [row("Matthews", 6), row("Matthews", 6, market="Points", ev=1.0), row("Once", 1), row("Dahlin", 4),
            row("Luukkonen", 6, kind="goalie_vs_team", market="Saves")]
    s = cs.sections(rows)
    assert [(rows[i]["player"], rows[i]["market"]) for i in s["pvp_skaters"]] == [("Matthews", "Points"), ("Dahlin", "SOG")]
    assert [rows[i]["player"] for i in s["pvp_goalies"]] == ["Luukkonen"]


def test_a_started_game_uses_the_goalie_who_was_in_net(tmp_path):
    def started(url: str):
        if "/landing" in url:
            return {"gameState": "LIVE"}                                   # no matchup block once the game starts
        if "/boxscore" in url:
            return {"playerByGameStats": {
                "homeTeam": {"goalies": [{"playerId": BOB, "name": {"default": "S. Bobrovsky"}, "toi": "40:00"}]},
                "awayTeam": {"goalies": [{"playerId": UPL, "name": {"default": "U. Luukkonen"}, "toi": "00:00"},
                                         {"playerId": ELLIS, "name": {"default": "C. Ellis"}, "toi": "57:14"}]}}}
        if "/player/8481551/game-log/20252026/" in url:                      # Ellis was in net for game 1
            return {"gameLog": [{"gameId": 1, "teamAbbrev": "BUF", "opponentAbbrev": "TOR"}]}
        return fake(url)

    api = svg.NhlApi(tmp_path / "d", tmp_path / "p", fetch=started)
    goalies = svg.likely_goalies(api, 9)
    assert goalies["away"]["name"] == "C. Ellis" and goalies["away"]["started"] is True    # Ellis played, UPL did not
    got = svg.matchups([{"player": "Auston Matthews", "market": "SOG"}], date="2026-10-15", api=api)
    assert got[("austonmatthews", "sog")]["opponent"] == "C. Ellis (started)"
    assert got[("austonmatthews", "sog")]["line"] == {"games": 1, "sog": 1, "goals": 0}     # his one shot with Ellis in net


def test_roster_ids_carry_position_and_team_for_the_sheet_faces(tmp_path):
    ids = svg.player_ids(svg.NhlApi(tmp_path / "d", tmp_path / "p", fetch=fake), "2026-10-15")
    assert ids["austonmatthews"] == {"id": MATTHEWS, "name": "Auston Matthews", "goalie": False, "position": "F", "team": "TOR"}
    assert ids["ukkopekkaluukkonen"]["position"] == "G" and ids["ukkopekkaluukkonen"]["team"] == "BUF"
