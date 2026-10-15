"""Batter vs pitcher for the MLB cheat sheet: names resolved inside the game's two rosters, the opposing probable
starter, career lines from StatsAPI's vsPlayerTotal -- all through an injectable fetch (no network in tests)."""
from __future__ import annotations

from syndicate.features.mlb import batter_vs_pitcher as bvp
from syndicate.features.shared import cheat_sheets as cs

SCHEDULE = {"dates": [{"games": [{"gamePk": 1, "teams": {
    "home": {"team": {"id": 119, "name": "Los Angeles Dodgers"}, "probablePitcher": {"id": 607192, "fullName": "Tyler Glasnow"}},
    "away": {"team": {"id": 158, "name": "Milwaukee Brewers"}, "probablePitcher": {"id": 642547, "fullName": "Freddy Peralta"}}}}]}]}
ROSTERS = {
    119: {"roster": [{"person": {"id": 660271, "fullName": "Shohei Ohtani"}, "position": {"abbreviation": "DH"}},
                     {"person": {"id": 607192, "fullName": "Tyler Glasnow"}, "position": {"abbreviation": "P"}}]},
    158: {"roster": [{"person": {"id": 663457, "fullName": "Jackson Chourio"}, "position": {"abbreviation": "CF"}},
                     {"person": {"id": 592885, "fullName": "Christian Yelich"}, "position": {"abbreviation": "LF"}},
                     {"person": {"id": 642547, "fullName": "Freddy Peralta"}, "position": {"abbreviation": "P"}}]},
}
VS = {(660271, 642547): {"plateAppearances": 15, "atBats": 12, "hits": 4, "homeRuns": 2, "strikeOuts": 4, "baseOnBalls": 2,
                         "avg": ".333", "ops": "1.384"},
      (663457, 607192): {"plateAppearances": 6, "atBats": 6, "hits": 1, "homeRuns": 0, "strikeOuts": 3, "baseOnBalls": 0, "avg": ".167"},
      (592885, 607192): {"plateAppearances": 20, "atBats": 18, "hits": 6, "homeRuns": 1, "strikeOuts": 5, "baseOnBalls": 2, "avg": ".333"}}


def fake(url: str):
    if "/schedule" in url:
        return SCHEDULE
    if "/roster" in url:
        return ROSTERS[int(url.split("/teams/")[1].split("/")[0])]
    batter = int(url.split("/people/")[1].split("/")[0])
    pitcher = int(url.split("opposingPlayerId=")[1].split("&")[0])
    line = VS.get((batter, pitcher))
    return {"stats": [{"type": {"displayName": "vsPlayerTotal"}, "splits": [{"stat": line}] if line else []}]}


def test_a_batter_gets_his_line_against_the_opposing_starter_and_a_pitcher_the_opposing_roster(tmp_path):
    api = bvp.StatsApi(tmp_path, fetch=fake)
    rows = [{"player": "Shohei Ohtani", "market": "batter_hits"}, {"player": "Tyler Glasnow", "market": "strikeouts"},
            {"player": "Jackson Chourio", "market": "batter_total_bases"}, {"player": "Nobody Here", "market": "batter_hits"}]
    got = bvp.matchups(rows, date="2026-10-15", api=api)
    ohtani = got[("shoheiohtani", "batter_hits")]
    assert ohtani["opponent"] == "Freddy Peralta" and ohtani["summary"] == "4-for-12, 2 HR, 4 K, 2 BB (15 PA)"
    glasnow = got[("tylerglasnow", "strikeouts")]
    assert glasnow["kind"] == "pitcher_vs_lineup" and glasnow["line"]["hits"] == 7 and glasnow["line"]["atBats"] == 24
    assert glasnow["line"]["hitters"] == 2 and glasnow["line"]["k_rate"] == round(8 / 26, 3)       # pitchers excluded
    assert got[("jacksonchourio", "batter_total_bases")]["opponent"] == "Tyler Glasnow"
    assert ("nobodyhere", "batter_hits") not in got                                               # not on either roster
    offline = bvp.StatsApi(tmp_path, fetch=lambda u: (_ for _ in ()).throw(AssertionError(u)))
    assert bvp.matchups(rows, date="2026-10-15", api=offline) == got and offline.calls == 0     # second build: all cached


def test_no_starter_announced_means_no_batter_matchup(tmp_path):
    tbd = {"dates": [{"games": [{"gamePk": 1, "teams": {
        "home": {"team": {"id": 119, "name": "Los Angeles Dodgers"}, "probablePitcher": {"id": 607192, "fullName": "Tyler Glasnow"}},
        "away": {"team": {"id": 158, "name": "Milwaukee Brewers"}}}}]}]}
    api = bvp.StatsApi(None, fetch=lambda u: tbd if "/schedule" in u else fake(u))
    got = bvp.matchups([{"player": "Shohei Ohtani", "market": "batter_hits"}], date="2026-10-15", api=api)
    assert got == {}


def test_the_sheet_sections_split_batters_from_pitchers_and_stay_compact():
    def row(player, pa, price=-110, market="batter_hits", side="over", ev=0.0, kind="batter_vs_pitcher"):
        return {"player": player, "market": market, "side": side, "pvp": {"kind": kind, "line": {"plateAppearances": pa}},
                "check": {"verdict": "neutral", "price": price, "ev_market": ev}}

    rows = [row("A", 15), row("A", 15, side="under", ev=2.0), row("B", 2), row("C", 30, price=-400), row("D", 6),
            row("Snell", 53, market="strikeouts", ev=-2.4, kind="pitcher_vs_lineup"),
            row("Snell", 53, market="strikeouts", side="under", ev=-4.9, kind="pitcher_vs_lineup"),
            row("Snell", 53, market="outs", ev=-1.8, kind="pitcher_vs_lineup")]
    s = cs.sections(rows)
    assert [(rows[i]["player"], rows[i]["side"]) for i in s["pvp_batters"]] == [("A", "under"), ("D", "over")]
    assert [(rows[i]["player"], rows[i]["market"], rows[i]["side"]) for i in s["pvp_pitchers"]] == [("Snell", "strikeouts", "over")]
