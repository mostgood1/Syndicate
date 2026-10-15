"""NBA defender matchups: who guarded him (NBA.com's season matchups), counted only for TODAY's opponent's current
defenders, regular season only, with completed seasons cached for good -- all through an injectable fetch."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from syndicate.features.nba import defender_matchups as dm
from syndicate.features.shared import cheat_sheets as cs

SGA, THOMPSON, SMITH, CAMARA = 1628983, 1641708, 1641733, 1641739
HEADS = ["OFF_PLAYER_ID", "DEF_PLAYER_ID", "DEF_PLAYER_NAME", "GP", "PARTIAL_POSS", "PLAYER_PTS", "MATCHUP_FGM",
         "MATCHUP_FGA", "MATCHUP_FG3M", "MATCHUP_FG3A", "MATCHUP_AST", "MATCHUP_TOV"]
SEASONS = {   # season -> rows for SGA; Camara is on POR now, so he counts toward "everyone" only
    "2026-27": [[SGA, THOMPSON, "Amen Thompson", 1, 20.0, 8, 3, 6, 0, 1, 1, 0]],
    "2025-26": [[SGA, THOMPSON, "Amen Thompson", 3, 60.0, 30, 11, 20, 2, 4, 3, 1],
                [SGA, CAMARA, "Toumani Camara", 4, 120.0, 40, 15, 30, 2, 6, 5, 2]],
    "2024-25": [[SGA, SMITH, "Jabari Smith Jr.", 2, 30.0, 10, 4, 9, 1, 3, 0, 1]],
}


def fake(url: str):
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    if "/commonallplayers" in url:
        assert q["Season"] == "2026-27"
        return {"resultSets": [{"headers": ["PERSON_ID", "DISPLAY_FIRST_LAST", "TEAM_ABBREVIATION"], "rowSet": [
            [SGA, "Shai Gilgeous-Alexander", "OKC"], [THOMPSON, "Amen Thompson", "HOU"],
            [SMITH, "Jabari Smith Jr.", "HOU"], [CAMARA, "Toumani Camara", "POR"]]}]}
    if "/leagueseasonmatchups" in url:
        assert q["SeasonType"] == "Regular Season"                              # never preseason or playoffs
        return {"resultSets": [{"headers": HEADS, "rowSet": SEASONS[q["Season"]] if q["OffPlayerID"] == str(SGA) else []}]}
    raise AssertionError(url)


def test_his_line_is_against_todays_opponents_current_defenders_only(tmp_path):
    api = dm.NbaApi(tmp_path / "d", tmp_path / "p", fetch=fake)
    rows = [{"player": "Shai Gilgeous-Alexander", "market": "player_points", "team": "OKC", "opponent": "HOU"},
            {"player": "Shai Gilgeous-Alexander", "market": "player_assists", "team": "OKC", "opponent": "HOU"},
            {"player": "Shai Gilgeous-Alexander", "market": "player_rebounds", "team": "OKC", "opponent": "HOU"}]
    got = dm.matchups(rows, date="2026-10-21", api=api)
    assert set(got) == {("shaigilgeousalexander", "player_points"), ("shaigilgeousalexander", "player_assists")}  # no rebounds
    m = got[("shaigilgeousalexander", "player_points")]
    ln = m["line"]
    assert m["kind"] == "scorer_vs_defenders" and m["opponent"] == "HOU defenders"
    assert (ln["poss"], ln["pts"], ln["fgm"], ln["fga"], ln["gp"]) == (110.0, 48, 18, 35, 6)        # Camara (POR) excluded
    assert ln["pts_per_100"] == round(100 * 48 / 110, 1) and ln["overall_pts_per_100"] == round(100 * 88 / 230, 1)
    assert [d["name"] for d in ln["defenders"]] == ["Amen Thompson", "Jabari Smith Jr."]            # most possessions first
    assert m["summary"].startswith("A. Thompson: 38 pts, 14/26 FG in 80 poss (4 GP)")
    assert api.calls == 4                                                         # roster + 3 seasons, once per player
    offline = dm.NbaApi(tmp_path / "d", tmp_path / "p", fetch=lambda u: (_ for _ in ()).throw(AssertionError(u)))
    assert dm.matchups(rows, date="2026-10-21", api=offline) == got and offline.calls == 0
    assert len(list((tmp_path / "p").glob("*.json"))) == 2                       # the two completed seasons, for good


def test_seasons_and_team_codes():
    assert dm.seasons_for("2026-10-21") == ["2026-27", "2025-26", "2024-25"]
    assert dm.seasons_for("2027-04-01")[0] == "2026-27"
    assert dm.team_code("GS") == "GSW" and dm.team_code("nyk") == "NYK"
    assert dm.scoring_market("Points") and dm.scoring_market("player_threes") and dm.scoring_market("PRA")
    assert not dm.scoring_market("player_rebounds") and not dm.scoring_market("Blocks")


def test_an_unknown_or_ambiguous_name_gets_no_line(tmp_path):
    api = dm.NbaApi(None, fetch=fake)
    rows = [{"player": "Nobody Here", "market": "player_points", "team": "OKC", "opponent": "HOU"}]
    assert dm.matchups(rows, date="2026-10-21", api=api) == {}


def test_the_sheet_section_needs_forty_possessions_one_row_a_player():
    def row(player, poss, market="player_points", ev=0.0):
        return {"player": player, "market": market, "side": "over", "check": {"verdict": "neutral", "price": -110, "ev_market": ev},
                "pvp": {"kind": "scorer_vs_defenders", "line": {"poss": poss}}}

    rows = [row("SGA", 110.0), row("SGA", 110.0, market="player_assists", ev=2.0), row("Few", 12.5), row("Brunson", 355.5)]
    assert [(rows[i]["player"], rows[i]["market"]) for i in cs.sections(rows)["pvp_scorers"]] == [
        ("Brunson", "player_points"), ("SGA", "player_assists")]
