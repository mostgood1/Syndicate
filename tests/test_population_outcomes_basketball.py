"""NBA joins the ESPN population settler; NCAAB deliberately does not yet.

Lane `daily-accuracy-suite` `[2026-09-20]`.

THE POINT OF THESE TESTS IS REACHABILITY BEFORE CORRECTNESS. NBA is out of season on
the day this shipped (regular season opens late October), so there is no live slate to
grade and no correctness reading is available. What CAN be proved today is that the
sport is reachable at all -- that `handles()` says yes, that the registry advertises a
version for it, and that its reads are aimed at `basketball/nba` rather than silently
at WNBA's endpoints. A settler that is registered but unreachable looks identical to a
working one until the season opens, which is the failure mode this file exists for.

The `off != on` pair is NBA against NCAAB in the same run: one must be handled and the
other must not, so neither a hard-coded True nor a hard-coded False passes.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import population_outcomes as po
from syndicate.features.shared import population_outcomes_espn as espn


def _row(sport: str, **extra):
    """A row the ESPN settler OWNS. Plain full-game `h2h` is deliberately NOT one: that is
    `grade_population`'s job and this settler passes it through (`_FULL_GAME_MARKETS_HANDLED`).
    A player prop is the cleanest owned shape, so that is the default here."""
    row = {"sport": sport, "market": "player_points", "segment": "full", "player_name": "A Player",
           "home_team": "A", "away_team": "B", "commence_time": "2026-11-15T00:00:00Z"}
    row.update(extra)
    return row


# --------------------------------------------------------------------------------------
# Reachability: NBA in, NCAAB out, in one run.
# --------------------------------------------------------------------------------------


def test_nba_and_ncaab_are_both_handled_now():
    """NCAAB was this test's out-exemplar until 2026-09-23, when its one documented
    blocker -- no team registry -- was cleared and it joined `HANDLED_SPORTS`."""
    settler = espn.EspnPopulationSettler()
    assert settler.handles(_row("nba")) is True
    assert settler.handles(_row("ncaab")) is True
    # The control: the sports that were already handled still are.
    assert settler.handles(_row("wnba")) is True
    assert settler.handles(_row("nfl", market="passing yards")) is True
    # And a market this settler does not own stays unowned for NBA too -- registration
    # widened the SPORT set, it did not widen what the settler claims. Same for NCAAB.
    assert settler.handles(_row("nba", market="h2h", player_name=None)) is False
    assert settler.handles(_row("ncaab", market="h2h", player_name=None)) is False
    # A sport this settler genuinely does not own, so "handles" is not read off a table
    # where every entry happens to be True.
    assert settler.handles(_row("nhl")) is False


def test_an_unhandled_sport_returns_none_meaning_not_mine_rather_than_a_verdict():
    """`None` is 'some other settler's problem'. A `(status, reason)` tuple would claim
    the row as graded-and-refused, which is a different and wrong statement.

    NCAAB was the exemplar until it was registered on 2026-09-23; NHL carries the case
    now. The rule is what matters, not which sport illustrates it -- and NHL is the
    honest choice because this settler really does not own it (its zero was diagnosed
    as UPSTREAM of the settler by lane `daily-accuracy-suite`)."""
    settler = espn.EspnPopulationSettler()
    assert settler(_row("nhl")) is None


def test_the_registry_advertises_a_version_for_nba_and_none_for_ncaab():
    """`sport_versions` is what the scorecard stamps itself with, so a sport missing here
    is a sport the artifact cannot claim to have graded."""
    composite = po.build_extra_settler()
    versions = composite.sport_versions
    assert versions.get("nba") == espn.GRADER_VERSION
    # NCAAB advertises a version from 2026-09-23, the same day it joined HANDLED_SPORTS.
    # A sport missing here is a sport the artifact cannot claim to have graded, so the
    # two must move together or the scorecard stamps itself with a lie in one direction
    # or the other.
    assert versions.get("ncaab") == espn.GRADER_VERSION
    for already in ("nfl", "ncaaf", "wnba"):
        assert versions.get(already) == espn.GRADER_VERSION
    # A sport this settler does not grade must still be advertised by ITS OWN settler,
    # not by espn -- or the assertion above only proves the dict is non-empty.
    assert versions.get("nhl") != espn.GRADER_VERSION


def test_the_two_lists_that_name_the_espn_settlers_sports_agree():
    """`HANDLED_SPORTS` decides what the settler GRADES; `SETTLER_MODULES`'s sports
    column decides what `sport_versions` ADVERTISES. Two lists, one fact, read by
    different things -- and moving one alone fails silently, as a sport that is graded
    and not stamped (or stamped and not graded).

    Added 2026-09-23 after registering NCAAB required editing both, in two files, with
    nothing connecting them but a comment."""
    declared = dict((name, sports) for name, _module, _cls, sports in po.SETTLER_MODULES)
    assert set(declared["espn"]) == set(espn.HANDLED_SPORTS), (
        sorted(set(declared["espn"]) ^ set(espn.HANDLED_SPORTS))
    )


def test_nba_reads_the_nba_endpoint_not_wnbas():
    """The defect this would have shipped as: `_settle_basketball_prop` used to hard-code
    `self._summary("wnba", event_id)`, so an NBA event id would have been sent to the WNBA
    summary endpoint and come back empty or wrong."""
    assert espn._SPORT_PATHS["nba"] == "basketball/nba"
    assert espn._SPORT_PATHS["wnba"] == "basketball/wnba"
    assert espn._SPORT_PATHS["nba"] != espn._SPORT_PATHS["wnba"]


def test_ncaabs_documented_blocker_is_gone_and_ncaab_is_now_registered():
    """**THE BLOCKER THIS TEST EXISTED TO PIN HAS BEEN CLEARED, and the test firing is
    what reported it.** That is the whole point of pinning a cause.

    It used to assert `canonical_team("ncaab", ...) is None` and said: "If this
    assertion ever fails, the blocker is gone and NCAAB should be added to
    HANDLED_SPORTS." On 2026-09-23 (lane `nhl-ncaab-club-maps`) NCAAB gained a
    362-school registry and a club map, so it failed -- and the instruction it carried
    was followed in the same change rather than filed.

    WHAT IS ASSERTED NOW. Both halves, because either alone is a trap: the map must
    RESOLVE real schools, and it must REFUSE shared mascots. A map that answered
    "Tigers" would satisfy a resolution-only test while being worse than the empty map
    it replaced -- `teams_match` treats a map as authoritative and skips its
    heuristics, so a wrong answer would be confident rather than absent.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    assert canonical_team("ncaab", "Duke Blue Devils") == "duke"
    assert canonical_team("ncaab", "Gonzaga") == "gonzaga"
    assert canonical_team("ncaab", "Tigers") is None
    assert canonical_team("ncaab", "Bulldogs") is None
    # ... while the sport NBA joined on does resolve, which is why NBA could be added.
    assert canonical_team("nba", "Boston Celtics") is not None
    assert "ncaab" in espn.HANDLED_SPORTS


def test_everything_except_the_registry_is_already_in_place_for_ncaab():
    """The remaining job is one registry plus one string, and these are the other pieces."""
    assert espn._SPORT_PATHS["ncaab"] == "basketball/mens-college-basketball"
    assert "ncaab" in espn.BASKETBALL_SPORTS
    assert espn.regulation_periods("ncaab") == 2


# --------------------------------------------------------------------------------------
# Halves are not quarters.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("sport,expected", [("ncaab", 2), ("nba", 4), ("wnba", 4), ("nfl", 4), ("", 4)])
def test_regulation_periods_per_sport(sport, expected):
    assert espn.regulation_periods(sport) == expected


def test_ncaab_first_half_closes_at_period_two_and_a_quarter_sports_does_not():
    """NCAAB's h1 ends when period 2 starts; NBA's h1 ends when period 3 starts. Reading
    NCAAB's h1 with the quarter rule would never close it inside regulation."""
    live_p2 = {"completed": False, "period": 2}
    assert espn.EspnPopulationSettler._segment_closed("h1", live_p2, "ncaab") is True
    assert espn.EspnPopulationSettler._segment_closed("h1", live_p2, "nba") is False
    assert espn.EspnPopulationSettler._segment_closed("h1", {"completed": False, "period": 3}, "nba") is True


def test_a_completed_game_closes_every_segment_for_either_shape():
    for sport in ("ncaab", "nba"):
        assert espn.EspnPopulationSettler._segment_closed("h1", {"completed": True}, sport) is True


def test_h2_never_closes_early():
    assert espn.EspnPopulationSettler._segment_closed("h2", {"completed": False, "period": 4}, "nba") is False


# --------------------------------------------------------------------------------------
# Market canonicalisation is asked under the caller's own sport.
# --------------------------------------------------------------------------------------


def test_basketball_markets_canonicalise_per_sport_and_agree_today():
    """nba, wnba and ncaab share one `_BASKETBALL` table, so the answers agree -- but the
    question is now asked under the caller's sport, so a future divergence is honoured
    instead of being silently answered as WNBA."""
    for market in ("player_points", "player_rebounds", "player_points_rebounds_assists"):
        assert espn._basketball_market("nba", market) == espn._basketball_market("wnba", market)


def test_nba_player_props_are_supported_and_a_nonsense_market_is_not():
    assert espn._prop_supported("nba", "player_points") is True
    assert espn._prop_supported("nba", "player_double_double") is True
    assert espn._prop_supported("nba", "player_hole_in_ones") is False


# --------------------------------------------------------------------------------------
# NCAAB halves are graded off the HALVES (lane `college-basketball-settlement`, 2026-11-02).
# --------------------------------------------------------------------------------------


def _linescores(home, away):
    return {"home": {"linescores": home}, "away": {"linescores": away}}


def test_an_ncaab_first_half_is_period_one_not_the_whole_regulation_game():
    """Before this, NCAAB went through WNBA's quarter table: `h1` = periods 1+2, which on
    two halves is the whole regulation game (FAU-Charlotte 2026-03-01 read 69-69 for a
    first half that ended 35-45)."""
    settler = espn.EspnPopulationSettler()
    game = _linescores([35, 34, 8], [45, 24, 7])
    assert settler._segment_pair("ncaab", "h1", game) == (35.0, 45.0)
    # `h2` is the second half AND the overtime, not the overtime alone.
    assert settler._segment_pair("ncaab", "h2", game) == (42.0, 31.0)
    assert settler._segment_pair("ncaab", "h2", _linescores([35, 30, 8, 9], [33, 32, 8, 5])) == (47.0, 45.0)
    # The quarter sports are untouched: NBA's h1 is still Q1+Q2.
    assert settler._segment_pair("nba", "h1", _linescores([30, 28, 25, 22], [27, 33, 24, 30])) == (58.0, 60.0)


def test_an_ncaab_half_with_a_missing_period_or_a_quarter_segment_refuses():
    settler = espn.EspnPopulationSettler()
    assert settler._segment_pair("ncaab", "h2", _linescores([35], [45])) is None
    assert settler._segment_pair("ncaab", "h2", _linescores([35, 34, 8], [45, 24])) is None
    assert settler._segment_pair("ncaab", "q1", _linescores([35, 34], [45, 24])) is None


# --------------------------------------------------------------------------------------
# WNCAAB joins: four quarters, the women's ESPN path, the Division I scoreboard.
# --------------------------------------------------------------------------------------


def test_wncaab_is_handled_and_read_from_the_womens_path():
    settler = espn.EspnPopulationSettler()
    assert settler.handles(_row("wncaab")) is True
    assert settler.handles(_row("wncaab", market="totals", segment="q1", player_name=None)) is True
    assert espn._SPORT_PATHS["wncaab"] == "basketball/womens-college-basketball"
    assert "wncaab" in espn.BASKETBALL_SPORTS
    assert espn.regulation_periods("wncaab") == 4
    # Quarters, so WNBA's table: h1 = Q1+Q2.
    assert settler._segment_pair("wncaab", "h1", _linescores([33, 28, 17, 23], [14, 19, 26, 34])) == (61.0, 33.0)


@pytest.mark.parametrize("sport,path", [("ncaab", "mens-college-basketball"), ("wncaab", "womens-college-basketball")])
def test_the_college_scoreboard_asks_for_division_one(sport, path):
    """Without `groups=50` ESPN serves a featured subset: 18 of 182 men's and 16 of 164
    women's events on 2026-11-02."""
    urls = []
    settler = espn.EspnPopulationSettler(fetch_json=lambda url: urls.append(url) or {"events": []})
    settler._scoreboard(sport, "2026-11-02")
    assert urls[0] == (f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/scoreboard"
                       "?dates=20261102&groups=50&limit=500")


# --------------------------------------------------------------------------------------
# At a neutral site "home" is a label: a swapped college basketball pair is ORIENTED.
# --------------------------------------------------------------------------------------


def _scoreboard_event(home, away, home_periods, away_periods, *, neutral):
    def side(home_away, name, periods):
        return {"homeAway": home_away, "team": {"id": name[:4], "displayName": name}, "score": str(sum(periods)),
                "linescores": [{"value": float(v), "period": n} for n, v in enumerate(periods, start=1)]}
    status = {"period": 2, "type": {"state": "post", "completed": True, "name": "STATUS_FINAL"}}
    return {"id": "401911707", "date": "2026-03-01T16:30Z", "status": status,
            "competitions": [{"neutralSite": neutral, "status": status, "competitors": [
                side("home", home, home_periods), side("away", away, away_periods)]}]}


def _half_row(sport="ncaab", **extra):
    # The odds feed's orientation: Murray St at home. ESPN lists Tennessee St at home.
    row = {"sport": sport, "market": "spreads", "segment": "h1", "side": "home", "line": -5.0, "player_name": None,
           "home_team": "Murray St Racers", "away_team": "Tennessee St Tigers", "commence_time": "2026-03-01T16:30:00Z"}
    row.update(extra)
    return row


@pytest.mark.parametrize("neutral,expected", [(True, ("win", "espn_linescore")), (False, (None, "home_away_disagree"))])
def test_a_swapped_neutral_site_ncaab_game_is_oriented_and_a_swapped_home_game_still_refuses(neutral, expected):
    """2026-11-02: 106 of 118 NCAAB half rows on the fleet refused `home_away_disagree`, all on
    two neutral-site games. Murray St led the first half 46-35, so the record's home -5 wins."""
    event = _scoreboard_event("Tennessee State Tigers", "Murray State Racers", [35, 29], [46, 48], neutral=neutral)
    settler = espn.EspnPopulationSettler(fetch_json=lambda url: {"events": [event]})
    assert settler.settle(_half_row()) == expected


def test_neutral_site_orientation_is_college_basketball_only():
    """NBA has no measured case; a swapped pair there keeps the refusal it always had."""
    event = _scoreboard_event("Indiana Pacers", "Boston Celtics", [30, 28, 25, 22], [27, 33, 24, 30], neutral=True)
    settler = espn.EspnPopulationSettler(fetch_json=lambda url: {"events": [event]})
    row = _half_row(sport="nba", home_team="Boston Celtics", away_team="Indiana Pacers")
    assert settler.settle(row) == (None, "home_away_disagree")
