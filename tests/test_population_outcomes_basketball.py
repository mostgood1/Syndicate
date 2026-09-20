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


def test_nba_is_handled_and_ncaab_is_not():
    settler = espn.EspnPopulationSettler()
    assert settler.handles(_row("nba")) is True
    assert settler.handles(_row("ncaab")) is False
    # The control: the sports that were already handled still are.
    assert settler.handles(_row("wnba")) is True
    assert settler.handles(_row("nfl", market="passing yards")) is True
    # And a market this settler does not own stays unowned for NBA too -- registration
    # widened the SPORT set, it did not widen what the settler claims.
    assert settler.handles(_row("nba", market="h2h", player_name=None)) is False


def test_an_unhandled_sport_returns_none_meaning_not_mine_rather_than_a_verdict():
    """`None` is 'some other settler's problem'. A `(status, reason)` tuple would claim
    NCAAB as graded-and-refused, which is a different and wrong statement."""
    settler = espn.EspnPopulationSettler()
    assert settler(_row("ncaab")) is None


def test_the_registry_advertises_a_version_for_nba_and_none_for_ncaab():
    """`sport_versions` is what the scorecard stamps itself with, so a sport missing here
    is a sport the artifact cannot claim to have graded."""
    composite = po.build_extra_settler()
    versions = composite.sport_versions
    assert versions.get("nba") == espn.GRADER_VERSION
    assert "ncaab" not in versions
    for already in ("nfl", "ncaaf", "wnba"):
        assert versions.get(already) == espn.GRADER_VERSION


def test_nba_reads_the_nba_endpoint_not_wnbas():
    """The defect this would have shipped as: `_settle_basketball_prop` used to hard-code
    `self._summary("wnba", event_id)`, so an NBA event id would have been sent to the WNBA
    summary endpoint and come back empty or wrong."""
    assert espn._SPORT_PATHS["nba"] == "basketball/nba"
    assert espn._SPORT_PATHS["wnba"] == "basketball/wnba"
    assert espn._SPORT_PATHS["nba"] != espn._SPORT_PATHS["wnba"]


def test_ncaabs_exclusion_has_exactly_the_documented_cause():
    """NCAAB is out because no team registry resolves its names -- not for any other
    reason. If this assertion ever fails, the blocker is gone and NCAAB should be added
    to HANDLED_SPORTS. Pinning the CAUSE stops the exclusion outliving it."""
    from syndicate.features.shared.team_aliases import canonical_team

    assert canonical_team("ncaab", "Duke Blue Devils") is None
    assert canonical_team("ncaab", "Gonzaga") is None
    # ... while the sport NBA joined on does resolve, which is why NBA could be added.
    assert canonical_team("nba", "Boston Celtics") is not None


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
