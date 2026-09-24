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
